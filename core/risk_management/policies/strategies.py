"""Strategy family and manifest-based permissions."""

from __future__ import annotations

from typing import Any

from .. import reason_codes as rc


def _family_allowed(
    *,
    family: str,
    trading_mode: str,
    market_state: str | None,
    market_phase: str | None,
    primary_regime: str,
    data_trust_level: str,
    squeeze_risk: str,
    allowed_directions: list[str],
    candidate_direction: str,
    block_breakouts: bool,
    allowed_special_families: list[str],
) -> tuple[bool, str | None]:
    if candidate_direction not in {"both", *allowed_directions} and not (
        candidate_direction == "both" and allowed_directions
    ):
        return False, rc.STRATEGY_BLOCKED_BY_DIRECTION

    if trading_mode == "blocked":
        return False, rc.STRATEGY_BLOCKED_BY_FAMILY

    if family == "trend_continuation":
        if primary_regime not in {"trend_up", "trend_down"} or market_state == "range":
            return False, rc.STRATEGY_BLOCKED_BY_FAMILY
    elif family == "pullback_trend":
        if market_state not in {"trend", "pullback"} or market_phase != "pullback":
            return False, rc.STRATEGY_BLOCKED_BY_FAMILY
    elif family == "breakout":
        if block_breakouts or squeeze_risk in {"medium", "high"} or data_trust_level == "low_trust":
            return False, rc.STRATEGY_BLOCKED_BY_FAMILY
    elif family == "mean_reversion":
        if primary_regime not in {"range", "low_vol"}:
            return False, rc.STRATEGY_BLOCKED_BY_FAMILY
    elif family == "panic_reversal":
        if family not in allowed_special_families:
            return False, rc.STRATEGY_BLOCKED_BY_FAMILY
    elif family == "defense_only":
        if trading_mode == "blocked":
            return False, rc.STRATEGY_BLOCKED_BY_FAMILY
    return True, None


def evaluate_strategy_permissions(
    *,
    strategy_manifests: list[dict[str, Any]],
    regime_report: dict[str, Any],
    allowed_directions: list[str],
    trading_mode: str,
    data_trust_level: str,
    event_overrides: dict[str, Any],
) -> dict[str, Any]:
    eligible_from_regime = set(regime_report.get("eligible_candidate_ids") or [])
    blocked_from_regime = set(regime_report.get("blocked_candidate_ids") or [])
    primary_regime = str(regime_report.get("primary_regime") or "unknown")
    market_state = regime_report.get("market_state")
    market_phase = regime_report.get("market_phase")
    derivatives = dict(regime_report.get("derivatives_state") or {})
    squeeze_risk = str(derivatives.get("squeeze_risk") or "unknown")
    reason_codes: list[str] = []
    notes: list[str] = []
    allowed_ids: list[str] = []
    blocked_ids: list[str] = []
    allowed_families: set[str] = set()
    blocked_families: set[str] = set()

    for manifest in strategy_manifests:
        strategy_id = str(manifest.get("strategy_id") or "")
        if not strategy_id:
            continue
        family = str(manifest.get("strategy_family") or "trend_continuation")
        allowed_sides = str(
            manifest.get("allowed_sides")
            or (
                (manifest.get("entry_semantics") or {}).get("allowed_directions")
                if isinstance(manifest.get("entry_semantics"), dict)
                else None
            )
            or manifest.get("allowed_directions")
            or "both"
        )
        risk_profile = str(manifest.get("risk_profile") or "balanced")

        if strategy_id in blocked_from_regime:
            blocked_ids.append(strategy_id)
            blocked_families.add(family)
            continue
        if eligible_from_regime and strategy_id not in eligible_from_regime:
            blocked_ids.append(strategy_id)
            blocked_families.add(family)
            continue

        ok, code = _family_allowed(
            family=family,
            trading_mode=trading_mode,
            market_state=market_state,
            market_phase=market_phase,
            primary_regime=primary_regime,
            data_trust_level=data_trust_level,
            squeeze_risk=squeeze_risk,
            allowed_directions=allowed_directions,
            candidate_direction=allowed_sides,
            block_breakouts=bool(event_overrides.get("block_breakouts")),
            allowed_special_families=list(event_overrides.get("allowed_special_families") or []),
        )
        if not ok:
            blocked_ids.append(strategy_id)
            blocked_families.add(family)
            if code:
                reason_codes.append(code)
            continue

        if trading_mode in {"capital_protection", "reduced_risk"} and risk_profile == "aggressive":
            blocked_ids.append(strategy_id)
            blocked_families.add(family)
            reason_codes.append(rc.STRATEGY_BLOCKED_BY_RISK_PROFILE)
            continue

        allowed_ids.append(strategy_id)
        allowed_families.add(family)
        reason_codes.append(rc.STRATEGY_ALLOWED)

    if not allowed_ids:
        notes.append("Risk engine nie dopuscil zadnej strategii po filtrach rodzin i risk profile.")

    return {
        "allowed_strategy_ids": sorted(set(allowed_ids)),
        "blocked_strategy_ids": sorted(set(blocked_ids)),
        "allowed_strategy_families": sorted(allowed_families),
        "blocked_strategy_families": sorted(blocked_families),
        "reason_codes": reason_codes,
        "notes": notes,
    }
