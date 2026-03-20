"""Portfolio-aware overlays for risk budgets."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .. import reason_codes as rc
from ..models import PortfolioState


def build_portfolio_state(snapshot: dict[str, Any] | None) -> PortfolioState | None:
    if not snapshot:
        return None

    total_equity = 0.0
    balance_summary = snapshot.get("balance_summary") or {}
    try:
        total_equity = float(balance_summary.get("total") or 0.0)
    except (TypeError, ValueError):
        total_equity = 0.0

    trade_count_summary = snapshot.get("trade_count_summary") or {}
    try:
        total_open_stakes = float(trade_count_summary.get("total_open_trades_stakes") or 0.0)
    except (TypeError, ValueError):
        total_open_stakes = 0.0
    open_positions = list(snapshot.get("open_trades") or [])
    positions_per_symbol = Counter()
    direction_counts = Counter()
    correlation_counts = Counter()
    for trade in open_positions:
        pair = str(trade.get("pair") or "unknown")
        side = str(trade.get("side") or "unknown")
        base = pair.split("/")[0] if "/" in pair else pair.split(":")[0]
        positions_per_symbol[pair] += 1
        direction_counts[side] += 1
        correlation_counts[base] += 1
    return PortfolioState(
        bot_id=snapshot.get("bot_id"),
        total_equity=total_equity,
        open_positions=open_positions,
        open_positions_count=int(snapshot.get("open_trades_count") or len(open_positions)),
        gross_exposure_pct=round((total_open_stakes / total_equity) * 100.0, 4) if total_equity > 0 else 0.0,
        max_open_positions_config=trade_count_summary.get("max_open_trades"),
        positions_per_symbol=dict(positions_per_symbol),
        direction_counts=dict(direction_counts),
        correlation_counts=dict(correlation_counts),
    )


def evaluate_portfolio_overlay(
    *,
    portfolio_state: PortfolioState,
    allowed_directions: list[str],
    base_budget: dict[str, Any],
) -> dict[str, Any]:
    reason_codes: list[str] = []
    notes: list[str] = []
    adjusted = dict(base_budget)

    if portfolio_state.open_positions_count >= int(base_budget.get("max_positions_total", 0)):
        adjusted["max_position_size_pct"] = 0.0
        adjusted["max_total_exposure_pct"] = min(
            float(adjusted.get("max_total_exposure_pct", 0.0)),
            portfolio_state.gross_exposure_pct,
        )
        reason_codes.append(rc.PORTFOLIO_POSITION_LIMIT_REACHED)
        notes.append("Portfel wykorzystuje juz limit otwartych pozycji.")

    configured_limit = portfolio_state.max_open_positions_config
    if configured_limit is not None and portfolio_state.open_positions_count >= int(configured_limit):
        adjusted["max_positions_total"] = min(int(adjusted.get("max_positions_total", 0)), int(configured_limit))
        adjusted["max_position_size_pct"] = 0.0
        reason_codes.append(rc.PORTFOLIO_POSITION_LIMIT_REACHED)
        notes.append("Runtime wykorzystuje juz skonfigurowany limit max_open_trades.")

    if portfolio_state.gross_exposure_pct >= float(base_budget.get("max_total_exposure_pct", 0.0)):
        adjusted["max_position_size_pct"] = 0.0
        reason_codes.append(rc.PORTFOLIO_EXPOSURE_CAP_REACHED)
        notes.append("Gross exposure portfela przekracza dopuszczalny budzet ryzyka.")

    if any(count > int(base_budget.get("max_correlated_positions", 0)) for count in portfolio_state.correlation_counts.values()):
        adjusted["max_positions_total"] = min(int(adjusted.get("max_positions_total", 0)), 1)
        reason_codes.append(rc.PORTFOLIO_CORRELATION_CAP_REACHED)
        notes.append("Portfel ma zbyt wiele skorelowanych pozycji i ogranicza nowe wejscia.")

    known_sides = {side for side in portfolio_state.direction_counts if side in {"long", "short"}}
    if known_sides and allowed_directions:
        disallowed_open = known_sides - set(allowed_directions)
        if disallowed_open and portfolio_state.open_positions_count > 0:
            adjusted["max_position_size_pct"] = 0.0
            reason_codes.append(rc.PORTFOLIO_DIRECTION_OVERLOAD)
            notes.append("Portfel ma otwarte pozycje w kierunku, ktorego risk engine juz nie dopuszcza.")

    return {
        "adjusted_budget": adjusted,
        "reason_codes": reason_codes,
        "notes": notes,
    }
