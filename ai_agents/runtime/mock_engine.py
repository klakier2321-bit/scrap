"""Deterministic mock runtime used when no real LLM should be called."""

from __future__ import annotations

from .schemas import PlanOutput, ReviewOutput, StepUsage


class MockExecutionEngine:
    """Produces deterministic plans and reviews without LLM calls."""

    def run_plan_agent(self, request_payload: dict, run_context: dict) -> tuple[PlanOutput, StepUsage]:
        requested_paths = request_payload.get("requested_paths") or []
        affected_paths = requested_paths or self._default_paths_for_agent(
            request_payload["agent_name"]
        )
        plan = PlanOutput(
            summary=(
                f"Mock plan for {request_payload['agent_name']} focused on "
                f"'{request_payload['goal']}'."
            ),
            recommended_actions=[
                "Read canonical docs before touching module files.",
                "Keep the change within the declared scope and small-change rule.",
                "Prepare a reviewable diff before any write step.",
            ],
            affected_paths=affected_paths,
            review_required=bool(run_context.get("review_required")),
            human_decision_required=bool(run_context.get("human_decision_required")),
            warnings=list(run_context.get("warnings", [])),
        )
        return (
            plan,
            StepUsage(
                agent_name=request_payload["agent_name"],
                model=run_context["selected_model"],
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                successful_requests=0,
                estimated_cost_usd=0.0,
            ),
        )

    def run_review_agent(
        self,
        request_payload: dict,
        plan_output: PlanOutput,
        run_context: dict,
    ) -> tuple[ReviewOutput, StepUsage]:
        if run_context.get("human_decision_required"):
            decision = "human_review_required"
        elif run_context.get("review_required"):
            decision = "revise"
        else:
            decision = "approve"

        review = ReviewOutput(
            decision=decision,
            risk_level=request_payload.get("risk_level", "low"),
            main_findings=[
                "Mock review path executed successfully.",
                "No real LLM call was made because AGENT_USE_MOCK_LLM=true.",
            ],
            required_changes=(
                ["Human review is still required before sensitive or high-risk changes."]
                if decision != "approve"
                else []
            ),
        )
        return (
            review,
            StepUsage(
                agent_name="review_agent",
                model="mock/review",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                successful_requests=0,
                estimated_cost_usd=0.0,
            ),
        )

    @staticmethod
    def _default_paths_for_agent(agent_name: str) -> list[str]:
        defaults = {
            "system_lead_agent": ["docs/", "ai_agents/"],
            "architecture_agent": ["docs/ARCHITECTURE.md"],
            "monitoring_agent": ["monitoring/", "infrastructure/grafana/"],
            "control_layer_agent": ["core/"],
            "strategy_agent": ["trading/"],
            "integration_agent": ["docs/", "core/", "ai_agents/"],
            "api_agent": ["docs/openapi.yaml"],
            "gui_agent": ["core/templates/operator.html"],
            "review_agent": ["docs/", "ai_agents/"],
        }
        return defaults.get(agent_name, ["docs/"])
