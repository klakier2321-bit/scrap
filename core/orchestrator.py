"""Main coordination module for the control layer."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from pathlib import Path
from time import monotonic
import uuid
from typing import Any

from ai_agents.runtime.service import AgentRuntimeService

from .bot_manager import BotManager
from .config import AppSettings
from .metrics import (
    record_blocked_call,
    record_human_escalation,
    record_review_required,
    record_run_created,
    record_run_failed,
    record_run_started,
    record_run_succeeded,
    record_scope_violation,
)
from .risk_manager import RiskManager
from .storage import RunStore
from .strategy_manager import StrategyManager


logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates bot actions, agent runs, metrics, and persistence."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.bot_manager = BotManager(docker_base_url=settings.docker_socket_path)
        self.risk_manager = RiskManager()
        self.strategy_manager = StrategyManager(
            user_data_dir=settings.freqtrade_user_data_path
        )
        self.store = RunStore(settings.database_path)
        stale_runs = self.store.reconcile_stale_runs()
        self.agent_runtime = AgentRuntimeService(settings=settings)
        self.executor = ThreadPoolExecutor(max_workers=settings.agent_max_parallel_runs)
        self.futures: dict[str, Future[Any]] = {}
        if stale_runs["queued"] or stale_runs["running"]:
            logger.warning(
                "Reconciled stale agent runs after startup.",
                extra={
                    "event": "reconcile_stale_runs",
                    "queued_count": stale_runs["queued"],
                    "running_count": stale_runs["running"],
                },
            )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "agent_mode": self.settings.agent_mode,
            "mock_llm": self.settings.agent_use_mock_llm,
            "litellm_url": self.settings.agent_litellm_base_url,
            "kill_switch": self.settings.agent_kill_switch,
            "docker_available": self.bot_manager.docker_available(),
        }

    def list_bots(self) -> list[dict[str, Any]]:
        return self.bot_manager.list_bots()

    def get_bot_status(self, bot_id: str) -> dict[str, Any]:
        return self.bot_manager.get_bot_status(bot_id)

    def start_bot(self, bot_id: str) -> dict[str, Any]:
        bot_status = self.bot_manager.get_bot_status(bot_id)
        self.risk_manager.ensure_bot_start_allowed(bot_status)
        return self.bot_manager.start_bot(bot_id)

    def stop_bot(self, bot_id: str) -> dict[str, Any]:
        return self.bot_manager.stop_bot(bot_id)

    def get_bot_logs(self, bot_id: str, tail: int | None = None) -> list[str]:
        return self.bot_manager.get_bot_logs(bot_id, tail=tail)

    def list_agents(self) -> list[dict[str, Any]]:
        return self.agent_runtime.list_agents()

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_runs(limit=limit)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return run

    def create_agent_run(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        if self.settings.agent_kill_switch:
            run_id = str(uuid.uuid4())
            task_id = f"task-{uuid.uuid4()}"
            now = datetime.now(timezone.utc).isoformat()
            record = {
                "run_id": run_id,
                "task_id": task_id,
                "agent_name": request_payload["agent_name"],
                "goal": request_payload["goal"],
                "business_reason": request_payload.get("business_reason", ""),
                "payload_json": request_payload,
                "status": "blocked",
                "risk_level": request_payload["risk_level"],
                "model": None,
                "model_tier": None,
                "review_required": True,
                "human_decision_required": True,
                "approval_required": False,
                "approval_granted": False,
                "stop_requested": False,
                "cross_layer": bool(request_payload.get("cross_layer")),
                "does_touch_contract": bool(request_payload.get("does_touch_contract")),
                "does_touch_runtime": bool(request_payload.get("does_touch_runtime")),
                "estimated_cost_usd": 0.0,
                "warnings_json": ["Agent kill switch is enabled."],
                "blocked_reason": "kill_switch_enabled",
                "max_iterations": 0,
                "max_retry_limit": 0,
                "created_at": now,
                "started_at": None,
                "finished_at": now,
                "result_json": None,
                "review_json": None,
                "error": "AI control layer is disabled by kill switch.",
            }
            self.store.create_run(record)
            record_run_created(record["agent_name"], "blocked")
            record_blocked_call(record["agent_name"], "kill_switch_enabled")
            record_human_escalation(record["agent_name"])
            return self.get_run(run_id)

        current_agent_spend = self.store.get_today_spend(request_payload["agent_name"])
        current_total_spend = self.store.get_today_total_spend()
        risk_decision = self.risk_manager.evaluate_request_risk(request_payload)
        sensitive_paths = self.risk_manager.validate_requested_paths(
            request_payload.get("requested_paths", [])
        )
        for path_value in sensitive_paths:
            record_scope_violation(request_payload["agent_name"])

        decision = self.agent_runtime.prepare_run(
            request_payload=request_payload,
            current_agent_spend=current_agent_spend,
            current_total_spend=current_total_spend,
            risk_overrides=risk_decision,
            sensitive_path_violations=sensitive_paths,
        )

        run_id = str(uuid.uuid4())
        task_id = f"task-{uuid.uuid4()}"
        now = datetime.now(timezone.utc).isoformat()

        status = "queued"
        if not decision["allowed"]:
            status = "blocked"
        elif decision["approval_required"]:
            status = "awaiting_approval"

        record = {
            "run_id": run_id,
            "task_id": task_id,
            "agent_name": request_payload["agent_name"],
            "goal": request_payload["goal"],
            "business_reason": request_payload.get("business_reason", ""),
            "payload_json": request_payload,
            "status": status,
            "risk_level": request_payload["risk_level"],
            "model": decision["selected_model"],
            "model_tier": decision["selected_model_tier"],
            "review_required": decision["review_required"],
            "human_decision_required": decision["human_decision_required"],
            "approval_required": decision["approval_required"],
            "approval_granted": False,
            "stop_requested": False,
            "cross_layer": bool(request_payload.get("cross_layer")),
            "does_touch_contract": bool(request_payload.get("does_touch_contract")),
            "does_touch_runtime": bool(request_payload.get("does_touch_runtime")),
            "estimated_cost_usd": decision["estimated_cost_usd"],
            "warnings_json": decision["warnings"],
            "blocked_reason": decision["blocked_reason"],
            "max_iterations": decision["max_iterations"],
            "max_retry_limit": decision["max_retry_limit"],
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "result_json": None,
            "review_json": None,
            "error": None,
        }
        self.store.create_run(record)
        record_run_created(record["agent_name"], status)

        if decision["review_required"]:
            record_review_required(record["agent_name"])
        if decision["human_decision_required"]:
            record_human_escalation(record["agent_name"])
        if not decision["allowed"]:
            record_blocked_call(record["agent_name"], decision["blocked_reason"] or "blocked")
            return self.get_run(run_id)

        if status == "queued":
            self._submit_run(run_id)
        return self.get_run(run_id)

    def approve_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "awaiting_approval":
            return run
        self.store.update_run(
            run_id,
            approval_granted=True,
            status="queued",
            error=None,
        )
        self._submit_run(run_id)
        return self.get_run(run_id)

    def stop_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        self.store.update_run(run_id, stop_requested=True)
        future = self.futures.get(run_id)
        if future and future.cancel():
            self.store.update_run(
                run_id,
                status="stopped",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error="Run was cancelled before it started.",
            )
            return self.get_run(run_id)

        if run["status"] in {"queued", "awaiting_approval"}:
            self.store.update_run(
                run_id,
                status="stopped",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error="Run was stopped before execution.",
            )
        return self.get_run(run_id)

    def _submit_run(self, run_id: str) -> None:
        if self.settings.agent_max_parallel_runs <= 1:
            self._execute_run(run_id)
            return
        future = self.executor.submit(self._execute_run, run_id)
        self.futures[run_id] = future

    def _execute_run(self, run_id: str) -> None:
        run = self.get_run(run_id)
        if run.get("stop_requested"):
            self.store.update_run(
                run_id,
                status="stopped",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error="Run was stopped before execution.",
            )
            return

        started_at = datetime.now(timezone.utc)
        deadline = monotonic() + self.settings.agent_run_timeout_seconds
        self.store.update_run(run_id, status="running", started_at=started_at.isoformat())
        record_run_started(run["agent_name"])

        try:
            result = self.agent_runtime.execute(
                run_record=self.get_run(run_id),
                stop_requested_callback=lambda: bool(
                    (self.store.get_run(run_id) or {}).get("stop_requested")
                )
                or monotonic() >= deadline,
            )
            finished_at = datetime.now(timezone.utc)
            duration_seconds = max((finished_at - started_at).total_seconds(), 0.0)
            self.store.update_run(
                run_id,
                status="completed",
                finished_at=finished_at.isoformat(),
                result_json=result["result_json"],
                review_json=result["review_json"],
                actual_cost_usd=result["actual_cost_usd"],
                prompt_tokens=result["prompt_tokens"],
                completion_tokens=result["completion_tokens"],
                total_tokens=result["total_tokens"],
                successful_requests=result["successful_requests"],
                duration_seconds=duration_seconds,
                error=None,
            )
            record_run_succeeded(
                agent_name=run["agent_name"],
                model=result["model"],
                duration_seconds=duration_seconds,
                prompt_tokens=result["prompt_tokens"],
                completion_tokens=result["completion_tokens"],
                total_tokens=result["total_tokens"],
                successful_requests=result["successful_requests"],
                estimated_cost_usd=result["actual_cost_usd"],
            )
            logger.info(
                "Agent run completed.",
                extra={
                    "run_id": run_id,
                    "task_id": run["task_id"],
                    "agent_name": run["agent_name"],
                    "model": result["model"],
                    "status": "completed",
                    "event": "agent_run_completed",
                },
            )
        except Exception as exc:  # noqa: BLE001
            finished_at = datetime.now(timezone.utc)
            duration_seconds = max((finished_at - started_at).total_seconds(), 0.0)
            self.store.update_run(
                run_id,
                status="failed",
                finished_at=finished_at.isoformat(),
                error=str(exc),
                duration_seconds=duration_seconds,
            )
            record_run_failed(run["agent_name"], duration_seconds, reason="exception")
            logger.exception(
                "Agent run failed.",
                extra={
                    "run_id": run_id,
                    "task_id": run["task_id"],
                    "agent_name": run["agent_name"],
                    "status": "failed",
                    "event": "agent_run_failed",
                },
            )
        finally:
            self.futures.pop(run_id, None)
