"""Flow-based orchestration for plan and review execution."""

from __future__ import annotations

from typing import Any

from crewai.flow.flow import Flow, FlowState, listen, start
from pydantic import Field

from .schemas import PlanOutput, ReviewOutput, StepUsage


class PlanningFlowState(FlowState):
    """State for one planning flow run."""

    run_id: str = ""
    task_id: str = ""
    agent_name: str = ""
    request_payload: dict[str, Any] = Field(default_factory=dict)
    run_context: dict[str, Any] = Field(default_factory=dict)
    plan_output: dict[str, Any] | None = None
    review_output: dict[str, Any] | None = None
    usage_steps: list[dict[str, Any]] = Field(default_factory=list)


class PlanningFlow(Flow[PlanningFlowState]):
    """Plan -> review -> finalize execution flow."""

    def __init__(
        self,
        *,
        engine: Any,
        run_id: str,
        task_id: str,
        request_payload: dict[str, Any],
        run_context: dict[str, Any],
        stop_requested_callback: Any,
    ) -> None:
        self.engine = engine
        self.stop_requested_callback = stop_requested_callback
        self.request_payload = request_payload
        self.run_context = run_context
        self.plan_output_data: dict[str, Any] | None = None
        self.review_output_data: dict[str, Any] | None = None
        self.usage_steps_data: list[dict[str, Any]] = []
        super().__init__(tracing=False, suppress_flow_events=True)
        self._initialize_state(
            {
                "run_id": run_id,
                "task_id": task_id,
                "agent_name": request_payload["agent_name"],
            }
        )

    @start()
    def generate_plan(self) -> dict[str, Any]:
        if self.stop_requested_callback():
            raise RuntimeError("Run was stopped before the planning step.")
        plan_output, usage = self.engine.run_plan_agent(
            self.request_payload,
            self.run_context,
        )
        self.plan_output_data = plan_output.model_dump()
        self.usage_steps_data.append(usage.model_dump())
        return self.plan_output_data

    @listen(generate_plan)
    def review_plan(self, _: dict[str, Any]) -> dict[str, Any]:
        if self.stop_requested_callback():
            raise RuntimeError("Run was stopped before the review step.")
        if not self.run_context.get("review_required"):
            self.review_output_data = ReviewOutput(
                decision="approve",
                risk_level=self.request_payload.get("risk_level", "low"),
                main_findings=["Review step skipped because the run is low risk."],
                required_changes=[],
            ).model_dump()
            return self.review_output_data

        review_output, usage = self.engine.run_review_agent(
            self.request_payload,
            PlanOutput.model_validate(self.plan_output_data),
            self.run_context,
        )
        self.review_output_data = review_output.model_dump()
        self.usage_steps_data.append(usage.model_dump())
        return self.review_output_data

    @listen(review_plan)
    def finalize(self, _: dict[str, Any]) -> dict[str, Any]:
        total_prompt = sum(step.get("prompt_tokens", 0) for step in self.usage_steps_data)
        total_completion = sum(
            step.get("completion_tokens", 0) for step in self.usage_steps_data
        )
        total_tokens = sum(step.get("total_tokens", 0) for step in self.usage_steps_data)
        total_requests = sum(
            step.get("successful_requests", 0) for step in self.usage_steps_data
        )
        total_cost = round(
            sum(step.get("estimated_cost_usd", 0.0) for step in self.usage_steps_data),
            6,
        )
        return {
            "result_json": self.plan_output_data or {},
            "review_json": self.review_output_data or {},
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "successful_requests": total_requests,
            "actual_cost_usd": total_cost,
            "model": self.run_context["selected_model"],
        }
