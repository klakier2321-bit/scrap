"""Testy izolowanych git worktree dla agentów kodujących."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from core.worktree_manager import WorktreeManager


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


class WorktreeManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name) / "repo"
        self.worktree_root = Path(self.temp_dir.name) / "worktrees"
        (self.repo_path / "core").mkdir(parents=True)
        (self.repo_path / "core" / "README.md").write_text(
            "Pierwsza wersja README control layer.\n",
            encoding="utf-8",
        )
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
        self.manager = WorktreeManager(
            repo_path=self.repo_path,
            worktree_root=self.worktree_root,
            git_author_name="Agent Test",
            git_author_email="agent@test.local",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_worktree_supports_modified_and_new_files_before_commit(self) -> None:
        info = self.manager.create_workspace(
            task_id="task-1",
            agent_name="control_layer_agent",
        )
        worktree_path = Path(info.worktree_path)

        self.manager.write_allowed_file(
            path="core/README.md",
            worktree_path=worktree_path,
            content="Zmieniony README control layer.\n",
        )
        self.manager.write_allowed_file(
            path="core/generated_slice.py",
            worktree_path=worktree_path,
            content="VALUE = 'offline'\n",
        )

        changed_files = self.manager.changed_files(worktree_path=worktree_path)
        diff_text = self.manager.show_git_diff(worktree_path=worktree_path)
        commit_sha = self.manager.commit_changes(
            worktree_path=worktree_path,
            message="Agent slice",
        )

        self.assertIn("core/README.md", changed_files)
        self.assertIn("core/generated_slice.py", changed_files)
        self.assertIn("generated_slice.py", diff_text)
        self.assertEqual(len(commit_sha), 40)

