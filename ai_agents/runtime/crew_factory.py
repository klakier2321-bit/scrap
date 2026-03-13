"""CrewAI-based execution engine for planning and review workflows."""

from __future__ import annotations

import json
from typing import Any

from crewai import Agent, Crew, LLM, Process, Task

from .config import AgentProfile, ModelProfile, load_prompt
from .schemas import PlanOutput, ReviewOutput, StepUsage


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
        return LLM(
            model=model_profile.model,
            is_litellm=True,
            base_url=self.settings.agent_litellm_base_url,
            api_key=self.settings.agent_litellm_api_key,
            temperature=0.1,
        )

    def _extract_structured_output(self, crew_output: Any, output_model: type) -> Any:
        if crew_output.tasks_output:
            task_output = crew_output.tasks_output[0]
            if getattr(task_output, "pydantic", None):
                return task_output.pydantic
            if getattr(task_output, "json_dict", None):
                return output_model.model_validate(task_output.json_dict)
            if getattr(task_output, "raw", None):
                raw = task_output.raw.strip()
                return output_model.model_validate(json.loads(raw))
        if getattr(crew_output, "pydantic", None):
            return crew_output.pydantic
        if getattr(crew_output, "json_dict", None):
            return output_model.model_validate(crew_output.json_dict)
        raise ValueError("Crew output did not contain a structured response.")

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
            "and keep the change within the ownership model."
        )
        task = Task(
            description=description,
            expected_output=(
                "A structured plan with summary, recommended actions, affected paths, "
                "review_required, human_decision_required, and warnings."
            ),
            agent=agent,
            output_pydantic=PlanOutput,
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
            "Respect the project rules and escalate to human review for high-risk or runtime-sensitive work."
        )
        task = Task(
            description=description,
            expected_output=(
                "A structured review decision with approve, revise, or human_review_required."
            ),
            agent=agent,
            output_pydantic=ReviewOutput,
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
