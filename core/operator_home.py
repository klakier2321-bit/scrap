"""Helpers for building the lightweight operator home snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _bool_label(value: bool | None) -> str:
    if value is None:
        return "brak danych"
    return "tak" if bool(value) else "nie"


def _translate_cluster_state(bots: list[dict[str, Any]]) -> str:
    if not bots:
        return "missing"
    running = sum(1 for bot in bots if str(bot.get("state")) == "running")
    if running == len(bots):
        return "running"
    if running == 0:
        return "stopped"
    return "degraded"


def _summarize_agent_tree(agents: list[dict[str, Any]]) -> dict[str, Any]:
    activation_counts = {
        "always_on_guarded": 0,
        "manual_only": 0,
        "disabled_by_default": 0,
    }
    operational_counts = {
        "active_core": 0,
        "manual_enabled": 0,
        "manual_only": 0,
        "operator_disabled": 0,
        "disabled": 0,
    }
    for agent in agents:
        activation_mode = str(agent.get("activation_mode") or "")
        if activation_mode in activation_counts:
            activation_counts[activation_mode] += 1
        operational_state = str(agent.get("operational_state") or "")
        if operational_state in operational_counts:
            operational_counts[operational_state] += 1
    return {
        "activation_counts": activation_counts,
        "operational_counts": operational_counts,
        "active_core_agents": [
            str(agent.get("name"))
            for agent in agents
            if str(agent.get("operational_state")) == "active_core"
        ],
    }


def _action_state(*, enabled: bool, blocked_reason: str | None = None) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "blocked_reason": blocked_reason,
    }


def _normalize_attention_items(
    *,
    observability_summary: dict[str, Any],
    risk_decision: dict[str, Any] | None,
    futures_health: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for blocker in list(observability_summary.get("top_blockers") or [])[:5]:
        items.append(
            {
                "kind": "blocker",
                "severity": str(blocker.get("severity") or "medium"),
                "title": str(blocker.get("title") or blocker.get("source") or "Blocker"),
                "summary": str(
                    blocker.get("why_blocking")
                    or blocker.get("expected_action")
                    or blocker.get("status")
                    or "Wymaga uwagi operatora."
                ),
                "owner": blocker.get("area"),
            }
        )
    for line in list(observability_summary.get("operator_attention") or [])[:5 - len(items)]:
        items.append(
            {
                "kind": "attention",
                "severity": "medium",
                "title": "Wymaga uwagi",
                "summary": str(line),
                "owner": None,
            }
        )
    if risk_decision and risk_decision.get("risk_reason_codes") and len(items) < 5:
        items.append(
            {
                "kind": "risk",
                "severity": "medium",
                "title": "Aktywne ograniczenia risk",
                "summary": ", ".join(list(risk_decision.get("risk_reason_codes") or [])[:3]),
                "owner": "risk",
            }
        )
    if futures_health and futures_health.get("warnings") and len(items) < 5:
        items.append(
            {
                "kind": "runtime",
                "severity": "medium",
                "title": "Ostrzeżenia klastra futures",
                "summary": " | ".join(list(futures_health.get("warnings") or [])[:2]),
                "owner": "futures_runtime",
            }
        )
    return items[:5]


def _normalize_recent_errors(observability_summary: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    for item in list(observability_summary.get("recent_errors") or [])[:5]:
        errors.append(
            {
                "title": str(item.get("title") or item.get("source") or "Błąd"),
                "summary": str(item.get("summary") or item.get("message") or "Brak szczegółów."),
                "severity": str(item.get("severity") or "medium"),
                "owner": item.get("agent_name") or item.get("bot_id") or item.get("source"),
            }
        )
    return errors


def _normalize_recent_actions(
    observability_summary: dict[str, Any],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions = []
    for item in list(observability_summary.get("recent_handoffs") or [])[:5]:
        actions.append(
            {
                "title": str(item.get("title") or "Handoff"),
                "summary": str(item.get("summary") or item.get("status") or "Przekazanie pracy."),
                "owner": item.get("from_agent") or item.get("to_agent"),
                "status": item.get("status") or "handoff",
            }
        )
    if not actions:
        for run in runs[:5]:
            actions.append(
                {
                    "title": str(run.get("goal") or "Run agenta"),
                    "summary": str(run.get("status") or "unknown"),
                    "owner": run.get("agent_name"),
                    "status": run.get("status"),
                }
            )
    return actions[:5]


def build_operator_home(
    *,
    health: dict[str, Any],
    futures_bots: list[dict[str, Any]],
    futures_health: dict[str, Any] | None,
    futures_snapshot: dict[str, Any] | None,
    risk_decision: dict[str, Any] | None,
    strategy_layer_report: dict[str, Any] | None,
    autopilot_status: dict[str, Any],
    coding_status: dict[str, Any],
    agents: list[dict[str, Any]],
    observability_summary: dict[str, Any] | None,
    runtime_flags: dict[str, Any],
    recent_runs: list[dict[str, Any]],
    settings: Any,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    observability_summary = dict(observability_summary or {})
    futures_health = dict(futures_health or {})
    risk_decision = dict(risk_decision or {})
    strategy_layer_report = dict(strategy_layer_report or {})
    futures_cluster_state = _translate_cluster_state(futures_bots)
    any_bot_running = any(str(bot.get("state")) == "running" for bot in futures_bots)
    all_bots_running = bool(futures_bots) and all(str(bot.get("state")) == "running" for bot in futures_bots)
    effective_kill = bool((runtime_flags.get("kill_switch") or {}).get("effective_enabled"))
    effective_freeze = bool((runtime_flags.get("runtime_freeze") or {}).get("effective_enabled"))
    resource_guard = dict(health.get("resource_guard") or {})
    ai_block_reason = None
    if effective_kill:
        ai_block_reason = "kill_switch_enabled"
    elif effective_freeze:
        ai_block_reason = "runtime_freeze_enabled"
    elif not bool(resource_guard.get("allow_new_runs", True)):
        ai_block_reason = str(resource_guard.get("primary_reason") or "resource_guard_blocked")

    futures_actions = {
        "start_cluster": _action_state(
            enabled=not all_bots_running and bool(futures_bots) and bool(health.get("docker_available")),
            blocked_reason=None
            if (not all_bots_running and futures_bots and health.get("docker_available"))
            else ("cluster_already_running" if all_bots_running else "docker_unavailable"),
        ),
        "stop_cluster": _action_state(
            enabled=any_bot_running,
            blocked_reason=None if any_bot_running else "cluster_not_running",
        ),
        "run_smoke": _action_state(
            enabled=any_bot_running,
            blocked_reason=None if any_bot_running else "cluster_not_running",
        ),
        "refresh_snapshot": _action_state(
            enabled=any_bot_running,
            blocked_reason=None if any_bot_running else "cluster_not_running",
        ),
    }
    ai_actions = {
        "start_autopilot": _action_state(
            enabled=(not autopilot_status.get("running")) and ai_block_reason is None,
            blocked_reason=None if ((not autopilot_status.get("running")) and ai_block_reason is None) else (ai_block_reason or "autopilot_already_running"),
        ),
        "stop_autopilot": _action_state(
            enabled=bool(autopilot_status.get("running")),
            blocked_reason=None if autopilot_status.get("running") else "autopilot_not_running",
        ),
        "start_coding_supervisor": _action_state(
            enabled=(not coding_status.get("running")) and ai_block_reason is None,
            blocked_reason=None if ((not coding_status.get("running")) and ai_block_reason is None) else (ai_block_reason or "coding_supervisor_already_running"),
        ),
        "stop_coding_supervisor": _action_state(
            enabled=bool(coding_status.get("running")),
            blocked_reason=None if coding_status.get("running") else "coding_supervisor_not_running",
        ),
        "toggle_kill_switch": _action_state(enabled=True),
        "toggle_runtime_freeze": _action_state(enabled=True),
    }
    agent_tree_summary = _summarize_agent_tree(agents)
    blocked_budget_runs = sum(
        1
        for run in recent_runs
        if str(run.get("blocked_reason") or "").startswith("budget_")
    )
    blocked_resource_runs = sum(
        1
        for run in recent_runs
        if str(run.get("blocked_reason") or "").startswith("host_resource_guard:")
    )
    top_trading_blocks = list(dict.fromkeys(
        list(risk_decision.get("risk_reason_codes") or [])[:3]
        + list(futures_health.get("warnings") or [])[:2]
    ))[:5]
    return {
        "generated_at": generated_at,
        "status": "ok",
        "freshness": dict(observability_summary.get("freshness") or {}),
        "futures": {
            "cluster_id": "futures_canonical",
            "cluster_state": futures_cluster_state,
            "bots": futures_bots,
            "ready": bool(futures_health.get("ready")),
            "snapshot_age_seconds": futures_health.get("snapshot_age_seconds"),
            "last_smoke_status": futures_health.get("last_smoke_status"),
            "risk_mode": risk_decision.get("trading_mode"),
            "allow_trading": risk_decision.get("allow_trading"),
            "force_reduce_only": risk_decision.get("force_reduce_only"),
            "cooldown_active": risk_decision.get("cooldown_active"),
            "preferred_risk_admitted_strategy_id": strategy_layer_report.get(
                "preferred_risk_admitted_strategy_id"
            ),
            "top_blockers": top_trading_blocks,
            "snapshot_open_trades": (futures_snapshot or {}).get("open_trades_count"),
            "actions": futures_actions,
        },
        "ai": {
            "agents_status": health.get("agents_status"),
            "agents_reason": health.get("agents_reason"),
            "autopilot_running": bool(autopilot_status.get("running")),
            "coding_supervisor_running": bool(coding_status.get("running")),
            "resource_guard": resource_guard,
            "global_daily_budget_usd": float(getattr(settings, "agent_global_daily_budget_usd", 0.0)),
            "global_per_run_budget_usd": float(getattr(settings, "agent_global_per_run_budget_usd", 0.0)),
            "blocked_by_budget_total": blocked_budget_runs,
            "blocked_by_resource_guard_total": blocked_resource_runs,
            "agent_tree_summary": agent_tree_summary,
            "runtime_flags": runtime_flags,
            "actions": ai_actions,
        },
        "attention_items": _normalize_attention_items(
            observability_summary=observability_summary,
            risk_decision=risk_decision,
            futures_health=futures_health,
        ),
        "recent_errors": _normalize_recent_errors(observability_summary),
        "recent_actions": _normalize_recent_actions(observability_summary, recent_runs),
        "goals_and_direction": dict(observability_summary.get("goals_and_direction") or {}),
        "operator_attention": list(observability_summary.get("operator_attention") or [])[:5],
        "observability_owner": "ops_observability_agent",
        "summary_labels": {
            "kill_switch": _bool_label(effective_kill),
            "runtime_freeze": _bool_label(effective_freeze),
            "resource_guard": "blokuje"
            if not bool(resource_guard.get("allow_new_runs", True))
            else "ok",
        },
    }
