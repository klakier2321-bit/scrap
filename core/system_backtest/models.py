"""Models for canonical live-like system replay backtests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from ..runtime_artifacts import canonical_futures_bot_id


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_datetime(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Datetime value is required.")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "T" in text:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=UTC)


def parse_timerange(value: str) -> tuple[datetime, datetime]:
    start_text, _, end_text = str(value or "").partition(":")
    if not start_text or not end_text:
        raise ValueError("Timerange must have format <start>:<end>.")
    start = parse_datetime(start_text)
    end = parse_datetime(end_text)
    if "T" not in end_text:
        end += timedelta(days=1)
    if end <= start:
        raise ValueError("Timerange end must be after start.")
    return start, end


@dataclass(slots=True)
class SystemBacktestConfig:
    universe: list[str]
    base_timeframe: str
    htf_timeframe: str
    starting_equity: float
    fee_rate: float
    slippage_rate: float
    replay_warmup_bars: int
    replay_warmup_1h_bars: int
    enabled_strategy_ids: list[str]
    output_root: Path
    user_data_dir: Path
    research_dir: Path
    write_detailed_reports: bool = True
    max_bars: int | None = None
    scenario_overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def bot_ids(self) -> list[str]:
        return [canonical_futures_bot_id(strategy_id) for strategy_id in self.enabled_strategy_ids]

    @classmethod
    def from_yaml(cls, path: Path) -> SystemBacktestConfig:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            universe=list(payload.get("universe") or ["BTC/USDT:USDT", "ETH/USDT:USDT"]),
            base_timeframe=str(payload.get("base_timeframe") or "5m"),
            htf_timeframe=str(payload.get("htf_timeframe") or "1h"),
            starting_equity=float(payload.get("starting_equity") or 10000.0),
            fee_rate=float(payload.get("fee_rate") or 0.0004),
            slippage_rate=float(payload.get("slippage_rate") or 0.0002),
            replay_warmup_bars=int(payload.get("replay_warmup_bars") or 288),
            replay_warmup_1h_bars=int(payload.get("replay_warmup_1h_bars") or 72),
            enabled_strategy_ids=list(payload.get("enabled_strategy_ids") or []),
            output_root=Path(payload.get("output_root") or "backtests/system"),
            user_data_dir=Path(payload.get("user_data_dir") or "trading/freqtrade/user_data"),
            research_dir=Path(payload.get("research_dir") or "research"),
            write_detailed_reports=bool(payload.get("write_detailed_reports", True)),
            max_bars=int(payload["max_bars"]) if payload.get("max_bars") is not None else None,
            scenario_overrides=dict(payload.get("scenario_overrides") or {}),
        )


@dataclass(slots=True)
class ReplayPendingOrder:
    signal_id: str
    strategy_id: str
    bot_id: str
    pair: str
    side: str
    entry_type: str
    entry_zone: dict[str, Any]
    signal: dict[str, Any]
    created_at: str
    stake: float
    leverage: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReplayPosition:
    trade_id: str
    signal_id: str
    strategy_id: str
    bot_id: str
    pair: str
    side: str
    entry_type: str
    entry_time: str
    entry_price: float
    stake: float
    leverage: float
    quantity: float
    stop_price: float
    target_price: float
    max_hold_bars: int
    bars_open: int = 0
    last_price: float = 0.0
    signal: dict[str, Any] = field(default_factory=dict)

    def to_snapshot_trade(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "signal_id": self.signal_id,
            "strategy_id": self.strategy_id,
            "source_bot_id": self.bot_id,
            "pair": self.pair,
            "side": self.side,
            "is_short": self.side == "short",
            "open_rate": round(self.entry_price, 8),
            "stake_amount": round(self.stake, 8),
            "leverage": round(self.leverage, 8),
        }


@dataclass(slots=True)
class SystemBacktestTrade:
    trade_id: str
    signal_id: str
    strategy_id: str
    bot_id: str
    pair: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stake: float
    leverage: float
    gross_pnl: float
    fees_paid: float
    net_pnl: float
    net_pnl_pct: float
    exit_reason: str
    entry_type: str
    primary_regime_at_entry: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SystemBacktestBarEvent:
    timestamp: str
    primary_regime: str
    trading_mode: str
    signals_built: int
    signals_risk_admitted: int
    entries_attempted: int
    entries_filled: int
    entries_blocked_by_risk: int
    entries_blocked_by_execution: int
    open_positions: int
    total_equity: float
    preferred_strategy_id: str | None
    blocked_reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SystemBacktestSummary:
    run_id: str
    generated_at: str
    timerange: str
    pairs: list[str]
    strategies_enabled: list[str]
    total_signals_built: int
    total_signals_risk_admitted: int
    total_entries_attempted: int
    total_entries_filled: int
    total_entries_blocked_by_risk: int
    total_entries_blocked_by_execution: int
    total_closed_trades: int
    net_profit_pct: float
    max_drawdown_pct: float
    exposure_efficiency: float
    blocked_reason_breakdown: dict[str, int]
    strategy_breakdown: dict[str, Any]
    regime_breakdown: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
