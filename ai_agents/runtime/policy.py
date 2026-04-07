"""Policy and cost gates for the agent runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .config import AgentProfile, BudgetProfile, ModelProfile


CROSS_LAYER_COORDINATORS = {
    "system_lead_agent",
    "integration_agent",
    "review_agent",
    "architecture_agent",
}
STRONG_MODEL_ELIGIBLE_AGENTS = {
    "system_lead_agent",
    "architecture_agent",
    "strategy_agent",
}
REPO_WIDE_PATH_MARKERS = {"", ".", "./", "/", "*", "**", "../", ".."}
MAX_REQUESTED_PATHS = 10
MAX_CONTEXT_TEXT_CHARS = 4000
MAX_REQUESTED_PATHS_CHARS = 1000
MAX_ESTIMATED_PROMPT_TOKENS = 1500


@dataclass(frozen=True)
class PolicyDecision:
    """Final decision returned by the policy layer."""

    allowed: bool
    blocked_reason: str | None
    review_required: bool
    human_decision_required: bool
    approval_required: bool
    selected_model_tier: str
    selected_model: str
    estimated_cost_usd: float
    max_iterations: int
    max_retry_limit: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _matches_scope(candidate: str, scope_rule: str) -> bool:
    candidate = candidate.lstrip("./")
    scope_rule = scope_rule.lstrip("./")
    if scope_rule in {"", "."}:
        return True
    if scope_rule.endswith("/"):
        return candidate.startswith(scope_rule)
    return candidate == scope_rule or candidate.startswith(f"{scope_rule}/")


def _estimate_prompt_tokens(request_payload: dict[str, Any]) -> int:
    joined = " ".join(
        [
            request_payload.get("goal", ""),
            request_payload.get("business_reason", ""),
            " ".join(request_payload.get("requested_paths", [])),
        ]
    )
    return max(300, len(joined) // 4 + 200)


def _is_repo_wide_request(path_value: str) -> bool:
    normalized = path_value.strip()
    return normalized in REPO_WIDE_PATH_MARKERS or normalized.startswith("../")


def _estimate_cost(
    model_profile: ModelProfile,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    prompt_cost = (prompt_tokens / 1000) * model_profile.estimated_input_cost_per_1k_usd
    completion_cost = (
        completion_tokens / 1000
    ) * model_profile.estimated_output_cost_per_1k_usd
    return round(prompt_cost + completion_cost, 6)


def _resolve_model_profile(
    *,
    requested_tier: str,
    agent_profile: AgentProfile,
    models: dict[str, ModelProfile],
) -> tuple[str, ModelProfile]:
    if requested_tier in models:
        return requested_tier, models[requested_tier]
    fallback_tier = agent_profile.model_tier
    if fallback_tier in models:
        return fallback_tier, models[fallback_tier]
    first_tier = next(iter(models))
    return first_tier, models[first_tier]


def _decision_blocked(
    *,
    reason: str,
    warnings: list[str],
    agent_profile: AgentProfile,
    budget_profile: BudgetProfile,
    models: dict[str, ModelProfile],
) -> PolicyDecision:
    selected_tier, model_profile = _resolve_model_profile(
        requested_tier=agent_profile.model_tier,
        agent_profile=agent_profile,
        models=models,
    )
    return PolicyDecision(
        allowed=False,
        blocked_reason=reason,
        review_required=True,
        human_decision_required=True,
        approval_required=False,
        selected_model_tier=selected_tier,
        selected_model=model_profile.model,
        estimated_cost_usd=0.0,
        max_iterations=budget_profile.max_iterations,
        max_retry_limit=budget_profile.max_retry_limit,
        warnings=warnings,
    )


def evaluate_request(
    request_payload: dict[str, Any],
    agent_profile: AgentProfile,
    budget_profile: BudgetProfile,
    models: dict[str, ModelProfile],
    scope_manifest: dict[str, Any],
    current_agent_spend: float,
    current_total_spend: float,
    global_daily_budget_usd: float,
    global_per_run_budget_usd: float,
    risk_overrides: dict[str, Any],
    sensitive_path_violations: list[str],
    current_agent_active_runs: int = 0,
) -> PolicyDecision:
    warnings = list(risk_overrides.get("warnings", []))
    requested_paths = request_payload.get("requested_paths", [])
    combined_context_length = len(request_payload.get("goal", "")) + len(
        request_payload.get("business_reason", "")
    )
    requested_paths_chars = sum(len(path_value) for path_value in requested_paths)
    metadata = request_payload.get("metadata") or {}
    autopilot_request = bool(metadata.get("autopilot"))
    explicit_enable = bool(metadata.get("explicit_enable"))

    manifest_entry = scope_manifest["agents"][agent_profile.name]
    owned_scope = manifest_entry["owned_scope"]
    read_only_scope = manifest_entry.get("read_only_scope", [])
    allowed_request_scope = list(dict.fromkeys(owned_scope + read_only_scope))
    path_outside_scope = [
        path_value
        for path_value in requested_paths
        if not any(_matches_scope(path_value, rule) for rule in allowed_request_scope)
    ]

    if agent_profile.activation_mode == "disabled_by_default" and not explicit_enable:
        warnings.append(
            "This agent is disabled by default and requires an explicit manual enable."
        )
        return _decision_blocked(
            reason="agent_disabled_by_default",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    if agent_profile.activation_mode == "manual_only" and autopilot_request:
        warnings.append("This agent may not be dispatched by autopilot.")
        return _decision_blocked(
            reason="autopilot_agent_not_allowed",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    if request_payload.get("does_touch_runtime") and not agent_profile.can_touch_runtime:
        warnings.append("This agent is not allowed to touch paper/live runtime behavior.")
        return _decision_blocked(
            reason="runtime_touch_not_allowed",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    if current_agent_active_runs >= int(agent_profile.max_parallel_runs):
        warnings.append("This agent already reached its parallel run limit.")
        return _decision_blocked(
            reason="agent_parallel_limit",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    if any(_is_repo_wide_request(path_value) for path_value in requested_paths):
        warnings.append("Repo-wide or parent-directory path requests are not allowed.")
        return _decision_blocked(
            reason="repo_scope_request",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    if len(requested_paths) > MAX_REQUESTED_PATHS:
        warnings.append("Requested path count exceeds the configured maximum.")
        return _decision_blocked(
            reason="requested_paths_limit_exceeded",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    if (
        combined_context_length > MAX_CONTEXT_TEXT_CHARS
        or requested_paths_chars > MAX_REQUESTED_PATHS_CHARS
    ):
        warnings.append("Task context exceeds the configured maximum size.")
        return _decision_blocked(
            reason="context_too_large",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    estimated_prompt_tokens = _estimate_prompt_tokens(request_payload)
    if estimated_prompt_tokens > MAX_ESTIMATED_PROMPT_TOKENS:
        warnings.append("Estimated prompt token usage exceeds the configured maximum.")
        return _decision_blocked(
            reason="context_too_large",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    if sensitive_path_violations:
        warnings.append(
            "Sensitive paths were requested and cannot be handled by AI directly."
        )
        return _decision_blocked(
            reason="sensitive_path_violation",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    cross_layer = bool(request_payload.get("cross_layer"))
    if cross_layer and agent_profile.name not in CROSS_LAYER_COORDINATORS:
        warnings.append("Cross-layer work is not allowed for this agent.")
        return _decision_blocked(
            reason="cross_layer_not_allowed",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    if path_outside_scope and agent_profile.name not in CROSS_LAYER_COORDINATORS:
        warnings.append(
            "Requested paths exceed the allowed read/write scope for this agent."
        )
        return _decision_blocked(
            reason="scope_violation",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    selected_model_tier = agent_profile.model_tier
    wants_strong_model = bool(request_payload.get("force_strong_model")) or (
        agent_profile.name in STRONG_MODEL_ELIGIBLE_AGENTS
        and (
            cross_layer
            or bool(request_payload.get("does_touch_contract"))
            or request_payload.get("risk_level") == "high"
        )
    )
    if wants_strong_model and agent_profile.name not in STRONG_MODEL_ELIGIBLE_AGENTS:
        warnings.append("This agent is not allowed to use the strong model tier.")
        return _decision_blocked(
            reason="model_not_allowed",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )
    if wants_strong_model:
        selected_model_tier = "strong_review_only"

    selected_model_tier, model_profile = _resolve_model_profile(
        requested_tier=selected_model_tier,
        agent_profile=agent_profile,
        models=models,
    )

    estimated_completion_tokens = min(model_profile.max_output_tokens, 800)
    estimated_cost_usd = _estimate_cost(
        model_profile,
        prompt_tokens=estimated_prompt_tokens,
        completion_tokens=estimated_completion_tokens,
    )
    if estimated_cost_usd > budget_profile.per_run_usd:
        warnings.append("Estimated cost exceeds the per-run budget for this agent.")
        return _decision_blocked(
            reason="agent_per_run_budget_exceeded",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )
    if estimated_cost_usd > global_per_run_budget_usd:
        warnings.append("Estimated cost exceeds the global per-run budget.")
        return _decision_blocked(
            reason="global_per_run_budget_exceeded",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )
    if current_agent_spend + estimated_cost_usd > budget_profile.daily_usd:
        warnings.append("Estimated cost exceeds the daily budget for this agent.")
        return _decision_blocked(
            reason="agent_daily_budget_exceeded",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )
    if current_total_spend + estimated_cost_usd > global_daily_budget_usd:
        warnings.append("Estimated cost exceeds the global daily budget.")
        return _decision_blocked(
            reason="global_daily_budget_exceeded",
            warnings=warnings,
            agent_profile=agent_profile,
            budget_profile=budget_profile,
            models=models,
        )

    review_required = bool(risk_overrides.get("review_required"))
    human_decision_required = bool(risk_overrides.get("human_decision_required"))
    approval_required = False
    if wants_strong_model and (
        budget_profile.require_approval_for_strong_model
        or bool(risk_overrides.get("require_approval_for_strong_model"))
    ):
        approval_required = True
        review_required = True
        human_decision_required = True
        warnings.append("Strong model access requires approval before execution.")

    if agent_profile.requires_review_for_activation:
        review_required = True
        human_decision_required = human_decision_required or bool(autopilot_request)
        warnings.append("This agent requires explicit review-aware activation.")

    return PolicyDecision(
        allowed=True,
        blocked_reason=None,
        review_required=review_required,
        human_decision_required=human_decision_required,
        approval_required=approval_required,
        selected_model_tier=selected_model_tier,
        selected_model=model_profile.model,
        estimated_cost_usd=estimated_cost_usd,
        max_iterations=min(agent_profile.max_iter, budget_profile.max_iterations),
        max_retry_limit=min(
            agent_profile.max_retry_limit,
            budget_profile.max_retry_limit,
        ),
        warnings=warnings,
    )
