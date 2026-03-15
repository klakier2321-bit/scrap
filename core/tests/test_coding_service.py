"""Testy supervised write dla coding supervisor."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import time
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
        target_file = next(
            (
                candidate
                for candidate in module_context["target_candidates"]
                if not str(candidate).endswith("/")
            ),
            "core/README.md",
        )
        return (
            {
                "summary": module_context["module_summary"],
                "module_id": module_context["module_id"],
                "owner_agent": module_context["owner_agent"],
                "goal": "Dodac maly offlineowy plik do control layer.",
                "business_reason": "Potwierdzic supervised write w izolowanym worktree.",
                "owned_scope": module_context["owned_scope"],
                "read_only_context": module_context["read_only_context"],
                "target_files": [target_file],
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


class HangingAgentRuntime(FakeAgentRuntime):
    def generate_coding_change(self, *, agent_name, task_packet, file_contexts, review_feedback=None):
        time.sleep(0.2)
        return super().generate_coding_change(
            agent_name=agent_name,
            task_packet=task_packet,
            file_contexts=file_contexts,
            review_feedback=review_feedback,
        )


class AliveWorker:
    def is_alive(self) -> bool:
        return True


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
    - module_id: "secondary_control_layer"
      owner_agent: "control_layer_agent"
      enabled: true
      priority: 10
      title: "Secondary control"
      module_summary: "Nizszy priorytet."
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
    - module_id: "control_layer_runtime"
      owner_agent: "control_layer_agent"
      enabled: true
      priority: 100
      title: "Control layer"
      module_summary: "Maly offlineowy przyrost control layer."
      read_only_context:
        - "docs/ARCHITECTURE.md"
      max_target_files: 2
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
            agent_coding_task_timeout_seconds=180,
            agent_run_timeout_seconds=180,
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

    def test_manual_task_accepts_narrow_target_override_within_scope(self) -> None:
        task = self.service.create_manual_task(
            module_id="control_layer_runtime",
            target_files_override=["core/generated_runtime_slice.py"],
        )

        self.assertEqual(task["target_files"], ["core/generated_runtime_slice.py"])

    def test_validate_task_packet_filters_disallowed_required_tests(self) -> None:
        module = self.service.modules_by_id["control_layer_runtime"]
        packet = {
            "module_id": module.module_id,
            "owner_agent": module.owner_agent,
            "goal": "Maly task",
            "business_reason": "Test",
            "target_files": ["core/README.md"],
            "read_only_context": [],
            "acceptance_checks": [],
            "required_tests": [
                "python -m compileall core",
                "python scripts/not_allowed.py --help",
            ],
            "definition_of_done": [],
            "risk_level": "low",
        }

        validated = self.service._validate_task_packet(module=module, packet=packet)

        self.assertIsNotNone(validated)
        self.assertEqual(validated["required_tests"], ["python -m compileall core"])

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

    def test_reconcile_orphaned_active_task_blocks_stale_task(self) -> None:
        task = self.service.create_manual_task(module_id="control_layer_runtime")
        info = self.service.worktree_manager.create_workspace(
            task_id=task["task_id"],
            agent_name=task["owner_agent"],
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
                "created_at": "2026-03-15T00:00:00+00:00",
                "updated_at": "2026-03-15T00:00:00+00:00",
            }
        )
        self.store.update_coding_task(task["task_id"], status="coding", started_at="2026-03-15T00:00:00+00:00")

        self.service._reconcile_orphaned_active_tasks(
            reason="Task lost worker context.",
            event_type="worker_context_lost",
        )

        updated = self.store.get_coding_task(task["task_id"])
        workspace = self.store.get_coding_workspace(task["task_id"])
        self.assertEqual(updated["status"], "blocked")
        self.assertEqual(workspace["status"], "blocked")
        self.assertEqual(updated["last_error"], "Task lost worker context.")

    def test_review_task_is_not_blocked_as_orphaned_worker(self) -> None:
        task = self.service.create_manual_task(module_id="control_layer_runtime")
        info = self.service.worktree_manager.create_workspace(
            task_id=task["task_id"],
            agent_name=task["owner_agent"],
        )
        self.store.create_coding_workspace(
            {
                "task_id": task["task_id"],
                "agent_name": task["owner_agent"],
                "worktree_path": info.worktree_path,
                "branch_name": info.branch_name,
                "base_ref": info.base_ref,
                "base_commit": info.base_commit,
                "changed_files": ["core/generated_runtime_slice.py"],
                "diff_text": "diff --git a/core/generated_runtime_slice.py b/core/generated_runtime_slice.py",
                "check_results": {},
                "status": "review",
                "created_at": "2026-03-15T00:00:00+00:00",
                "updated_at": "2026-03-15T00:00:00+00:00",
            }
        )
        self.store.update_coding_task(
            task["task_id"],
            status="review",
            started_at="2026-03-15T00:00:00+00:00",
        )

        self.service._reconcile_orphaned_active_tasks(
            reason="Task lost worker context.",
            event_type="worker_context_lost",
        )

        updated = self.store.get_coding_task(task["task_id"])
        status = self.service.status()
        self.assertEqual(updated["status"], "review")
        self.assertIsNone(status["active_task_id"])
        self.assertEqual(status["review_tasks"], 1)
        self.assertFalse(status["attention_needed"])

    def test_timeout_marks_hanging_task_blocked(self) -> None:
        timeout_settings = SimpleNamespace(**self.settings.__dict__)
        timeout_settings.agent_coding_task_timeout_seconds = 0
        service = CodingSupervisorService(
            settings=timeout_settings,
            store=self.store,
            agent_runtime=HangingAgentRuntime(),
            executive_report_provider=lambda: {
                "strategic_goal": "Zrobic maly slice.",
                "modules": [{"id": "control_layer_runtime", "name": "Control layer"}],
                "recent_changes": [],
                "blockers": [],
            },
        )

        task = service.create_manual_task(module_id="control_layer_runtime")
        service._dispatch_ready_task()
        time.sleep(0.05)
        service._reconcile_worker_state()
        time.sleep(0.25)

        updated = service.get_coding_task(task["task_id"])
        self.assertEqual(updated["status"], "blocked")
        self.assertIn("timeout", (updated["last_error"] or "").lower())

    def test_refresh_queue_prefers_highest_priority_module(self) -> None:
        self.service._refresh_lead_queue()

        tasks = self.service.list_coding_tasks(limit=5)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["module_id"], "control_layer_runtime")

    def test_status_ignores_stale_last_error_when_active_worker_is_healthy(self) -> None:
        task = self.service.create_manual_task(module_id="control_layer_runtime")
        self.store.update_coding_task(
            task["task_id"],
            status="coding",
            started_at="2099-01-01T00:00:00+00:00",
        )
        self.service._last_error = "Previous task failed."
        self.service._worker_thread = AliveWorker()
        self.service._worker_task_id = task["task_id"]
        self.service._worker_started_monotonic = time.monotonic()

        status = self.service.status()

        self.assertFalse(status["attention_needed"])
        self.assertTrue(status["active_worker_alive"])
        self.assertEqual(status["active_task_id"], task["task_id"])
