"""Policy and cost gates for the agent runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .config import AgentProfile, BudgetProfile, ModelProfile


CROSS_LAYER_COORDINATORS = {
    "system_lead_agent",
    "integration_agent",
    "review_agent",
}


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
) -> PolicyDecision:
    warnings = list(risk_overrides.get("warnings", []))

    requested_paths = request_payload.get("requested_paths", [])
    owned_scope = scope_manifest["agents"][agent_profile.name]["owned_scope"]
    path_outside_scope = [
        path_value
        for path_value in requested_paths
        if not any(_matches_scope(path_value, rule) for rule in owned_scope)
    ]

    if sensitive_path_violations:
        warnings.append(
            "Sensitive paths were requested and cannot be handled by AI directly."
        )
        return PolicyDecision(
            allowed=False,
            blocked_reason="sensitive_path_violation",
            review_required=True,
            human_decision_required=True,
            approval_required=False,
            selected_model_tier=agent_profile.model_tier,
            selected_model=models[agent_profile.model_tier].model,
            estimated_cost_usd=0.0,
            max_iterations=budget_profile.max_iterations,
            max_retry_limit=budget_profile.max_retry_limit,
            warnings=warnings,
        )

    cross_layer = bool(request_payload.get("cross_layer"))
    if cross_layer and agent_profile.name not in CROSS_LAYER_COORDINATORS:
        warnings.append("Cross-layer work is not allowed for this agent.")
        return PolicyDecision(
            allowed=False,
            blocked_reason="cross_layer_not_allowed",
            review_required=True,
            human_decision_required=True,
            approval_required=False,
            selected_model_tier=agent_profile.model_tier,
            selected_model=models[agent_profile.model_tier].model,
            estimated_cost_usd=0.0,
            max_iterations=budget_profile.max_iterations,
            max_retry_limit=budget_profile.max_retry_limit,
            warnings=warnings,
        )

    if path_outside_scope and agent_profile.name not in CROSS_LAYER_COORDINATORS:
        warnings.append("Requested paths exceed the owned scope for this agent.")
        return PolicyDecision(
            allowed=False,
            blocked_reason="scope_violation",
            review_required=True,
            human_decision_required=True,
            approval_required=False,
            selected_model_tier=agent_profile.model_tier,
            selected_model=models[agent_profile.model_tier].model,
            estimated_cost_usd=0.0,
            max_iterations=budget_profile.max_iterations,
            max_retry_limit=budget_profile.max_retry_limit,
            warnings=warnings,
        )

    selected_model_tier = agent_profile.model_tier
    if bool(request_payload.get("force_strong_model")) or (
        agent_profile.name in {"system_lead_agent", "architecture_agent"}
        and (
            cross_layer
            or bool(request_payload.get("does_touch_contract"))
            or request_payload.get("risk_level") == "high"
        )
    ):
        selected_model_tier = "strong"
    model_profile = models[selected_model_tier]

    review_required = bool(risk_overrides.get("review_required"))
    human_decision_required = bool(risk_overrides.get("human_decision_required"))

    prompt_tokens = _estimate_prompt_tokens(request_payload)
    completion_tokens = max(model_profile.max_output_tokens // 2, 400)
    estimated_cost = _estimate_cost(model_profile, prompt_tokens, completion_tokens)

    if review_required:
        review_model = models["cheap"]
        estimated_cost += _estimate_cost(review_model, 250, 500)
        estimated_cost = round(estimated_cost, 6)

    approval_required = False
    if selected_model_tier == "strong" and budget_profile.require_approval_for_strong_model:
        approval_required = True
        warnings.append("Strong model selected. Human approval is required.")

    if estimated_cost > budget_profile.per_run_usd or estimated_cost > global_per_run_budget_usd:
        approval_required = True
        warnings.append("Estimated run cost exceeds the default per-run budget.")

    if current_agent_spend + estimated_cost > budget_profile.daily_usd:
        return PolicyDecision(
            allowed=False,
            blocked_reason="agent_daily_budget_exceeded",
            review_required=review_required,
            human_decision_required=True,
            approval_required=False,
            selected_model_tier=selected_model_tier,
            selected_model=model_profile.model,
            estimated_cost_usd=estimated_cost,
            max_iterations=budget_profile.max_iterations,
            max_retry_limit=budget_profile.max_retry_limit,
            warnings=warnings,
        )

    if current_total_spend + estimated_cost > global_daily_budget_usd:
        return PolicyDecision(
            allowed=False,
            blocked_reason="global_daily_budget_exceeded",
            review_required=review_required,
            human_decision_required=True,
            approval_required=False,
            selected_model_tier=selected_model_tier,
            selected_model=model_profile.model,
            estimated_cost_usd=estimated_cost,
            max_iterations=budget_profile.max_iterations,
            max_retry_limit=budget_profile.max_retry_limit,
            warnings=warnings,
        )

    return PolicyDecision(
        allowed=True,
        blocked_reason=None,
        review_required=review_required,
        human_decision_required=human_decision_required,
        approval_required=approval_required,
        selected_model_tier=selected_model_tier,
        selected_model=model_profile.model,
        estimated_cost_usd=estimated_cost,
        max_iterations=budget_profile.max_iterations,
        max_retry_limit=budget_profile.max_retry_limit,
        warnings=warnings,
    )
