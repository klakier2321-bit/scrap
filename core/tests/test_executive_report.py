from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.executive_report import ExecutiveReportService


def _write_exec_config(repo_root: Path) -> None:
    config_dir = repo_root / "ai_agents" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "executive_roadmap.yaml").write_text(
        """
executive_dashboard:
  title: "Pulpit Prezesa"
  subtitle: "Test"
  strategic_goal: "Test"
  modules: []
  tasks: []
  decisions: []
  assumptions: []
  risks:
    - id: "autopilot_fallback"
      title: "Fallback"
      area: "CrewAI"
      severity: "Wysokie"
      status: "Otwarte"
      mitigation: "Mitigation"
    - id: "strategy_overreach"
      title: "Overreach"
      area: "Trading"
      severity: "Wysokie"
      status: "Otwarte"
      mitigation: "Mitigation"
""".strip(),
        encoding="utf-8",
    )


class ExecutiveReportServiceTests(unittest.TestCase):
    def test_branch_only_vs_mainline_semantics_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_exec_config(repo_root)
            service = ExecutiveReportService(repo_root)

            report = service.build_report(
                runs=[],
                autopilot_status={
                    "running": True,
                    "poll_interval_seconds": 300,
                },
                strategy_report=None,
                dry_run_health={
                    "ready": True,
                    "runtime_mode": "dry_run",
                },
                dry_run_snapshot=None,
                dry_run_smoke=None,
                control_status=None,
                coding_status={"running": False, "enabled": True, "attention_needed": False},
                coding_tasks=[
                    {
                        "task_id": "code-1",
                        "module_id": "monitoring_and_visibility",
                        "status": "committed",
                        "goal": "Branch-only commit",
                        "owner_agent": "monitoring_agent",
                    },
                    {
                        "task_id": "code-2",
                        "module_id": "monitoring_and_visibility",
                        "status": "review",
                        "goal": "Active runtime task",
                        "owner_agent": "monitoring_agent",
                    },
                ],
                coding_workspaces=[],
            )

            self.assertEqual(report["summary"]["coding_tasks_branch_only_total"], 1)
            self.assertEqual(report["summary"]["coding_tasks_merged_to_main_total"], 0)
            self.assertEqual(report["summary"]["runtime_active_total"], 1)
            self.assertIn("branch_only_progress", report["coding"]["delivery_semantics"])

    def test_progress_pct_is_derived_from_module_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            config_dir = repo_root / "ai_agents" / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "executive_roadmap.yaml").write_text(
                """
executive_dashboard:
  title: "Pulpit Prezesa"
  subtitle: "Test"
  strategic_goal: "Test"
  assumptions: []
  risks: []
  decisions: []
  modules:
    - id: "mod-1"
      name: "Modul 1"
      owner_agent: "system_lead_agent"
      status: "W toku"
      progress_pct: 91
      direction: "Test"
      current_focus: "Test"
      next_milestone: "Test"
      risk_level: "Niskie"
      executive_note: "Test"
      paths: []
  tasks:
    - id: "task-1"
      module_id: "mod-1"
      title: "Task 1"
      status: "Zamknięte"
      owner_agent: "system_lead_agent"
      priority: "Wysoki"
      needs_human: "Nie"
      next_step: "done"
    - id: "task-2"
      module_id: "mod-1"
      title: "Task 2"
      status: "W toku"
      owner_agent: "system_lead_agent"
      priority: "Wysoki"
      needs_human: "Nie"
      next_step: "todo"
""".strip(),
                encoding="utf-8",
            )
            service = ExecutiveReportService(repo_root)

            report = service.build_report(
                runs=[],
                autopilot_status={"running": True, "poll_interval_seconds": 300},
                strategy_report=None,
                dry_run_health={"ready": True, "runtime_mode": "dry_run"},
                dry_run_snapshot=None,
                dry_run_smoke=None,
                control_status=None,
                coding_status={"running": False, "enabled": True, "attention_needed": False},
                coding_tasks=[],
                coding_workspaces=[],
            )

            module = report["modules"][0]
            self.assertEqual(module["declared_progress_pct"], 91.0)
            self.assertEqual(module["live_progress_pct"], 50.0)
            self.assertEqual(module["progress_pct"], 50.0)
            self.assertEqual(module["progress_source"], "roadmap_tasks")

    def test_stable_autopilot_and_dry_run_downgrade_risks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_exec_config(repo_root)
            service = ExecutiveReportService(repo_root)

            report = service.build_report(
                runs=[
                    {
                        "run_id": "run-1",
                        "agent_name": "system_lead_agent",
                        "status": "completed",
                        "warnings_json": [],
                        "error": None,
                        "blocked_reason": None,
                        "payload_json": {"requested_paths": []},
                    }
                ],
                autopilot_status={
                    "running": True,
                    "poll_interval_seconds": 300,
                },
                strategy_report=None,
                dry_run_health={
                    "ready": True,
                    "runtime_mode": "dry_run",
                },
                dry_run_snapshot=None,
                dry_run_smoke=None,
                control_status=None,
                coding_status={"running": True, "enabled": True, "attention_needed": False},
                coding_tasks=[],
                coding_workspaces=[],
            )

            risks = {risk["id"]: risk for risk in report["risks"]}
            blocker_ids = {blocker["blocker_id"] for blocker in report["blockers"]}

            self.assertEqual(risks["autopilot_fallback"]["status"], "Monitorowane")
            self.assertEqual(risks["strategy_overreach"]["status"], "Kontrolowane")
            self.assertNotIn("risk:autopilot_fallback", blocker_ids)
            self.assertNotIn("risk:strategy_overreach", blocker_ids)
            self.assertEqual(report["summary"]["high_risks_total"], 0)

    def test_recent_mock_fallback_keeps_autopilot_risk_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_exec_config(repo_root)
            service = ExecutiveReportService(repo_root)

            report = service.build_report(
                runs=[
                    {
                        "run_id": "run-fallback",
                        "agent_name": "system_lead_agent",
                        "status": "completed",
                        "warnings_json": ["mock_fallback activated"],
                        "error": None,
                        "blocked_reason": None,
                        "payload_json": {"requested_paths": []},
                    }
                ],
                autopilot_status={
                    "running": True,
                    "poll_interval_seconds": 300,
                },
                strategy_report=None,
                dry_run_health={
                    "ready": False,
                    "runtime_mode": "webserver",
                },
                dry_run_snapshot=None,
                dry_run_smoke=None,
                control_status=None,
                coding_status={"running": True, "enabled": True, "attention_needed": False},
                coding_tasks=[],
                coding_workspaces=[],
            )

            risks = {risk["id"]: risk for risk in report["risks"]}
            blocker_ids = {blocker["blocker_id"] for blocker in report["blockers"]}

            self.assertEqual(risks["autopilot_fallback"]["status"], "Otwarte")
            self.assertIn("risk:autopilot_fallback", blocker_ids)
            self.assertGreaterEqual(report["summary"]["high_risks_total"], 1)

    def test_control_status_is_included_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_exec_config(repo_root)
            service = ExecutiveReportService(repo_root)

            report = service.build_report(
                runs=[],
                autopilot_status={"running": True, "poll_interval_seconds": 300},
                strategy_report=None,
                dry_run_health={"ready": True, "runtime_mode": "dry_run"},
                dry_run_snapshot=None,
                dry_run_smoke=None,
                control_status={
                    "generated_at": "2026-03-19T00:00:00+00:00",
                    "overall_status": "warn",
                    "summary": "Wykryto 1 uwage.",
                    "sources": [],
                },
                coding_status={"running": True, "enabled": True, "attention_needed": False},
                coding_tasks=[],
                coding_workspaces=[],
            )

            self.assertEqual(report["summary"]["control_status_available"], 1)
            self.assertEqual(report["summary"]["control_status_warn"], 1)
            self.assertEqual(report["control_status"]["overall_status"], "warn")

    def test_candidate_factory_is_included_in_executive_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_exec_config(repo_root)
            service = ExecutiveReportService(repo_root)

            report = service.build_report(
                runs=[],
                autopilot_status={"running": True, "poll_interval_seconds": 300},
                strategy_report=None,
                dry_run_health={"ready": True, "runtime_mode": "dry_run"},
                dry_run_snapshot=None,
                dry_run_smoke=None,
                candidate_assessments=[
                    {
                        "candidate_id": "structured_futures_baseline_v1",
                        "candidate_bot_id": "freqtrade_candidate",
                        "lifecycle_status": "limited_dry_run_candidate",
                        "active_side_policy": "long_biased_with_parked_short",
                        "broad_backtest_status": "pass",
                        "risk_gate_status": "ready",
                        "dry_run_gate_status": "ready",
                        "overall_decision": "continue_limited_dry_run",
                        "next_step": "Monitor limited dry run.",
                        "blocked_reasons": [],
                    }
                ],
                candidate_dry_run={
                    "candidate_id": "structured_futures_baseline_v1",
                    "bot_id": "freqtrade_candidate",
                    "health": {"ready": True},
                    "latest_snapshot": {"strategy": "StructuredFuturesBaselineStrategy"},
                    "latest_smoke": {"status": "pass"},
                },
                control_status=None,
                coding_status={"running": True, "enabled": True, "attention_needed": False},
                coding_tasks=[],
                coding_workspaces=[],
            )

            self.assertEqual(
                report["candidate_factory"]["shipping_candidate_id"],
                "structured_futures_baseline_v1",
            )
            self.assertEqual(report["summary"]["candidate_assessments_total"], 1)
            self.assertEqual(report["summary"]["candidate_dry_run_ready"], 1)

    def test_regime_freeze_mode_is_exposed_in_executive_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            _write_exec_config(repo_root)
            service = ExecutiveReportService(repo_root)

            report = service.build_report(
                runs=[],
                autopilot_status={"running": True, "poll_interval_seconds": 300},
                strategy_report=None,
                dry_run_health={"ready": True, "runtime_mode": "dry_run"},
                dry_run_snapshot=None,
                dry_run_smoke=None,
                candidate_assessments=[
                    {
                        "candidate_id": "structured_futures_baseline_v1",
                        "candidate_bot_id": "freqtrade_candidate",
                        "lifecycle_status": "frozen_pending_regime_engine",
                        "active_side_policy": "long_biased_with_parked_short",
                        "broad_backtest_status": "pass",
                        "risk_gate_status": "ready",
                        "dry_run_gate_status": "telemetry_ready",
                        "overall_decision": "wait_for_regime_engine",
                        "next_step": "Keep candidate in telemetry-only dry run.",
                        "blocked_reasons": ["Candidate build is frozen until regime detector is ready."],
                    }
                ],
                candidate_dry_run={
                    "candidate_id": "structured_futures_baseline_v1",
                    "bot_id": "freqtrade_candidate",
                    "health": {"ready": True},
                    "latest_snapshot": {"strategy": "StructuredFuturesBaselineStrategy"},
                    "latest_smoke": {"status": "pass"},
                },
                regime_report={
                    "generated_at": "2026-03-19T00:00:00+00:00",
                    "asof_timeframe": "1h",
                    "universe": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
                    "primary_regime": "trend_up",
                    "confidence": 0.81,
                    "risk_level": "low",
                    "trend_strength": 0.77,
                    "volatility_level": "normal",
                    "volume_state": "normal",
                    "derivatives_state": {"feed_status": "ok", "positioning_state": "long_build"},
                    "feature_snapshot": {},
                    "reasons": ["Trend i ADX wspieraja wzrost."],
                    "eligible_candidate_ids": ["structured_futures_baseline_v1"],
                    "blocked_candidate_ids": ["structured_futures_short_breakdown_v1"],
                    "candidate_freeze_mode": "freeze_build_keep_dry_run",
                },
                derivatives_report={
                    "generated_at": "2026-03-19T00:00:00+00:00",
                    "source": "external_vendor",
                    "feed_status": "ok",
                    "vendor_available": True,
                    "universe": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
                    "symbols": [],
                },
                regime_replay_report={
                    "generated_at": "2026-03-19T00:00:00+00:00",
                    "asof_timeframe": "1h",
                    "bar_count": 120,
                    "replay_status": "ready",
                    "warmup_bars": 48,
                    "regime_switches_total": 12,
                    "avg_minutes_in_regime": 55.0,
                    "no_trade_zone_share": 0.2,
                    "compression_to_expansion_count": 7,
                    "bias_followthrough_15m_pct": 0.61,
                    "bias_followthrough_1h_pct": 0.58,
                    "market_consensus_breakdown": {"strong_bullish": 40},
                    "regime_coverage": {"trend_up": 60},
                    "event_counts": {},
                    "notes": [],
                },
                control_status=None,
                coding_status={"running": True, "enabled": True, "attention_needed": False},
                coding_tasks=[],
                coding_workspaces=[],
            )

            self.assertEqual(
                report["candidate_factory"]["factory_mode"],
                "regime_first_freeze_build_keep_dry_run",
            )
            self.assertEqual(report["summary"]["regime_available"], 1)
            self.assertEqual(report["summary"]["derivatives_available"], 1)
            self.assertEqual(report["summary"]["regime_replay_available"], 1)
            self.assertEqual(report["regime"]["latest"]["primary_regime"], "trend_up")
