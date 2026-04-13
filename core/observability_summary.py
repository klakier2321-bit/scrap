"""Bounded observability summary artifacts for the Grafana control tower."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .config import AppSettings

FUTURES_OPERATOR_FRESHNESS_SECONDS = 15 * 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 1, 0)].rstrip()}…"


def _safe_title(value: Any, *, fallback: str, limit: int = 96) -> str:
    text = _truncate(value, limit)
    return text or fallback


def _status_rank(status: str) -> int:
    normalized = str(status or "").strip().lower()
    if normalized in {"failed", "blocked", "error", "operator_disabled"}:
        return 0
    if normalized in {"awaiting_approval", "review", "guarded", "manual_only", "manual_enabled"}:
        return 1
    if normalized in {"queued", "running", "coding", "active", "active_core"}:
        return 2
    return 3


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


def _risk_reason_excerpt(risk_decision: dict[str, Any] | None) -> str:
    reasons = [str(item) for item in list((risk_decision or {}).get("risk_reason_codes") or []) if str(item)]
    if not reasons:
        return ""
    return ", ".join(reasons[:3])


def _budget_block_count(runs: list[dict[str, Any]]) -> int:
    total = 0
    for run in runs:
        text = " ".join(
            str(part or "")
            for part in (
                run.get("blocked_reason"),
                run.get("error"),
                " ".join(str(item) for item in (run.get("warnings_json") or [])),
            )
        ).lower()
        if "budget" in text:
            total += 1
    return total


def _active_agent_names(runs: list[dict[str, Any]]) -> set[str]:
    return {
        str(run.get("agent_name"))
        for run in runs
        if str(run.get("status") or "") in {"queued", "running", "awaiting_approval"}
        and run.get("agent_name")
    }


def _futures_cluster_state(bot_states: list[dict[str, Any]]) -> str:
    futures_bots = [
        bot
        for bot in bot_states
        if str(bot.get("runtime_group") or "") == "futures_canonical"
    ]
    if not futures_bots:
        return "missing"
    running = sum(1 for bot in futures_bots if str(bot.get("state") or "") == "running")
    if running == len(futures_bots):
        return "running"
    if running == 0:
        return "stopped"
    return "degraded"


def _coding_review_tasks(executive_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(task)
        for task in list(((executive_report.get("coding") or {}).get("tasks") or []))
        if str(task.get("status") or "") == "review"
    ]


def _structured_futures_blocker(
    *,
    executive_report: dict[str, Any],
    bot_states: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    dry_run_health = ((executive_report.get("dry_run") or {}).get("health") or {})
    strategy_layer = executive_report.get("strategy_layer") or {}
    risk_decision = ((executive_report.get("regime") or {}).get("risk_decision") or {})
    cluster_state = _futures_cluster_state(bot_states)
    snapshot_age_seconds = (
        float(dry_run_health.get("snapshot_age_seconds"))
        if dry_run_health.get("snapshot_age_seconds") is not None
        else None
    )
    last_smoke_at = dry_run_health.get("last_smoke_at")
    last_smoke_age_seconds = _age_seconds(last_smoke_at)
    preferred_strategy_id = (
        strategy_layer.get("preferred_risk_admitted_strategy_id")
        or strategy_layer.get("preferred_strategy_id")
    )
    data_fresh = (
        cluster_state == "running"
        and snapshot_age_seconds is not None
        and snapshot_age_seconds <= FUTURES_OPERATOR_FRESHNESS_SECONDS
        and last_smoke_age_seconds is not None
        and last_smoke_age_seconds <= FUTURES_OPERATOR_FRESHNESS_SECONDS
    )
    smoke_status = str(dry_run_health.get("last_smoke_status") or "").strip().lower()
    smoke_healthy = smoke_status in {"pass", "ok"}
    runtime_operational = cluster_state == "running" and bool(dry_run_health.get("ready")) and data_fresh

    blocker_code = None
    title = None
    why_blocking = None
    expected_action = None
    if cluster_state == "stopped":
        blocker_code = "futures_cluster_stopped"
        title = "Futures cluster jest zatrzymany"
        why_blocking = "Pięć kanonicznych botów futures nie działa, więc runtime nie produkuje świeżych artefaktów."
        expected_action = "Podnieść klaster, odświeżyć snapshot i wykonać smoke dla całego futures_canonical."
    elif not data_fresh:
        blocker_code = "futures_runtime_stale"
        title = "Futures runtime jest nieświeży"
        why_blocking = "Snapshot albo smoke są zbyt stare, więc dashboard nie może ufać bieżącej ocenie futures runtime."
        expected_action = "Odświeżyć snapshot i smoke dla całego futures_canonical."
    elif not smoke_healthy or not bool(dry_run_health.get("ready")):
        blocker_code = "futures_smoke_degraded"
        title = "Futures smoke jest zdegradowany"
        why_blocking = "Któryś z botów canonical futures nie przechodzi pełnego smoke/health checku."
        expected_action = "Sprawdzić member health i powtórzyć smoke dla 5 botów po usunięciu przyczyny degradacji."
    elif not preferred_strategy_id:
        blocker_code = "futures_no_admitted_strategy"
        title = "Futures runtime nie ma dopuszczonej strategii"
        reason_excerpt = _risk_reason_excerpt(risk_decision)
        why_blocking = "Runtime jest świeży, ale centralny risk nie dopuszcza teraz żadnej z 5 kanonicznych strategii do nowych wejść."
        if reason_excerpt:
            why_blocking = f"{why_blocking} Powody: {reason_excerpt}."
        expected_action = "To nie wygląda na awarię. Sprawdzić aktualny reżim, risk_reason_codes i allowed_strategy_ids przed próbą wymuszania wejść."

    blocker = None
    if blocker_code:
        blocker = {
            "blocker_id": blocker_code,
            "source": "Futures runtime",
            "area": "futures_canonical",
            "title": title,
            "severity": "Wysoki",
            "status": blocker_code,
            "why_blocking": why_blocking,
            "expected_action": expected_action,
        }
    return blocker, {
        "cluster_state": cluster_state,
        "data_fresh": data_fresh,
        "runtime_operational": runtime_operational,
        "snapshot_age_seconds": snapshot_age_seconds,
        "last_smoke_at": last_smoke_at,
        "last_smoke_age_seconds": last_smoke_age_seconds,
        "preferred_strategy_id": preferred_strategy_id,
        "risk_reason_codes": list(risk_decision.get("risk_reason_codes") or []),
    }


def _build_graph_nodes(
    *,
    executive_report: dict[str, Any],
    bot_states: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active_agents = _active_agent_names(runs)
    nodes: list[dict[str, Any]] = []
    agent_runtime = executive_report.get("agent_runtime") or {}
    for agent in agent_runtime.get("tree") or []:
        effective_enabled = bool(agent.get("effective_enabled"))
        operational_state = str(agent.get("operational_state") or "unknown")
        if not effective_enabled:
            visual_state = "disabled"
        elif str(agent.get("name")) in active_agents:
            visual_state = "active"
        elif operational_state in {"manual_only", "manual_enabled", "active_core"}:
            visual_state = "guarded"
        else:
            visual_state = operational_state
        nodes.append(
            {
                "node_id": str(agent.get("name")),
                "label": str(agent.get("name")).replace("_", " "),
                "node_type": "agent",
                "lane": str(agent.get("domain") or "platform"),
                "operational_state": visual_state,
                "owner": str(agent.get("parent_agent") or ""),
                "summary": _safe_title(
                    agent.get("role"),
                    fallback=str(agent.get("name")),
                    limit=120,
                ),
                "target_url": "/d/crypto-agent-overview/przeglad-agentow",
            }
        )

    summary = executive_report.get("summary") or {}
    dry_run_health = ((executive_report.get("dry_run") or {}).get("health") or {})
    strategy_layer = executive_report.get("strategy_layer") or {}
    regime = executive_report.get("regime") or {}
    system_nodes = [
        (
            "regime_engine",
            "Regime Engine",
            "platform",
            "active" if summary.get("regime_available") else "warn",
            _safe_title(((regime.get("latest") or {}).get("primary_regime")), fallback="Brak reżimu", limit=96),
        ),
        (
            "risk_desk",
            "Risk Desk",
            "platform",
            "active" if summary.get("risk_decision_available") else "warn",
            _safe_title(((regime.get("risk_decision") or {}).get("trading_mode")), fallback="Brak risk decision", limit=96),
        ),
        (
            "strategy_layer",
            "Strategy Layer",
            "strategy",
            "active" if summary.get("strategy_layer_available") else "warn",
            _safe_title(
                strategy_layer.get("preferred_risk_admitted_strategy_id")
                or strategy_layer.get("preferred_strategy_id"),
                fallback="Brak preferowanej strategii",
                limit=96,
            ),
        ),
        (
            "execution_runtime",
            "Execution Runtime",
            "runtime",
            "active" if dry_run_health.get("ready") else "blocked",
            _safe_title(
                (dry_run_health or {}).get("bridge_status"),
                fallback="Brak health runtime",
                limit=96,
            ),
        ),
        (
            "futures_cluster",
            "Futures Cluster",
            "runtime",
            "active" if dry_run_health.get("ready") else "degraded",
            _safe_title(
                (dry_run_health or {}).get("blocking_reason"),
                fallback="Cluster ready" if dry_run_health.get("ready") else "Cluster degraded",
                limit=96,
            ),
        ),
    ]
    for node_id, label, lane, visual_state, summary_text in system_nodes:
        nodes.append(
            {
                "node_id": node_id,
                "label": label,
                "node_type": "system",
                "lane": lane,
                "operational_state": visual_state,
                "owner": "",
                "summary": summary_text,
                "target_url": "/d/crypto-trading-ai/trading-i-ai",
            }
        )

    member_health = {
        str(member.get("bot_id")): dict(member)
        for member in list(dry_run_health.get("members") or [])
        if member.get("bot_id")
    }
    for bot in bot_states:
        runtime_group = str(bot.get("runtime_group") or "")
        if runtime_group != "futures_canonical":
            continue
        bot_id = str(bot.get("bot_id"))
        member = member_health.get(bot_id, {})
        ready = bool(member.get("ready"))
        state = str(bot.get("state") or "unknown")
        if state == "running" and ready:
            visual_state = "active"
        elif state == "running":
            visual_state = "degraded"
        else:
            visual_state = "disabled"
        nodes.append(
            {
                "node_id": bot_id,
                "label": bot_id,
                "node_type": "bot",
                "lane": "runtime",
                "operational_state": visual_state,
                "owner": str(bot.get("strategy_id") or ""),
                "summary": _safe_title(
                    bot.get("strategy_id") or member.get("blocking_reason") or state,
                    fallback=state,
                    limit=120,
                ),
                "target_url": "/d/crypto-trading-ai/trading-i-ai",
            }
        )
    return nodes


def _build_graph_edges(
    *,
    executive_report: dict[str, Any],
    bot_states: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for agent in (executive_report.get("agent_runtime") or {}).get("tree") or []:
        parent = agent.get("parent_agent")
        name = agent.get("name")
        if parent and name:
            edges.append(
                {
                    "edge_id": f"{parent}->{name}",
                    "source": str(parent),
                    "target": str(name),
                    "edge_type": "ownership",
                    "status": "active",
                    "summary": "ownership",
                }
            )
    static_edges = [
        ("control_layer_agent", "regime_engine", "control"),
        ("control_layer_agent", "risk_desk", "control"),
        ("strategy_agent", "strategy_layer", "control"),
        ("risk_desk", "execution_runtime", "runtime"),
        ("regime_engine", "risk_desk", "dataflow"),
        ("strategy_layer", "execution_runtime", "dataflow"),
        ("execution_runtime", "futures_cluster", "runtime"),
    ]
    for source, target, edge_type in static_edges:
        edges.append(
            {
                "edge_id": f"{source}->{target}",
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "status": "active",
                "summary": edge_type,
            }
        )
    for bot in bot_states:
        if str(bot.get("runtime_group") or "") != "futures_canonical":
            continue
        bot_id = str(bot.get("bot_id"))
        edges.append(
            {
                "edge_id": f"futures_cluster->{bot_id}",
                "source": "futures_cluster",
                "target": bot_id,
                "edge_type": "member",
                "status": "active",
                "summary": str(bot.get("strategy_id") or "canonical bot"),
            }
        )
    return edges


def _build_current_work(
    *,
    executive_report: dict[str, Any],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for run in runs:
        status = str(run.get("status") or "")
        if status not in {"queued", "running", "awaiting_approval"}:
            continue
        payload = dict(run.get("payload_json") or {})
        metadata = dict(payload.get("metadata") or {})
        requested_paths = list(payload.get("requested_paths") or [])
        items.append(
            {
                "item_id": str(run.get("run_id")),
                "owner_name": str(run.get("agent_name") or "unknown"),
                "owner_type": "agent",
                "workstream": _safe_title(
                    metadata.get("autopilot_task") or metadata.get("autopilot_cycle") or "agent_run",
                    fallback="agent_run",
                    limit=64,
                ),
                "status": status,
                "title": _safe_title(run.get("goal"), fallback="Aktywny run", limit=120),
                "next_step": _safe_title(
                    metadata.get("next_step") or "Czeka na zakończenie bieżącego kroku.",
                    fallback="Czeka na zakończenie bieżącego kroku.",
                    limit=140,
                ),
                "scope": _safe_title(requested_paths[0] if requested_paths else "cross_module", fallback="cross_module", limit=72),
            }
        )

    coding = executive_report.get("coding") or {}
    for task in coding.get("tasks") or []:
        status = str(task.get("status") or "")
        if status not in {"dispatched", "coding", "review", "approved"}:
            continue
        items.append(
            {
                "item_id": f"coding:{task.get('task_id')}",
                "owner_name": str(task.get("owner_agent") or "unknown"),
                "owner_type": "coding",
                "workstream": "coding_supervisor",
                "status": status,
                "title": _safe_title(task.get("goal"), fallback="Coding task", limit=120),
                "next_step": _safe_title(
                    (task.get("review_json") or {}).get("decision")
                    or "Dowieźć task do review albo commitu.",
                    fallback="Dowieźć task do review albo commitu.",
                    limit=140,
                ),
                "scope": _safe_title(task.get("module_id"), fallback="module", limit=72),
            }
        )

    autopilot = executive_report.get("autopilot") or {}
    if autopilot.get("running"):
        items.append(
            {
                "item_id": "autopilot:current",
                "owner_name": "system_lead_agent",
                "owner_type": "autopilot",
                "workstream": "autopilot",
                "status": str(autopilot.get("last_status") or "running"),
                "title": _safe_title(
                    autopilot.get("current_task_name") or autopilot.get("next_task_name") or "Cykl autopilota",
                    fallback="Cykl autopilota",
                    limit=120,
                ),
                "next_step": _safe_title(
                    autopilot.get("next_task_name") or "Kolejny cykl zgodnie z kolejką leada.",
                    fallback="Kolejny cykl zgodnie z kolejką leada.",
                    limit=140,
                ),
                "scope": "autopilot",
            }
        )

    items.sort(key=lambda item: (_status_rank(item.get("status", "")), item.get("owner_name", ""), item.get("title", "")))
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        item_id = str(item.get("item_id"))
        if item_id in seen_ids:
            continue
        deduped.append(item)
        seen_ids.add(item_id)
        if len(deduped) >= 12:
            break
    return deduped


def _build_recent_handoffs(executive_report: dict[str, Any]) -> list[dict[str, Any]]:
    handoffs: list[dict[str, Any]] = []
    for task in (executive_report.get("coding") or {}).get("tasks") or []:
        status = str(task.get("status") or "")
        if status not in {"dispatched", "review", "approved", "committed"}:
            continue
        from_actor = "system_lead_agent" if status == "dispatched" else str(task.get("owner_agent") or "unknown")
        to_actor = str(task.get("owner_agent") or "unknown")
        if status == "review":
            to_actor = "review_agent"
        elif status == "approved":
            to_actor = "control_layer_agent"
        elif status == "committed":
            to_actor = "control_layer_agent"
        handoffs.append(
            {
                "handoff_id": f"handoff:{task.get('task_id')}:{status}",
                "from_actor": from_actor,
                "to_actor": to_actor,
                "status": status,
                "title": _safe_title(task.get("goal"), fallback="Coding task", limit=120),
                "reason": _safe_title(task.get("module_id"), fallback="module", limit=96),
            }
        )
        if len(handoffs) >= 8:
            break
    return handoffs


def _build_top_blockers(
    *,
    executive_report: dict[str, Any],
    bot_states: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    stale_attention_items_count = 0
    futures_blocker, futures_state = _structured_futures_blocker(
        executive_report=executive_report,
        bot_states=bot_states,
    )
    if futures_blocker is not None:
        blockers.append(futures_blocker)
        if not futures_state.get("data_fresh"):
            stale_attention_items_count += 1

    for task in _coding_review_tasks(executive_report)[:3]:
        blockers.append(
            {
                "blocker_id": f"coding_review:{task.get('task_id')}",
                "source": "Coding review",
                "area": str(task.get("module_id") or "coding"),
                "title": _safe_title(task.get("goal"), fallback="Coding review", limit=120),
                "severity": "Średni",
                "status": "review",
                "why_blocking": "Task kodujący nadal czeka na decyzję review i nie powinien wracać jako aktywny blocker po zamknięciu.",
                "expected_action": "Zatwierdzić, odrzucić albo oznaczyć task jako superseded, jeśli został już zastąpiony inną zmianą.",
            }
        )

    coding_status = dict(((executive_report.get("coding") or {}).get("status") or {}))
    if coding_status.get("attention_needed"):
        blockers.append(
            {
                "blocker_id": "coding_supervisor_attention",
                "source": "Coding supervisor",
                "area": "control_layer_runtime",
                "title": "Coding supervisor wymaga uwagi",
                "severity": "Wysoki",
                "status": str(coding_status.get("last_error") or "attention"),
                "why_blocking": _safe_title(
                    coding_status.get("last_error"),
                    fallback="Supervisor wykrył stan wymagający interwencji operatora.",
                    limit=180,
                ),
                "expected_action": "Sprawdzić aktywny task, worker context i resource guard przed wznowieniem kolejnych dispatchy.",
            }
        )

    stale_attention_items_count += len(list(executive_report.get("blockers") or []))
    return blockers[:6], {
        **futures_state,
        "coding_review_blockers": len(_coding_review_tasks(executive_report)),
        "stale_attention_items_count": stale_attention_items_count,
    }


def _build_recent_errors(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for blocker in blockers:
        severity = str(blocker.get("severity") or "").lower()
        if severity not in {"wysoki", "krytyczne", "high", "critical"}:
            continue
        errors.append(
            {
                "source": str(blocker.get("source") or "unknown"),
                "status": str(blocker.get("status") or "unknown"),
                "title": _safe_title(blocker.get("title"), fallback="Bloker", limit=120),
                "summary": _safe_title(blocker.get("why_blocking"), fallback="Brak szczegółu.", limit=160),
            }
        )
        if len(errors) >= 6:
            break
    return errors


def _build_runtime_focus(executive_report: dict[str, Any]) -> list[dict[str, Any]]:
    summary = executive_report.get("summary") or {}
    regime = executive_report.get("regime") or {}
    risk_decision = regime.get("risk_decision") or {}
    strategy_layer = executive_report.get("strategy_layer") or {}
    dry_run_health = ((executive_report.get("dry_run") or {}).get("health") or {})
    items = [
        {
            "item_id": "runtime:cluster",
            "area": "futures_runtime",
            "status": "ready" if dry_run_health.get("ready") else "degraded",
            "title": "Futures cluster health",
            "detail": _safe_title(dry_run_health.get("bridge_status") or dry_run_health.get("blocking_reason"), fallback="Brak health runtime", limit=140),
            "next_step": _safe_title("Utrzymać świeże snapshoty i smoke test dla wszystkich canonical botów.", fallback="Utrzymać health runtime.", limit=140),
        },
        {
            "item_id": "runtime:regime",
            "area": "regime",
            "status": "ready" if summary.get("regime_available") else "missing",
            "title": "Primary regime",
            "detail": _safe_title((regime.get("latest") or {}).get("primary_regime"), fallback="Brak regime report", limit=140),
            "next_step": _safe_title("Potwierdzić klasyfikację reżimu i bias przed kolejnym cyclem.", fallback="Wygenerować regime report.", limit=140),
        },
        {
            "item_id": "runtime:risk",
            "area": "risk",
            "status": "ready" if summary.get("risk_decision_available") else "missing",
            "title": "Risk desk",
            "detail": _safe_title(risk_decision.get("trading_mode") or risk_decision.get("allow_trading"), fallback="Brak risk decision", limit=140),
            "next_step": _safe_title("Sprawdzić allowed directions, caps i enforcement counters.", fallback="Wygenerować risk decision.", limit=140),
        },
        {
            "item_id": "runtime:strategy",
            "area": "strategy_layer",
            "status": "ready" if summary.get("strategy_layer_available") else "missing",
            "title": "Strategy layer",
            "detail": _safe_title(
                strategy_layer.get("preferred_risk_admitted_strategy_id")
                or strategy_layer.get("preferred_strategy_id"),
                fallback="Brak preferowanej strategii",
                limit=140,
            ),
            "next_step": _safe_title("Monitorować built signals, admitted strategies i block reasony.", fallback="Wygenerować strategy layer report.", limit=140),
        },
        {
            "item_id": "runtime:replay",
            "area": "system_replay",
            "status": "ready" if summary.get("regime_replay_available") else "missing",
            "title": "System replay",
            "detail": _safe_title(
                (regime.get("replay") or {}).get("status") or "Brak replay artifact",
                fallback="Brak replay artifact",
                limit=140,
            ),
            "next_step": _safe_title("Domknąć regularny replay smoke i miesięczne readiness runy.", fallback="Uruchomić replay.", limit=140),
        },
    ]
    return items


def _build_cost_control(
    *,
    executive_report: dict[str, Any],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = executive_report.get("summary") or {}
    agent_runtime = executive_report.get("agent_runtime") or {}
    return {
        "agents_status": str(agent_runtime.get("status") or "unknown"),
        "observability_owner": str(agent_runtime.get("observability_owner") or ""),
        "daily_budget_usd": float(summary.get("agent_budget_daily_total_usd", 0.0) or 0.0),
        "per_run_budget_usd": float(summary.get("agent_budget_per_run_total_usd", 0.0) or 0.0),
        "budget_blocked_runs_total": _budget_block_count(runs),
        "active_core_agents": list((agent_runtime.get("summary") or {}).get("active_core_agents") or [])[:8],
        "items": [
            {
                "item_id": "cost:agents",
                "title": "Agent runtime",
                "status": str(agent_runtime.get("status") or "unknown"),
                "detail": _safe_title(agent_runtime.get("reason"), fallback="Brak dodatkowego powodu.", limit=140),
            },
            {
                "item_id": "cost:daily_budget",
                "title": "Daily budget",
                "status": "guarded",
                "detail": f"{float(summary.get('agent_budget_daily_total_usd', 0.0) or 0.0):.2f} USD",
            },
            {
                "item_id": "cost:per_run_budget",
                "title": "Per run budget",
                "status": "guarded",
                "detail": f"{float(summary.get('agent_budget_per_run_total_usd', 0.0) or 0.0):.2f} USD",
            },
            {
                "item_id": "cost:budget_blocks",
                "title": "Budget blocks",
                "status": "ok" if _budget_block_count(runs) == 0 else "attention",
                "detail": str(_budget_block_count(runs)),
            },
        ],
    }


def build_observability_summary(
    *,
    executive_report: dict[str, Any],
    bot_states: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = executive_report.get("summary") or {}
    top_blockers, structured_state = _build_top_blockers(
        executive_report=executive_report,
        bot_states=bot_states,
    )
    goals_and_direction = {
        "strategic_goal": _safe_title(executive_report.get("strategic_goal"), fallback="Brak strategicznego celu.", limit=180),
        "lead_note": _safe_title(
            ((executive_report.get("lead_notes") or [{}])[0] or {}).get("message"),
            fallback="Brak świeżej notki leada.",
            limit=180,
        ),
        "next_step": _safe_title(
            ((executive_report.get("lead_notes") or [{}])[0] or {}).get("next_step"),
            fallback="Brak kolejnego kroku w lead notes.",
            limit=180,
        ),
        "module_directions": [
            {
                "module_id": str(module.get("id")),
                "module_name": _safe_title(module.get("name"), fallback="module", limit=80),
                "direction": _safe_title(module.get("direction"), fallback="Brak kierunku.", limit=120),
                "current_focus": _safe_title(module.get("current_focus"), fallback="Brak focusu.", limit=120),
            }
            for module in list(executive_report.get("modules") or [])[:6]
        ],
    }
    operator_attention = [
        _safe_title(blocker.get("title"), fallback="Bloker", limit=140)
        for blocker in top_blockers[:5]
    ]
    executive_generated_at = executive_report.get("generated_at")
    executive_age_seconds = _age_seconds(executive_generated_at)
    built = {
        "generated_at": _utc_now(),
        "graph_nodes": _build_graph_nodes(
            executive_report=executive_report,
            bot_states=bot_states,
            runs=runs,
        ),
        "graph_edges": _build_graph_edges(
            executive_report=executive_report,
            bot_states=bot_states,
        ),
        "current_work": _build_current_work(
            executive_report=executive_report,
            runs=runs,
        ),
        "recent_handoffs": _build_recent_handoffs(executive_report),
        "recent_errors": _build_recent_errors(top_blockers),
        "top_blockers": top_blockers,
        "goals_and_direction": goals_and_direction,
        "operator_attention": operator_attention,
        "futures_runtime": {
            "health": (executive_report.get("dry_run") or {}).get("health") or {},
            "preferred_risk_admitted_strategy_id": (executive_report.get("strategy_layer") or {}).get(
                "preferred_risk_admitted_strategy_id"
            ),
            "preferred_strategy_id": (executive_report.get("strategy_layer") or {}).get("preferred_strategy_id"),
            "built_signals_total": int(summary.get("strategy_layer_built_signals_total", 0) or 0),
            "risk_admitted_total": int(summary.get("strategy_layer_risk_admitted_total", 0) or 0),
            "risk_trading_mode": ((executive_report.get("regime") or {}).get("risk_decision") or {}).get("trading_mode"),
            "new_entries_allowed": bool(
                ((executive_report.get("regime") or {}).get("risk_decision") or {}).get("new_entries_allowed")
            ),
            "risk_reason_codes": list(
                (((executive_report.get("regime") or {}).get("risk_decision") or {}).get("risk_reason_codes") or [])
            ),
            "runtime_operational": bool(structured_state.get("runtime_operational")),
            "data_fresh": bool(structured_state.get("data_fresh")),
            "snapshot_age_seconds": structured_state.get("snapshot_age_seconds"),
            "last_smoke_at": structured_state.get("last_smoke_at"),
            "last_smoke_age_seconds": structured_state.get("last_smoke_age_seconds"),
        },
        "runtime_focus": _build_runtime_focus(executive_report),
        "cost_control": _build_cost_control(
            executive_report=executive_report,
            runs=runs,
        ),
        "freshness": {
            "executive_generated_at": executive_generated_at,
            "observability_generated_at": _utc_now(),
            "is_agent_stack_disabled": bool(summary.get("agents_disabled")),
            "is_runtime_ready": bool(summary.get("dry_run_ready")),
            "ai_runtime_fresh": executive_age_seconds is None or executive_age_seconds <= FUTURES_OPERATOR_FRESHNESS_SECONDS,
            "futures_data_fresh": bool(structured_state.get("data_fresh")),
            "coding_review_blockers": int(structured_state.get("coding_review_blockers", 0) or 0),
            "stale_attention_items_count": int(structured_state.get("stale_attention_items_count", 0) or 0),
        },
    }
    state_payload = dict(built)
    state_payload.pop("generated_at", None)
    freshness = dict(state_payload.get("freshness") or {})
    freshness.pop("observability_generated_at", None)
    state_payload["freshness"] = freshness
    built["state_hash"] = hashlib.sha256(
        json.dumps(state_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return built


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent) as handle:
        temp_path = Path(handle.name)
        try:
            handle.write(content)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    os.replace(temp_path, target)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_latest_observability_summary(settings: AppSettings) -> dict[str, Any] | None:
    path = settings.observability_latest_path
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_observability_summary_history(settings: AppSettings, *, limit: int = 20) -> list[dict[str, Any]]:
    path = settings.observability_history_path
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return items[-limit:]


def persist_observability_summary(settings: AppSettings, summary: dict[str, Any]) -> dict[str, Any]:
    previous = load_latest_observability_summary(settings)
    previous_hash = str((previous or {}).get("state_hash") or "")
    current_hash = str(summary.get("state_hash") or "")

    latest_payload = dict(summary)
    _atomic_write_text(
        settings.observability_latest_path,
        json.dumps(latest_payload, ensure_ascii=False, indent=2) + "\n",
    )

    if previous_hash == current_hash:
        return latest_payload

    _append_jsonl(settings.observability_history_path, latest_payload)

    log_record = {
        "timestamp": summary.get("generated_at"),
        "event_type": "observability_summary",
        "status": str(((summary.get("cost_control") or {}).get("agents_status")) or "unknown"),
        "title": "Observability summary refreshed",
        "summary": _safe_title(
            "; ".join(str(item) for item in list(summary.get("operator_attention") or [])[:3]),
            fallback="Brak nowych uwag operatora.",
            limit=200,
        ),
        "next_step": _safe_title(
            (((summary.get("goals_and_direction") or {}).get("next_step"))),
            fallback="Kontynuować guarded monitoring i futures runtime watch.",
            limit=180,
        ),
        "severity": "info" if not (summary.get("top_blockers") or []) else "warning",
    }
    _append_jsonl(settings.observability_log_path, log_record)
    return latest_payload
