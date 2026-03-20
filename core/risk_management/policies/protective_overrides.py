"""Protective overrides derived from final risk state."""

from __future__ import annotations

from typing import Any


def derive_protective_overrides(
    *,
    trading_mode: str,
    execution_constraints: dict[str, Any],
    data_trust_level: str,
    actionable_event_flags: dict[str, bool],
) -> dict[str, bool]:
    constraints = dict(execution_constraints or {})
    disable_aggressive_entries = (
        trading_mode in {"blocked", "capital_protection", "reduced_risk"}
        or bool(constraints.get("high_noise_environment"))
        or data_trust_level in {"limited_trust", "low_trust", "broken"}
        or any(bool(actionable_event_flags.get(name)) for name in ("panic_flush", "capitulation", "deleveraging"))
    )
    force_conservative_execution = disable_aggressive_entries or bool(constraints.get("post_shock_cooldown"))
    tighter_risk_budget = (
        trading_mode in {"capital_protection", "reduced_risk"}
        or bool(constraints.get("reduced_exposure_only"))
        or bool(constraints.get("high_noise_environment"))
    )
    return {
        "force_conservative_execution": force_conservative_execution,
        "disable_aggressive_entries": disable_aggressive_entries,
        "tighter_risk_budget": tighter_risk_budget,
    }
