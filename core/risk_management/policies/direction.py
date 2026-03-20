"""Directional permission logic."""

from __future__ import annotations

from typing import Any

from .. import reason_codes as rc


def evaluate_direction_permissions(
    *,
    primary_regime: str,
    htf_bias: str | None,
    market_state: str | None,
    market_phase: str | None,
    btc_state: dict[str, Any] | None,
    eth_state: dict[str, Any] | None,
    market_consensus: str | None,
    consensus_strength: float | None,
    actionable_event_flags: dict[str, bool],
    derivatives: dict[str, Any],
    hard_block: bool,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    notes: list[str] = []
    if hard_block:
        reason_codes.append(rc.DIRECTION_BLOCKED_ALL)
        return {
            "allowed_directions": [],
            "blocked_directions": ["long", "short"],
            "reason_codes": reason_codes,
            "notes": ["Globalny hard block wyłącza oba kierunki."],
        }

    allowed: list[str] = []
    blocked: list[str] = []
    bias = str(htf_bias or "neutral")
    consensus = str(market_consensus or "neutral")
    consensus_strength_value = float(consensus_strength or 0.0)
    squeeze_risk = str(derivatives.get("squeeze_risk") or "unknown")
    positioning_state = str(derivatives.get("positioning_state") or "unknown")
    oi_price_agreement = str(derivatives.get("oi_price_agreement") or "unknown")

    if primary_regime in {"range", "low_vol"} and consensus in {"mixed", "neutral", "weak_bullish", "weak_bearish"}:
        reason_codes.append(rc.DIRECTION_BLOCKED_ALL)
        return {
            "allowed_directions": [],
            "blocked_directions": ["long", "short"],
            "reason_codes": reason_codes,
            "notes": ["Range albo low-vol przy slabym consensus nie daje prawa do kierunku."],
        }

    long_allowed = bias == "long" or primary_regime == "trend_up"
    short_allowed = bias == "short" or primary_regime == "trend_down"

    if actionable_event_flags.get("long_squeeze"):
        long_allowed = False
        reason_codes.append(rc.LONG_SQUEEZE_RISK)
        reason_codes.append(rc.DIRECTION_BLOCKED_LONG)
        notes.append("Actionable long squeeze blokuje nowe longi.")
    if actionable_event_flags.get("short_squeeze"):
        short_allowed = False
        reason_codes.append(rc.SHORT_SQUEEZE_RISK)
        reason_codes.append(rc.DIRECTION_BLOCKED_SHORT)
        notes.append("Actionable short squeeze blokuje nowe shorty.")

    if squeeze_risk in {"medium", "high"} and positioning_state == "short_covering":
        short_allowed = False
        reason_codes.append(rc.DISABLE_AGGRESSIVE_SHORTS)
    if squeeze_risk in {"medium", "high"} and positioning_state == "long_unwind":
        long_allowed = False
        reason_codes.append(rc.DISABLE_AGGRESSIVE_LONGS)

    if market_state == "pullback" and market_phase == "pullback":
        if bias == "long":
            long_allowed = True
        elif bias == "short":
            short_allowed = True

    if consensus_strength_value < 0.55:
        if consensus in {"weak_bullish", "weak_bearish"}:
            if consensus == "weak_bullish":
                short_allowed = False
            else:
                long_allowed = False
            reason_codes.append(rc.WEAK_MARKET_CONSENSUS)
        elif consensus in {"mixed", "neutral"}:
            long_allowed = False
            short_allowed = False
            reason_codes.append(rc.DIRECTION_BLOCKED_ALL)
            notes.append("Slaby consensus blokuje oba kierunki.")

    if primary_regime == "trend_up":
        reason_codes.append(rc.LONG_BIAS_CONFIRMED)
    elif primary_regime == "trend_down":
        reason_codes.append(rc.SHORT_BIAS_CONFIRMED)

    if long_allowed:
        allowed.append("long")
    else:
        blocked.append("long")
    if short_allowed:
        allowed.append("short")
    else:
        blocked.append("short")

    if not allowed:
        reason_codes.append(rc.DIRECTION_BLOCKED_ALL)

    if oi_price_agreement in {"short_build", "bearish"} and "short" in allowed and "long" in allowed:
        allowed = ["short"]
        blocked = ["long"]
        reason_codes.append(rc.SHORT_BIAS_CONFIRMED)
    elif oi_price_agreement in {"long_build", "bullish"} and "long" in allowed and "short" in allowed:
        allowed = ["long"]
        blocked = ["short"]
        reason_codes.append(rc.LONG_BIAS_CONFIRMED)

    return {
        "allowed_directions": allowed,
        "blocked_directions": blocked,
        "reason_codes": reason_codes,
        "notes": notes,
    }
