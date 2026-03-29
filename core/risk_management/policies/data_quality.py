"""Data quality policies for regime and derivatives inputs."""

from __future__ import annotations

from typing import Any

from .. import reason_codes as rc
from ..models import DataQualityAssessment


def evaluate_data_quality(derivatives_state: dict[str, Any] | None) -> DataQualityAssessment:
    state = dict(derivatives_state or {})
    feed_status = str(state.get("feed_status") or "missing")
    vendor_available = bool(state.get("vendor_available"))
    source = str(state.get("source") or "unknown")
    reliability = str(state.get("event_reliability") or "low")
    liquidation_confidence = str(state.get("liquidation_event_confidence") or "low")
    age_seconds = state.get("age_seconds")
    try:
        age = float(age_seconds) if age_seconds is not None else None
    except (TypeError, ValueError):
        age = None
    is_stale = bool(state.get("is_stale"))

    reason_codes: list[str] = []
    notes: list[str] = []
    degradation_flags = {
        "stale_feed": False,
        "low_event_reliability": False,
        "event_decisions_limited": False,
        "portfolio_state_missing": False,
    }

    if feed_status in {"error", "missing"} or (age is not None and age > 1800):
        reason_codes.append(rc.DATA_FEED_BROKEN)
        notes.append("Feed derivatives jest niedostepny albo zbyt stary do bezpiecznych decyzji futures.")
        return DataQualityAssessment(
            validation_status="invalid",
            trust_level="broken",
            degradation_flags=degradation_flags,
            reason_codes=reason_codes,
            notes=notes,
        )

    trust_level = "full_trust"
    validation_status = "valid"

    if is_stale or (age is not None and age > 900):
        trust_level = "low_trust"
        validation_status = "valid_with_degradation"
        degradation_flags["stale_feed"] = True
        degradation_flags["event_decisions_limited"] = True
        reason_codes.append(rc.STALE_DERIVATIVES_FEED)
        notes.append("Feed derivatives jest stary, wiec eventy pozostaja tylko sygnalem defensywnym.")
    elif feed_status == "ok" and vendor_available and age is not None and age <= 300 and reliability in {"medium", "high"}:
        trust_level = "full_trust"
    elif source == "replay_proxy" and feed_status == "replay_proxy" and not is_stale:
        trust_level = "limited_trust"
        validation_status = "valid_with_degradation"
        degradation_flags["event_decisions_limited"] = True
        notes.append("Replay proxy dostarcza spojny kontekst derivatives do backtestu systemowego, ale bez pelnego trustu eventowego.")
    elif source in {"binance_futures_public_api", "local_vendor_snapshot"} and age is not None and age <= 900:
        trust_level = "limited_trust"
        validation_status = "valid_with_degradation"
    else:
        trust_level = "low_trust"
        validation_status = "valid_with_degradation"

    if reliability == "low" or liquidation_confidence == "low":
        degradation_flags["low_event_reliability"] = True
        degradation_flags["event_decisions_limited"] = True
        reason_codes.append(rc.LOW_EVENT_RELIABILITY)
        notes.append("Jakosc eventow derivatives jest niska, wiec overrides pozostaja defensywne.")
        if trust_level == "full_trust":
            trust_level = "limited_trust"
            validation_status = "valid_with_degradation"

    if source == "degraded_proxy":
        trust_level = "low_trust"
        validation_status = "valid_with_degradation"
        degradation_flags["event_decisions_limited"] = True
        reason_codes.append(rc.EVENT_DECISIONS_LIMITED)
        notes.append("Engine pracuje na degraded_proxy, wiec blokuje agresywne decyzje eventowe.")

    return DataQualityAssessment(
        validation_status=validation_status,
        trust_level=trust_level,
        degradation_flags=degradation_flags,
        reason_codes=reason_codes,
        notes=notes,
    )
