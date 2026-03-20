"""Leverage policy."""

from __future__ import annotations

from typing import Any

from .. import reason_codes as rc


def derive_leverage_cap(
    *,
    trading_mode: str,
    risk_regime: str,
    volatility_phase: str | None,
    derivatives: dict[str, Any],
    consensus_strength: float | None,
    data_trust_level: str,
    actionable_event_flags: dict[str, bool],
) -> tuple[float, list[str], list[str]]:
    reason_codes: list[str] = []
    notes: list[str] = []
    squeeze_risk = str((derivatives or {}).get("squeeze_risk") or "unknown")
    if (
        trading_mode == "blocked"
        or trading_mode == "capital_protection"
        or risk_regime == "high"
        or str(volatility_phase or "") == "extreme"
        or actionable_event_flags.get("deleveraging")
        or data_trust_level == "broken"
    ):
        reason_codes.append(rc.LEVERAGE_MINIMIZED)
        return 1.0, reason_codes, ["Leverage zostaje zredukowany do 1x przez tryb ochronny albo wysoki stress."]

    if (
        trading_mode == "reduced_risk"
        or risk_regime == "elevated"
        or str(volatility_phase or "") in {"expanding", "extreme"}
        or squeeze_risk in {"medium", "high"}
        or data_trust_level in {"limited_trust", "low_trust"}
    ):
        reason_codes.append(rc.LEVERAGE_MINIMIZED)
        return 2.0, reason_codes, ["Leverage zostaje ograniczony do 2x przez elevated risk lub slabsze dane."]

    if (
        trading_mode == "selective_offense"
        and risk_regime == "normal"
        and str(volatility_phase or "") not in {"expanding", "extreme"}
        and squeeze_risk not in {"medium", "high"}
        and data_trust_level == "full_trust"
        and float(consensus_strength or 0.0) >= 0.70
    ):
        return 4.0, reason_codes, ["Rynek przechodzi warunki selective offense i pozwala na leverage do 4x."]

    return 3.0, reason_codes, ["Standardowy runtime futures ogranicza leverage do 3x."]
