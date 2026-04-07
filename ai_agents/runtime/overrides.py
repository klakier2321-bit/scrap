"""Operator-managed runtime overrides for guarded agent activation and budgets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _normalize_override_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    agents = data.get("agents")
    if not isinstance(agents, dict):
        agents = {}
    normalized_agents: dict[str, dict[str, Any]] = {}
    for agent_name, raw in agents.items():
        if not isinstance(raw, dict):
            continue
        normalized_agents[str(agent_name)] = {
            "enabled": raw.get("enabled"),
            "daily_budget_usd": raw.get("daily_budget_usd"),
            "per_run_budget_usd": raw.get("per_run_usd", raw.get("per_run_budget_usd")),
        }
    return {"agents": normalized_agents}


def load_runtime_overrides(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"agents": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"agents": {}}
    return _normalize_override_payload(payload)


def write_runtime_overrides(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_override_payload(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def merge_agent_override(
    path: Path,
    *,
    agent_name: str,
    enabled: bool | None = None,
    daily_budget_usd: float | None = None,
    per_run_budget_usd: float | None = None,
) -> dict[str, Any]:
    payload = load_runtime_overrides(path)
    agents = dict(payload.get("agents") or {})
    current = dict(agents.get(agent_name) or {})
    current["enabled"] = enabled
    current["daily_budget_usd"] = daily_budget_usd
    current["per_run_budget_usd"] = per_run_budget_usd
    agents[agent_name] = current
    return write_runtime_overrides(path, {"agents": agents})

