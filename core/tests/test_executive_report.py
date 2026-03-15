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
                coding_status={"running": True, "enabled": True, "attention_needed": False},
                coding_tasks=[],
                coding_workspaces=[],
            )

            risks = {risk["id"]: risk for risk in report["risks"]}
            blocker_ids = {blocker["blocker_id"] for blocker in report["blockers"]}

            self.assertEqual(risks["autopilot_fallback"]["status"], "Otwarte")
            self.assertIn("risk:autopilot_fallback", blocker_ids)
            self.assertGreaterEqual(report["summary"]["high_risks_total"], 1)
