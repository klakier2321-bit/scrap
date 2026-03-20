"""Defense-only strategy."""

from __future__ import annotations

from ...base import BaseStrategy
from ...models import ApplicabilityResult, ExitTemplateSpec, InvalidationSpec, SetupEvaluation, StrategyContext


class DefenseOnlyStrategy(BaseStrategy):
    """Explicit no-trade / wait-state strategy."""

    def is_applicable(self, context: StrategyContext) -> ApplicabilityResult:
        if (
            context.execution_constraints.get("no_trade_zone")
            or context.execution_constraints.get("high_noise_environment")
            or context.primary_regime in {"low_vol", "stress_panic", "range"}
            or context.market_state in {"transition", "range"}
            or context.trading_mode in {"blocked", "capital_protection"}
        ):
            return ApplicabilityResult(applicable=True, reasons=[])
        return ApplicabilityResult(applicable=False, reasons=["market_not_in_defense_state"])

    def evaluate_setup(self, context: StrategyContext) -> SetupEvaluation:
        evidence = ["defense_runtime_state"]
        if context.execution_constraints.get("no_trade_zone"):
            evidence.append("no_trade_zone")
        if context.trading_mode in {"blocked", "capital_protection"}:
            evidence.append("risk_mode_defensive")
        return SetupEvaluation(
            setup_detected=True,
            setup_quality=1.0,
            entry_type="wait",
            aggressiveness_tag="defensive",
            evidence=evidence,
            reasons=["advisory_only_no_trade"],
            advisory_only=True,
        )

    def invalidation_logic(self, context: StrategyContext, setup: SetupEvaluation) -> InvalidationSpec:
        del context, setup
        return InvalidationSpec(type="state_change", condition="market_becomes_tradeable")

    def exit_template(self, context: StrategyContext, setup: SetupEvaluation) -> ExitTemplateSpec:
        del context, setup
        return ExitTemplateSpec(name="no_trade")

    def telemetry_snapshot(self, context: StrategyContext, setup: SetupEvaluation, signal) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "primary_regime": context.primary_regime,
            "trading_mode": context.trading_mode,
            "setup_quality": round(setup.setup_quality, 4),
            "signal_id": signal.signal_id if signal else None,
            "advisory_only": True,
        }
