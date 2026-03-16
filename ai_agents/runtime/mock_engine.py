"""Deterministic mock runtime used when no real LLM should be called."""

from __future__ import annotations

from .schemas import (
    CodingChangeOutput,
    CodingTaskPacketOutput,
    FileEditOutput,
    PlanOutput,
    ReviewOutput,
    StepUsage,
    StrategyAssessmentOutput,
)


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

    def run_strategy_assessment_agent(
        self,
        strategy_report: dict,
        run_context: dict,
        *,
        readiness_gate: dict | None = None,
        dry_run_context: dict | None = None,
    ) -> tuple[StrategyAssessmentOutput, StepUsage]:
        evaluation_status = strategy_report.get("evaluation_status", "needs_manual_review")
        stage_candidate = bool(strategy_report.get("stage_candidate"))
        drawdown_pct = float(strategy_report.get("drawdown_pct", 0.0))
        gate_status = (readiness_gate or {}).get("overall_status")
        if gate_status == "blocked" or evaluation_status == "rejected":
            recommendation = "reject"
            risk_level = "high"
        elif gate_status == "ready_for_next_stage_review" or stage_candidate:
            recommendation = "promote_after_human_review"
            risk_level = "low" if drawdown_pct <= 0.03 else "medium"
        else:
            recommendation = "needs_manual_review"
            risk_level = "medium"

        assessment = StrategyAssessmentOutput(
            summary=(
                f"Mock assessment for {strategy_report['strategy_name']} based on the latest backtest "
                f"({strategy_report.get('timeframe', 'unknown')}): profit {strategy_report.get('profit_pct', 0.0):.2%}, "
                f"drawdown {drawdown_pct:.2%}, trades {strategy_report.get('total_trades', 0)}."
            ),
            recommendation=recommendation,
            risk_level=risk_level,
            rationale=[
                f"Profit ratio: {strategy_report.get('profit_pct', 0.0):.4f}.",
                f"Drawdown ratio: {drawdown_pct:.4f}.",
                f"Win rate: {strategy_report.get('win_rate', 0.0):.4f}.",
                f"Evaluation status from strategy report: {evaluation_status}.",
                f"Combined readiness status: {gate_status or 'unknown'}.",
            ],
            stage_candidate=stage_candidate,
        )
        return (
            assessment,
            StepUsage(
                agent_name="strategy_agent",
                model=run_context["selected_model"],
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                successful_requests=0,
                estimated_cost_usd=0.0,
            ),
        )

    def run_lead_task_packet_agent(
        self,
        *,
        module_context: dict,
        executive_context: dict,
    ) -> tuple[CodingTaskPacketOutput, StepUsage]:
        packet = CodingTaskPacketOutput(
            summary=f"Mock packet dla modułu {module_context['module_id']}.",
            module_id=module_context["module_id"],
            owner_agent=module_context["owner_agent"],
            goal=f"Wykonaj mały przyrost w module {module_context['title']}.",
            business_reason=module_context["module_summary"],
            owned_scope=module_context.get("owned_scope", []),
            read_only_context=module_context.get("read_only_context", []),
            target_files=module_context.get("target_candidates", [])[:2],
            forbidden_paths=module_context.get("forbidden_paths", []),
            risk_level="low",
            acceptance_checks=module_context.get("acceptance_checks", []),
            required_tests=module_context.get("required_tests", []),
            definition_of_done=module_context.get("definition_of_done", []),
            warnings=["Mock task packet generated."],
            review_required=True,
            human_decision_required=False,
        )
        return (
            packet,
            StepUsage(
                agent_name="system_lead_agent",
                model="mock/system-lead",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                successful_requests=0,
                estimated_cost_usd=0.0,
            ),
        )

    def run_coding_agent(
        self,
        *,
        agent_name: str,
        selected_model_tier: str,
        task_packet: dict,
        file_contexts: list[dict[str, str]],
        review_feedback: list[str] | None = None,
    ) -> tuple[CodingChangeOutput, StepUsage]:
        target_path = (task_packet.get("target_files") or ["README.md"])[0]
        existing = next((item for item in file_contexts if item.get("path") == target_path), None)
        base_content = existing.get("content", "") if existing else ""
        content = base_content
        if not content:
            content = "# Mock change\n\nTen plik został przygotowany w trybie mock.\n"
        change = CodingChangeOutput(
            summary=f"Mock coding change dla {agent_name}.",
            file_edits=[
                FileEditOutput(
                    path=target_path,
                    content=content,
                    is_new_file=existing is None,
                    rationale="Mock coding flow created a placeholder edit.",
                )
            ],
            notes=["No real coding LLM call was made."],
            required_checks=task_packet.get("required_tests", []),
        )
        return (
            change,
            StepUsage(
                agent_name=agent_name,
                model=f"mock/{selected_model_tier}",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                successful_requests=0,
                estimated_cost_usd=0.0,
            ),
        )

    def run_coding_review_agent(
        self,
        *,
        task_packet: dict,
        diff_text: str,
        check_results: dict,
        change_summary: str,
    ) -> tuple[ReviewOutput, StepUsage]:
        review = ReviewOutput(
            decision="approve",
            risk_level=task_packet.get("risk_level", "low"),
            main_findings=[
                "Mock coding review completed successfully.",
                f"Summary: {change_summary}",
            ],
            required_changes=[],
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
