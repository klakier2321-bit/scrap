import tempfile
import unittest
from pathlib import Path

from core.autopilot import AutopilotService


class _FakeSettings:
    def __init__(self, agent_max_parallel_runs: int = 3) -> None:
        self.agent_max_parallel_runs = agent_max_parallel_runs
        self.agent_kill_switch = False


class _FakeOrchestrator:
    def __init__(self, runs: list[dict] | None = None, *, max_parallel_runs: int = 3) -> None:
        self._runs = runs or []
        self.settings = _FakeSettings(agent_max_parallel_runs=max_parallel_runs)

    def list_runs(self, limit: int = 50) -> list[dict]:
        return list(self._runs)[:limit]


class TestAutopilotParallelSelection(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tempdir.name) / "autopilot.yaml"
        self.config_path.write_text(
            """
autopilot:
  objective: "test"
  auto_start: false
  poll_interval_seconds: 300
  max_cycles: 0
  tasks:
    - name: "lead_next_increment"
      agent_name: "system_lead_agent"
      goal: "lead"
      business_reason: "lead"
      requested_paths: ["docs/"]
      risk_level: "medium"
      cross_layer: true
      does_touch_contract: false
      does_touch_runtime: false
      force_strong_model: false
      auto_approve: true
    - name: "strategy_lead_foundation"
      agent_name: "strategy_agent"
      goal: "strategy lead"
      business_reason: "strategy lead"
      requested_paths: ["docs/"]
      risk_level: "medium"
      cross_layer: true
      does_touch_contract: false
      does_touch_runtime: false
      force_strong_model: false
      auto_approve: false
      allow_parallel: true
    - name: "feature_foundation_watch"
      agent_name: "feature_engineering_agent"
      goal: "feature"
      business_reason: "feature"
      requested_paths: ["research/"]
      risk_level: "low"
      cross_layer: false
      does_touch_contract: false
      does_touch_runtime: false
      force_strong_model: false
      auto_approve: false
      allow_parallel: true
    - name: "risk_research_foundation"
      agent_name: "risk_research_agent"
      goal: "risk"
      business_reason: "risk"
      requested_paths: ["research/"]
      risk_level: "low"
      cross_layer: false
      does_touch_contract: false
      does_touch_runtime: false
      force_strong_model: false
      auto_approve: false
      allow_parallel: true
""".strip(),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_selects_parallel_strategy_task_when_one_run_is_already_active(self) -> None:
        service = AutopilotService(
            orchestrator=_FakeOrchestrator(),
            config_path=self.config_path,
            poll_interval_seconds=300,
        )
        tasks = service._loaded_config["tasks"]
        selection = service._select_next_task(
            tasks,
            active_task_names={"lead_next_increment"},
            active_count=1,
            max_parallel_runs=3,
        )
        self.assertIsNotNone(selection)
        _index, task = selection
        self.assertEqual(task.name, "strategy_lead_foundation")

    def test_skips_already_active_parallel_task_and_picks_next_one(self) -> None:
        service = AutopilotService(
            orchestrator=_FakeOrchestrator(),
            config_path=self.config_path,
            poll_interval_seconds=300,
        )
        tasks = service._loaded_config["tasks"]
        selection = service._select_next_task(
            tasks,
            active_task_names={"lead_next_increment", "strategy_lead_foundation"},
            active_count=2,
            max_parallel_runs=3,
        )
        self.assertIsNotNone(selection)
        _index, task = selection
        self.assertEqual(task.name, "feature_foundation_watch")

    def test_does_not_dispatch_above_parallel_limit(self) -> None:
        service = AutopilotService(
            orchestrator=_FakeOrchestrator(),
            config_path=self.config_path,
            poll_interval_seconds=300,
        )
        tasks = service._loaded_config["tasks"]
        selection = service._select_next_task(
            tasks,
            active_task_names={"lead_next_increment", "strategy_lead_foundation", "feature_foundation_watch"},
            active_count=3,
            max_parallel_runs=3,
        )
        self.assertIsNone(selection)


if __name__ == "__main__":
    unittest.main()
