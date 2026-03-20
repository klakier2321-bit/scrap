"""Internal helpers and defaults for the risk engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


TRADING_MODE_DEFAULTS: dict[str, dict[str, float | int | bool | str]] = {
    "blocked": {
        "max_position_size_pct": 0.0,
        "max_total_exposure_pct": 0.0,
        "max_positions_total": 0,
        "max_positions_per_symbol": 0,
        "max_correlated_positions": 0,
        "leverage_cap": 1.0,
        "force_reduce_only": True,
        "new_entries_allowed": False,
        "entry_aggressiveness": "blocked",
    },
    "capital_protection": {
        "max_position_size_pct": 0.25,
        "max_total_exposure_pct": 5.0,
        "max_positions_total": 1,
        "max_positions_per_symbol": 1,
        "max_correlated_positions": 1,
        "leverage_cap": 1.0,
        "force_reduce_only": False,
        "new_entries_allowed": True,
        "entry_aggressiveness": "low",
    },
    "reduced_risk": {
        "max_position_size_pct": 0.50,
        "max_total_exposure_pct": 12.0,
        "max_positions_total": 2,
        "max_positions_per_symbol": 1,
        "max_correlated_positions": 1,
        "leverage_cap": 2.0,
        "force_reduce_only": False,
        "new_entries_allowed": True,
        "entry_aggressiveness": "moderate",
    },
    "normal": {
        "max_position_size_pct": 1.00,
        "max_total_exposure_pct": 25.0,
        "max_positions_total": 3,
        "max_positions_per_symbol": 1,
        "max_correlated_positions": 2,
        "leverage_cap": 3.0,
        "force_reduce_only": False,
        "new_entries_allowed": True,
        "entry_aggressiveness": "moderate",
    },
    "selective_offense": {
        "max_position_size_pct": 1.25,
        "max_total_exposure_pct": 35.0,
        "max_positions_total": 4,
        "max_positions_per_symbol": 1,
        "max_correlated_positions": 2,
        "leverage_cap": 4.0,
        "force_reduce_only": False,
        "new_entries_allowed": True,
        "entry_aggressiveness": "high",
    },
}


@dataclass(slots=True)
class PortfolioState:
    bot_id: str | None = None
    total_equity: float = 0.0
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    open_positions_count: int = 0
    gross_exposure_pct: float = 0.0
    max_open_positions_config: int | None = None
    positions_per_symbol: dict[str, int] = field(default_factory=dict)
    direction_counts: dict[str, int] = field(default_factory=dict)
    correlation_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class DataQualityAssessment:
    validation_status: str
    trust_level: str
    degradation_flags: dict[str, bool]
    reason_codes: list[str]
    notes: list[str]


def empty_risk_decision() -> dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "allow_trading": False,
        "trading_mode": "blocked",
        "risk_state": "unknown",
        "risk_score": 100,
        "data_validation_status": "missing",
        "data_trust_level": "broken",
        "allowed_directions": [],
        "blocked_directions": ["long", "short"],
        "max_position_size_pct": 0.0,
        "max_total_exposure_pct": 0.0,
        "max_positions_total": 0,
        "max_positions_per_symbol": 0,
        "max_correlated_positions": 0,
        "allowed_strategy_ids": [],
        "blocked_strategy_ids": [],
        "allowed_strategy_families": [],
        "blocked_strategy_families": [],
        "leverage_cap": 1.0,
        "force_reduce_only": True,
        "new_entries_allowed": False,
        "cooldown_active": False,
        "protective_overrides": {
            "force_conservative_execution": True,
            "disable_aggressive_entries": True,
            "tighter_risk_budget": True,
        },
        "risk_reason_codes": [],
        "risk_notes": [],
        "decision_trace": [],
        "degradation_flags": {
            "stale_feed": False,
            "low_event_reliability": False,
            "event_decisions_limited": False,
            "portfolio_state_missing": False,
        },
    }
