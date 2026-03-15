"""Lead queue, worktree dispatch i supervised write dla agentów kodujących."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from ai_agents.runtime.config import CodingModuleProfile, load_coding_runtime_config

from .storage import RunStore
from .worktree_manager import WorktreeInfo, WorktreeManager

if TYPE_CHECKING:
    from ai_agents.runtime.service import AgentRuntimeService


logger = logging.getLogger(__name__)
FINAL_CODING_STATUSES = {"committed", "blocked", "rejected"}
ACTIVE_CODING_STATUSES = {"dispatched", "coding", "review", "approved"}


class CodingSupervisorService:
    """Zarządza kolejką lead agenta, worktree i supervised write."""

    def __init__(
        self,
        *,
        settings: Any,
        store: RunStore,
        agent_runtime: "AgentRuntimeService",
        executive_report_provider: Any,
    ) -> None:
        self.settings = settings
        self.store = store
        self.agent_runtime = agent_runtime
        self.executive_report_provider = executive_report_provider
        self.scope_manifest = self.agent_runtime.scope_manifest
        self.runtime_config, modules = load_coding_runtime_config(settings.coding_modules_config_path)
        self.modules_by_id = {module.module_id: module for module in modules if module.enabled}
        self.worktree_manager = WorktreeManager(
            repo_path=settings.repo_checkout_path,
            worktree_root=settings.agent_worktree_root_path,
            git_author_name=settings.agent_git_author_name,
            git_author_email=settings.agent_git_author_email,
        )
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._worker_task_id: str | None = None
        self._worker_started_monotonic: float | None = None
        self._last_queue_refresh_at: str | None = None
        self._last_dispatch_at: str | None = None
        self._last_error: str | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if not self.settings.agent_coding_enabled:
                return self.status()
            if self._thread and self._thread.is_alive():
                return self.status()
            self.worktree_manager.ensure_repo()
            self._reconcile_orphaned_active_tasks(
                reason="Coding task was left active after ai_control restart.",
                event_type="restart_reconcile",
            )
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="crypto-coding-supervisor",
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        return self.status()

    def status(self) -> dict[str, Any]:
        tasks = self.store.list_coding_tasks(limit=100)
        active_task = self.store.get_active_coding_task()
        task_timeout_seconds = self._coding_task_timeout_seconds()
        active_task_age_seconds = self._task_age_seconds(active_task)
        attention_needed = bool(self._last_error)
        if (
            active_task is not None
            and active_task_age_seconds is not None
            and active_task_age_seconds > task_timeout_seconds
        ):
            attention_needed = True
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "enabled": bool(self.settings.agent_coding_enabled),
            "lead_refresh_interval_seconds": self.runtime_config.get(
                "lead_refresh_interval_seconds",
                self.settings.agent_lead_queue_refresh_interval_seconds,
            ),
            "dispatcher_poll_interval_seconds": self.runtime_config.get(
                "dispatcher_poll_interval_seconds",
                self.settings.agent_coding_dispatcher_poll_interval_seconds,
            ),
            "max_active_tasks": int(self.runtime_config.get("max_active_tasks", 1)),
            "last_queue_refresh_at": self._last_queue_refresh_at,
            "last_dispatch_at": self._last_dispatch_at,
            "last_error": self._last_error,
            "attention_needed": attention_needed,
            "task_timeout_seconds": task_timeout_seconds,
            "active_task_id": active_task["task_id"] if active_task else None,
            "active_task_age_seconds": active_task_age_seconds,
            "active_worker_alive": bool(self._worker_thread and self._worker_thread.is_alive()),
            "ready_tasks": sum(1 for task in tasks if task.get("status") == "ready"),
            "review_tasks": sum(1 for task in tasks if task.get("status") == "review"),
            "committed_tasks": sum(1 for task in tasks if task.get("status") == "committed"),
            "modules": [asdict(module) for module in self.modules_by_id.values()],
        }

    def list_coding_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_coding_tasks(limit=limit)

    def get_coding_task(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_coding_task(task_id)
        if task is None:
            raise KeyError(f"Unknown coding task: {task_id}")
        return task

    def list_workspaces(self) -> list[dict[str, Any]]:
        return self.store.list_coding_workspaces()

    def get_workspace_diff(self, task_id: str) -> dict[str, Any]:
        workspace = self.store.get_coding_workspace(task_id)
        if workspace is None:
            raise KeyError(f"No coding workspace for task: {task_id}")
        return workspace

    def create_manual_task(
        self,
        *,
        module_id: str,
        goal_override: str | None = None,
        business_reason: str | None = None,
    ) -> dict[str, Any]:
        module = self._require_module(module_id)
        packet = self._build_manual_task_packet(
            module=module,
            goal_override=goal_override,
            business_reason=business_reason,
        )
        record = self._persist_task_packet(
            packet=packet,
            module=module,
            created_by_run_id=f"manual-{uuid.uuid4()}",
            usage={"estimated_cost_usd": 0.0},
        )
        return record

    def approve_review(self, task_id: str) -> dict[str, Any]:
        task = self.get_coding_task(task_id)
        if task["status"] not in {"review", "approved"}:
            return task
        workspace = self.store.get_coding_workspace(task_id)
        if workspace is None:
            raise KeyError(f"No coding workspace for task: {task_id}")
        commit_sha = self.worktree_manager.commit_changes(
            worktree_path=Path(workspace["worktree_path"]),
            message=f"Agent task {task_id}: {task['goal'][:72]}",
        )
        finished_at = self._now()
        self.store.update_coding_task(
            task_id,
            status="committed",
            commit_sha=commit_sha,
            finished_at=finished_at,
        )
        self.store.add_coding_task_event(
            {
                "event_id": str(uuid.uuid4()),
                "task_id": task_id,
                "event_type": "commit",
                "payload": {"commit_sha": commit_sha},
                "created_at": finished_at,
            }
        )
        return self.get_coding_task(task_id)

    def reject_review(self, task_id: str, reason: str = "Manual review rejection.") -> dict[str, Any]:
        task = self.get_coding_task(task_id)
        finished_at = self._now()
        self.store.update_coding_task(
            task_id,
            status="rejected",
            last_error=reason,
            finished_at=finished_at,
        )
        self.store.add_coding_task_event(
            {
                "event_id": str(uuid.uuid4()),
                "task_id": task_id,
                "event_type": "reject",
                "payload": {"reason": reason},
                "created_at": finished_at,
            }
        )
        return self.get_coding_task(task_id)

    def reset_workspace(self, task_id: str) -> dict[str, Any]:
        task = self.get_coding_task(task_id)
        if task["status"] == "committed":
            raise RuntimeError("Committed coding task cannot be reset.")
        workspace = self.store.get_coding_workspace(task_id)
        if workspace is None:
            raise KeyError(f"No coding workspace for task: {task_id}")
        info = self.worktree_manager.reset_workspace(
            task_id=task_id,
            agent_name=task["owner_agent"],
            base_ref=task.get("base_ref") or "main",
        )
        self.store.update_coding_workspace(
            task_id,
            worktree_path=info.worktree_path,
            branch_name=info.branch_name,
            base_ref=info.base_ref,
            base_commit=info.base_commit,
            changed_files=[],
            diff_text="",
            check_results={},
            status="ready",
        )
        self.store.update_coding_task(
            task_id,
            status="ready",
            worktree_path=info.worktree_path,
            branch_name=info.branch_name,
            base_ref=info.base_ref,
            base_commit=info.base_commit,
            diff_summary="",
            check_results={},
            review_json={},
            last_error=None,
        )
        self.store.add_coding_task_event(
            {
                "event_id": str(uuid.uuid4()),
                "task_id": task_id,
                "event_type": "workspace_reset",
                "payload": {
                    "branch": info.branch_name,
                    "worktree_path": info.worktree_path,
                },
                "created_at": self._now(),
            }
        )
        return self.get_coding_task(task_id)

    def _run_loop(self) -> None:
        next_queue_refresh = 0.0
        next_dispatch = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            try:
                self._reconcile_worker_state()
                if now >= next_queue_refresh:
                    self._refresh_lead_queue()
                    next_queue_refresh = (
                        now
                        + int(
                            self.runtime_config.get(
                                "lead_refresh_interval_seconds",
                                self.settings.agent_lead_queue_refresh_interval_seconds,
                            )
                        )
                    )
                if now >= next_dispatch:
                    self._dispatch_ready_task()
                    next_dispatch = (
                        now
                        + int(
                            self.runtime_config.get(
                                "dispatcher_poll_interval_seconds",
                                self.settings.agent_coding_dispatcher_poll_interval_seconds,
                            )
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.exception("Coding supervisor loop failed.")
            time.sleep(1)

    def _refresh_lead_queue(self) -> None:
        self._last_queue_refresh_at = self._now()
        open_tasks = self.store.list_coding_tasks_by_status(
            ["proposed", "ready", "dispatched", "coding", "review", "approved"]
        )
        if open_tasks:
            return
        for module in self._ordered_modules():
            packet, usage = self._generate_task_packet(module)
            if packet is None:
                continue
            self._persist_task_packet(
                packet=packet,
                module=module,
                created_by_run_id=f"leadpkt-{uuid.uuid4()}",
                usage=usage,
            )
            break

    def _ordered_modules(self) -> list[CodingModuleProfile]:
        return sorted(
            self.modules_by_id.values(),
            key=lambda module: (-int(module.priority), module.module_id),
        )

    def _dispatch_ready_task(self) -> None:
        self._last_dispatch_at = self._now()
        if self._worker_thread and self._worker_thread.is_alive():
            return
        if self.store.get_active_coding_task() is not None:
            self._reconcile_orphaned_active_tasks(
                reason="Coding task lost its worker context and was blocked for safety.",
                event_type="worker_context_lost",
            )
        if self.store.get_active_coding_task() is not None:
            return
        ready_tasks = self.store.list_coding_tasks_by_status(["ready"])
        if not ready_tasks:
            return
        task = ready_tasks[0]
        self._start_task_worker(task)

    def _generate_task_packet(
        self,
        module: CodingModuleProfile,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        executive = self.executive_report_provider()
        module_context = self._build_module_context(module)
        executive_context = {
            "strategic_goal": executive.get("strategic_goal"),
            "module_summary": next(
                (item for item in executive.get("modules", []) if item["id"] == module.module_id),
                {},
            ),
            "recent_changes": executive.get("recent_changes", [])[:3],
            "blockers": executive.get("blockers", [])[:3],
        }
        packet, usage = self.agent_runtime.generate_coding_task_packet(
            module_context=module_context,
            executive_context=executive_context,
        )
        validated = self._validate_task_packet(module=module, packet=packet)
        return validated, usage

    def _persist_task_packet(
        self,
        *,
        packet: dict[str, Any],
        module: CodingModuleProfile,
        created_by_run_id: str,
        usage: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._now()
        task_id = f"code-{uuid.uuid4()}"
        record = {
            "task_id": task_id,
            "module_id": packet["module_id"],
            "owner_agent": packet["owner_agent"],
            "goal": packet["goal"],
            "business_reason": packet["business_reason"],
            "owned_scope": packet["owned_scope"],
            "read_only_context": packet["read_only_context"],
            "target_files": packet["target_files"],
            "forbidden_paths": packet["forbidden_paths"],
            "risk_level": packet["risk_level"],
            "acceptance_checks": packet["acceptance_checks"],
            "required_tests": packet["required_tests"],
            "definition_of_done": packet["definition_of_done"],
            "created_by_run_id": created_by_run_id,
            "status": "ready",
            "attempt_count": 0,
            "review_attempt_count": 0,
            "planning_cost_usd": float(usage.get("estimated_cost_usd", 0.0)),
            "coding_cost_usd": 0.0,
            "review_cost_usd": 0.0,
            "total_cost_usd": float(usage.get("estimated_cost_usd", 0.0)),
            "created_at": now,
            "updated_at": now,
        }
        self.store.create_coding_task(record)
        self.store.add_coding_task_event(
            {
                "event_id": str(uuid.uuid4()),
                "task_id": task_id,
                "event_type": "task_created",
                "payload": {
                    "module_id": module.module_id,
                    "goal": packet["goal"],
                    "target_files": packet["target_files"],
                },
                "created_at": now,
            }
        )
        return self.get_coding_task(task_id)

    def _execute_task(self, task: dict[str, Any], review_feedback: list[str] | None = None) -> dict[str, Any]:
        info = self.worktree_manager.create_workspace(
            task_id=task["task_id"],
            agent_name=task["owner_agent"],
            base_ref=task.get("base_ref") or "main",
        )
        self.store.create_coding_workspace(
            {
                "task_id": task["task_id"],
                "agent_name": task["owner_agent"],
                "worktree_path": info.worktree_path,
                "branch_name": info.branch_name,
                "base_ref": info.base_ref,
                "base_commit": info.base_commit,
                "changed_files": [],
                "diff_text": "",
                "check_results": {},
                "status": "coding",
                "created_at": self._now(),
                "updated_at": self._now(),
            }
        )
        self.store.update_coding_task(
            task["task_id"],
            status="coding",
            worktree_path=info.worktree_path,
            branch_name=info.branch_name,
            base_ref=info.base_ref,
            base_commit=info.base_commit,
            started_at=self._now(),
            attempt_count=int(task.get("attempt_count", 0)) + 1,
        )
        self.store.add_coding_task_event(
            {
                "event_id": str(uuid.uuid4()),
                "task_id": task["task_id"],
                "event_type": "dispatch",
                "payload": {"branch": info.branch_name, "worktree_path": info.worktree_path},
                "created_at": self._now(),
            }
        )

        file_contexts = self.worktree_manager.collect_file_contexts(
            worktree_path=Path(info.worktree_path),
            target_files=task["target_files"],
            read_only_context=task["read_only_context"],
        )
        change_output, coding_usage = self.agent_runtime.generate_coding_change(
            agent_name=task["owner_agent"],
            task_packet=self._task_packet_from_record(task),
            file_contexts=file_contexts,
            review_feedback=review_feedback,
        )
        self._ensure_task_active(task["task_id"])
        self._apply_coding_changes(task, info, change_output)
        self._ensure_task_active(task["task_id"])
        diff_text = self.worktree_manager.show_git_diff(worktree_path=Path(info.worktree_path))
        changed_files = self.worktree_manager.changed_files(worktree_path=Path(info.worktree_path))
        check_results = self.worktree_manager.run_allowed_checks(
            worktree_path=Path(info.worktree_path),
            commands=task["required_tests"],
        )
        self.store.update_coding_workspace(
            task["task_id"],
            changed_files=changed_files,
            diff_text=diff_text,
            check_results=check_results,
            status="review",
        )
        self.store.update_coding_task(
            task["task_id"],
            status="review",
            diff_summary=change_output["summary"],
            check_results=check_results,
            coding_cost_usd=float(coding_usage.get("estimated_cost_usd", 0.0)),
            total_cost_usd=(
                float(task.get("planning_cost_usd", 0.0))
                + float(coding_usage.get("estimated_cost_usd", 0.0))
            ),
        )

        review_output, review_usage = self.agent_runtime.review_coding_change(
            task_packet=self._task_packet_from_record(self.get_coding_task(task["task_id"])),
            diff_text=diff_text,
            check_results=check_results,
            change_summary=change_output["summary"],
        )
        self._ensure_task_active(task["task_id"])
        updated_task = self.get_coding_task(task["task_id"])
        total_cost = (
            float(updated_task.get("planning_cost_usd", 0.0))
            + float(updated_task.get("coding_cost_usd", 0.0))
            + float(review_usage.get("estimated_cost_usd", 0.0))
        )
        self.store.update_coding_task(
            task["task_id"],
            review_json=review_output,
            review_cost_usd=float(review_usage.get("estimated_cost_usd", 0.0)),
            total_cost_usd=total_cost,
        )
        self.store.add_coding_task_event(
            {
                "event_id": str(uuid.uuid4()),
                "task_id": task["task_id"],
                "event_type": "review_result",
                "payload": {
                    "decision": review_output["decision"],
                    "risk_level": review_output.get("risk_level"),
                    "required_changes": review_output.get("required_changes", []),
                },
                "created_at": self._now(),
            }
        )

        if review_output["decision"] == "approve":
            return self.approve_review(task["task_id"])

        if review_output["decision"] == "revise":
            review_attempt_count = int(updated_task.get("review_attempt_count", 0)) + 1
            if review_attempt_count >= 2:
                self.store.update_coding_task(
                    task["task_id"],
                    status="blocked",
                    review_attempt_count=review_attempt_count,
                    last_error="Review rejected the task twice.",
                    finished_at=self._now(),
                )
                return self.get_coding_task(task["task_id"])
            self.store.update_coding_task(
                task["task_id"],
                status="coding",
                review_attempt_count=review_attempt_count,
            )
            return self._execute_task(
                self.get_coding_task(task["task_id"]),
                review_feedback=review_output.get("required_changes", []),
            )

        self.store.update_coding_task(
            task["task_id"],
            status="review",
            last_error="Human review required before commit.",
        )
        return self.get_coding_task(task["task_id"])

    def _start_task_worker(self, task: dict[str, Any]) -> None:
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return
            self._worker_task_id = task["task_id"]
            self._worker_started_monotonic = time.monotonic()
            self._worker_thread = threading.Thread(
                target=self._execute_task_worker,
                args=(task["task_id"],),
                name=f"crypto-coding-task-{task['task_id'][:8]}",
                daemon=True,
            )
            self._worker_thread.start()
        logger.info(
            "Coding task worker started.",
            extra={
                "event": "coding_task_worker_started",
                "task_id": task["task_id"],
                "agent_name": task["owner_agent"],
            },
        )

    def _execute_task_worker(self, task_id: str) -> None:
        try:
            task = self.get_coding_task(task_id)
            self._execute_task(task)
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            logger.exception(
                "Coding task worker failed.",
                extra={"event": "coding_task_worker_failed", "task_id": task_id},
            )
            self._mark_task_blocked(
                task_id,
                reason=str(exc),
                event_type="failed",
            )
        finally:
            with self._lock:
                if self._worker_task_id == task_id:
                    self._worker_task_id = None
                    self._worker_started_monotonic = None
                    self._worker_thread = None

    def _reconcile_worker_state(self) -> None:
        with self._lock:
            worker = self._worker_thread
            worker_task_id = self._worker_task_id
            worker_started_monotonic = self._worker_started_monotonic

        if worker is None:
            return

        if worker.is_alive():
            if (
                worker_task_id
                and worker_started_monotonic is not None
                and (time.monotonic() - worker_started_monotonic) > self._coding_task_timeout_seconds()
            ):
                reason = (
                    "Coding task exceeded the configured timeout and was blocked for safety."
                )
                self._last_error = reason
                logger.warning(
                    "Coding task timed out.",
                    extra={"event": "coding_task_timeout", "task_id": worker_task_id},
                )
                self._mark_task_blocked(
                    worker_task_id,
                    reason=reason,
                    event_type="timeout",
                )
                with self._lock:
                    if self._worker_task_id == worker_task_id:
                        self._worker_task_id = None
                        self._worker_started_monotonic = None
                        self._worker_thread = None
            return

        with self._lock:
            self._worker_task_id = None
            self._worker_started_monotonic = None
            self._worker_thread = None

    def _reconcile_orphaned_active_tasks(self, *, reason: str, event_type: str) -> None:
        active_tasks = self.store.list_coding_tasks_by_status(list(ACTIVE_CODING_STATUSES))
        for task in active_tasks:
            if self._worker_task_id and task["task_id"] == self._worker_task_id:
                continue
            self._mark_task_blocked(task["task_id"], reason=reason, event_type=event_type)

    def _mark_task_blocked(self, task_id: str, *, reason: str, event_type: str) -> None:
        task = self.store.get_coding_task(task_id)
        if task is None or task.get("status") in FINAL_CODING_STATUSES:
            return
        now = self._now()
        self.store.update_coding_task(
            task_id,
            status="blocked",
            last_error=reason,
            finished_at=now,
        )
        workspace = self.store.get_coding_workspace(task_id)
        if workspace is not None:
            self.store.update_coding_workspace(
                task_id,
                status="blocked",
            )
        self.store.add_coding_task_event(
            {
                "event_id": str(uuid.uuid4()),
                "task_id": task_id,
                "event_type": event_type,
                "payload": {"reason": reason},
                "created_at": now,
            }
        )

    def _ensure_task_active(self, task_id: str) -> None:
        task = self.get_coding_task(task_id)
        if task["status"] not in ACTIVE_CODING_STATUSES:
            raise RuntimeError(
                f"Coding task {task_id} is no longer active (status={task['status']})."
            )

    def _coding_task_timeout_seconds(self) -> int:
        explicit_timeout = getattr(self.settings, "agent_coding_task_timeout_seconds", None)
        if explicit_timeout is not None:
            return int(explicit_timeout)
        return int(getattr(self.settings, "agent_run_timeout_seconds", 180))

    def _task_age_seconds(self, task: dict[str, Any] | None) -> float | None:
        if task is None:
            return None
        timestamp = task.get("started_at") or task.get("updated_at") or task.get("created_at")
        if not timestamp:
            return None
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            return None
        return max(0.0, round((datetime.now(timezone.utc) - parsed).total_seconds(), 2))

    def _apply_coding_changes(
        self,
        task: dict[str, Any],
        info: WorktreeInfo,
        change_output: dict[str, Any],
    ) -> None:
        allowed_targets = set(task["target_files"])
        owned_scope = task["owned_scope"]
        for edit in change_output.get("file_edits", []):
            path = edit["path"]
            in_scope = any(path == target or path.startswith(f"{target.rstrip('/')}/") for target in allowed_targets)
            if not in_scope:
                in_scope = any(path.startswith(scope.rstrip("/") + "/") or path == scope.rstrip("/") for scope in owned_scope)
            if not in_scope:
                raise RuntimeError(f"Coding agent attempted to edit path outside task scope: {path}")
            if any(path == forbidden or path.startswith(f"{forbidden.rstrip('/')}/") for forbidden in task["forbidden_paths"]):
                raise RuntimeError(f"Coding agent attempted forbidden path: {path}")
            self.worktree_manager.write_allowed_file(
                path=path,
                worktree_path=Path(info.worktree_path),
                content=edit["content"],
            )

    def _build_module_context(self, module: CodingModuleProfile) -> dict[str, Any]:
        manifest_entry = self.scope_manifest["agents"][module.owner_agent]
        return {
            "module_id": module.module_id,
            "title": module.title,
            "owner_agent": module.owner_agent,
            "module_summary": module.module_summary,
            "owned_scope": manifest_entry.get("owned_scope", []),
            "read_only_scope": manifest_entry.get("read_only_scope", []),
            "forbidden_paths": list(
                dict.fromkeys(
                    self.scope_manifest.get("rules", {}).get("sensitive_paths", [])
                    + manifest_entry.get("forbidden_scope", [])
                )
            ),
            "read_only_context": module.read_only_context,
            "target_candidates": module.target_candidates,
            "acceptance_checks": module.acceptance_checks,
            "required_tests": module.required_tests,
            "definition_of_done": module.definition_of_done,
        }

    def _validate_task_packet(
        self,
        *,
        module: CodingModuleProfile,
        packet: dict[str, Any],
    ) -> dict[str, Any] | None:
        manifest_entry = self.scope_manifest["agents"][module.owner_agent]
        owned_scope = list(manifest_entry.get("owned_scope", []))
        forbidden_paths = list(
            dict.fromkeys(
                self.scope_manifest.get("rules", {}).get("sensitive_paths", [])
                + manifest_entry.get("forbidden_scope", [])
            )
        )
        target_files = list(dict.fromkeys(packet.get("target_files", [])))
        if not target_files or len(target_files) > int(self.runtime_config.get("max_target_files", 6)):
            return None
        for path in target_files:
            if path.endswith("/"):
                return None
            if not any(path.startswith(scope.rstrip("/") + "/") or path == scope.rstrip("/") for scope in owned_scope):
                return None
            if any(path == forbidden or path.startswith(f"{forbidden.rstrip('/')}/") for forbidden in forbidden_paths):
                return None
        risk_level = packet.get("risk_level", "low")
        if risk_level not in {"low", "medium"}:
            risk_level = "medium"
        return {
            "summary": packet.get("summary", module.module_summary),
            "module_id": module.module_id,
            "owner_agent": module.owner_agent,
            "goal": packet.get("goal", module.module_summary),
            "business_reason": packet.get("business_reason", module.module_summary),
            "owned_scope": owned_scope,
            "read_only_context": list(
                dict.fromkeys(
                    [
                        path
                        for path in packet.get("read_only_context", [])
                        if path in module.read_only_context
                    ]
                    or module.read_only_context
                )
            ),
            "target_files": target_files,
            "forbidden_paths": forbidden_paths,
            "risk_level": risk_level,
            "acceptance_checks": packet.get("acceptance_checks") or module.acceptance_checks,
            "required_tests": packet.get("required_tests") or module.required_tests,
            "definition_of_done": packet.get("definition_of_done") or module.definition_of_done,
            "warnings": packet.get("warnings", []),
            "review_required": True,
            "human_decision_required": False,
        }

    def _build_manual_task_packet(
        self,
        *,
        module: CodingModuleProfile,
        goal_override: str | None,
        business_reason: str | None,
    ) -> dict[str, Any]:
        manifest_entry = self.scope_manifest["agents"][module.owner_agent]
        file_candidates = [candidate for candidate in module.target_candidates if not candidate.endswith("/")]
        if not file_candidates:
            file_candidates = module.target_candidates[:1]
        return {
            "summary": module.module_summary,
            "module_id": module.module_id,
            "owner_agent": module.owner_agent,
            "goal": goal_override or module.module_summary,
            "business_reason": business_reason or module.module_summary,
            "owned_scope": list(manifest_entry.get("owned_scope", [])),
            "read_only_context": module.read_only_context,
            "target_files": file_candidates[:2],
            "forbidden_paths": list(
                dict.fromkeys(
                    self.scope_manifest.get("rules", {}).get("sensitive_paths", [])
                    + manifest_entry.get("forbidden_scope", [])
                )
            ),
            "risk_level": "low",
            "acceptance_checks": module.acceptance_checks,
            "required_tests": module.required_tests,
            "definition_of_done": module.definition_of_done,
        }

    def _task_packet_from_record(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task["task_id"],
            "module_id": task["module_id"],
            "owner_agent": task["owner_agent"],
            "goal": task["goal"],
            "business_reason": task["business_reason"],
            "owned_scope": task["owned_scope_json"],
            "read_only_context": task["read_only_context_json"],
            "target_files": task["target_files_json"],
            "forbidden_paths": task["forbidden_paths_json"],
            "risk_level": task["risk_level"],
            "acceptance_checks": task["acceptance_checks_json"],
            "required_tests": task["required_tests_json"],
            "definition_of_done": task["definition_of_done_json"],
        }

    def _require_module(self, module_id: str) -> CodingModuleProfile:
        try:
            return self.modules_by_id[module_id]
        except KeyError as exc:
            raise KeyError(f"Unknown coding module: {module_id}") from exc

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
