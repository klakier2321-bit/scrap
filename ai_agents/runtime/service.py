"""Runtime service that enforces policy and executes CrewAI flows."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from typing import Any

from opentelemetry import trace
from crewai.events.listeners.tracing import utils as tracing_utils

from core.metrics import record_blocked_call, record_model_allowlist_violation

from .config import (
    BudgetProfile,
    ModelProfile,
    load_agent_profiles,
    load_budget_profiles,
    load_model_profiles,
    load_prompt,
    load_scope_manifest,
)
from .crew_factory import CrewAIExecutionEngine
from .flow import PlanningFlow
from .hooks import HookRunContext, register_runtime_hooks, reset_current_run_context, set_current_run_context
from .mock_engine import MockExecutionEngine
from .policy import evaluate_request
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class RuntimeDecision:
    """Prepared runtime decision for one run."""

    agent_name: str
    selected_model_tier: str
    selected_model: str
    review_required: bool
    human_decision_required: bool
    approval_required: bool
    estimated_cost_usd: float
    max_iterations: int
    max_retry_limit: int
    warnings: list[str]
    blocked_reason: str | None
    allowed: bool


class AgentRuntimeService:
    """Loads agent config, applies policy, and executes flows."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.agent_profiles = load_agent_profiles()
        self.model_profiles = load_model_profiles()
        self.global_budget, self.budget_profiles = load_budget_profiles()
        self.scope_manifest = load_scope_manifest()
        self.prompt_hashes = {
            name: hashlib.sha256(load_prompt(profile.prompt_file).encode("utf-8")).hexdigest()
            for name, profile in self.agent_profiles.items()
        }
        self.real_engine = CrewAIExecutionEngine(
            settings=settings,
            agent_profiles=self.agent_profiles,
            model_profiles=self.model_profiles,
        )
        self.mock_engine = MockExecutionEngine()
        register_runtime_hooks()

    def _select_engine(self) -> Any:
        return self.mock_engine if self.settings.agent_use_mock_llm else self.real_engine

    def _run_with_optional_mock_fallback(
        self,
        *,
        agent_name: str,
        task_label: str,
        runner: Any,
    ) -> tuple[Any, Any]:
        engine = self._select_engine()
        try:
            return runner(engine)
        except Exception:  # noqa: BLE001
            if self.settings.agent_use_mock_llm or not self.settings.agent_allow_mock_fallback:
                raise
            logger.exception(
                "Real LLM helper call failed. Falling back to the mock engine.",
                extra={
                    "agent_name": agent_name,
                    "status": "fallback",
                    "event": "mock_fallback",
                    "task_label": task_label,
                },
            )
            return runner(self.mock_engine)

    def list_agents(self) -> list[dict[str, Any]]:
        agents = []
        for name, profile in self.agent_profiles.items():
            budget = self.budget_profiles[name]
            manifest = self.scope_manifest["agents"].get(name, {})
            agents.append(
                {
                    "name": name,
                    "role": profile.role,
                    "model_tier": profile.model_tier,
                    "default_daily_budget_usd": budget.daily_usd,
                    "default_per_run_budget_usd": budget.per_run_usd,
                    "owned_scope": manifest.get("owned_scope", []),
                    "read_only_scope": manifest.get("read_only_scope", []),
                    "forbidden_scope": manifest.get("forbidden_scope", []),
                }
            )
        return agents

    def generate_coding_task_packet(
        self,
        *,
        module_context: dict[str, Any],
        executive_context: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        packet_output, usage = self._run_with_optional_mock_fallback(
            agent_name="system_lead_agent",
            task_label="coding_task_packet",
            runner=lambda engine: engine.run_lead_task_packet_agent(
                module_context=module_context,
                executive_context=executive_context,
            ),
        )
        return packet_output.model_dump(), usage.model_dump()

    def generate_coding_change(
        self,
        *,
        agent_name: str,
        task_packet: dict[str, Any],
        file_contexts: list[dict[str, str]],
        review_feedback: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        change_output, usage = self._run_with_optional_mock_fallback(
            agent_name=agent_name,
            task_label="coding_change",
            runner=lambda engine: engine.run_coding_agent(
                agent_name=agent_name,
                selected_model_tier="cheap",
                task_packet=task_packet,
                file_contexts=file_contexts,
                review_feedback=review_feedback,
            ),
        )
        return change_output.model_dump(), usage.model_dump()

    def review_coding_change(
        self,
        *,
        task_packet: dict[str, Any],
        diff_text: str,
        check_results: dict[str, Any],
        change_summary: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        review_output, usage = self._run_with_optional_mock_fallback(
            agent_name="review_agent",
            task_label="coding_review",
            runner=lambda engine: engine.run_coding_review_agent(
                task_packet=task_packet,
                diff_text=diff_text,
                check_results=check_results,
                change_summary=change_summary,
            ),
        )
        return review_output.model_dump(), usage.model_dump()

    def prepare_run(
        self,
        *,
        request_payload: dict[str, Any],
        current_agent_spend: float,
        current_total_spend: float,
        risk_overrides: dict[str, Any],
        sensitive_path_violations: list[str],
    ) -> dict[str, Any]:
        with tracer.start_as_current_span("AgentRuntimeService.prepare_run") as span:
            agent_name = request_payload["agent_name"]
            span.set_attribute("crypto.agent_name", agent_name)
            if agent_name not in self.agent_profiles:
                return RuntimeDecision(
                    agent_name=agent_name,
                    selected_model_tier="cheap",
                    selected_model=self.model_profiles["cheap"].model,
                    review_required=True,
                    human_decision_required=True,
                    approval_required=False,
                    estimated_cost_usd=0.0,
                    max_iterations=1,
                    max_retry_limit=0,
                    warnings=[f"Unknown agent: {agent_name}"],
                    blocked_reason="unknown_agent",
                    allowed=False,
                ).__dict__

            if self.agent_profiles[agent_name].model_tier not in self.model_profiles:
                record_model_allowlist_violation(agent_name)
                return RuntimeDecision(
                    agent_name=agent_name,
                    selected_model_tier=self.agent_profiles[agent_name].model_tier,
                    selected_model=self.agent_profiles[agent_name].model_tier,
                    review_required=True,
                    human_decision_required=True,
                    approval_required=False,
                    estimated_cost_usd=0.0,
                    max_iterations=1,
                    max_retry_limit=0,
                    warnings=["Agent model tier is outside the configured allowlist."],
                    blocked_reason="model_not_allowed",
                    allowed=False,
                ).__dict__

            decision = evaluate_request(
                request_payload=request_payload,
                agent_profile=self.agent_profiles[agent_name],
                budget_profile=self.budget_profiles[agent_name],
                models=self.model_profiles,
                scope_manifest=self.scope_manifest,
                current_agent_spend=current_agent_spend,
                current_total_spend=current_total_spend,
                global_daily_budget_usd=float(
                    self.global_budget.get(
                        "daily_usd",
                        self.settings.agent_global_daily_budget_usd,
                    )
                ),
                global_per_run_budget_usd=float(
                    self.global_budget.get(
                        "per_run_usd",
                        self.settings.agent_global_per_run_budget_usd,
                    )
                ),
                risk_overrides=risk_overrides,
                sensitive_path_violations=sensitive_path_violations,
            )
            decision_dict = decision.to_dict()
            span.set_attribute("crypto.allowed", bool(decision_dict.get("allowed")))
            span.set_attribute(
                "crypto.blocked_reason",
                decision_dict.get("blocked_reason") or "none",
            )
            if decision_dict.get("blocked_reason") == "model_not_allowed":
                record_model_allowlist_violation(agent_name)
            return decision_dict

    def execute(
        self,
        *,
        run_record: dict[str, Any],
        stop_requested_callback: Any,
        cache_lookup: Any | None = None,
        cache_store: Any | None = None,
        cache_hit_callback: Any | None = None,
        cache_miss_callback: Any | None = None,
    ) -> dict[str, Any]:
        run_context = {
            "selected_model_tier": run_record["model_tier"],
            "selected_model": run_record["model"],
            "review_required": run_record["review_required"],
            "human_decision_required": run_record["human_decision_required"],
            "warnings": run_record.get("warnings_json") or [],
            "max_iterations": int(run_record.get("max_iterations", 1)),
            "max_retry_limit": int(run_record.get("max_retry_limit", 0)),
            "plan_prompt_hash": self.prompt_hashes.get(run_record["agent_name"], "plan"),
            "review_prompt_hash": self.prompt_hashes.get("review_agent", "review"),
            "review_model": self.model_profiles["cheap"].model,
        }

        hook_context = HookRunContext(
            run_id=run_record["run_id"],
            task_id=run_record["task_id"],
            agent_name=run_record["agent_name"],
            model=run_record["model"],
            max_iterations=run_context["max_iterations"],
            stop_requested=stop_requested_callback,
            on_blocked=lambda reason: record_blocked_call(run_record["agent_name"], reason),
            on_llm_call=lambda agent_name, model: logger.info(
                "LLM call executed.",
                extra={
                    "run_id": run_record["run_id"],
                    "task_id": run_record["task_id"],
                    "agent_name": agent_name,
                    "model": model,
                    "status": "running",
                    "event": "llm_call",
                },
            ),
        )

        token = set_current_run_context(hook_context)
        suppress_tracing_token = tracing_utils.set_suppress_tracing_messages(True)
        try:
            engine = self._select_engine()
            try:
                flow = PlanningFlow(
                    engine=engine,
                    run_id=run_record["run_id"],
                    task_id=run_record["task_id"],
                    request_payload=run_record["payload_json"],
                    run_context=run_context,
                    stop_requested_callback=stop_requested_callback,
                    cache_lookup=cache_lookup,
                    cache_store=cache_store,
                    cache_hit_callback=cache_hit_callback,
                    cache_miss_callback=cache_miss_callback,
                )
                return flow.kickoff()
            except Exception:  # noqa: BLE001
                if self.settings.agent_use_mock_llm or not self.settings.agent_allow_mock_fallback:
                    raise
                logger.exception(
                    "Real LLM execution failed. Falling back to the mock engine.",
                    extra={
                        "run_id": run_record["run_id"],
                        "task_id": run_record["task_id"],
                        "agent_name": run_record["agent_name"],
                        "status": "fallback",
                        "event": "mock_fallback",
                    },
                )
                run_context["warnings"] = list(run_context.get("warnings", [])) + [
                    "Real model execution failed. Mock fallback was used."
                ]
                flow = PlanningFlow(
                    engine=self.mock_engine,
                    run_id=run_record["run_id"],
                    task_id=run_record["task_id"],
                    request_payload=run_record["payload_json"],
                    run_context=run_context,
                    stop_requested_callback=stop_requested_callback,
                    cache_lookup=cache_lookup,
                    cache_store=cache_store,
                    cache_hit_callback=cache_hit_callback,
                    cache_miss_callback=cache_miss_callback,
                )
                return flow.kickoff()
        finally:
            tracing_utils._suppress_tracing_messages.reset(suppress_tracing_token)
            reset_current_run_context(token)

    def generate_strategy_assessment(
        self,
        strategy_report: dict[str, Any],
    ) -> dict[str, Any]:
        selected_model_tier = self.agent_profiles["strategy_agent"].model_tier
        selected_model = self.model_profiles[selected_model_tier].model
        run_context = {
            "selected_model_tier": selected_model_tier,
            "selected_model": selected_model,
        }
        assessment_output, usage = self._run_with_optional_mock_fallback(
            agent_name="strategy_agent",
            task_label="strategy_assessment",
            runner=lambda engine: engine.run_strategy_assessment_agent(
                strategy_report,
                run_context,
            ),
        )
        return {
            "generated_by": "strategy_agent",
            "model": selected_model,
            "summary": assessment_output.summary,
            "recommendation": assessment_output.recommendation,
            "risk_level": assessment_output.risk_level,
            "rationale": assessment_output.rationale,
            "stage_candidate": assessment_output.stage_candidate,
            "estimated_cost_usd": usage.estimated_cost_usd,
        }
