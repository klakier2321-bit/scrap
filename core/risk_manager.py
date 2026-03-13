"""Risk and safety validation for the control layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class RiskManager:
    """Centralizes runtime safety checks and approval rules."""

    def __init__(self, sensitive_paths: list[str] | None = None) -> None:
        self.sensitive_paths = sensitive_paths or [
            ".env",
            "docker-compose.yml",
            "trading/freqtrade/user_data/config.json",
            "trading/freqtrade/user_data/config.backtest.local.json",
        ]
        self.forbidden_keywords = {
            "live trading",
            "exchange api key",
            "api keys",
            "secret",
            "telegram token",
        }

    def ensure_bot_start_allowed(self, bot_status: dict[str, Any]) -> None:
        if not bot_status.get("dry_run", True):
            raise PermissionError(
                "Bot start was blocked because dry_run is disabled. "
                "Live trading is outside the allowed AI control scope."
            )

    def evaluate_request_risk(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        goal_text = " ".join(
            str(value)
            for value in (
                request_payload.get("goal", ""),
                request_payload.get("business_reason", ""),
            )
        ).lower()

        warnings: list[str] = []
        human_decision_required = bool(request_payload.get("does_touch_runtime"))

        for keyword in self.forbidden_keywords:
            if keyword in goal_text:
                warnings.append(
                    f"Goal contains a forbidden or human-controlled keyword: '{keyword}'."
                )
                human_decision_required = True

        risk_level = request_payload.get("risk_level", "low")
        review_required = risk_level in {"medium", "high"} or bool(
            request_payload.get("cross_layer")
        )
        if bool(request_payload.get("does_touch_contract")):
            review_required = True

        if risk_level == "high":
            human_decision_required = True

        return {
            "warnings": warnings,
            "review_required": review_required,
            "human_decision_required": human_decision_required,
        }

    def path_is_sensitive(self, path_value: str) -> bool:
        normalized = path_value.lstrip("./")
        return any(
            normalized == sensitive or normalized.startswith(f"{sensitive}/")
            for sensitive in self.sensitive_paths
        )

    def validate_requested_paths(self, requested_paths: list[str]) -> list[str]:
        violations = []
        for path_value in requested_paths:
            if self.path_is_sensitive(path_value):
                violations.append(path_value)
        return violations
