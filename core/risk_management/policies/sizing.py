"""Position sizing and exposure caps."""

from __future__ import annotations

from typing import Any

from ..models import TRADING_MODE_DEFAULTS


def derive_base_risk_budget(trading_mode: str) -> dict[str, Any]:
    return dict(TRADING_MODE_DEFAULTS.get(trading_mode, TRADING_MODE_DEFAULTS["blocked"]))


def apply_regime_modifiers(
    budget: dict[str, Any],
    *,
    position_size_multiplier: float | None,
    regime_quality: float | None,
    confidence: float | None,
    execution_constraints: dict[str, Any],
    volatility_phase: str | None,
    data_trust_level: str,
) -> dict[str, Any]:
    out = dict(budget)
    multiplier = float(position_size_multiplier if position_size_multiplier is not None else 1.0)
    quality = float(regime_quality or 0.0)
    conf = float(confidence or 0.0)

    scale = multiplier
    if quality < 0.50:
        scale *= 0.7
    if conf < 0.55:
        scale *= 0.8
    if bool((execution_constraints or {}).get("high_noise_environment")):
        scale *= 0.7
    if bool((execution_constraints or {}).get("reduced_exposure_only")):
        scale *= 0.75
    if str(volatility_phase or "") == "extreme":
        scale *= 0.5
    elif str(volatility_phase or "") == "expanding":
        scale *= 0.8
    if data_trust_level == "low_trust":
        scale *= 0.6
    elif data_trust_level == "limited_trust":
        scale *= 0.85

    scale = max(0.0, min(1.25, scale))
    for key in ("max_position_size_pct", "max_total_exposure_pct"):
        out[key] = round(float(out[key]) * scale, 4)
    if scale < 0.8:
        out["max_positions_total"] = min(int(out["max_positions_total"]), 2)
    if scale < 0.6:
        out["max_positions_total"] = min(int(out["max_positions_total"]), 1)
        out["max_correlated_positions"] = min(int(out["max_correlated_positions"]), 1)
    return out


def apply_event_caps(
    budget: dict[str, Any],
    *,
    actionable_event_flags: dict[str, bool],
    event_reliability: str,
) -> dict[str, Any]:
    out = dict(budget)
    if event_reliability not in {"medium", "high"}:
        return out
    if actionable_event_flags.get("deleveraging") or actionable_event_flags.get("capitulation"):
        out["max_position_size_pct"] = min(float(out["max_position_size_pct"]), 0.25)
        out["max_total_exposure_pct"] = min(float(out["max_total_exposure_pct"]), 5.0)
        out["max_positions_total"] = min(int(out["max_positions_total"]), 1)
        out["max_correlated_positions"] = min(int(out["max_correlated_positions"]), 1)
    elif actionable_event_flags.get("panic_flush"):
        out["max_position_size_pct"] = min(float(out["max_position_size_pct"]), 0.35)
        out["max_total_exposure_pct"] = min(float(out["max_total_exposure_pct"]), 8.0)
        out["max_positions_total"] = min(int(out["max_positions_total"]), 1)
    return out
