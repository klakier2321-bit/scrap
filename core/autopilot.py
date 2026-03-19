"""Continuous planning autopilot for safe long-running agent work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import time
from typing import Any

import yaml


logger = logging.getLogger(__name__)
ACTIVE_RUN_STATUSES = {"queued", "running", "awaiting_approval"}


@dataclass(frozen=True)
class AutopilotTask:
    """One recurring task definition for the autopilot loop."""

    name: str
    payload: dict[str, Any]
    auto_approve: bool = False
    allow_parallel: bool = False


class AutopilotService:
    """Runs a safe background loop that submits recurring planning tasks."""

    def __init__(self, *, orchestrator: Any, config_path: Path, poll_interval_seconds: int) -> None:
        self.orchestrator = orchestrator
        self.config_path = config_path
        self.default_poll_interval_seconds = poll_interval_seconds
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cycle_index = 0
        self._cycle_count = 0
        self._current_task_name: str | None = None
        self._current_run_id: str | None = None
        self._last_run_id: str | None = None
        self._last_status: str | None = None
        self._last_error: str | None = None
        self._last_started_at: str | None = None
        self._loaded_config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            logger.warning(
                "Autopilot config file does not exist.",
                extra={"event": "autopilot_config_missing", "config_path": str(self.config_path)},
            )
            return {
                "objective": "Autopilot config missing.",
                "auto_start": False,
                "poll_interval_seconds": self.default_poll_interval_seconds,
                "max_cycles": 0,
                "tasks": [],
            }

        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        config = raw.get("autopilot", {})
        tasks: list[AutopilotTask] = []
        for item in config.get("tasks", []):
            payload = {
                "agent_name": item["agent_name"],
                "goal": item["goal"],
                "business_reason": item.get("business_reason", ""),
                "requested_paths": item.get("requested_paths", []),
                "risk_level": item.get("risk_level", "low"),
                "cross_layer": bool(item.get("cross_layer", False)),
                "does_touch_contract": bool(item.get("does_touch_contract", False)),
                "does_touch_runtime": bool(item.get("does_touch_runtime", False)),
                "force_strong_model": bool(item.get("force_strong_model", False)),
                "metadata": {
                    "autopilot": True,
                    "autopilot_task": item["name"],
                },
            }
            tasks.append(
                AutopilotTask(
                    name=item["name"],
                    payload=payload,
                    auto_approve=bool(item.get("auto_approve", False)),
                    allow_parallel=bool(item.get("allow_parallel", False)),
                )
            )

        return {
            "objective": config.get("objective", ""),
            "auto_start": bool(config.get("auto_start", False)),
            "poll_interval_seconds": int(
                config.get("poll_interval_seconds", self.default_poll_interval_seconds)
            ),
            "max_cycles": int(config.get("max_cycles", 0)),
            "tasks": tasks,
        }

    def reload(self) -> None:
        with self._lock:
            self._loaded_config = self._load_config()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self.reload()
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="crypto-autopilot",
                daemon=True,
            )
            self._thread.start()
        logger.info(
            "Autopilot started.",
            extra={"event": "autopilot_started", "objective": self._loaded_config["objective"]},
        )
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        current_run_id = self._current_run_id
        if current_run_id:
            try:
                self.orchestrator.stop_run(current_run_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to stop the current autopilot run.",
                    extra={"event": "autopilot_stop_current_run_failed", "run_id": current_run_id},
                )
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("Autopilot stop requested.", extra={"event": "autopilot_stop_requested"})
        return self.status()

    def status(self) -> dict[str, Any]:
        self._sync_active_run_state()
        tasks: list[AutopilotTask] = self._loaded_config.get("tasks", [])
        next_task_name = tasks[self._cycle_index % len(tasks)].name if tasks else None
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "objective": self._loaded_config.get("objective", ""),
            "poll_interval_seconds": int(self._loaded_config.get("poll_interval_seconds", 0)),
            "max_cycles": int(self._loaded_config.get("max_cycles", 0)),
            "cycle_count": self._cycle_count,
            "current_task_name": self._current_task_name,
            "current_run_id": self._current_run_id,
            "last_run_id": self._last_run_id,
            "last_status": self._last_status,
            "last_error": self._last_error,
            "last_started_at": self._last_started_at,
            "task_names": [task.name for task in tasks],
            "next_task_name": next_task_name,
            "config_path": str(self.config_path),
        }

    def _sync_active_run_state(self) -> None:
        active = self._active_runs()
        if not active:
            self._current_run_id = None
            if self._current_task_name and not (self._thread and self._thread.is_alive()):
                self._current_task_name = None
            return

        current = active[0]
        self._current_run_id = current["run_id"]
        payload = current.get("payload_json") or {}
        metadata = payload.get("metadata") or {}
        task_name = metadata.get("autopilot_task")
        if task_name:
            self._current_task_name = str(task_name)

    def _active_runs(self) -> list[dict[str, Any]]:
        runs = self.orchestrator.list_runs(limit=50)
        return [run for run in runs if run.get("status") in ACTIVE_RUN_STATUSES]

    def _active_autopilot_task_names(self, runs: list[dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for run in runs:
            payload = run.get("payload_json") or {}
            metadata = payload.get("metadata") or {}
            task_name = metadata.get("autopilot_task")
            if task_name:
                names.add(str(task_name))
        return names

    def _select_next_task(
        self,
        tasks: list[AutopilotTask],
        *,
        active_task_names: set[str],
        active_count: int,
        max_parallel_runs: int,
    ) -> tuple[int, AutopilotTask] | None:
        if not tasks or active_count >= max_parallel_runs:
            return None

        for offset in range(len(tasks)):
            index = (self._cycle_index + offset) % len(tasks)
            task = tasks[index]
            if task.name in active_task_names:
                continue
            if active_count > 0 and not task.allow_parallel:
                continue
            return index, task
        return None

    def _sleep_until_next_cycle(self, seconds: int) -> None:
        deadline = time.time() + max(seconds, 1)
        while time.time() < deadline and not self._stop_event.is_set():
            time.sleep(1)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            config = self._loaded_config
            tasks: list[AutopilotTask] = config.get("tasks", [])

            if not tasks:
                self._last_error = "No autopilot tasks are configured."
                self._sleep_until_next_cycle(config.get("poll_interval_seconds", 60))
                continue

            max_cycles = int(config.get("max_cycles", 0))
            if max_cycles > 0 and self._cycle_count >= max_cycles:
                logger.info(
                    "Autopilot reached the configured max cycle count.",
                    extra={"event": "autopilot_max_cycles_reached", "cycle_count": self._cycle_count},
                )
                self._stop_event.set()
                break

            if self.orchestrator.settings.agent_kill_switch:
                self._last_error = "Agent kill switch is enabled."
                self._sleep_until_next_cycle(config.get("poll_interval_seconds", 60))
                continue

            active_runs = self._active_runs()
            active_count = len(active_runs)
            if active_runs:
                self._current_run_id = active_runs[0]["run_id"]
            else:
                self._current_run_id = None

            max_parallel_runs = max(1, int(self.orchestrator.settings.agent_max_parallel_runs))
            selection = self._select_next_task(
                tasks,
                active_task_names=self._active_autopilot_task_names(active_runs),
                active_count=active_count,
                max_parallel_runs=max_parallel_runs,
            )
            if selection is None:
                self._sleep_until_next_cycle(5)
                continue

            next_index, task = selection
            payload = dict(task.payload)
            payload["metadata"] = dict(payload.get("metadata", {}))
            payload["metadata"]["autopilot_cycle"] = self._cycle_count + 1
            payload["metadata"]["autopilot_started_at"] = datetime.now(timezone.utc).isoformat()
            payload["metadata"]["idempotency_key"] = (
                f"{task.name}-cycle-{self._cycle_count + 1}-{int(time.time())}"
            )

            self._current_task_name = task.name
            self._last_started_at = datetime.now(timezone.utc).isoformat()
            self._last_error = None

            logger.info(
                "Autopilot dispatching task.",
                extra={
                    "event": "autopilot_dispatch",
                    "task_name": task.name,
                    "agent_name": payload["agent_name"],
                    "cycle_count": self._cycle_count + 1,
                },
            )

            try:
                record = self.orchestrator.create_agent_run(payload)
                if record.get("status") == "awaiting_approval" and task.auto_approve:
                    record = self.orchestrator.approve_run(record["run_id"])
                self._last_run_id = record.get("run_id")
                self._last_status = record.get("status")
                self._last_error = record.get("error") or record.get("blocked_reason")
                self._current_run_id = (
                    record.get("run_id") if record.get("status") in ACTIVE_RUN_STATUSES else None
                )
            except Exception as exc:  # noqa: BLE001
                self._last_status = "failed"
                self._last_error = str(exc)
                logger.exception(
                    "Autopilot task failed.",
                    extra={"event": "autopilot_task_failed", "task_name": task.name},
                )

            self._cycle_count += 1
            self._cycle_index = (next_index + 1) % len(tasks)
            self._sync_active_run_state()
            if self._current_run_id is None:
                self._current_task_name = None
            remaining_capacity = max_parallel_runs - len(self._active_runs())
            if remaining_capacity > 0:
                self._sleep_until_next_cycle(1)
            else:
                self._sleep_until_next_cycle(config.get("poll_interval_seconds", 60))
            self._sync_active_run_state()
            if self._current_run_id is None:
                self._current_task_name = None
