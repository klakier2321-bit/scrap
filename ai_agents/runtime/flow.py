"""Flow-based orchestration for plan and review execution."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from crewai.flow.flow import Flow, FlowState, listen, start
from opentelemetry import trace
from pydantic import Field

from .schemas import PlanOutput, ReviewOutput, StepUsage


tracer = trace.get_tracer(__name__)


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
        cache_lookup: Any | None = None,
        cache_store: Any | None = None,
        cache_hit_callback: Any | None = None,
        cache_miss_callback: Any | None = None,
    ) -> None:
        self.engine = engine
        self.stop_requested_callback = stop_requested_callback
        self.request_payload = request_payload
        self.run_context = run_context
        self.cache_lookup = cache_lookup
        self.cache_store = cache_store
        self.cache_hit_callback = cache_hit_callback
        self.cache_miss_callback = cache_miss_callback
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

    @staticmethod
    def _normalize_payload_for_cache(payload: Any) -> Any:
        if isinstance(payload, dict):
            normalized: dict[str, Any] = {}
            for key, value in payload.items():
                if key == "metadata" and isinstance(value, dict):
                    metadata = {
                        meta_key: PlanningFlow._normalize_payload_for_cache(meta_value)
                        for meta_key, meta_value in value.items()
                        if meta_key != "idempotency_key"
                    }
                    normalized[key] = metadata
                else:
                    normalized[key] = PlanningFlow._normalize_payload_for_cache(value)
            return normalized
        if isinstance(payload, list):
            return [PlanningFlow._normalize_payload_for_cache(item) for item in payload]
        return payload

    @classmethod
    def _make_payload_hash(cls, payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                cls._normalize_payload_for_cache(payload),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _make_cache_key(
        *,
        agent_name: str,
        selected_model: str,
        step_type: str,
        prompt_hash: str,
        payload_hash: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                [
                    agent_name,
                    selected_model,
                    step_type,
                    prompt_hash,
                    payload_hash,
                ]
            ).encode("utf-8")
        ).hexdigest()

    @start()
    def generate_plan(self) -> dict[str, Any]:
        with tracer.start_as_current_span("PlanningFlow.generate_plan") as span:
            span.set_attribute("crypto.agent_name", self.request_payload["agent_name"])
            span.set_attribute("crypto.run_id", self.state.run_id)
            span.set_attribute("crypto.task_id", self.state.task_id)
            if self.stop_requested_callback():
                raise RuntimeError("Run was stopped before the planning step.")

            step_payload = {"request_payload": self.request_payload}
            step_type = "plan"
            agent_name = self.request_payload["agent_name"]
            selected_model = self.run_context["selected_model"]
            prompt_hash = self.run_context.get("plan_prompt_hash", "plan")
            payload_hash = self._make_payload_hash(step_payload)
            cache_key = self._make_cache_key(
                agent_name=agent_name,
                selected_model=selected_model,
                step_type=step_type,
                prompt_hash=prompt_hash,
                payload_hash=payload_hash,
            )
            if self.cache_lookup:
                cached = self.cache_lookup(cache_key)
                if cached is not None:
                    if self.cache_hit_callback:
                        self.cache_hit_callback(agent_name, step_type)
                    self.plan_output_data = cached
                    self.usage_steps_data.append(
                        StepUsage(
                            agent_name=agent_name,
                            model=selected_model,
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_tokens=0,
                            successful_requests=0,
                            estimated_cost_usd=0.0,
                        ).model_dump()
                    )
                    span.set_attribute("crypto.cache_hit", True)
                    return self.plan_output_data
                if self.cache_miss_callback:
                    self.cache_miss_callback(agent_name, step_type)

            plan_output, usage = self.engine.run_plan_agent(
                self.request_payload,
                self.run_context,
            )
            self.plan_output_data = plan_output.model_dump()
            self.usage_steps_data.append(usage.model_dump())
            if self.cache_store:
                self.cache_store(
                    cache_key=cache_key,
                    agent_name=agent_name,
                    selected_model=selected_model,
                    step_type=step_type,
                    prompt_hash=prompt_hash,
                    payload_hash=payload_hash,
                    response=self.plan_output_data,
                )
            span.set_attribute("crypto.cache_hit", False)
            return self.plan_output_data

    @listen(generate_plan)
    def review_plan(self, _: dict[str, Any]) -> dict[str, Any]:
        with tracer.start_as_current_span("PlanningFlow.review_plan") as span:
            span.set_attribute("crypto.agent_name", self.request_payload["agent_name"])
            span.set_attribute("crypto.run_id", self.state.run_id)
            span.set_attribute("crypto.task_id", self.state.task_id)
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

            step_payload = {
                "request_payload": self.request_payload,
                "plan_output": self.plan_output_data,
            }
            step_type = "review"
            agent_name = "review_agent"
            selected_model = self.run_context.get("review_model", self.run_context["selected_model"])
            prompt_hash = self.run_context.get("review_prompt_hash", "review")
            payload_hash = self._make_payload_hash(step_payload)
            cache_key = self._make_cache_key(
                agent_name=agent_name,
                selected_model=selected_model,
                step_type=step_type,
                prompt_hash=prompt_hash,
                payload_hash=payload_hash,
            )
            if self.cache_lookup:
                cached = self.cache_lookup(cache_key)
                if cached is not None:
                    if self.cache_hit_callback:
                        self.cache_hit_callback(agent_name, step_type)
                    self.review_output_data = cached
                    self.usage_steps_data.append(
                        StepUsage(
                            agent_name=agent_name,
                            model=selected_model,
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_tokens=0,
                            successful_requests=0,
                            estimated_cost_usd=0.0,
                        ).model_dump()
                    )
                    span.set_attribute("crypto.cache_hit", True)
                    return self.review_output_data
                if self.cache_miss_callback:
                    self.cache_miss_callback(agent_name, step_type)

            review_output, usage = self.engine.run_review_agent(
                self.request_payload,
                PlanOutput.model_validate(self.plan_output_data),
                self.run_context,
            )
            self.review_output_data = review_output.model_dump()
            self.usage_steps_data.append(usage.model_dump())
            if self.cache_store:
                self.cache_store(
                    cache_key=cache_key,
                    agent_name=agent_name,
                    selected_model=selected_model,
                    step_type=step_type,
                    prompt_hash=prompt_hash,
                    payload_hash=payload_hash,
                    response=self.review_output_data,
                )
            span.set_attribute("crypto.cache_hit", False)
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
        retry_like_requests = sum(
            max(step.get("successful_requests", 0) - 1, 0)
            for step in self.usage_steps_data
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
            "retry_like_requests": retry_like_requests,
            "actual_cost_usd": total_cost,
            "model": self.run_context["selected_model"],
        }
