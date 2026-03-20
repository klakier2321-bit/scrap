"""Trend pullback continuation strategy."""

from __future__ import annotations

from ...base import BaseStrategy
from ...models import ApplicabilityResult, ExitTemplateSpec, InvalidationSpec, SetupEvaluation, StrategyContext


class TrendPullbackContinuationStrategy(BaseStrategy):
    """Continuation after a controlled pullback inside a mature trend."""

    def is_applicable(self, context: StrategyContext) -> ApplicabilityResult:
        reasons: list[str] = []
        if context.primary_regime not in {"trend_up", "trend_down"}:
            reasons.append("primary_regime_out_of_scope")
        if context.market_state not in {"trend", "pullback"}:
            reasons.append("market_state_out_of_scope")
        if context.market_phase not in {"pullback", "mature_trend"}:
            reasons.append("market_phase_out_of_scope")
        if context.execution_constraints.get("high_noise_environment"):
            reasons.append("high_noise_environment")
        if context.execution_constraints.get("no_trade_zone"):
            reasons.append("no_trade_zone")
        return ApplicabilityResult(applicable=not reasons, reasons=reasons)

    def evaluate_setup(self, context: StrategyContext) -> SetupEvaluation:
        evidence: list[str] = []
        score = 0.55
        score += min(0.20, context.confidence * 0.20)
        score += min(0.15, context.regime_quality * 0.15)
        score += min(0.15, context.consensus_strength * 0.15)
        if context.market_phase == "pullback":
            score += 0.10
            evidence.append("phase_pullback")
        if str(context.regime_report.get("ltf_execution_state")) == "momentum_resuming":
            score += 0.12
            evidence.append("ltf_momentum_resuming")
        if str(context.derivatives_state.get("oi_price_agreement") or "") in {"long_build", "short_build"}:
            score += 0.05
            evidence.append("oi_supportive")
        if any(bool(context.actionable_event_flags.get(name)) for name in ("panic_flush", "capitulation", "deleveraging")):
            return SetupEvaluation(
                setup_detected=False,
                setup_quality=0.0,
                entry_type="pullback_limit",
                aggressiveness_tag="standard",
                evidence=evidence,
                reasons=["actionable_event_blocks_trend_pullback"],
            )
        return SetupEvaluation(
            setup_detected=score >= 0.72,
            setup_quality=min(score, 0.98),
            entry_type="pullback_limit",
            aggressiveness_tag="standard",
            evidence=evidence,
            reasons=[] if score >= 0.72 else ["setup_quality_below_threshold"],
        )

    def invalidation_logic(self, context: StrategyContext, setup: SetupEvaluation) -> InvalidationSpec:
        del setup
        if context.htf_bias == "short":
            return InvalidationSpec(type="structure_break", condition="pullback_breaks_last_lower_high")
        return InvalidationSpec(type="structure_break", condition="pullback_breaks_last_higher_low")

    def exit_template(self, context: StrategyContext, setup: SetupEvaluation) -> ExitTemplateSpec:
        del context, setup
        return ExitTemplateSpec(name="trend_structure_trail", details={"partial_take": "first_impulse_extension"})

    def telemetry_snapshot(self, context: StrategyContext, setup: SetupEvaluation, signal) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "primary_regime": context.primary_regime,
            "market_state": context.market_state,
            "market_phase": context.market_phase,
            "setup_quality": round(setup.setup_quality, 4),
            "signal_id": signal.signal_id if signal else None,
            "event_flags": context.actionable_event_flags,
        }
