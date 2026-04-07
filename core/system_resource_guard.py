"""Host resource guardrails for safe agent and coding runtime dispatch."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Any

try:
    import docker
    from docker.errors import DockerException
except Exception:  # noqa: BLE001
    docker = None

    class DockerException(Exception):
        pass


_MB = 1024 * 1024
_BACKTEST_MARKERS = (
    "backtesting",
    "hyperopt",
    "system_backtest",
    "candidate_backtest_runner",
    "core.system_backtest.run",
)


@dataclass
class _MemInfo:
    total_bytes: int
    available_bytes: int
    swap_total_bytes: int
    swap_free_bytes: int


def _read_meminfo() -> _MemInfo:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if not parts:
                continue
            try:
                values[key] = int(parts[0]) * 1024
            except ValueError:
                continue
    except OSError:
        values = {}
    return _MemInfo(
        total_bytes=int(values.get("MemTotal", 0)),
        available_bytes=int(values.get("MemAvailable", values.get("MemFree", 0))),
        swap_total_bytes=int(values.get("SwapTotal", 0)),
        swap_free_bytes=int(values.get("SwapFree", 0)),
    )


class SystemResourceGuard:
    """Small cached snapshot of host pressure used to protect agent dispatch."""

    def __init__(self, settings: Any, *, docker_base_url: str | None = None) -> None:
        self.settings = settings
        self.docker_base_url = docker_base_url
        self._docker_client = None
        self._last_snapshot: dict[str, Any] | None = None
        self._last_snapshot_at = 0.0

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        cache_seconds = int(
            getattr(self.settings, "agent_resource_guard_cache_seconds", 5) or 5
        )
        now = time.monotonic()
        if not force and self._last_snapshot is not None:
            if now - self._last_snapshot_at <= max(cache_seconds, 1):
                return dict(self._last_snapshot)
        snapshot = self._collect_snapshot()
        self._last_snapshot = dict(snapshot)
        self._last_snapshot_at = now
        return snapshot

    def _collect_snapshot(self) -> dict[str, Any]:
        enabled = bool(getattr(self.settings, "agent_resource_guard_enabled", False))
        meminfo = _read_meminfo()
        cpu_count = max(int(os.cpu_count() or 1), 1)
        try:
            load_1m, load_5m, load_15m = os.getloadavg()
        except OSError:
            load_1m, load_5m, load_15m = (0.0, 0.0, 0.0)

        available_pct = (
            float(meminfo.available_bytes) / float(meminfo.total_bytes)
            if meminfo.total_bytes
            else 0.0
        )
        load_per_cpu = float(load_1m) / float(cpu_count)

        min_available_bytes = int(
            float(getattr(self.settings, "agent_resource_guard_min_available_memory_mb", 1536))
            * _MB
        )
        min_available_pct = float(
            getattr(self.settings, "agent_resource_guard_min_available_memory_pct", 0.18)
        )
        max_load_per_cpu = float(
            getattr(self.settings, "agent_resource_guard_max_load_per_cpu", 1.5)
        )
        block_backtests = bool(
            getattr(self.settings, "agent_resource_guard_block_backtests", True)
        )

        heavy_jobs = self._detect_heavy_jobs() if block_backtests else []
        blocked_reasons: list[str] = []
        notes: list[str] = []

        if enabled:
            if meminfo.available_bytes and (
                meminfo.available_bytes < min_available_bytes
                or available_pct < min_available_pct
            ):
                blocked_reasons.append("low_available_memory")
                notes.append(
                    f"Available memory is low ({meminfo.available_bytes / _MB:.0f} MiB, {available_pct:.0%})."
                )
            if load_per_cpu > max_load_per_cpu:
                blocked_reasons.append("high_host_load")
                notes.append(
                    f"Host load per CPU is too high ({load_per_cpu:.2f} > {max_load_per_cpu:.2f})."
                )
            if heavy_jobs:
                blocked_reasons.append("backtest_in_progress")
                notes.append(
                    "Heavy replay/backtest workload is already running and coding dispatch is paused."
                )

        if meminfo.swap_total_bytes == 0:
            notes.append("Host has no swap configured.")

        if not notes:
            notes.append("Host resource guard is healthy.")

        return {
            "enabled": enabled,
            "allow_new_runs": enabled is False or not blocked_reasons,
            "allow_coding_dispatch": enabled is False or not blocked_reasons,
            "primary_reason": blocked_reasons[0] if blocked_reasons else None,
            "blocked_reasons": blocked_reasons,
            "operator_message": notes[0],
            "notes": notes,
            "resources": {
                "cpu_count": cpu_count,
                "load_1m": round(float(load_1m), 4),
                "load_5m": round(float(load_5m), 4),
                "load_15m": round(float(load_15m), 4),
                "load_per_cpu": round(load_per_cpu, 4),
                "mem_total_bytes": int(meminfo.total_bytes),
                "mem_available_bytes": int(meminfo.available_bytes),
                "mem_available_pct": round(available_pct, 6),
                "swap_total_bytes": int(meminfo.swap_total_bytes),
                "swap_free_bytes": int(meminfo.swap_free_bytes),
                "heavy_jobs": heavy_jobs,
                "thresholds": {
                    "min_available_memory_mb": int(min_available_bytes / _MB),
                    "min_available_memory_pct": min_available_pct,
                    "max_load_per_cpu": max_load_per_cpu,
                    "block_backtests": block_backtests,
                },
            },
        }

    def _get_docker_client(self):
        if docker is None:
            return None
        if self._docker_client is None:
            try:
                if self.docker_base_url:
                    self._docker_client = docker.DockerClient(
                        base_url=self.docker_base_url,
                        timeout=1,
                    )
                else:
                    self._docker_client = docker.from_env(timeout=1)
            except DockerException:
                self._docker_client = False
        return None if self._docker_client is False else self._docker_client

    def _detect_heavy_jobs(self) -> list[dict[str, str]]:
        jobs: list[dict[str, str]] = []

        for proc_dir in Path("/proc").iterdir():
            if not proc_dir.name.isdigit():
                continue
            cmdline_path = proc_dir / "cmdline"
            try:
                raw = cmdline_path.read_bytes()
            except OSError:
                continue
            if not raw:
                continue
            cmdline = " ".join(
                part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part
            ).lower()
            if any(marker in cmdline for marker in _BACKTEST_MARKERS):
                jobs.append(
                    {
                        "source": "process",
                        "name": proc_dir.name,
                        "command": cmdline[:160],
                    }
                )

        client = self._get_docker_client()
        if client is None:
            return jobs
        try:
            containers = client.containers.list()
        except DockerException:
            return jobs
        for container in containers:
            try:
                attrs = container.attrs or {}
            except DockerException:
                continue
            command = " ".join(str(part) for part in (attrs.get("Config", {}).get("Cmd") or []))
            entrypoint = " ".join(
                str(part) for part in (attrs.get("Config", {}).get("Entrypoint") or [])
            )
            searchable = f"{container.name} {entrypoint} {command}".lower()
            if any(marker in searchable for marker in _BACKTEST_MARKERS):
                jobs.append(
                    {
                        "source": "container",
                        "name": str(container.name),
                        "command": searchable[:160],
                    }
                )
        return jobs
