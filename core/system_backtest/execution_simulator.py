"""Deterministic execution and portfolio simulation for system replay."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from ..risk_management import reason_codes as rc
from .models import ReplayPendingOrder, ReplayPosition, SystemBacktestTrade


EXIT_TEMPLATE_DEFAULTS: dict[str, dict[str, float | int]] = {
    "trend_structure_trail": {"time_stop_bars": 12, "target_pct": 0.010, "stop_pct": 0.005},
    "expansion_follow_through": {"time_stop_bars": 6, "target_pct": 0.012, "stop_pct": 0.006},
    "return_to_mid_or_opposite_boundary": {"time_stop_bars": 8, "target_pct": 0.007, "stop_pct": 0.005},
    "fast_shock_reversion": {"time_stop_bars": 4, "target_pct": 0.010, "stop_pct": 0.007},
}


class ExecutionSimulator:
    """Simulates global-cluster execution, fills, exits, and portfolio state."""

    def __init__(self, *, starting_equity: float, fee_rate: float, slippage_rate: float) -> None:
        self.starting_equity = float(starting_equity)
        self.fee_rate = float(fee_rate)
        self.slippage_rate = float(slippage_rate)
        self.realized_pnl = 0.0
        self.pending_orders: list[ReplayPendingOrder] = []
        self.open_positions: list[ReplayPosition] = []
        self.closed_trades: list[SystemBacktestTrade] = []
        self.execution_events: list[dict[str, Any]] = []

    def current_total_equity(self, current_bars: dict[str, dict[str, Any]] | None = None) -> float:
        return round(self.starting_equity + self.realized_pnl + self._unrealized_pnl(current_bars or {}), 8)

    def build_portfolio_snapshot(
        self,
        *,
        timestamp: str,
        current_bars: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        open_trades = [position.to_snapshot_trade() for position in self.open_positions]
        total_open_stakes = round(sum(position.stake for position in self.open_positions), 8)
        return {
            "bot_id": "futures_canonical_cluster",
            "runtime_group": "futures_canonical",
            "generated_at": timestamp,
            "source": "system_replay",
            "balance_summary": {"total": self.current_total_equity(current_bars)},
            "trade_count_summary": {
                "current_open_trades": len(self.open_positions),
                "total_open_trades_stakes": total_open_stakes,
                "max_open_trades": None,
            },
            "open_trades_count": len(self.open_positions),
            "open_trades": open_trades,
            "snapshot_status": "ok",
            "runmode": "system_replay",
            "dry_run": True,
        }

    def process_new_signals(
        self,
        *,
        timestamp: str,
        risk_decision: dict[str, Any],
        strategy_reports: list[dict[str, Any]],
        current_bars: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        counters = {
            "signals_built": 0,
            "signals_risk_admitted": 0,
            "entries_attempted": 0,
            "entries_blocked_by_risk": 0,
            "entries_blocked_by_execution": 0,
        }
        blocked_reason_codes: list[str] = []
        snapshot = self.build_portfolio_snapshot(timestamp=timestamp, current_bars=current_bars)

        for report in strategy_reports:
            counters["signals_built"] += len(list(report.get("built_signals") or []))
            counters["signals_risk_admitted"] += len(list(report.get("risk_admitted_strategy_ids") or []))
            for signal in list(report.get("built_signals") or []):
                if not signal.get("risk_admissible"):
                    counters["entries_blocked_by_risk"] += 1
                    blocked_reason_codes.extend(list(signal.get("risk_block_reasons") or []))
                    self.execution_events.append(
                        {
                            "timestamp": timestamp,
                            "event_type": "risk_blocked_signal",
                            "strategy_id": signal.get("strategy_id"),
                            "signal_id": signal.get("signal_id"),
                            "reason_codes": list(signal.get("risk_block_reasons") or []),
                        }
                    )
                    continue

                counters["entries_attempted"] += 1
                admission = self._admit_signal(
                    signal=signal,
                    risk_decision=risk_decision,
                    snapshot=snapshot,
                )
                if not admission["entry_allowed"]:
                    counters["entries_blocked_by_execution"] += 1
                    blocked_reason_codes.extend(list(admission["blocked_reason_codes"]))
                    self.execution_events.append(
                        {
                            "timestamp": timestamp,
                            "event_type": "execution_blocked_signal",
                            "strategy_id": signal.get("strategy_id"),
                            "signal_id": signal.get("signal_id"),
                            "reason_codes": list(admission["blocked_reason_codes"]),
                        }
                    )
                    continue

                order = ReplayPendingOrder(
                    signal_id=str(signal["signal_id"]),
                    strategy_id=str(signal["strategy_id"]),
                    bot_id=f"ft_{signal['strategy_id']}",
                    pair=str(signal["pair"]),
                    side=str(signal["direction"]),
                    entry_type=str(signal["entry_type"]),
                    entry_zone=dict(signal.get("entry_zone") or {}),
                    signal=dict(signal),
                    created_at=timestamp,
                    stake=float(admission["final_stake"]),
                    leverage=float(admission["final_leverage"]),
                )
                self.pending_orders.append(order)
                self.execution_events.append(
                    {
                        "timestamp": timestamp,
                        "event_type": "entry_scheduled",
                        "strategy_id": order.strategy_id,
                        "signal_id": order.signal_id,
                        "pair": order.pair,
                        "side": order.side,
                        "stake": order.stake,
                        "leverage": order.leverage,
                    }
                )
                snapshot_open_trades = list(snapshot.get("open_trades") or [])
                snapshot_open_trades.append(
                    {
                        "pair": order.pair,
                        "side": order.side,
                        "is_short": order.side == "short",
                        "stake_amount": order.stake,
                        "source_bot_id": order.bot_id,
                    }
                )
                current_stakes = float((snapshot.get("trade_count_summary") or {}).get("total_open_trades_stakes") or 0.0)
                snapshot = {
                    **snapshot,
                    "open_trades": snapshot_open_trades,
                    "open_trades_count": len(snapshot_open_trades),
                    "trade_count_summary": {
                        **dict(snapshot.get("trade_count_summary") or {}),
                        "current_open_trades": len(snapshot_open_trades),
                        "total_open_trades_stakes": round(current_stakes + order.stake, 8),
                    },
                }

        return {
            **counters,
            "blocked_reason_codes": blocked_reason_codes,
        }

    def fill_pending_orders(
        self,
        *,
        timestamp: str,
        current_bars: dict[str, dict[str, Any]],
    ) -> int:
        filled = 0
        remaining: list[ReplayPendingOrder] = []
        for order in self.pending_orders:
            bar = current_bars.get(order.pair)
            if bar is None:
                remaining.append(order)
                continue
            fill_price = self._fill_price(order=order, bar=bar)
            if fill_price is None:
                remaining.append(order)
                continue
            position = self._position_from_order(order=order, timestamp=timestamp, fill_price=fill_price)
            self.open_positions.append(position)
            filled += 1
            self.execution_events.append(
                {
                    "timestamp": timestamp,
                    "event_type": "entry_filled",
                    "trade_id": position.trade_id,
                    "strategy_id": position.strategy_id,
                    "signal_id": position.signal_id,
                    "pair": position.pair,
                    "side": position.side,
                    "entry_price": round(position.entry_price, 8),
                }
            )
        self.pending_orders = remaining
        return filled

    def evaluate_exits(
        self,
        *,
        timestamp: str,
        current_bars: dict[str, dict[str, Any]],
        primary_regime: str,
    ) -> int:
        closed = 0
        survivors: list[ReplayPosition] = []
        for position in self.open_positions:
            bar = current_bars.get(position.pair)
            if bar is None:
                survivors.append(position)
                continue
            position.bars_open += 1
            position.last_price = float(bar.get("close") or position.entry_price)
            exit_price, exit_reason = self._should_exit(position=position, bar=bar)
            if exit_price is None or exit_reason is None:
                survivors.append(position)
                continue
            trade = self._close_position(
                position=position,
                exit_time=timestamp,
                exit_price=exit_price,
                exit_reason=exit_reason,
                primary_regime=primary_regime,
            )
            self.closed_trades.append(trade)
            self.realized_pnl += trade.net_pnl
            closed += 1
            self.execution_events.append(
                {
                    "timestamp": timestamp,
                    "event_type": "position_closed",
                    "trade_id": trade.trade_id,
                    "strategy_id": trade.strategy_id,
                    "signal_id": trade.signal_id,
                    "exit_reason": exit_reason,
                    "net_pnl": round(trade.net_pnl, 8),
                }
            )
        self.open_positions = survivors
        return closed

    def _admit_signal(
        self,
        *,
        signal: dict[str, Any],
        risk_decision: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        blocked_reason_codes: list[str] = []
        side = str(signal.get("direction") or "")
        strategy_id = str(signal.get("strategy_id") or "")
        pair = str(signal.get("pair") or "")
        allowed_strategy_ids = list(risk_decision.get("allowed_strategy_ids") or [])
        blocked_strategy_ids = list(risk_decision.get("blocked_strategy_ids") or [])

        if not bool(risk_decision.get("allow_trading")):
            blocked_reason_codes.append(rc.EXECUTION_HARD_BLOCK_ALLOW_TRADING)
        if not bool(risk_decision.get("new_entries_allowed")):
            blocked_reason_codes.append(rc.EXECUTION_HARD_BLOCK_NEW_ENTRIES)
        if bool(risk_decision.get("force_reduce_only")):
            blocked_reason_codes.append(rc.EXECUTION_FORCE_REDUCE_ONLY)
        if bool(risk_decision.get("cooldown_active")):
            blocked_reason_codes.append(rc.EXECUTION_COOLDOWN_ACTIVE)
        if side not in list(risk_decision.get("allowed_directions") or []):
            blocked_reason_codes.append(rc.EXECUTION_BLOCKED_DIRECTION)
        if strategy_id in blocked_strategy_ids or (allowed_strategy_ids and strategy_id not in allowed_strategy_ids):
            blocked_reason_codes.append(rc.EXECUTION_BLOCKED_STRATEGY)

        if (
            bool((risk_decision.get("protective_overrides") or {}).get("disable_aggressive_entries"))
            and str(signal.get("aggressiveness_tag") or "aggressive") != "standard"
        ):
            blocked_reason_codes.append(rc.EXECUTION_AGGRESSIVE_ENTRY_BLOCKED)

        open_trades = list(snapshot.get("open_trades") or [])
        base = pair.split("/")[0] if "/" in pair else pair.split(":")[0]
        pair_count = sum(1 for trade in open_trades if str(trade.get("pair")) == pair)
        correlated_count = sum(
            1
            for trade in open_trades
            if (
                (str(trade.get("pair") or "").split("/")[0] if "/" in str(trade.get("pair") or "") else str(trade.get("pair") or "").split(":")[0])
                == base
            )
        )
        if len(open_trades) >= int(risk_decision.get("max_positions_total") or 0):
            blocked_reason_codes.append(rc.EXECUTION_PORTFOLIO_FULL)
        if int(risk_decision.get("max_positions_per_symbol") or 0) > 0 and pair_count >= int(risk_decision.get("max_positions_per_symbol") or 0):
            blocked_reason_codes.append(rc.EXECUTION_SYMBOL_LIMIT)
        if int(risk_decision.get("max_correlated_positions") or 0) > 0 and correlated_count >= int(risk_decision.get("max_correlated_positions") or 0):
            blocked_reason_codes.append(rc.EXECUTION_CORRELATION_LIMIT)

        if blocked_reason_codes:
            return {
                "entry_allowed": False,
                "blocked_reason_codes": blocked_reason_codes,
                "final_stake": 0.0,
                "final_leverage": 0.0,
            }

        total_equity = float((snapshot.get("balance_summary") or {}).get("total") or 0.0)
        open_stakes = float((snapshot.get("trade_count_summary") or {}).get("total_open_trades_stakes") or 0.0)
        per_position_pct = float(risk_decision.get("max_position_size_pct") or 0.0)
        total_exposure_pct = float(risk_decision.get("max_total_exposure_pct") or 0.0)
        execution_budget_multiplier = float(risk_decision.get("execution_budget_multiplier") or 1.0)
        if total_equity <= 0 or per_position_pct <= 0:
            blocked_reason_codes.append(rc.EXECUTION_STAKE_BLOCKED)
            return {
                "entry_allowed": False,
                "blocked_reason_codes": blocked_reason_codes,
                "final_stake": 0.0,
                "final_leverage": 0.0,
            }

        per_position_cap = total_equity * (per_position_pct / 100.0)
        remaining_exposure_cap = max(0.0, (total_equity * (total_exposure_pct / 100.0)) - open_stakes)
        final_stake = min(per_position_cap, remaining_exposure_cap)
        final_stake *= execution_budget_multiplier
        if final_stake <= 0:
            blocked_reason_codes.append(rc.EXECUTION_STAKE_BLOCKED)
            return {
                "entry_allowed": False,
                "blocked_reason_codes": blocked_reason_codes,
                "final_stake": 0.0,
                "final_leverage": 0.0,
            }

        proposed_leverage = float(signal.get("signal_leverage") or risk_decision.get("leverage_cap") or 1.0)
        final_leverage = min(proposed_leverage, float(risk_decision.get("leverage_cap") or 1.0))
        return {
            "entry_allowed": True,
            "blocked_reason_codes": [],
            "final_stake": round(final_stake, 8),
            "final_leverage": round(final_leverage, 8),
        }

    def _fill_price(self, *, order: ReplayPendingOrder, bar: dict[str, Any]) -> float | None:
        side = 1.0 if order.side == "long" else -1.0
        open_price = float(bar.get("open") or 0.0)
        high_price = float(bar.get("high") or open_price)
        low_price = float(bar.get("low") or open_price)
        zone = dict(order.entry_zone or {})
        if order.entry_type in {"market_confirmation", "reversal_confirmation"}:
            return self._apply_slippage(open_price, side)
        if order.entry_type == "pullback_limit":
            entry_min = float(zone.get("entry_min") or zone.get("reference_price") or open_price)
            entry_max = float(zone.get("entry_max") or zone.get("reference_price") or open_price)
            if low_price <= entry_max and high_price >= entry_min:
                target = entry_max if order.side == "long" else entry_min
                return self._apply_slippage(target, side)
            return None
        if order.entry_type == "breakout_stop":
            trigger = float(zone.get("entry_max") or zone.get("reference_price") or open_price)
            if order.side == "long" and high_price >= trigger:
                return self._apply_slippage(max(open_price, trigger), side)
            if order.side == "short":
                trigger = float(zone.get("entry_min") or zone.get("reference_price") or open_price)
                if low_price <= trigger:
                    return self._apply_slippage(min(open_price, trigger), side)
            return None
        return None

    def _position_from_order(
        self,
        *,
        order: ReplayPendingOrder,
        timestamp: str,
        fill_price: float,
    ) -> ReplayPosition:
        template = EXIT_TEMPLATE_DEFAULTS.get(
            str(order.signal.get("exit_logic_template") or ""),
            {"time_stop_bars": 10, "target_pct": 0.009, "stop_pct": 0.006},
        )
        side_mult = 1.0 if order.side == "long" else -1.0
        stop_pct = float(template["stop_pct"])
        target_pct = float(template["target_pct"])
        stop_price = fill_price * (1.0 - stop_pct * side_mult)
        target_price = fill_price * (1.0 + target_pct * side_mult)
        quantity = (order.stake * order.leverage) / max(fill_price, 1e-9)
        return ReplayPosition(
            trade_id=f"{order.strategy_id}-{order.signal_id}",
            signal_id=order.signal_id,
            strategy_id=order.strategy_id,
            bot_id=order.bot_id,
            pair=order.pair,
            side=order.side,
            entry_type=order.entry_type,
            entry_time=timestamp,
            entry_price=fill_price,
            stake=order.stake,
            leverage=order.leverage,
            quantity=quantity,
            stop_price=stop_price,
            target_price=target_price,
            max_hold_bars=int(template["time_stop_bars"]),
            last_price=fill_price,
            signal=dict(order.signal),
        )

    def _should_exit(
        self,
        *,
        position: ReplayPosition,
        bar: dict[str, Any],
    ) -> tuple[float | None, str | None]:
        high_price = float(bar.get("high") or position.last_price or position.entry_price)
        low_price = float(bar.get("low") or position.last_price or position.entry_price)
        close_price = float(bar.get("close") or position.last_price or position.entry_price)
        if position.side == "long":
            if low_price <= position.stop_price:
                return self._apply_slippage(position.stop_price, -1.0), "invalidation_stop"
            if high_price >= position.target_price:
                return self._apply_slippage(position.target_price, 1.0), "target_reached"
        else:
            if high_price >= position.stop_price:
                return self._apply_slippage(position.stop_price, 1.0), "invalidation_stop"
            if low_price <= position.target_price:
                return self._apply_slippage(position.target_price, -1.0), "target_reached"
        if position.bars_open >= position.max_hold_bars:
            return self._apply_slippage(close_price, -1.0 if position.side == "long" else 1.0), "time_stop"
        return None, None

    def _close_position(
        self,
        *,
        position: ReplayPosition,
        exit_time: str,
        exit_price: float,
        exit_reason: str,
        primary_regime: str,
    ) -> SystemBacktestTrade:
        side_mult = 1.0 if position.side == "long" else -1.0
        gross_pnl = ((exit_price - position.entry_price) / max(position.entry_price, 1e-9)) * position.stake * position.leverage * side_mult
        fees_paid = (position.stake * position.leverage * self.fee_rate) * 2.0
        net_pnl = gross_pnl - fees_paid
        net_pnl_pct = (net_pnl / max(position.stake, 1e-9)) * 100.0
        return SystemBacktestTrade(
            trade_id=position.trade_id,
            signal_id=position.signal_id,
            strategy_id=position.strategy_id,
            bot_id=position.bot_id,
            pair=position.pair,
            side=position.side,
            entry_time=position.entry_time,
            exit_time=exit_time,
            entry_price=round(position.entry_price, 8),
            exit_price=round(exit_price, 8),
            stake=round(position.stake, 8),
            leverage=round(position.leverage, 8),
            gross_pnl=round(gross_pnl, 8),
            fees_paid=round(fees_paid, 8),
            net_pnl=round(net_pnl, 8),
            net_pnl_pct=round(net_pnl_pct, 6),
            exit_reason=exit_reason,
            entry_type=position.entry_type,
            primary_regime_at_entry=str(position.signal.get("regime_alignment", {}).get("primary_regime") or primary_regime),
        )

    def _unrealized_pnl(self, current_bars: dict[str, dict[str, Any]]) -> float:
        total = 0.0
        for position in self.open_positions:
            bar = current_bars.get(position.pair)
            if not bar:
                continue
            close_price = float(bar.get("close") or position.entry_price)
            side_mult = 1.0 if position.side == "long" else -1.0
            total += ((close_price - position.entry_price) / max(position.entry_price, 1e-9)) * position.stake * position.leverage * side_mult
        return total

    def _apply_slippage(self, price: float, side: float) -> float:
        return round(price * (1.0 + (self.slippage_rate * side)), 8)
