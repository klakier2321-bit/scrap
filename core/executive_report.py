"""Executive roadmap and management reporting for Grafana dashboards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


class ExecutiveReportService:
    """Builds a CEO-friendly view of modules, tasks, risks, and decisions."""

    _INACTIVE_RISK_STATUSES = {"zamknięte", "zamkniete", "monitorowane", "kontrolowane", "ograniczone"}

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

    def _is_active_risk(self, risk: dict[str, Any]) -> bool:
        return str(risk.get("status", "")).strip().lower() not in self._INACTIVE_RISK_STATUSES

    def _recent_mock_fallback_count(self, runs: list[dict[str, Any]], *, limit: int = 40) -> int:
        count = 0
        for run in runs[:limit]:
            warnings = run.get("warnings_json") or []
            text = " ".join(
                str(part)
                for part in (
                    *warnings,
                    run.get("error") or "",
                    run.get("blocked_reason") or "",
                )
            ).lower()
            if "mock_fallback" in text:
                count += 1
        return count

    def _normalize_risks(
        self,
        *,
        risks: list[dict[str, Any]],
        runs: list[dict[str, Any]],
        autopilot_status: dict[str, Any],
        autopilot_attention_needed: bool,
        dry_run_health: dict[str, Any],
    ) -> list[dict[str, Any]]:
        normalized = [dict(risk) for risk in risks]
        recent_mock_fallbacks = self._recent_mock_fallback_count(runs)
        dry_run_guardrails_active = bool(
            dry_run_health.get("ready") and dry_run_health.get("runtime_mode") == "dry_run"
        )

        for risk in normalized:
            risk_id = risk.get("id")
            if risk_id == "autopilot_fallback":
                if autopilot_status.get("running") and not autopilot_attention_needed and recent_mock_fallbacks == 0:
                    risk["status"] = "Monitorowane"
                    risk["mitigation"] = (
                        "W ostatnich runach nie widać mock fallback. Utrzymać obserwację jakości structured output "
                        "i przywrócić alert dopiero wtedy, gdy fallback wróci."
                    )
                else:
                    risk["status"] = "Otwarte"
                    risk["mitigation"] = (
                        "Utrzymać działającą pętlę, ale dopracować integrację z realnym modelem i structured output, "
                        "żeby lead agent raportował stabilnie bez awaryjnego fallbacku."
                    )

            if risk_id == "strategy_overreach" and dry_run_guardrails_active:
                risk["status"] = "Kontrolowane"
                risk["mitigation"] = (
                    "Guardraile są aktywne: system działa w dry_run, agenci dostają tylko read-only dane runtime, "
                    "a droga do live tradingu nadal wymaga review i decyzji człowieka."
                )

        return normalized

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
        candidate_assessments: list[dict[str, Any]] | None = None,
        candidate_dry_run: dict[str, Any] | None = None,
        regime_report: dict[str, Any] | None = None,
        derivatives_report: dict[str, Any] | None = None,
        risk_decision: dict[str, Any] | None = None,
        regime_replay_report: dict[str, Any] | None = None,
        strategy_layer_report: dict[str, Any] | None = None,
        control_status: dict[str, Any] | None = None,
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
        candidate_assessments = list(candidate_assessments or [])
        candidate_dry_run = dict(candidate_dry_run or {}) if candidate_dry_run else None
        regime_report = dict(regime_report or {}) if regime_report else None
        derivatives_report = dict(derivatives_report or {}) if derivatives_report else None
        risk_decision = dict(risk_decision or {}) if risk_decision else None
        regime_replay_report = dict(regime_replay_report or {}) if regime_replay_report else None
        strategy_layer_report = dict(strategy_layer_report or {}) if strategy_layer_report else None
        control_status = dict(control_status or {}) if control_status else None
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
            total_module_tasks = len(module_tasks)
            closed_module_tasks = sum(
                1 for task in module_tasks if self._is_closed_task(task.get("status"))
            )
            open_tasks = [task for task in module_tasks if not self._is_closed_task(task.get("status"))]
            ceo_tasks = [task for task in open_tasks if task.get("needs_human") == "Tak"]
            module.update(runs_by_module.get(module_id, {}))
            module["declared_progress_pct"] = float(module.get("progress_pct", 0.0))
            if total_module_tasks > 0:
                module["live_progress_pct"] = round((closed_module_tasks / total_module_tasks) * 100.0, 2)
                module["progress_pct"] = module["live_progress_pct"]
                module["progress_source"] = "roadmap_tasks"
            else:
                module["live_progress_pct"] = float(module.get("progress_pct", 0.0))
                module["progress_source"] = "declared"
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
            module["coding_tasks_branch_only"] = sum(
                1 for task in module_coding_tasks if task.get("status") == "committed"
            )
            module["coding_tasks_merged_to_main"] = sum(
                1 for task in module_coding_tasks if task.get("merged_to_main") is True
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
        risks = self._normalize_risks(
            risks=risks,
            runs=runs,
            autopilot_status=autopilot_status,
            autopilot_attention_needed=autopilot_attention_needed,
            dry_run_health=dry_run_health,
        )
        high_risks = [
            risk
            for risk in risks
            if risk.get("severity") in {"Wysokie", "Krytyczne"} and self._is_active_risk(risk)
        ]

        recent_changes = self._build_recent_changes(runs, modules)
        lead_notes = self._build_lead_notes(runs)
        blockers = self._build_blockers(
            tasks=open_tasks,
            decisions=waiting_decisions,
            risks=[risk for risk in risks if self._is_active_risk(risk)],
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

        shipping_candidate = next(
            (
                candidate
                for candidate in candidate_assessments
                if candidate.get("lifecycle_status") in {"limited_dry_run_candidate", "frozen_pending_regime_engine"}
                and candidate.get("candidate_bot_id")
            ),
            None,
        )
        selector_candidate = next(
            (
                candidate
                for candidate in sorted(
                    candidate_assessments,
                    key=lambda item: (
                        item.get("selector_rank") if item.get("selector_rank") is not None else 999,
                        item.get("candidate_id", ""),
                    ),
                )
                if candidate.get("selector_status") == "allowed"
                and (candidate.get("runtime_policy") or {}).get("entry_allowed") is True
            ),
            None,
        )
        selector_decision = {
            "selected_candidate_id": selector_candidate.get("candidate_id") if selector_candidate else None,
            "selected_candidate_rank": selector_candidate.get("selector_rank") if selector_candidate else None,
            "selected_strategy_name": selector_candidate.get("strategy_name") if selector_candidate else None,
            "risk_regime": (regime_report or {}).get("risk_regime"),
            "execution_constraints": (regime_report or {}).get("execution_constraints") or {},
            "strategy_priority_order": (regime_report or {}).get("strategy_priority_order") or [],
            "entry_allowed": bool((selector_candidate or {}).get("runtime_policy", {}).get("entry_allowed")),
            "trading_mode": (risk_decision or {}).get("trading_mode"),
            "allowed_directions": (risk_decision or {}).get("allowed_directions") or [],
            "leverage_cap": (risk_decision or {}).get("leverage_cap"),
            "data_trust_level": (risk_decision or {}).get("data_trust_level"),
            "cooldown_active": bool((risk_decision or {}).get("cooldown_active")),
            "execution_budget_multiplier": (risk_decision or {}).get("execution_budget_multiplier"),
            "hard_enforcement_enabled": bool((risk_decision or {}).get("hard_enforcement_enabled")),
            "last_enforcement_status": (risk_decision or {}).get("last_enforcement_status"),
            "last_blocked_order_reason_codes": (risk_decision or {}).get("last_blocked_order_reason_codes") or [],
        }
        if shipping_candidate and shipping_candidate.get("dry_run_gate_status") not in {"ready", "telemetry_ready"}:
            blockers.append(
                {
                    "blocker_id": f"candidate:{shipping_candidate['candidate_id']}",
                    "source": "Candidate factory",
                    "area": "Strategie futures",
                    "title": "Shipping candidate nie ma jeszcze gotowego candidate dry-run",
                    "severity": "Wysoki",
                    "status": shipping_candidate.get("dry_run_gate_status", "blocked"),
                    "why_blocking": "; ".join(shipping_candidate.get("blocked_reasons") or [])
                    or "Kandydat shippingowy nie ma jeszcze osobnego, gotowego toru dry-run.",
                    "expected_action": "Uruchomic osobnego candidate bota i potwierdzic snapshot, smoke oraz assessment baseline.",
                }
            )
        if regime_report is None:
            blockers.append(
                {
                    "blocker_id": "regime:not-available",
                    "source": "Regime detector",
                    "area": "Regime detection",
                    "title": "Brakuje kanonicznego raportu reżimu rynku",
                    "severity": "Wysoki",
                    "status": "Wymaga uwagi",
                    "why_blocking": "Platforma jest przestawiona na regime-first, ale nie ma jeszcze aktualnego latest.json dla reżimu.",
                    "expected_action": "Wygenerować raport reżimu i potwierdzić klasyfikację 6 głównych stanów rynku.",
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
            "branch_only_committed_total": sum(
                1 for task in coding_tasks if task.get("status") == "committed"
            ),
            "merged_to_main_total": sum(
                1 for task in coding_tasks if task.get("merged_to_main") is True
            ),
            "blocked_total": sum(1 for task in coding_tasks if task.get("status") == "blocked"),
            "tasks_waiting_ceo_total": len(coding_tasks_waiting_ceo),
            "runtime_active_total": sum(
                1 for task in coding_tasks if task.get("status") in {"dispatched", "coding", "review", "approved"}
            ),
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
            "candidate_factory": {
                "shipping_candidate_id": (
                    shipping_candidate.get("candidate_id") if shipping_candidate else None
                ),
                "selector": selector_decision,
                "candidate_assessments": candidate_assessments,
                "candidate_dry_run": candidate_dry_run,
                "factory_mode": "regime_first_freeze_build_keep_dry_run",
            },
            "strategy_layer": {
                "latest": strategy_layer_report,
                "preferred_strategy_id": (strategy_layer_report or {}).get("preferred_strategy_id"),
                "preferred_risk_admitted_strategy_id": (strategy_layer_report or {}).get("preferred_risk_admitted_strategy_id"),
                "built_signals": (strategy_layer_report or {}).get("built_signals") or [],
                "applicable_strategy_ids": (strategy_layer_report or {}).get("applicable_strategy_ids") or [],
                "risk_admitted_strategy_ids": (strategy_layer_report or {}).get("risk_admitted_strategy_ids") or [],
                "blocked_by_risk_strategy_ids": (strategy_layer_report or {}).get("blocked_by_risk_strategy_ids") or [],
            },
            "regime": {
                "latest": regime_report,
                "derivatives": derivatives_report,
                "risk_decision": risk_decision,
                "execution_enforcement": {
                    "enabled": bool((risk_decision or {}).get("hard_enforcement_enabled")),
                    "enforced_by": (risk_decision or {}).get("enforced_by") or [],
                    "execution_budget_multiplier": (risk_decision or {}).get("execution_budget_multiplier"),
                    "last_status": (risk_decision or {}).get("last_enforcement_status"),
                    "last_blocked_order_reason_codes": (risk_decision or {}).get("last_blocked_order_reason_codes") or [],
                    "counters": (risk_decision or {}).get("enforcement_counters") or {},
                },
                "replay": regime_replay_report,
                "derivatives_runtime_quality": {
                    "source": (derivatives_report or {}).get("source"),
                    "feed_status": (derivatives_report or {}).get("feed_status"),
                    "event_reliability": (derivatives_report or {}).get("event_reliability"),
                    "is_stale": bool((derivatives_report or {}).get("is_stale")),
                    "liquidation_event_confidence": (derivatives_report or {}).get("liquidation_event_confidence"),
                },
            },
            "control_status": control_status,
            "assumptions": assumptions,
            "modules": modules,
            "tasks": open_tasks,
            "completed_tasks": completed_tasks[:6],
            "decisions": waiting_decisions,
            "risks": risks,
            "recent_changes": recent_changes,
            "lead_notes": lead_notes,
            "blockers": blockers,
            "coding": {
                "status": coding_status,
                "summary": coding_summary,
                "delivery_semantics": {
                    "branch_only_progress": "Task agenta w statusie `committed` oznacza commit na branchu worktree i nie jest rownoznaczny z merge do `main`.",
                    "mainline_progress": "W v1 merge do `main` pozostaje poza agentami; jesli brak jawnego `merged_to_main`, executive report traktuje commit jako branch-only progress.",
                    "runtime_active_progress": "Za runtime-active uznajemy tylko aktualnie dzialajace uslugi i taski widoczne w biezacym runtime, a nie sam commit na branchu.",
                },
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
                "coding_tasks_branch_only_total": coding_summary["branch_only_committed_total"],
                "coding_tasks_merged_to_main_total": coding_summary["merged_to_main_total"],
                "coding_tasks_waiting_ceo_total": coding_summary["tasks_waiting_ceo_total"],
                "runtime_active_total": coding_summary["runtime_active_total"],
                "decisions_waiting_total": len(waiting_decisions),
                "high_risks_total": len(high_risks),
                "active_agent_runs_total": sum(
                    1 for run in runs if run.get("status") in {"queued", "running", "awaiting_approval"}
                ),
                "blockers_total": len(blockers),
                "autopilot_attention_needed": 1 if autopilot_attention_needed else 0,
                "dry_run_ready": 1 if dry_run_ready else 0,
                "candidate_assessments_total": len(candidate_assessments),
                "candidate_shipping_ready_total": sum(
                    1
                    for candidate in candidate_assessments
                    if candidate.get("lifecycle_status") in {"limited_dry_run_candidate", "frozen_pending_regime_engine"}
                    and candidate.get("candidate_bot_id")
                ),
                "candidate_dry_run_ready": 1
                if (candidate_dry_run or {}).get("health", {}).get("ready")
                else 0,
                "selector_candidate_available": 1 if selector_candidate else 0,
                "strategy_layer_available": 1 if strategy_layer_report else 0,
                "strategy_layer_built_signals_total": len((strategy_layer_report or {}).get("built_signals") or []),
                "strategy_layer_applicable_total": len((strategy_layer_report or {}).get("applicable_strategy_ids") or []),
                "strategy_layer_risk_admitted_total": len((strategy_layer_report or {}).get("risk_admitted_strategy_ids") or []),
                "regime_available": 1 if regime_report else 0,
                "derivatives_available": 1 if derivatives_report else 0,
                "risk_decision_available": 1 if risk_decision else 0,
                "risk_hard_enforcement_enabled": 1 if (risk_decision or {}).get("hard_enforcement_enabled") else 0,
                "risk_execution_blocked_total": int((risk_decision or {}).get("enforcement_counters", {}).get("blocked_total", 0) or 0),
                "risk_execution_clamped_stake_total": int((risk_decision or {}).get("enforcement_counters", {}).get("clamped_stake_total", 0) or 0),
                "risk_execution_clamped_leverage_total": int((risk_decision or {}).get("enforcement_counters", {}).get("clamped_leverage_total", 0) or 0),
                "risk_blocked_by_direction_total": int((risk_decision or {}).get("enforcement_counters", {}).get("blocked_by_direction", 0) or 0),
                "risk_blocked_by_strategy_total": int((risk_decision or {}).get("enforcement_counters", {}).get("blocked_by_strategy", 0) or 0),
                "risk_blocked_by_portfolio_limit_total": int((risk_decision or {}).get("enforcement_counters", {}).get("blocked_by_portfolio_limit", 0) or 0),
                "risk_blocked_by_cooldown_total": int((risk_decision or {}).get("enforcement_counters", {}).get("blocked_by_cooldown", 0) or 0),
                "risk_blocked_by_reduce_only_total": int((risk_decision or {}).get("enforcement_counters", {}).get("blocked_by_reduce_only", 0) or 0),
                "regime_replay_available": 1 if regime_replay_report else 0,
                "derivatives_stale": 1 if (derivatives_report or {}).get("is_stale") else 0,
                "derivatives_binance_share": round(
                    float((regime_replay_report or {}).get("derivatives_source_breakdown", {}).get("binance_futures_public_api", 0))
                    / max(float((regime_replay_report or {}).get("bar_count", 0) or 0), 1.0),
                    4,
                )
                if regime_replay_report
                else 0.0,
                "derivatives_snapshot_share": round(
                    float((regime_replay_report or {}).get("derivatives_source_breakdown", {}).get("external_vendor", 0))
                    / max(float((regime_replay_report or {}).get("bar_count", 0) or 0), 1.0),
                    4,
                )
                if regime_replay_report
                else 0.0,
                "derivatives_proxy_share": round(
                    float((regime_replay_report or {}).get("derivatives_source_breakdown", {}).get("replay_proxy", 0)
                    + (regime_replay_report or {}).get("derivatives_source_breakdown", {}).get("external_vendor_proxy_fallback", 0))
                    / max(float((regime_replay_report or {}).get("bar_count", 0) or 0), 1.0),
                    4,
                )
                if regime_replay_report
                else 0.0,
                "control_status_available": 1 if control_status else 0,
                "control_status_warn": 1 if (control_status or {}).get("overall_status") == "warn" else 0,
            },
        }
