"""Lightweight artifact-first context packets for low-cost agent runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _top_items(items: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    return [dict(item) for item in list(items or [])[:limit]]


def build_module_packet(module_context: dict[str, Any]) -> dict[str, Any]:
    target_candidates = list(module_context.get("target_candidates") or [])
    max_target_files = int(module_context.get("max_target_files", 6))
    return {
        "packet_type": "module_packet",
        "version": 1,
        "generated_at": _utc_now(),
        "module_id": module_context.get("module_id"),
        "title": module_context.get("title"),
        "owner_agent": module_context.get("owner_agent"),
        "module_summary": module_context.get("module_summary"),
        "target_files": target_candidates[:max_target_files],
        "target_candidates": target_candidates[:max_target_files],
        "max_target_files": max_target_files,
        "owned_scope": list(module_context.get("owned_scope") or []),
        "read_only_scope": list(module_context.get("read_only_scope") or []),
        "forbidden_paths": list(module_context.get("forbidden_paths") or []),
        "acceptance_checks": list(module_context.get("acceptance_checks") or [])[:4],
        "required_tests": list(module_context.get("required_tests") or [])[:4],
        "read_only_context": list(module_context.get("read_only_context") or [])[:6],
        "definition_of_done": list(module_context.get("definition_of_done") or [])[:6],
    }


def build_executive_packet(executive_report: dict[str, Any]) -> dict[str, Any]:
    summary = executive_report.get("summary") or {}
    autopilot = executive_report.get("autopilot") or {}
    return {
        "packet_type": "executive_packet",
        "version": 1,
        "generated_at": _utc_now(),
        "strategic_goal": executive_report.get("strategic_goal"),
        "agents_status": autopilot.get("agents_status"),
        "autopilot_running": bool(autopilot.get("running")),
        "active_agent_runs_total": int(summary.get("active_agent_runs_total", 0)),
        "high_risks_total": int(summary.get("high_risks_total", 0)),
        "blockers_total": int(summary.get("blockers_total", 0)),
        "coding_attention_needed": bool((executive_report.get("coding") or {}).get("summary", {}).get("attention_needed")),
        "top_blockers": _top_items(executive_report.get("blockers") or [], limit=3),
        "recent_changes": _top_items(executive_report.get("recent_changes") or [], limit=3),
    }


def build_strategy_packet(
    *,
    strategy_report: dict[str, Any],
    readiness_gate: dict[str, Any] | None = None,
    dry_run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "packet_type": "strategy_packet",
        "version": 1,
        "generated_at": _utc_now(),
        "strategy_name": strategy_report.get("strategy_name"),
        "timeframe": strategy_report.get("timeframe"),
        "profit_pct": float(strategy_report.get("profit_pct", 0.0)),
        "drawdown_pct": float(strategy_report.get("drawdown_pct", 0.0)),
        "total_trades": int(strategy_report.get("total_trades", 0)),
        "win_rate": float(strategy_report.get("win_rate", 0.0)),
        "evaluation_status": strategy_report.get("evaluation_status"),
        "rejection_reasons": list(strategy_report.get("rejection_reasons") or [])[:4],
        "readiness_gate": dict(readiness_gate or {}),
        "dry_run_summary": dict(dry_run_context or {}),
    }


def build_cost_packet(
    *,
    agents: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    global_budget: dict[str, Any],
) -> dict[str, Any]:
    recent_runs = list(runs or [])[:20]
    spend_per_agent: dict[str, float] = {}
    for run in recent_runs:
        agent_name = str(run.get("agent_name") or "")
        if not agent_name:
            continue
        spend_per_agent[agent_name] = spend_per_agent.get(agent_name, 0.0) + float(
            run.get("actual_cost_usd") or run.get("estimated_cost_usd") or 0.0
        )
    return {
        "packet_type": "cost_packet",
        "version": 1,
        "generated_at": _utc_now(),
        "global_budget": {
            "daily_usd": float(global_budget.get("daily_usd", 0.0)),
            "per_run_usd": float(global_budget.get("per_run_usd", 0.0)),
        },
        "agents": [
            {
                "name": agent.get("name"),
                "activation_mode": agent.get("activation_mode"),
                "operational_state": agent.get("operational_state"),
                "cost_tier": agent.get("cost_tier"),
                "default_daily_budget_usd": float(agent.get("default_daily_budget_usd", 0.0)),
                "default_per_run_budget_usd": float(agent.get("default_per_run_budget_usd", 0.0)),
                "effective_daily_budget_usd": float(
                    agent.get("effective_daily_budget_usd", agent.get("default_daily_budget_usd", 0.0))
                ),
                "effective_per_run_budget_usd": float(
                    agent.get("effective_per_run_budget_usd", agent.get("default_per_run_budget_usd", 0.0))
                ),
                "effective_enabled": bool(agent.get("effective_enabled")),
                "recent_estimated_spend_usd": round(float(spend_per_agent.get(agent.get("name"), 0.0)), 6),
            }
            for agent in agents
        ],
    }


def build_runtime_state_packet(
    *,
    health: dict[str, Any],
    autopilot_status: dict[str, Any],
    coding_status: dict[str, Any],
    resource_guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "packet_type": "runtime_state_packet",
        "version": 1,
        "generated_at": _utc_now(),
        "health": {
            "status": health.get("status"),
            "agents_status": health.get("agents_status"),
            "kill_switch": bool(health.get("kill_switch")),
            "runtime_freeze": bool(health.get("runtime_freeze")),
        },
        "autopilot": {
            "running": bool(autopilot_status.get("running")),
            "next_task_name": autopilot_status.get("next_task_name"),
            "cycle_count": int(autopilot_status.get("cycle_count", 0)),
        },
        "coding": {
            "running": bool(coding_status.get("running")),
            "active_task_id": coding_status.get("active_task_id"),
            "attention_needed": bool(coding_status.get("attention_needed")),
        },
        "resource_guard": dict(resource_guard or {}),
    }


def build_agent_tree_packet(agents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "packet_type": "agent_tree_packet",
        "version": 1,
        "generated_at": _utc_now(),
        "agents": [
            {
                "name": agent.get("name"),
                "parent_agent": agent.get("parent_agent"),
                "activation_mode": agent.get("activation_mode"),
                "domain": agent.get("domain"),
                "cost_tier": agent.get("cost_tier"),
                "child_agents": list(agent.get("child_agents") or []),
            }
            for agent in agents
        ],
    }


class ContextPacketStore:
    """Persists small context packets for operators and agents."""

    def __init__(self, packets_dir: Path) -> None:
        self.packets_dir = packets_dir

    def write_packet(self, *, packet_type: str, packet_name: str, payload: dict[str, Any]) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target_dir = self.packets_dir / packet_type
        target_dir.mkdir(parents=True, exist_ok=True)
        latest_path = target_dir / f"{packet_name}.latest.json"
        history_path = target_dir / f"{packet_name}.{timestamp}.json"
        latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        history_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return latest_path
