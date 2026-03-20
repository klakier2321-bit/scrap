"""Event-specific overrides for futures risk."""

from __future__ import annotations

from typing import Any

from .. import reason_codes as rc


def evaluate_event_overrides(
    *,
    actionable_event_flags: dict[str, bool],
    active_event_flags: dict[str, bool],
    event_reliability: str,
    data_trust_level: str,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    notes: list[str] = []
    force_capital_protection = False
    force_reduce_only = False
    block_breakouts = False
    defensive_only_families: list[str] = []
    blocked_directions: list[str] = []

    if event_reliability not in {"medium", "high"} or data_trust_level == "low_trust":
        return {
            "force_capital_protection": False,
            "force_reduce_only": False,
            "block_breakouts": False,
            "allowed_special_families": [],
            "blocked_directions": [],
            "reason_codes": reason_codes,
            "notes": notes,
        }

    if actionable_event_flags.get("panic_flush") or active_event_flags.get("panic_flush"):
        force_capital_protection = True
        block_breakouts = True
        defensive_only_families.extend(["panic_reversal", "defense_only"])
        reason_codes.append(rc.ACTIONABLE_PANIC_FLUSH)
        notes.append("Panic flush wymusza defensywne strategie i blokade breakoutow.")

    if actionable_event_flags.get("capitulation"):
        force_capital_protection = True
        block_breakouts = True
        defensive_only_families.extend(["panic_reversal", "defense_only"])
        reason_codes.append(rc.ACTIONABLE_CAPITULATION)
        notes.append("Capitulation wymusza panic reversal albo defense only.")

    if actionable_event_flags.get("deleveraging"):
        force_capital_protection = True
        force_reduce_only = True
        reason_codes.append(rc.ACTIONABLE_DELEVERAGING)
        reason_codes.append(rc.FORCE_REDUCE_ONLY)
        notes.append("Deleveraging wymusza reduce-only i minimalny lewar.")

    if actionable_event_flags.get("short_squeeze"):
        blocked_directions.append("short")
        block_breakouts = True
        reason_codes.append(rc.SHORT_SQUEEZE_RISK)
    if actionable_event_flags.get("long_squeeze"):
        blocked_directions.append("long")
        block_breakouts = True
        reason_codes.append(rc.LONG_SQUEEZE_RISK)

    return {
        "force_capital_protection": force_capital_protection,
        "force_reduce_only": force_reduce_only,
        "block_breakouts": block_breakouts,
        "allowed_special_families": sorted(set(defensive_only_families)),
        "blocked_directions": sorted(set(blocked_directions)),
        "reason_codes": reason_codes,
        "notes": notes,
    }
