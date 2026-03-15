"""Referencyjny handler offline'owej walidacji control layer."""

from __future__ import annotations

from typing import Any

from ..models import ControlDecision, ControlDecisionStatus, ControlRequest

FORBIDDEN_FLAGS = (
    "touches_runtime",
    "needs_network",
    "uses_secrets",
    "live_trading",
)


class DryControlCheckHandler:
    """Deterministyczny handler bez efektów ubocznych."""

    task_type = "dry_control_check"
    handler_name = "dry_control_check"

    def handle(self, request: ControlRequest) -> tuple[ControlDecision, dict[str, Any]]:
        payload = request.payload if isinstance(request.payload, dict) else {}
        reasons: list[str] = []
        warnings: list[str] = []

        subject = payload.get("subject", "")
        subject = subject.strip() if isinstance(subject, str) else ""
        checks_value = payload.get("checks", [])
        require_all_green = bool(payload.get("require_all_green", True))

        if not subject:
            reasons.append("Pole 'subject' jest wymagane.")
        elif len(subject) > 120:
            reasons.append("Pole 'subject' nie może przekraczać 120 znaków.")

        normalized_checks: list[str] = []
        if not isinstance(checks_value, list) or not checks_value:
            reasons.append("Lista 'checks' musi zawierać co najmniej jeden warunek.")
        elif len(checks_value) > 10:
            reasons.append("Lista 'checks' nie może zawierać więcej niż 10 pozycji.")
        else:
            for index, item in enumerate(checks_value, start=1):
                if not isinstance(item, str) or not item.strip():
                    reasons.append(f"Pozycja checks[{index}] musi być niepustym tekstem.")
                    continue
                check_name = item.strip()
                if len(check_name) > 64:
                    reasons.append(f"Pozycja checks[{index}] nie może przekraczać 64 znaków.")
                    continue
                normalized_checks.append(check_name)

        flagged_conditions = {
            flag: bool(payload.get(flag, False))
            for flag in FORBIDDEN_FLAGS
        }
        active_forbidden = [flag for flag, enabled in flagged_conditions.items() if enabled]
        if active_forbidden:
            reasons.append(
                "Zadanie narusza granice offline control layer: "
                + ", ".join(active_forbidden)
            )

        if not require_all_green:
            warnings.append(
                "Tryb require_all_green=False pozostaje tylko sygnałem testowym i nie zmienia granic bezpieczeństwa."
            )

        accepted = not reasons
        decision = ControlDecision(
            accepted=accepted,
            status=(
                ControlDecisionStatus.approved
                if accepted
                else ControlDecisionStatus.rejected
            ),
            reasons=(
                ["Wszystkie kontrole offline przeszły pozytywnie."]
                if accepted
                else reasons
            ),
            warnings=warnings,
            handler_name=self.handler_name,
        )
        output = {
            "subject": subject,
            "validated_checks": normalized_checks,
            "check_count": len(normalized_checks),
            "flagged_conditions": flagged_conditions,
            "require_all_green": require_all_green,
            "mode": "offline_only",
            "summary": (
                f"Dry control check zaakceptował temat '{subject}'."
                if accepted
                else "Dry control check odrzucił request na etapie walidacji."
            ),
        }
        return decision, output
