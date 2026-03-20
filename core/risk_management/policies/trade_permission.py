"""Trading mode and global permission logic."""

from __future__ import annotations

from typing import Any

from .. import reason_codes as rc


def evaluate_market_viability(
    *,
    primary_regime: str,
    risk_regime: str,
    regime_quality: float,
    execution_constraints: dict[str, Any],
    actionable_event_flags: dict[str, bool],
    event_reliability: str,
    data_trust_level: str,
    consensus: str | None,
    consensus_strength: float | None,
) -> dict[str, Any]:
    constraints = dict(execution_constraints or {})
    quality = float(regime_quality or 0.0)
    consensus_strength_value = float(consensus_strength or 0.0)
    reason_codes: list[str] = []
    notes: list[str] = []
    cooldown_active = bool(constraints.get("post_shock_cooldown"))

    if data_trust_level == "broken":
        reason_codes.append(rc.DATA_FEED_BROKEN)
        return {
            "allow_trading": False,
            "trading_mode": "blocked",
            "cooldown_active": cooldown_active,
            "reason_codes": reason_codes,
            "notes": ["Risk engine blokuje handel, bo dane derivatives nie przechodza minimalnej walidacji."],
        }

    if bool(constraints.get("no_trade_zone")):
        reason_codes.append(rc.NO_TRADE_ZONE_HARD_BLOCK)
        return {
            "allow_trading": False,
            "trading_mode": "blocked",
            "cooldown_active": cooldown_active,
            "reason_codes": reason_codes,
            "notes": ["Regime engine oznaczyl biezacy rynek jako no-trade zone."],
        }

    if cooldown_active and event_reliability in {"medium", "high"}:
        reason_codes.append(rc.POST_SHOCK_COOLDOWN)
        return {
            "allow_trading": True,
            "trading_mode": "capital_protection",
            "cooldown_active": True,
            "reason_codes": reason_codes,
            "notes": ["Aktywny post-shock cooldown wymusza tryb kapital protection."],
        }

    if risk_regime == "high":
        reason_codes.append(rc.RISK_HIGH)
        notes.append("Globalny risk_regime jest wysoki.")
        if actionable_event_flags.get("capitulation") or actionable_event_flags.get("deleveraging"):
            if data_trust_level in {"full_trust", "limited_trust"}:
                if actionable_event_flags.get("capitulation"):
                    reason_codes.append(rc.ACTIONABLE_CAPITULATION)
                if actionable_event_flags.get("deleveraging"):
                    reason_codes.append(rc.ACTIONABLE_DELEVERAGING)
                return {
                    "allow_trading": True,
                    "trading_mode": "capital_protection",
                    "cooldown_active": cooldown_active,
                    "reason_codes": reason_codes,
                    "notes": notes + ["Actionable stress event wymusza kapitałową obronę."],
                }

    if quality < 0.35:
        reason_codes.append(rc.LOW_REGIME_QUALITY)
        return {
            "allow_trading": False,
            "trading_mode": "blocked",
            "cooldown_active": cooldown_active,
            "reason_codes": reason_codes,
            "notes": ["Regime quality spadla ponizej minimalnego progu handlowalnosci."],
        }

    if (
        bool(constraints.get("reduced_exposure_only"))
        or bool(constraints.get("high_noise_environment"))
        or risk_regime == "elevated"
        or quality < 0.60
        or data_trust_level in {"limited_trust", "low_trust"}
    ):
        if bool(constraints.get("reduced_exposure_only")):
            reason_codes.append(rc.REDUCED_EXPOSURE_ONLY)
        if bool(constraints.get("high_noise_environment")):
            reason_codes.append(rc.HIGH_NOISE_ENVIRONMENT)
        if risk_regime == "elevated":
            reason_codes.append(rc.RISK_ELEVATED)
        if quality < 0.60:
            reason_codes.append(rc.LOW_REGIME_QUALITY)
        if consensus in {"weak_bearish", "weak_bullish", "mixed", "neutral"} or consensus_strength_value < 0.55:
            reason_codes.append(rc.WEAK_MARKET_CONSENSUS)
        return {
            "allow_trading": True,
            "trading_mode": "reduced_risk",
            "cooldown_active": cooldown_active,
            "reason_codes": reason_codes,
            "notes": notes + ["Rynek jest handlowalny tylko w trybie reduced risk."],
        }

    if (
        risk_regime == "normal"
        and quality >= 0.75
        and consensus_strength_value >= 0.70
        and data_trust_level == "full_trust"
        and primary_regime in {"trend_up", "trend_down"}
    ):
        return {
            "allow_trading": True,
            "trading_mode": "selective_offense",
            "cooldown_active": cooldown_active,
            "reason_codes": reason_codes,
            "notes": ["Rynek przechodzi do trybu selective offense."],
        }

    return {
        "allow_trading": True,
        "trading_mode": "normal",
        "cooldown_active": cooldown_active,
        "reason_codes": reason_codes,
        "notes": notes + ["Rynek przechodzi do standardowego futures runtime."],
    }
