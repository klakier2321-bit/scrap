"""Helpers for publishing runtime-consumable artifacts into Freqtrade user_data."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_futures_bot_id(strategy_id: str) -> str:
    return f"ft_{strategy_id}"


def strategy_id_from_bot_id(bot_id: str) -> str | None:
    if str(bot_id).startswith("ft_"):
        return str(bot_id)[3:]
    return None


def is_canonical_futures_bot_id(bot_id: str) -> bool:
    return strategy_id_from_bot_id(bot_id) is not None


def bot_artifact_dir(base_dir: Path, bot_id: str) -> Path:
    return base_dir / bot_id


def publish_risk_decision(base_dir: Path, bot_id: str, decision: dict[str, Any]) -> Path:
    path = bot_artifact_dir(base_dir, bot_id) / "risk" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def publish_strategy_report(
    base_dir: Path,
    bot_id: str,
    report: dict[str, Any],
) -> Path:
    path = bot_artifact_dir(base_dir, bot_id) / "signals" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def publish_global_portfolio(base_dir: Path, snapshot: dict[str, Any]) -> Path:
    path = base_dir / "global" / "portfolio" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def aggregate_portfolio_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    bot_ids: list[str],
) -> dict[str, Any]:
    generated_at = now_iso()
    balance_total = 0.0
    total_open_stakes = 0.0
    max_open_trades = 0
    open_trades: list[dict[str, Any]] = []
    strategies: list[str] = []

    for snapshot in snapshots:
        balance_summary = dict(snapshot.get("balance_summary") or {})
        trade_summary = dict(snapshot.get("trade_count_summary") or {})
        try:
            balance_total = max(balance_total, float(balance_summary.get("total") or 0.0))
        except (TypeError, ValueError):
            pass
        try:
            total_open_stakes += float(trade_summary.get("total_open_trades_stakes") or 0.0)
        except (TypeError, ValueError):
            pass
        try:
            max_open_trades = max(max_open_trades, int(trade_summary.get("max_open_trades") or 0))
        except (TypeError, ValueError):
            pass
        strategies.append(str(snapshot.get("strategy") or "unknown"))
        for trade in list(snapshot.get("open_trades") or []):
            payload = dict(trade)
            payload.setdefault("source_bot_id", snapshot.get("bot_id"))
            open_trades.append(payload)

    return {
        "bot_id": "futures_canonical_cluster",
        "runtime_group": "futures_canonical",
        "generated_at": generated_at,
        "source": "aggregated_futures_bot_snapshots",
        "aggregation_mode": {
            "balance_total": "max_member_balance",
            "open_trades": "union",
            "total_open_trades_stakes": "sum",
            "max_open_trades": "disabled_for_cluster_overlay",
        },
        "member_bot_ids": bot_ids,
        "member_strategies": strategies,
        "balance_summary": {"total": round(balance_total, 8)},
        "trade_count_summary": {
            "current_open_trades": len(open_trades),
            "total_open_trades_stakes": round(total_open_stakes, 8),
            "max_open_trades": None,
        },
        "open_trades_count": len(open_trades),
        "open_trades": open_trades,
        "snapshot_status": "ok",
        "runmode": "dry_run",
        "dry_run": True,
    }


def aggregate_strategy_layer_reports(
    reports: list[dict[str, Any]],
    *,
    bot_ids: list[str],
) -> dict[str, Any]:
    built_signals: list[dict[str, Any]] = []
    applicable: list[str] = []
    blocked: list[str] = []
    risk_admitted: list[str] = []
    blocked_by_risk: list[str] = []
    advisory: list[str] = []
    evaluations: list[dict[str, Any]] = []
    ranking: list[dict[str, Any]] = []
    manifests_total = 0
    implemented_total = 0
    first_report = reports[0] if reports else {}

    for report in reports:
        manifests_total += int(report.get("manifests_total") or 0)
        implemented_total += int(report.get("implemented_strategies_total") or 0)
        built_signals.extend(list(report.get("built_signals") or []))
        applicable.extend(list(report.get("applicable_strategy_ids") or []))
        blocked.extend(list(report.get("blocked_strategy_ids") or []))
        risk_admitted.extend(list(report.get("risk_admitted_strategy_ids") or []))
        blocked_by_risk.extend(list(report.get("blocked_by_risk_strategy_ids") or []))
        advisory.extend(list(report.get("advisory_strategy_ids") or []))
        evaluations.extend(list(report.get("strategy_evaluations") or []))
        ranking.extend(list(report.get("ranking") or []))

    built_signals.sort(
        key=lambda item: (
            0 if item.get("risk_admissible") else 1,
            -float(item.get("rank_score") or 0.0),
            item.get("strategy_id", ""),
        )
    )
    ranking.sort(key=lambda item: (-float(item.get("rank_score") or 0.0), item.get("strategy_id", "")))
    preferred = next((item.get("strategy_id") for item in built_signals if item.get("risk_admissible")), None)

    return {
        "generated_at": now_iso(),
        "bot_id": "futures_canonical_cluster",
        "member_bot_ids": bot_ids,
        "status": "ok" if reports else "missing",
        "primary_regime": first_report.get("primary_regime"),
        "market_state": first_report.get("market_state"),
        "market_phase": first_report.get("market_phase"),
        "volatility_phase": first_report.get("volatility_phase"),
        "trading_mode": first_report.get("trading_mode"),
        "data_trust_level": first_report.get("data_trust_level"),
        "allowed_directions": list(first_report.get("allowed_directions") or []),
        "manifests_total": manifests_total,
        "implemented_strategies_total": implemented_total,
        "applicable_strategy_ids": sorted(set(applicable)),
        "blocked_strategy_ids": sorted(set(blocked)),
        "risk_admitted_strategy_ids": sorted(set(risk_admitted)),
        "blocked_by_risk_strategy_ids": sorted(set(blocked_by_risk)),
        "advisory_strategy_ids": sorted(set(advisory)),
        "strategy_evaluations": evaluations,
        "built_signals": built_signals,
        "preferred_strategy_id": preferred,
        "preferred_risk_admitted_strategy_id": preferred,
        "ranking": ranking,
    }
