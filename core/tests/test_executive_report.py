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
