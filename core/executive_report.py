"""Executive roadmap and management reporting for Grafana dashboards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


class ExecutiveReportService:
    """Builds a CEO-friendly view of modules, tasks, risks, and decisions."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.config_path = repo_root / "ai_agents" / "config" / "executive_roadmap.yaml"

    def _load_config(self) -> dict[str, Any]:
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return raw.get("executive_dashboard", {})

    def _is_closed_task(self, status: str | None) -> bool:
        return (status or "").strip().lower() in {"zamkniete", "zamknięte", "gotowe", "domkniete", "domknięte"}

    def _parse_iso(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _format_timestamp(self, value: Any) -> str:
        parsed = self._parse_iso(value)
        if parsed is None:
            return "brak danych"
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def _matches_scope(self, candidate: str, scope_rule: str) -> bool:
        normalized_candidate = candidate.lstrip("./")
        normalized_rule = scope_rule.lstrip("./")
        if not normalized_rule:
            return False
        if normalized_rule.endswith("/"):
            return normalized_candidate.startswith(normalized_rule)
        return (
            normalized_candidate == normalized_rule
            or normalized_candidate.startswith(f"{normalized_rule}/")
        )

    def _module_ids_for_paths(self, requested_paths: list[str], modules: list[dict[str, Any]]) -> set[str]:
        matched: set[str] = set()
        for module in modules:
            for requested_path in requested_paths:
                if any(
                    self._matches_scope(requested_path, path_rule)
                    or path_rule in requested_path
                    for path_rule in module.get("paths", [])
                ):
                    matched.add(module["id"])
                    break
        return matched

    def _derive_change_effect(self, run: dict[str, Any]) -> str:
        if run.get("status") == "completed":
            result = run.get("result_json") or {}
            summary = result.get("summary")
            if summary:
                return str(summary)
            review = run.get("review_json") or {}
            findings = review.get("main_findings") or []
            if findings:
                return str(findings[0])
            return "Run zakończył się poprawnie i dostarczył kolejny krok lub wniosek."
        if run.get("status") == "awaiting_approval":
            return "Run czeka na akceptację przed wykonaniem kolejnego kroku."
        if run.get("status") == "blocked":
            reason = run.get("blocked_reason") or run.get("error") or "zasady bezpieczeństwa"
            return f"Run został zatrzymany: {reason}."
        if run.get("status") == "failed":
            return f"Run zakończył się błędem: {run.get('error') or 'brak szczegółu'}."
        return f"Aktualny status runu: {run.get('status') or 'nieznany'}."

    def _derive_change_title(self, run: dict[str, Any]) -> str:
        payload = run.get("payload_json") or {}
        metadata = payload.get("metadata") or {}
        task_name = metadata.get("autopilot_task")
        if task_name:
            return str(task_name).replace("_", " ")
        goal = str(run.get("goal") or "").strip()
        if not goal:
            return "Aktualizacja pracy agenta"
        return goal[:140]

    def _build_recent_changes(
        self,
        runs: list[dict[str, Any]],
        modules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        interesting_statuses = {"completed", "blocked", "failed", "awaiting_approval"}
        for run in runs:
            status = run.get("status")
            if status not in interesting_statuses:
                continue
            matched_module_ids = self._module_ids_for_paths(
                (run.get("payload_json") or {}).get("requested_paths", []),
                modules,
            )
            module_id = next(iter(matched_module_ids), "general")
            module_name = next(
                (module["name"] for module in modules if module["id"] == module_id),
                "Przekrojowo przez projekt",
            )
            changes.append(
                {
                    "change_id": run["run_id"],
                    "module_id": module_id,
                    "module_name": module_name,
                    "agent_name": run.get("agent_name", "unknown"),
                    "title": self._derive_change_title(run),
                    "status": status,
                    "effect": self._derive_change_effect(run),
                    "happened_at": self._format_timestamp(
                        run.get("finished_at") or run.get("updated_at") or run.get("created_at")
                    ),
                }
            )
            if len(changes) >= 8:
                break
        return changes

    def _build_lead_notes(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for run in runs:
            if run.get("agent_name") != "system_lead_agent":
                continue
            if run.get("status") not in {"completed", "awaiting_approval", "blocked"}:
                continue
            result = run.get("result_json") or {}
            review = run.get("review_json") or {}
            next_step = ""
            recommended_actions = result.get("recommended_actions") or []
            if recommended_actions:
                next_step = str(recommended_actions[0])
            elif review.get("required_changes"):
                next_step = str(review["required_changes"][0])

            notes.append(
                {
                    "note_id": run["run_id"],
                    "title": self._derive_change_title(run),
                    "agent_name": "system_lead_agent",
                    "status": run.get("status", "unknown"),
                    "message": self._derive_change_effect(run),
                    "next_step": next_step or "Brak kolejnego kroku w ostatnim wyniku.",
                    "updated_at": self._format_timestamp(
                        run.get("finished_at") or run.get("updated_at") or run.get("created_at")
                    ),
                }
            )
            if len(notes) >= 3:
                break
        return notes

    def _build_blockers(
        self,
        *,
        tasks: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        risks: list[dict[str, Any]],
        modules: list[dict[str, Any]],
        autopilot_status: dict[str, Any],
    ) -> list[dict[str, Any]]:
        modules_by_id = {module["id"]: module["name"] for module in modules}
        blockers: list[dict[str, Any]] = []

        for task in tasks:
            task_status = str(task.get("status", "")).strip()
            if task_status not in {"Wymaga uwagi", "Zablokowane", "W toku"} and task.get("needs_human") != "Tak":
                continue
            if task.get("needs_human") == "Tak" or task_status in {"Wymaga uwagi", "Zablokowane"}:
                blockers.append(
                    {
                        "blocker_id": f"task:{task['id']}",
                        "source": "Task",
                        "area": modules_by_id.get(task["module_id"], task["module_id"]),
                        "title": task["title"],
                        "severity": task.get("priority", "Średni"),
                        "status": task_status,
                        "why_blocking": task.get("next_step", "Wymaga doprecyzowania kolejnego kroku."),
                        "expected_action": (
                            "Potrzebna decyzja prezesa."
                            if task.get("needs_human") == "Tak"
                            else "Potrzebny kolejny mały krok i dopięcie wykonania."
                        ),
                    }
                )

        for decision in decisions:
            blockers.append(
                {
                    "blocker_id": f"decision:{decision['id']}",
                    "source": "Decyzja",
                    "area": decision["area"],
                    "title": decision["title"],
                    "severity": decision.get("priority", "Średni"),
                    "status": decision.get("status", "Oczekuje"),
                    "why_blocking": decision.get(
                        "impact",
                        "Bez tej decyzji trudniej ustawić następne kroki projektu.",
                    ),
                    "expected_action": decision.get(
                        "expected_from_ceo",
                        "Potrzebna decyzja prezesa.",
                    ),
                }
            )

        for risk in risks:
            if risk.get("severity") not in {"Wysokie", "Krytyczne"}:
                continue
            blockers.append(
                {
                    "blocker_id": f"risk:{risk['id']}",
                    "source": "Ryzyko",
                    "area": risk["area"],
                    "title": risk["title"],
                    "severity": risk["severity"],
                    "status": risk.get("status", "Otwarte"),
                    "why_blocking": risk.get(
                        "title",
                        "To ryzyko ogranicza tempo rozwoju projektu.",
                    ),
                    "expected_action": risk.get(
                        "mitigation",
                        "Potrzebny plan ograniczenia ryzyka.",
                    ),
                }
            )

        if autopilot_status.get("attention_needed"):
            blockers.append(
                {
                    "blocker_id": "autopilot:attention",
                    "source": "Autopilot",
                    "area": "CrewAI i control plane",
                    "title": "Autopilot wymaga uwagi",
                    "severity": "Wysoki",
                    "status": autopilot_status.get("last_status") or "Wymaga uwagi",
                    "why_blocking": "Warstwa ciągłej pracy agentów nie daje dziś pełnej pewności stabilnej pracy.",
                    "expected_action": "Sprawdzić ostatni run i ustabilizować kolejny cykl przed dalszym rozszerzaniem autopilota.",
                }
            )

        return blockers[:10]

    def build_report(
        self,
        *,
        runs: list[dict[str, Any]],
        autopilot_status: dict[str, Any],
        strategy_report: dict[str, Any] | None,
        dry_run_health: dict[str, Any] | None,
        dry_run_snapshot: dict[str, Any] | None,
        dry_run_smoke: dict[str, Any] | None,
        coding_status: dict[str, Any] | None = None,
        coding_tasks: list[dict[str, Any]] | None = None,
        coding_workspaces: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        config = self._load_config()
        generated_at = datetime.now(timezone.utc)
        modules = [dict(item) for item in config.get("modules", [])]
        tasks = [dict(item) for item in config.get("tasks", [])]
        decisions = [dict(item) for item in config.get("decisions", [])]
        risks = [dict(item) for item in config.get("risks", [])]
        assumptions = [dict(item) for item in config.get("assumptions", [])]
        coding_status = dict(coding_status or {})
        coding_tasks = list(coding_tasks or [])
        coding_workspaces = list(coding_workspaces or [])
        dry_run_health = dict(dry_run_health or {})
        dry_run_snapshot = dict(dry_run_snapshot or {}) if dry_run_snapshot else None
        dry_run_smoke = dict(dry_run_smoke or {}) if dry_run_smoke else None
        dry_run_ready = bool(dry_run_health.get("ready"))
        control_layer_has_commits = any(
            task.get("module_id") == "control_layer_runtime" and task.get("status") == "committed"
            for task in coding_tasks
        )

        for task in tasks:
            task_id = task.get("id")
            if dry_run_ready and task_id == "dry_run_runtime_bridge":
                task["status"] = "Zamknięte"
                task["next_step"] = "Bridge runtime, snapshoty i smoke test działają poprawnie."
            elif dry_run_ready and task_id == "dry_run_runtime_activation":
                task["status"] = "Zamknięte"
                task["next_step"] = "Freqtrade działa w prawdziwym dry_run z aktywnym wewnętrznym API."
            elif dry_run_ready and task_id == "dry_run_visibility":
                task["status"] = "Zamknięte"
                task["next_step"] = "Pulpit prezesa i panel operatora pokazują gotowość dry run oraz świeżość danych."
            elif control_layer_has_commits and task_id == "control_layer_first_coding_flow":
                task["status"] = "Zamknięte"
                task["next_step"] = "Pierwszy supervised write został dowieziony; teraz stabilizować kolejne małe taski."

        runs_by_module: dict[str, dict[str, Any]] = {
            module["id"]: {"active_runs": 0, "recent_runs_24h": 0, "last_run_status": None}
            for module in modules
        }
        cutoff = generated_at - timedelta(hours=24)

        for run in runs:
            run_created_at = self._parse_iso(run.get("created_at"))
            requested_paths = run.get("payload_json", {}).get("requested_paths", [])
            matched_module_ids = self._module_ids_for_paths(requested_paths, modules)
            for module_id in matched_module_ids:
                if run.get("status") in {"queued", "running", "awaiting_approval"}:
                    runs_by_module[module_id]["active_runs"] += 1
                if run_created_at and run_created_at >= cutoff:
                    runs_by_module[module_id]["recent_runs_24h"] += 1
                if runs_by_module[module_id]["last_run_status"] is None:
                    runs_by_module[module_id]["last_run_status"] = run.get("status")

        tasks_by_module: dict[str, list[dict[str, Any]]] = {}
        for task in tasks:
            tasks_by_module.setdefault(task["module_id"], []).append(task)

        for module in modules:
            module_id = module["id"]
            module_tasks = tasks_by_module.get(module_id, [])
            open_tasks = [task for task in module_tasks if not self._is_closed_task(task.get("status"))]
            ceo_tasks = [task for task in open_tasks if task.get("needs_human") == "Tak"]
            module.update(runs_by_module.get(module_id, {}))
            module["open_tasks"] = len(open_tasks)
            module["tasks_waiting_ceo"] = len(ceo_tasks)

        coding_tasks_by_module: dict[str, list[dict[str, Any]]] = {}
        for coding_task in coding_tasks:
            coding_tasks_by_module.setdefault(coding_task["module_id"], []).append(coding_task)

        for module in modules:
            module_id = module["id"]
            module_coding_tasks = coding_tasks_by_module.get(module_id, [])
            module["coding_tasks_total"] = len(module_coding_tasks)
            module["coding_tasks_active"] = sum(
                1 for task in module_coding_tasks if task.get("status") in {"dispatched", "coding", "review", "approved"}
            )
            module["coding_tasks_review"] = sum(
                1 for task in module_coding_tasks if task.get("status") == "review"
            )
            module["coding_tasks_committed"] = sum(
                1 for task in module_coding_tasks if task.get("status") == "committed"
            )
            latest_coding_task = next(
                (
                    task
                    for task in module_coding_tasks
                    if task.get("status") in {"coding", "review", "approved", "ready", "committed"}
                ),
                None,
            )
            module["coding_current_task"] = latest_coding_task.get("goal") if latest_coding_task else ""
            module["coding_current_status"] = latest_coding_task.get("status") if latest_coding_task else ""
            module["coding_current_owner"] = latest_coding_task.get("owner_agent") if latest_coding_task else ""

        autopilot_last_started = self._parse_iso(autopilot_status.get("last_started_at"))
        autopilot_attention_needed = False
        if not autopilot_status.get("running"):
            autopilot_attention_needed = True
        elif autopilot_last_started is not None:
            stale_after = autopilot_status.get("poll_interval_seconds", 300) + 60
            autopilot_attention_needed = (
                generated_at - autopilot_last_started
            ).total_seconds() > stale_after

        modules_by_status: dict[str, int] = {}
        for module in modules:
            modules_by_status[module["status"]] = modules_by_status.get(module["status"], 0) + 1

        open_tasks = [task for task in tasks if not self._is_closed_task(task.get("status"))]
        completed_tasks = [task for task in tasks if self._is_closed_task(task.get("status"))]
        tasks_needing_ceo = [task for task in open_tasks if task.get("needs_human") == "Tak"]
        coding_tasks_waiting_ceo = [
            task
            for task in coding_tasks
            if task.get("status") == "review"
            and (task.get("review_json") or {}).get("decision") == "human_review_required"
        ]
        waiting_decisions = [
            decision for decision in decisions if decision.get("status") not in {"Zamknięta", "Potwierdzone"}
        ]
        high_risks = [
            risk
            for risk in risks
            if risk.get("severity") in {"Wysokie", "Krytyczne"} and risk.get("status") != "Zamknięte"
        ]

        recent_changes = self._build_recent_changes(runs, modules)
        lead_notes = self._build_lead_notes(runs)
        blockers = self._build_blockers(
            tasks=open_tasks,
            decisions=waiting_decisions,
            risks=[risk for risk in risks if risk.get("status") != "Zamknięte"],
            modules=modules,
            autopilot_status={**autopilot_status, "attention_needed": autopilot_attention_needed},
        )
        for coding_task in coding_tasks_waiting_ceo[:3]:
            blockers.append(
                {
                    "blocker_id": f"coding:{coding_task['task_id']}",
                    "source": "Coding review",
                    "area": next(
                        (
                            module["name"]
                            for module in modules
                            if module["id"] == coding_task["module_id"]
                        ),
                        coding_task["module_id"],
                    ),
                    "title": coding_task["goal"],
                    "severity": "Średni",
                    "status": "Czeka na decyzję prezesa",
                    "why_blocking": "Task kodujący wymaga akceptacji review przed commitem na branchu worktree.",
                    "expected_action": "Sprawdzić diff i zdecydować: zaakceptować do commita albo odrzucić.",
                }
            )

        if dry_run_health and not dry_run_health.get("ready"):
            blockers.append(
                {
                    "blocker_id": "dry-run:not-ready",
                    "source": "Dry run",
                    "area": "Runtime tradingowy",
                    "title": "Dry run nie daje jeszcze stabilnych danych dla agentów",
                    "severity": "Wysoki",
                    "status": "Wymaga uwagi",
                    "why_blocking": (
                        dry_run_health.get("blocking_reason")
                        or "Brakuje świeżego snapshotu lub runtime nie jest jeszcze gotowy."
                    ),
                    "expected_action": "Uruchomić smoke test, potwierdzić gotowość runtime i odświeżyć snapshot.",
                }
            )

        if coding_status.get("attention_needed"):
            active_task = next(
                (
                    task
                    for task in coding_tasks
                    if task.get("status") in {"dispatched", "coding", "review", "approved"}
                ),
                None,
            )
            blockers.append(
                {
                    "blocker_id": "coding:attention-needed",
                    "source": "Coding supervisor",
                    "area": "Control layer",
                    "title": "Aktywny coding task wymaga uwagi",
                    "severity": "Wysoki",
                    "status": active_task.get("status") if active_task else "Wymaga uwagi",
                    "why_blocking": coding_status.get("last_error")
                    or "Jeden z tasków kodujących przekroczył bezpieczny czas wykonania albo utracił worker context.",
                    "expected_action": "Sprawdzić task, potwierdzić diff albo pozwolić supervisorowi zablokować go i ruszyć dalej.",
                }
            )

        active_coding_task = next(
            (
                task
                for task in coding_tasks
                if task.get("status") in {"dispatched", "coding", "review", "approved"}
            ),
            None,
        )
        last_committed_coding_task = next(
            (task for task in coding_tasks if task.get("status") == "committed"),
            None,
        )
        workspaces_by_task_id = {
            workspace["task_id"]: workspace
            for workspace in coding_workspaces
        }
        coding_summary = {
            "running": bool(coding_status.get("running")),
            "enabled": bool(coding_status.get("enabled", True)),
            "ready_total": sum(1 for task in coding_tasks if task.get("status") == "ready"),
            "review_total": sum(1 for task in coding_tasks if task.get("status") == "review"),
            "committed_total": sum(1 for task in coding_tasks if task.get("status") == "committed"),
            "blocked_total": sum(1 for task in coding_tasks if task.get("status") == "blocked"),
            "tasks_waiting_ceo_total": len(coding_tasks_waiting_ceo),
            "active_task": active_coding_task,
            "last_committed_task": last_committed_coding_task,
        }

        return {
            "title": config.get("title", "Pulpit Prezesa"),
            "subtitle": config.get("subtitle", ""),
            "strategic_goal": config.get("strategic_goal", ""),
            "generated_at": generated_at.isoformat(),
            "autopilot": {
                **autopilot_status,
                "attention_needed": autopilot_attention_needed,
            },
            "strategy_report": strategy_report,
            "dry_run": {
                "health": dry_run_health,
                "latest_snapshot": dry_run_snapshot,
                "latest_smoke": dry_run_smoke,
            },
            "assumptions": assumptions,
            "modules": modules,
            "tasks": open_tasks,
            "completed_tasks": completed_tasks[:6],
            "decisions": waiting_decisions,
            "risks": [risk for risk in risks if risk.get("status") != "Zamknięte"],
            "recent_changes": recent_changes,
            "lead_notes": lead_notes,
            "blockers": blockers,
            "coding": {
                "status": coding_status,
                "summary": coding_summary,
                "tasks": coding_tasks,
                "workspaces": coding_workspaces,
                "workspaces_by_task_id": workspaces_by_task_id,
            },
            "summary": {
                "modules_by_status": modules_by_status,
                "modules_total": len(modules),
                "open_tasks_total": len(open_tasks),
                "completed_tasks_total": len(completed_tasks),
                "tasks_needing_ceo_total": len(tasks_needing_ceo),
                "coding_tasks_ready_total": coding_summary["ready_total"],
                "coding_tasks_review_total": coding_summary["review_total"],
                "coding_tasks_committed_total": coding_summary["committed_total"],
                "coding_tasks_waiting_ceo_total": coding_summary["tasks_waiting_ceo_total"],
                "decisions_waiting_total": len(waiting_decisions),
                "high_risks_total": len(high_risks),
                "active_agent_runs_total": sum(
                    1 for run in runs if run.get("status") in {"queued", "running", "awaiting_approval"}
                ),
                "blockers_total": len(blockers),
                "autopilot_attention_needed": 1 if autopilot_attention_needed else 0,
                "dry_run_ready": 1 if dry_run_ready else 0,
            },
        }
