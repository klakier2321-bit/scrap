"""CrewAI-based execution engine for planning and review workflows."""

from __future__ import annotations

import json
import re
from typing import Any

from crewai import Agent, Crew, LLM, Process, Task

from .config import AgentProfile, ModelProfile, load_prompt
from .schemas import PlanOutput, ReviewOutput, StepUsage, StrategyAssessmentOutput


def _compute_cost(
    usage: dict[str, int],
    model_profile: ModelProfile,
) -> float:
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    prompt_cost = (
        prompt_tokens / 1000
    ) * model_profile.estimated_input_cost_per_1k_usd
    completion_cost = (
        completion_tokens / 1000
    ) * model_profile.estimated_output_cost_per_1k_usd
    return round(prompt_cost + completion_cost, 6)


class CrewAIExecutionEngine:
    """Runs structured planning and review tasks with CrewAI."""

    def __init__(self, settings: Any, agent_profiles: dict[str, AgentProfile], model_profiles: dict[str, ModelProfile]) -> None:
        self.settings = settings
        self.agent_profiles = agent_profiles
        self.model_profiles = model_profiles

    def _make_llm(self, model_profile: ModelProfile) -> LLM:
        allowed_models = {profile.model for profile in self.model_profiles.values()}
        if model_profile.model not in allowed_models:
            raise ValueError(f"Model '{model_profile.model}' is outside the configured allowlist.")
        return LLM(
            model=model_profile.model,
            is_litellm=True,
            base_url=self.settings.agent_litellm_base_url,
            api_base=self.settings.agent_litellm_base_url,
            api_key=self.settings.agent_litellm_api_key,
        )

    def _extract_structured_output(self, crew_output: Any, output_model: type) -> Any:
        if crew_output.tasks_output:
            task_output = crew_output.tasks_output[0]
            if getattr(task_output, "pydantic", None):
                pydantic_output = task_output.pydantic
                if isinstance(pydantic_output, output_model):
                    return pydantic_output
                payload = (
                    pydantic_output.model_dump()
                    if hasattr(pydantic_output, "model_dump")
                    else pydantic_output
                )
                return output_model.model_validate(
                    self._normalize_structured_payload(payload)
                )
            if getattr(task_output, "json_dict", None):
                return output_model.model_validate(
                    self._normalize_structured_payload(task_output.json_dict)
                )
            if getattr(task_output, "raw", None):
                return output_model.model_validate(
                    self._normalize_structured_payload(
                        self._extract_json_payload(task_output.raw)
                    )
                )
        if getattr(crew_output, "pydantic", None):
            pydantic_output = crew_output.pydantic
            if isinstance(pydantic_output, output_model):
                return pydantic_output
            payload = (
                pydantic_output.model_dump()
                if hasattr(pydantic_output, "model_dump")
                else pydantic_output
            )
            return output_model.model_validate(
                self._normalize_structured_payload(payload)
            )
        if getattr(crew_output, "json_dict", None):
            return output_model.model_validate(
                self._normalize_structured_payload(crew_output.json_dict)
            )
        raise ValueError("Crew output did not contain a structured response.")

    def _normalize_structured_payload(self, payload: Any) -> Any:
        if isinstance(payload, list):
            return [self._normalize_structured_payload(item) for item in payload]

        if not isinstance(payload, dict):
            return payload

        schema_wrapper_keys = {
            "title",
            "type",
            "description",
            "default",
            "items",
            "value",
        }
        if "value" in payload and any(key in payload for key in schema_wrapper_keys - {"value"}):
            return self._normalize_structured_payload(payload["value"])

        return {
            key: self._normalize_structured_payload(value)
            for key, value in payload.items()
        }

    def _extract_json_payload(self, raw_text: str) -> dict[str, Any]:
        raw = raw_text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            candidate = self._extract_balanced_json_object(raw)
            if candidate is None:
                raise
            return json.loads(candidate)

    def _extract_balanced_json_object(self, raw: str) -> str | None:
        start = raw.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False

        for index, char in enumerate(raw[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return raw[start : index + 1]

        return None

    def _build_json_output_instruction(self, output_model: type) -> str:
        schema = output_model.model_json_schema()
        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])
        return (
            "Return only valid JSON. Do not use markdown, code fences, or prose outside JSON.\n"
            f"Required fields: {', '.join(required_fields)}.\n"
            "JSON field schema:\n"
            f"{json.dumps(properties, ensure_ascii=False, indent=2)}"
        )

    def _usage_from_output(
        self,
        crew_output: Any,
        agent_name: str,
        model_profile: ModelProfile,
    ) -> StepUsage:
        token_usage = crew_output.token_usage.model_dump() if crew_output.token_usage else {}
        return StepUsage(
            agent_name=agent_name,
            model=model_profile.model,
            prompt_tokens=token_usage.get("prompt_tokens", 0),
            completion_tokens=token_usage.get("completion_tokens", 0),
            total_tokens=token_usage.get("total_tokens", 0),
            successful_requests=token_usage.get("successful_requests", 0),
            estimated_cost_usd=_compute_cost(token_usage, model_profile),
        )

    def run_plan_agent(
        self,
        request_payload: dict[str, Any],
        run_context: dict[str, Any],
    ) -> tuple[PlanOutput, StepUsage]:
        agent_profile = self.agent_profiles[request_payload["agent_name"]]
        model_profile = self.model_profiles[run_context["selected_model_tier"]]
        agent = Agent(
            role=agent_profile.role,
            goal=agent_profile.goal,
            backstory=f"{agent_profile.backstory}\n\n{load_prompt(agent_profile.prompt_file)}",
            llm=self._make_llm(model_profile),
            verbose=False,
            allow_delegation=False,
            max_iter=run_context["max_iterations"],
            max_retry_limit=run_context["max_retry_limit"],
        )
        description = (
            "Create a structured implementation plan for the following request.\n\n"
            f"Goal: {request_payload['goal']}\n"
            f"Business reason: {request_payload.get('business_reason', '')}\n"
            f"Requested paths: {', '.join(request_payload.get('requested_paths', [])) or 'not specified'}\n"
            f"Risk level: {request_payload.get('risk_level', 'low')}\n"
            f"Cross-layer: {request_payload.get('cross_layer', False)}\n"
            f"Touches contract: {request_payload.get('does_touch_contract', False)}\n"
            f"Touches runtime: {request_payload.get('does_touch_runtime', False)}\n"
            "Hard rules: no secrets, no local runtime config changes, no direct live trading, "
            "and keep the change within the ownership model.\n\n"
            f"{self._build_json_output_instruction(PlanOutput)}"
        )
        task = Task(
            description=description,
            expected_output=(
                "Strict JSON matching the requested plan schema."
            ),
            agent=agent,
        )
        crew = Crew(
            name=f"{request_payload['agent_name']}_planning_crew",
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
            memory=False,
            planning=False,
            tracing=False,
        )
        crew_output = crew.kickoff()
        plan_output = self._extract_structured_output(crew_output, PlanOutput)
        return plan_output, self._usage_from_output(
            crew_output,
            request_payload["agent_name"],
            model_profile,
        )

    def run_review_agent(
        self,
        request_payload: dict[str, Any],
        plan_output: PlanOutput,
        run_context: dict[str, Any],
    ) -> tuple[ReviewOutput, StepUsage]:
        agent_profile = self.agent_profiles["review_agent"]
        model_profile = self.model_profiles["cheap"]
        agent = Agent(
            role=agent_profile.role,
            goal=agent_profile.goal,
            backstory=f"{agent_profile.backstory}\n\n{load_prompt(agent_profile.prompt_file)}",
            llm=self._make_llm(model_profile),
            verbose=False,
            allow_delegation=False,
            max_iter=agent_profile.max_iter,
            max_retry_limit=agent_profile.max_retry_limit,
        )
        description = (
            "Review the following structured plan and classify the risk.\n\n"
            f"Original goal: {request_payload['goal']}\n"
            f"Risk level: {request_payload.get('risk_level', 'low')}\n"
            f"Cross-layer: {request_payload.get('cross_layer', False)}\n"
            f"Touches contract: {request_payload.get('does_touch_contract', False)}\n"
            f"Touches runtime: {request_payload.get('does_touch_runtime', False)}\n"
            f"Plan summary: {plan_output.summary}\n"
            f"Recommended actions: {plan_output.recommended_actions}\n"
            f"Affected paths: {plan_output.affected_paths}\n"
            f"Warnings: {plan_output.warnings}\n"
            "Respect the project rules and escalate to human review for high-risk or runtime-sensitive work.\n\n"
            f"{self._build_json_output_instruction(ReviewOutput)}"
        )
        task = Task(
            description=description,
            expected_output=(
                "Strict JSON matching the requested review schema."
            ),
            agent=agent,
        )
        crew = Crew(
            name="review_agent_crew",
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
            memory=False,
            planning=False,
            tracing=False,
        )
        crew_output = crew.kickoff()
        review_output = self._extract_structured_output(crew_output, ReviewOutput)
        return review_output, self._usage_from_output(
            crew_output,
            "review_agent",
            model_profile,
        )

    def run_strategy_assessment_agent(
        self,
        strategy_report: dict[str, Any],
        run_context: dict[str, Any],
    ) -> tuple[StrategyAssessmentOutput, StepUsage]:
        agent_profile = self.agent_profiles["strategy_agent"]
        model_profile = self.model_profiles[run_context["selected_model_tier"]]
        agent = Agent(
            role=agent_profile.role,
            goal=agent_profile.goal,
            backstory=f"{agent_profile.backstory}\n\n{load_prompt(agent_profile.prompt_file)}",
            llm=self._make_llm(model_profile),
            verbose=False,
            allow_delegation=False,
            max_iter=agent_profile.max_iter,
            max_retry_limit=agent_profile.max_retry_limit,
        )
        description = (
            "Assess the following strategy report and return a structured recommendation.\n\n"
            f"Strategy: {strategy_report['strategy_name']}\n"
            f"Timeframe: {strategy_report.get('timeframe', 'unknown')}\n"
            f"Profit ratio: {strategy_report.get('profit_pct', 0.0)}\n"
            f"Absolute profit: {strategy_report.get('absolute_profit', 0.0)}\n"
            f"Drawdown ratio: {strategy_report.get('drawdown_pct', 0.0)}\n"
            f"Drawdown abs: {strategy_report.get('drawdown_abs', 0.0)}\n"
            f"Total trades: {strategy_report.get('total_trades', 0)}\n"
            f"Win rate: {strategy_report.get('win_rate', 0.0)}\n"
            f"Stability score: {strategy_report.get('stability_score')}\n"
            f"Current evaluation status: {strategy_report.get('evaluation_status')}\n"
            f"Rejection reasons: {strategy_report.get('rejection_reasons', [])}\n"
            "Respect the project rules: no live trading promotion without human review, "
            "and profit never outweighs uncontrolled drawdown.\n\n"
            f"{self._build_json_output_instruction(StrategyAssessmentOutput)}"
        )
        task = Task(
            description=description,
            expected_output=(
                "Strict JSON matching the requested strategy assessment schema."
            ),
            agent=agent,
        )
        crew = Crew(
            name="strategy_agent_assessment_crew",
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
            memory=False,
            planning=False,
            tracing=False,
        )
        crew_output = crew.kickoff()
        assessment_output = self._extract_structured_output(
            crew_output,
            StrategyAssessmentOutput,
        )
        return assessment_output, self._usage_from_output(
            crew_output,
            "strategy_agent",
            model_profile,
        )
