from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path

from core.observability_summary import (
    build_observability_summary,
    load_latest_observability_summary,
    load_observability_summary_history,
    persist_observability_summary,
)


class _DummySettings:
    def __init__(self, base_dir: Path) -> None:
        self.observability_latest_path = base_dir / "observability" / "combined_dashboard.latest.json"
        self.observability_history_path = base_dir / "observability" / "combined_dashboard.history.jsonl"
        self.observability_log_path = base_dir / "logs" / "observability_summary.log"


def _sample_report() -> dict:
    return {
        "generated_at": "2026-03-29T12:00:00+00:00",
        "strategic_goal": "Domknąć paper-ready futures runtime.",
        "autopilot": {
            "running": True,
            "last_status": "running",
            "current_task_name": "observe_runtime",
            "next_task_name": "review_blockers",
            "agents_status": "agents_guarded",
            "kill_switch": False,
            "runtime_freeze": False,
        },
        "summary": {
            "agents_disabled": 0,
            "agents_guarded": 1,
            "agents_active_limited": 0,
            "agent_budget_daily_total_usd": 5.0,
            "agent_budget_per_run_total_usd": 0.5,
            "strategy_layer_available": 1,
            "strategy_layer_built_signals_total": 2,
            "strategy_layer_risk_admitted_total": 1,
            "regime_available": 1,
            "risk_decision_available": 1,
            "regime_replay_available": 1,
            "dry_run_ready": 1,
        },
        "agent_runtime": {
            "status": "agents_guarded",
            "reason": "manual_or_mock_mode",
            "observability_owner": "ops_observability_agent",
            "summary": {
                "active_core_agents": ["system_lead_agent", "ops_observability_agent"],
            },
            "tree": [
                {
                    "name": "system_lead_agent",
                    "role": "Lead",
                    "parent_agent": None,
                    "domain": "governance",
                    "effective_enabled": True,
                    "operational_state": "active_core",
                },
                {
                    "name": "ops_observability_agent",
                    "role": "Observability owner",
                    "parent_agent": "system_lead_agent",
                    "domain": "platform",
                    "effective_enabled": True,
                    "operational_state": "active_core",
                },
                {
                    "name": "trend_pullback_steward",
                    "role": "Steward",
                    "parent_agent": "strategy_agent",
                    "domain": "strategy",
                    "effective_enabled": False,
                    "operational_state": "disabled",
                },
            ],
        },
        "dry_run": {
            "health": {
                "ready": True,
                "bridge_status": "ok",
                "snapshot_age_seconds": 120,
                "last_smoke_status": "pass",
                "last_smoke_at": "2026-03-29T11:58:00+00:00",
                "members": [
                    {
                        "bot_id": "ft_trend_pullback_continuation_v1",
                        "ready": True,
                    }
                ],
            }
        },
        "strategy_layer": {
            "preferred_strategy_id": "trend_pullback_continuation_v1",
            "preferred_risk_admitted_strategy_id": "trend_pullback_continuation_v1",
        },
        "regime": {
            "latest": {"primary_regime": "trend_up"},
            "risk_decision": {"trading_mode": "normal"},
            "replay": {"status": "ready"},
        },
        "lead_notes": [
            {
                "message": "Skupić się na stabilnym futures control tower.",
                "next_step": "Dowieźć jeden home dashboard i bounded observability.",
            }
        ],
        "modules": [
            {
                "id": "control_layer_runtime",
                "name": "Control Layer",
                "direction": "Jeden spójny tor runtime.",
                "current_focus": "Grafana home dashboard.",
            }
        ],
        "blockers": [
            {
                "blocker_id": "risk:1",
                "source": "Ryzyko",
                "title": "Runtime still guarded",
                "severity": "Wysoki",
                "status": "Wymaga uwagi",
                "why_blocking": "Agenci nie mogą wejść w autopilot bez dodatkowej kontroli.",
            }
        ],
        "coding": {
            "tasks": [
                {
                    "task_id": "coding-1",
                    "module_id": "control_layer_runtime",
                    "owner_agent": "control_layer_agent",
                    "status": "review",
                    "goal": "Dowieźć unified dashboard.",
                    "review_json": {"decision": "human_review_required"},
                }
            ]
        },
    }


def _sample_runs() -> list[dict]:
    return [
        {
            "run_id": "run-1",
            "agent_name": "ops_observability_agent",
            "status": "running",
            "goal": "Refresh observability summary",
            "payload_json": {
                "requested_paths": ["core/metrics.py"],
                "metadata": {"autopilot_task": "ops_dashboard_refresh"},
            },
        },
        {
            "run_id": "run-2",
            "agent_name": "strategy_agent",
            "status": "blocked",
            "goal": "Do not spend too much",
            "blocked_reason": "budget_guard_triggered",
            "warnings_json": [],
            "payload_json": {"requested_paths": []},
        },
    ]


class ObservabilitySummaryTests(unittest.TestCase):
    def test_build_summary_contains_graph_work_and_cost_control(self) -> None:
        summary = build_observability_summary(
            executive_report=_sample_report(),
            bot_states=[
                {
                    "bot_id": "ft_trend_pullback_continuation_v1",
                    "state": "running",
                    "runtime_group": "futures_canonical",
                    "strategy_id": "trend_pullback_continuation_v1",
                }
            ],
            runs=_sample_runs(),
        )

        self.assertTrue(summary["state_hash"])
        self.assertGreaterEqual(len(summary["graph_nodes"]), 4)
        self.assertGreaterEqual(len(summary["graph_edges"]), 3)
        self.assertIn(
            "ops_observability_agent",
            {item["owner_name"] for item in summary["current_work"]},
        )
        self.assertEqual(summary["cost_control"]["budget_blocked_runs_total"], 1)
        self.assertEqual(
            summary["futures_runtime"]["preferred_risk_admitted_strategy_id"],
            "trend_pullback_continuation_v1",
        )
        self.assertIn("futures_data_fresh", summary["freshness"])
        self.assertIn("coding_review_blockers", summary["freshness"])
        self.assertEqual(len(summary["top_blockers"]), 2)
        self.assertEqual(summary["top_blockers"][0]["source"], "Futures runtime")
        self.assertEqual(summary["top_blockers"][1]["source"], "Coding review")
        self.assertEqual(summary["freshness"]["stale_attention_items_count"], 2)

    def test_persist_summary_writes_latest_history_and_log_without_duplicate_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _DummySettings(Path(tmpdir))
            summary = build_observability_summary(
                executive_report=_sample_report(),
                bot_states=[
                    {
                        "bot_id": "ft_trend_pullback_continuation_v1",
                        "state": "running",
                        "runtime_group": "futures_canonical",
                        "strategy_id": "trend_pullback_continuation_v1",
                    }
                ],
                runs=_sample_runs(),
            )

            persist_observability_summary(settings, summary)
            persist_observability_summary(settings, summary)

            latest = load_latest_observability_summary(settings)
            history = load_observability_summary_history(settings, limit=10)
            self.assertIsNotNone(latest)
            self.assertEqual(latest["state_hash"], summary["state_hash"])
            self.assertEqual(len(history), 1)

            log_lines = settings.observability_log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(log_lines), 1)
            payload = json.loads(log_lines[0])
            self.assertEqual(payload["event_type"], "observability_summary")

    def test_build_summary_distinguishes_risk_blocked_runtime_from_stale_runtime(self) -> None:
        report = _sample_report()
        now = datetime.now(timezone.utc).isoformat()
        report["dry_run"]["health"]["snapshot_age_seconds"] = 30
        report["dry_run"]["health"]["last_smoke_status"] = "pass"
        report["dry_run"]["health"]["last_smoke_at"] = now
        report["strategy_layer"]["preferred_risk_admitted_strategy_id"] = None
        report["strategy_layer"]["preferred_strategy_id"] = None
        report["regime"]["risk_decision"] = {
            "trading_mode": "reduced_risk",
            "new_entries_allowed": False,
            "risk_reason_codes": ["REDUCED_EXPOSURE_ONLY", "LOW_REGIME_QUALITY"],
        }

        summary = build_observability_summary(
            executive_report=report,
            bot_states=[
                {
                    "bot_id": "ft_trend_pullback_continuation_v1",
                    "state": "running",
                    "runtime_group": "futures_canonical",
                    "strategy_id": "trend_pullback_continuation_v1",
                }
            ],
            runs=[],
        )

        self.assertEqual(summary["top_blockers"][0]["status"], "futures_no_admitted_strategy")
        self.assertIn("REDUCED_EXPOSURE_ONLY", summary["top_blockers"][0]["why_blocking"])
        self.assertTrue(summary["futures_runtime"]["runtime_operational"])
        self.assertTrue(summary["futures_runtime"]["data_fresh"])
