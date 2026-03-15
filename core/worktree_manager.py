"""Obsługa izolowanych git worktree dla agentów kodujących."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any


ALLOWED_CHECK_PREFIXES = (
    "python -m compileall",
    "python -m unittest",
)
MAX_CONTEXT_FILES = 12
MAX_CONTEXT_FILE_CHARS = 6000
MAX_TOTAL_CONTEXT_CHARS = 24000


def _matches_scope(candidate: str, scope_rule: str) -> bool:
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


@dataclass(frozen=True)
class WorktreeInfo:
    """Metadane jednego worktree przypisanego do tasku."""

    task_id: str
    agent_name: str
    worktree_path: str
    branch_name: str
    base_ref: str
    base_commit: str


class WorktreeManager:
    """Tworzy, czyta i commituje izolowane worktree agentów kodujących."""

    def __init__(
        self,
        *,
        repo_path: Path,
        worktree_root: Path,
        git_author_name: str,
        git_author_email: str,
    ) -> None:
        self.repo_path = repo_path
        self.worktree_root = worktree_root
        self.git_author_name = git_author_name
        self.git_author_email = git_author_email
        self.worktree_root.mkdir(parents=True, exist_ok=True)

    def ensure_repo(self) -> None:
        if not (self.repo_path / ".git").exists():
            raise RuntimeError(f"Repo checkout '{self.repo_path}' does not contain .git.")
        self._mark_safe_directory(self.repo_path)

    def create_workspace(
        self,
        *,
        task_id: str,
        agent_name: str,
        base_ref: str = "main",
    ) -> WorktreeInfo:
        self.ensure_repo()
        branch_name = f"agent/{agent_name}/{task_id}"
        worktree_path = self.worktree_root / agent_name / task_id
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        if (worktree_path / ".git").exists():
            self._mark_safe_directory(worktree_path)
            base_commit = self._git(["rev-parse", "HEAD"], cwd=worktree_path)
            return WorktreeInfo(
                task_id=task_id,
                agent_name=agent_name,
                worktree_path=str(worktree_path),
                branch_name=branch_name,
                base_ref=base_ref,
                base_commit=base_commit,
            )

        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

        base_commit = self._git(["rev-parse", base_ref], cwd=self.repo_path)
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            cwd=self.repo_path,
            check=False,
        ).returncode == 0
        if branch_exists:
            self._git(["branch", "-f", branch_name, base_ref], cwd=self.repo_path)
            self._git(["worktree", "add", str(worktree_path), branch_name], cwd=self.repo_path)
        else:
            self._git(
                ["worktree", "add", "-b", branch_name, str(worktree_path), base_ref],
                cwd=self.repo_path,
            )
        self._mark_safe_directory(worktree_path)
        return WorktreeInfo(
            task_id=task_id,
            agent_name=agent_name,
            worktree_path=str(worktree_path),
            branch_name=branch_name,
            base_ref=base_ref,
            base_commit=base_commit,
        )

    def reset_workspace(self, *, task_id: str, agent_name: str, base_ref: str = "main") -> WorktreeInfo:
        worktree_path = self.worktree_root / agent_name / task_id
        if worktree_path.exists():
            self._git(["worktree", "remove", "--force", str(worktree_path)], cwd=self.repo_path)
        return self.create_workspace(task_id=task_id, agent_name=agent_name, base_ref=base_ref)

    def list_allowed_files(self, *, scope_rules: list[str], cwd: Path | None = None) -> list[str]:
        cwd = cwd or self.repo_path
        tracked = self._git(["ls-files"], cwd=cwd).splitlines()
        return [
            path
            for path in tracked
            if any(_matches_scope(path, rule) for rule in scope_rules)
        ]

    def collect_file_contexts(
        self,
        *,
        worktree_path: Path,
        target_files: list[str],
        read_only_context: list[str],
    ) -> list[dict[str, str]]:
        selected: list[str] = []
        total_chars = 0
        candidates = list(dict.fromkeys(target_files + read_only_context))
        for candidate in candidates:
            expanded = self._expand_candidate(candidate, worktree_path)
            for path in expanded:
                if path in selected:
                    continue
                content = self.read_allowed_file(path=path, worktree_path=worktree_path)
                truncated = content[:MAX_CONTEXT_FILE_CHARS]
                total_chars += len(truncated)
                if total_chars > MAX_TOTAL_CONTEXT_CHARS:
                    break
                selected.append(path)
                if len(selected) >= MAX_CONTEXT_FILES:
                    break
            if len(selected) >= MAX_CONTEXT_FILES or total_chars > MAX_TOTAL_CONTEXT_CHARS:
                break

        contexts: list[dict[str, str]] = []
        for path in selected:
            content = self.read_allowed_file(path=path, worktree_path=worktree_path)
            contexts.append(
                {
                    "path": path,
                    "content": content[:MAX_CONTEXT_FILE_CHARS],
                }
            )
        return contexts

    def read_allowed_file(self, *, path: str, worktree_path: Path) -> str:
        full_path = worktree_path / path
        if not full_path.exists() or not full_path.is_file():
            return ""
        return full_path.read_text(encoding="utf-8")

    def write_allowed_file(self, *, path: str, worktree_path: Path, content: str) -> None:
        full_path = worktree_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def show_git_diff(self, *, worktree_path: Path) -> str:
        diff_text = self._git(["diff", "--", "."], cwd=worktree_path)
        untracked_files = self._git(
            ["ls-files", "--others", "--exclude-standard"],
            cwd=worktree_path,
        ).splitlines()
        previews: list[str] = []
        for path in [item for item in untracked_files if item.strip()]:
            content = self.read_allowed_file(path=path, worktree_path=worktree_path)
            previews.append(
                "\n".join(
                    [
                        f"diff --git a/{path} b/{path}",
                        "new file mode 100644",
                        "--- /dev/null",
                        f"+++ b/{path}",
                        "@@ new file @@",
                        content,
                    ]
                )
            )
        preview_suffix = "\n\n".join(previews)
        if diff_text and preview_suffix:
            return f"{diff_text}\n\n{preview_suffix}"
        return diff_text or preview_suffix

    def changed_files(self, *, worktree_path: Path) -> list[str]:
        tracked_output = self._git(["diff", "--name-only", "--", "."], cwd=worktree_path)
        untracked_output = self._git(
            ["ls-files", "--others", "--exclude-standard"],
            cwd=worktree_path,
        )
        return list(
            dict.fromkeys(
                [line for line in tracked_output.splitlines() if line.strip()]
                + [line for line in untracked_output.splitlines() if line.strip()]
            )
        )

    def run_allowed_checks(self, *, worktree_path: Path, commands: list[str]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        all_passed = True
        for command in commands:
            normalized = command.strip()
            if not normalized or not normalized.startswith(ALLOWED_CHECK_PREFIXES):
                results.append(
                    {
                        "command": normalized,
                        "exit_code": 126,
                        "passed": False,
                        "stdout": "",
                        "stderr": "Command is not allowed by coding runtime.",
                    }
                )
                all_passed = False
                continue
            if normalized.startswith("python "):
                normalized = normalized.replace("python ", f"{sys.executable} ", 1)
            completed = subprocess.run(
                shlex.split(normalized),
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=False,
            )
            results.append(
                {
                    "command": normalized,
                    "exit_code": completed.returncode,
                    "passed": completed.returncode == 0,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
            if completed.returncode != 0:
                all_passed = False
        return {"all_passed": all_passed, "checks": results}

    def commit_changes(self, *, worktree_path: Path, message: str) -> str:
        changed_files = self.changed_files(worktree_path=worktree_path)
        if not changed_files:
            raise RuntimeError("No changed files to commit in worktree.")
        self._git(["add", "--all", "--", "."], cwd=worktree_path)
        self._git(
            [
                "-c",
                f"user.name={self.git_author_name}",
                "-c",
                f"user.email={self.git_author_email}",
                "commit",
                "-m",
                message,
            ],
            cwd=worktree_path,
        )
        return self._git(["rev-parse", "HEAD"], cwd=worktree_path)

    def _expand_candidate(self, candidate: str, worktree_path: Path) -> list[str]:
        path = candidate.lstrip("./")
        full_path = worktree_path / path
        if full_path.is_file():
            return [path]
        if full_path.is_dir():
            tracked = self.list_allowed_files(scope_rules=[path], cwd=worktree_path)
            return tracked[: max(1, MAX_CONTEXT_FILES // 2)]
        return [path]

    def _git(self, args: list[str], *, cwd: Path) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Git command failed: git {' '.join(args)}\n{completed.stderr.strip()}"
            )
        return completed.stdout.strip()

    def _mark_safe_directory(self, path: Path) -> None:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
