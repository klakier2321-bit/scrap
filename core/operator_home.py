"""Helpers for building the lightweight operator home snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FUTURES_OPERATOR_FRESHNESS_SECONDS = 15 * 60


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


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(value: Any) -> float | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    return max(0.0, round((datetime.now(timezone.utc) - parsed).total_seconds(), 2))


def _structured_blocker_summary(blocker_code: str) -> str:
    messages = {
        "futures_cluster_stopped": "Klaster futures nie działa. Trzeba podnieść 5 botów kanonicznych przed dalszą oceną gotowości.",
        "futures_runtime_stale": "Artefakty runtime są nieświeże albo brakuje aktualnej preferowanej strategii admitted przez risk.",
        "futures_smoke_degraded": "Smoke klastra futures jest zdegradowany albo któryś z botów nie przechodzi health checku.",
    }
    return messages.get(blocker_code, "Wymaga uwagi operatora.")


def _structured_blocker_title(blocker_code: str) -> str:
    titles = {
        "futures_cluster_stopped": "Futures cluster jest zatrzymany",
        "futures_runtime_stale": "Futures runtime jest nieświeży",
        "futures_smoke_degraded": "Futures smoke jest zdegradowany",
    }
    return titles.get(blocker_code, blocker_code)


def _build_futures_runtime_state(
    *,
    cluster_state: str,
    futures_health: dict[str, Any],
    strategy_layer_report: dict[str, Any],
) -> dict[str, Any]:
    snapshot_age_seconds = (
        float(futures_health.get("snapshot_age_seconds"))
        if futures_health.get("snapshot_age_seconds") is not None
        else None
    )
    last_smoke_at = futures_health.get("last_smoke_at")
    last_smoke_age_seconds = _age_seconds(last_smoke_at)
    preferred_strategy_id = (
        strategy_layer_report.get("preferred_risk_admitted_strategy_id")
        or strategy_layer_report.get("preferred_strategy_id")
    )
    snapshot_fresh = (
        snapshot_age_seconds is not None
        and snapshot_age_seconds <= FUTURES_OPERATOR_FRESHNESS_SECONDS
    )
    smoke_fresh = (
        last_smoke_age_seconds is not None
        and last_smoke_age_seconds <= FUTURES_OPERATOR_FRESHNESS_SECONDS
    )
    data_fresh = cluster_state == "running" and snapshot_fresh and smoke_fresh
    smoke_status = str(futures_health.get("last_smoke_status") or "").strip().lower()
    smoke_healthy = smoke_status in {"pass", "ok"}
    runtime_ready = (
        cluster_state == "running"
        and bool(futures_health.get("ready"))
        and data_fresh
        and bool(preferred_strategy_id)
    )
    blocker_code = None
    if cluster_state == "stopped":
        blocker_code = "futures_cluster_stopped"
    elif not data_fresh or not preferred_strategy_id:
        blocker_code = "futures_runtime_stale"
    elif not smoke_healthy or not bool(futures_health.get("ready")):
        blocker_code = "futures_smoke_degraded"
    return {
        "ready": runtime_ready,
        "data_fresh": data_fresh,
        "snapshot_age_seconds": snapshot_age_seconds,
        "last_smoke_at": last_smoke_at,
        "last_smoke_age_seconds": last_smoke_age_seconds,
        "blocker_codes": [blocker_code] if blocker_code else [],
    }


def _normalize_attention_items(
    *,
    observability_summary: dict[str, Any],
    futures_state: dict[str, Any],
    risk_decision: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_summaries: set[str] = set()
    futures_blocker_codes = set(str(code) for code in list(futures_state.get("blocker_codes") or []))
    for blocker_code in list(futures_state.get("blocker_codes") or [])[:1]:
        title = str(blocker_code)
        summary = _structured_blocker_summary(blocker_code)
        items.append(
            {
                "kind": "runtime",
                "severity": "high",
                "title": title,
                "summary": summary,
                "owner": "futures_runtime",
            }
        )
        seen_titles.add(title)
        seen_titles.add(_structured_blocker_title(blocker_code))
        seen_summaries.add(summary)
    for blocker in list(observability_summary.get("top_blockers") or [])[:5]:
        if str(blocker.get("source") or "") == "Futures runtime" and futures_blocker_codes:
            continue
        title = str(blocker.get("title") or blocker.get("source") or "Blocker")
        summary = str(
            blocker.get("why_blocking")
            or blocker.get("expected_action")
            or blocker.get("status")
            or "Wymaga uwagi operatora."
        )
        if title in seen_titles:
            continue
        items.append(
            {
                "kind": "blocker",
                "severity": str(blocker.get("severity") or "medium"),
                "title": title,
                "summary": summary,
                "owner": blocker.get("area"),
            }
        )
        seen_titles.add(title)
        seen_summaries.add(summary)
    for line in list(observability_summary.get("operator_attention") or [])[:5 - len(items)]:
        title = "Wymaga uwagi"
        if str(line) in seen_titles or str(line) in seen_summaries:
            continue
        items.append(
            {
                "kind": "attention",
                "severity": "medium",
                "title": title,
                "summary": str(line),
                "owner": None,
            }
        )
        seen_titles.add(str(line))
    if (
        risk_decision
        and risk_decision.get("risk_reason_codes")
        and len(items) < 5
        and not list(futures_state.get("blocker_codes") or [])
    ):
        items.append(
            {
                "kind": "risk",
                "severity": "medium",
                "title": "Aktywne ograniczenia risk",
                "summary": ", ".join(list(risk_decision.get("risk_reason_codes") or [])[:3]),
                "owner": "risk",
            }
        )
        seen_titles.add("Aktywne ograniczenia risk")
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
    futures_state = _build_futures_runtime_state(
        cluster_state=futures_cluster_state,
        futures_health=futures_health,
        strategy_layer_report=strategy_layer_report,
    )
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
    top_trading_blocks = list(futures_state.get("blocker_codes") or [])[:1]
    combined_freshness = dict(observability_summary.get("freshness") or {})
    combined_freshness.setdefault("futures_data_fresh", bool(futures_state.get("data_fresh")))
    combined_freshness.setdefault("ai_runtime_fresh", True)
    combined_freshness.setdefault("coding_review_blockers", int(coding_status.get("review_tasks", 0) or 0))
    combined_freshness.setdefault("stale_attention_items_count", 0)
    return {
        "generated_at": generated_at,
        "status": "ok",
        "freshness": combined_freshness,
        "futures": {
            "cluster_id": "futures_canonical",
            "cluster_state": futures_cluster_state,
            "bots": futures_bots,
            "ready": bool(futures_state.get("ready")),
            "data_fresh": bool(futures_state.get("data_fresh")),
            "snapshot_age_seconds": futures_health.get("snapshot_age_seconds"),
            "last_smoke_status": futures_health.get("last_smoke_status"),
            "last_smoke_at": futures_health.get("last_smoke_at"),
            "last_smoke_age_seconds": futures_state.get("last_smoke_age_seconds"),
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
            futures_state=futures_state,
            risk_decision=risk_decision,
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
