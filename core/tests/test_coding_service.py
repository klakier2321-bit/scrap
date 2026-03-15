"""Testy supervised write dla coding supervisor."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from ai_agents.runtime.config import load_scope_manifest
from core.coding_service import CodingSupervisorService
from core.storage import RunStore


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


class FakeAgentRuntime:
    def __init__(self) -> None:
        self.scope_manifest = load_scope_manifest()

    def generate_coding_task_packet(self, *, module_context, executive_context):
        return (
            {
                "summary": module_context["module_summary"],
                "module_id": module_context["module_id"],
                "owner_agent": module_context["owner_agent"],
                "goal": "Dodac maly offlineowy plik do control layer.",
                "business_reason": "Potwierdzic supervised write w izolowanym worktree.",
                "owned_scope": module_context["owned_scope"],
                "read_only_context": module_context["read_only_context"],
                "target_files": ["core/README.md"],
                "forbidden_paths": module_context["forbidden_paths"],
                "risk_level": "low",
                "acceptance_checks": module_context["acceptance_checks"],
                "required_tests": module_context["required_tests"],
                "definition_of_done": module_context["definition_of_done"],
                "warnings": [],
                "review_required": True,
                "human_decision_required": False,
            },
            {"estimated_cost_usd": 0.001},
        )

    def generate_coding_change(self, *, agent_name, task_packet, file_contexts, review_feedback=None):
        return (
            {
                "summary": "Dodano maly plik offline w core/.",
                "file_edits": [
                    {
                        "path": "core/generated_runtime_slice.py",
                        "content": "SLICE_NAME = 'control-layer-offline'\n",
                        "is_new_file": True,
                        "rationale": "Nowy, maly slice potwierdzajacy supervised write.",
                    }
                ],
                "notes": [],
                "required_checks": task_packet["required_tests"],
            },
            {"estimated_cost_usd": 0.002},
        )

    def review_coding_change(self, *, task_packet, diff_text, check_results, change_summary):
        return (
            {
                "decision": "approve",
                "risk_level": "low",
                "main_findings": ["Diff jest maly i miesci sie w owned scope."],
                "required_changes": [],
            },
            {"estimated_cost_usd": 0.001},
        )


class CodingSupervisorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name) / "repo"
        self.worktree_root = Path(self.temp_dir.name) / "worktrees"
        self.repo_path.mkdir(parents=True)
        (self.repo_path / "core").mkdir()
        (self.repo_path / "docs").mkdir()
        (self.repo_path / "core" / "README.md").write_text("Control layer README.\n", encoding="utf-8")
        (self.repo_path / "core" / "__init__.py").write_text("", encoding="utf-8")
        (self.repo_path / "docs" / "ARCHITECTURE.md").write_text("Architektura.\n", encoding="utf-8")
        (self.repo_path / "docs" / "PROJECT_MAP.md").write_text("Mapa projektu.\n", encoding="utf-8")
        (self.repo_path / "AGENT_BOUNDARIES.md").write_text("Granice agentow.\n", encoding="utf-8")
        _run(["git", "init", "-b", "main"], cwd=self.repo_path)
        _run(["git", "add", "."], cwd=self.repo_path)
        _run(
            [
                "git",
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "init",
            ],
            cwd=self.repo_path,
        )

        self.config_path = Path(self.temp_dir.name) / "coding_modules.yaml"
        self.config_path.write_text(
            """
coding_runtime:
  enabled: true
  auto_start: false
  lead_refresh_interval_seconds: 300
  dispatcher_poll_interval_seconds: 60
  max_active_tasks: 1
  max_target_files: 6
  modules:
    - module_id: "control_layer_runtime"
      owner_agent: "control_layer_agent"
      enabled: true
      priority: 100
      title: "Control layer"
      module_summary: "Maly offlineowy przyrost control layer."
      read_only_context:
        - "docs/ARCHITECTURE.md"
      target_candidates:
        - "core/README.md"
      acceptance_checks:
        - "Zmiana zostaje w core/"
      required_tests:
        - "python -m compileall core"
      definition_of_done:
        - "Diff jest maly i reviewable."
""".strip()
            + "\n",
            encoding="utf-8",
        )

        self.settings = SimpleNamespace(
            agent_coding_enabled=True,
            agent_coding_auto_start=False,
            agent_lead_queue_refresh_interval_seconds=300,
            agent_coding_dispatcher_poll_interval_seconds=60,
            repo_checkout_path=self.repo_path,
            agent_worktree_root_path=self.worktree_root,
            agent_git_author_name="Agent Test",
            agent_git_author_email="agent@test.local",
            coding_modules_config_path=self.config_path,
        )
        self.store = RunStore(Path(self.temp_dir.name) / "coding.db")
        self.service = CodingSupervisorService(
            settings=self.settings,
            store=self.store,
            agent_runtime=FakeAgentRuntime(),
            executive_report_provider=lambda: {
                "strategic_goal": "Zrobic maly slice.",
                "modules": [{"id": "control_layer_runtime", "name": "Control layer"}],
                "recent_changes": [],
                "blockers": [],
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_manual_task_can_run_to_committed_state(self) -> None:
        task = self.service.create_manual_task(module_id="control_layer_runtime")
        result = self.service._execute_task(task)

        self.assertEqual(result["status"], "committed")
        self.assertTrue(result["commit_sha"])
        workspace = self.store.get_coding_workspace(task["task_id"])
        self.assertIsNotNone(workspace)
        self.assertIn("core/generated_runtime_slice.py", workspace["changed_files"])

    def test_validate_task_packet_blocks_forbidden_target(self) -> None:
        module = self.service.modules_by_id["control_layer_runtime"]
        packet = {
            "module_id": module.module_id,
            "owner_agent": module.owner_agent,
            "goal": "Niepoprawny task",
            "business_reason": "Test",
            "target_files": [".env"],
            "read_only_context": [],
            "acceptance_checks": [],
            "required_tests": [],
            "definition_of_done": [],
            "risk_level": "low",
        }

        validated = self.service._validate_task_packet(module=module, packet=packet)

        self.assertIsNone(validated)
