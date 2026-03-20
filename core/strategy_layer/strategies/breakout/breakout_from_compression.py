"""Breakout from compression strategy."""

from __future__ import annotations

from ...base import BaseStrategy
from ...models import ApplicabilityResult, ExitTemplateSpec, InvalidationSpec, SetupEvaluation, StrategyContext


class BreakoutFromCompressionStrategy(BaseStrategy):
    """Directional breakout after compression and expansion confirmation."""

    def is_applicable(self, context: StrategyContext) -> ApplicabilityResult:
        reasons: list[str] = []
        if context.market_phase != "compression":
            reasons.append("market_phase_not_compression")
        if context.volatility_phase != "compression":
            reasons.append("volatility_phase_not_compression")
        if context.primary_regime not in {"low_vol", "high_vol", "trend_up", "trend_down"}:
            reasons.append("primary_regime_out_of_scope")
        if context.data_trust_level in {"low_trust", "broken"}:
            reasons.append("data_trust_too_low")
        return ApplicabilityResult(applicable=not reasons, reasons=reasons)

    def evaluate_setup(self, context: StrategyContext) -> SetupEvaluation:
        score = 0.45
        evidence: list[str] = ["compression_detected"]
        if context.regime_quality >= 0.65:
            score += 0.12
            evidence.append("quality_supportive")
        if context.consensus_strength >= 0.60:
            score += 0.10
            evidence.append("consensus_supportive")
        if str(context.derivatives_state.get("positioning_state") or "") in {"long_build", "short_build"}:
            score += 0.10
            evidence.append("positioning_supportive")
        if str(context.derivatives_state.get("squeeze_risk") or "") in {"medium", "high"}:
            score -= 0.25
        if context.risk_decision.get("protective_overrides", {}).get("disable_aggressive_entries"):
            score -= 0.20
        return SetupEvaluation(
            setup_detected=score >= 0.68,
            setup_quality=max(0.0, min(score, 0.95)),
            entry_type="breakout_stop",
            aggressiveness_tag="aggressive",
            evidence=evidence,
            reasons=[] if score >= 0.68 else ["compression_breakout_not_confirmed"],
        )

    def invalidation_logic(self, context: StrategyContext, setup: SetupEvaluation) -> InvalidationSpec:
        del context, setup
        return InvalidationSpec(type="failed_breakout", condition="price_returns_to_compression_range")

    def exit_template(self, context: StrategyContext, setup: SetupEvaluation) -> ExitTemplateSpec:
        del context, setup
        return ExitTemplateSpec(name="expansion_follow_through", details={"time_stop_bars": 6})

    def telemetry_snapshot(self, context: StrategyContext, setup: SetupEvaluation, signal) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "primary_regime": context.primary_regime,
            "volatility_phase": context.volatility_phase,
            "setup_quality": round(setup.setup_quality, 4),
            "signal_id": signal.signal_id if signal else None,
            "squeeze_risk": context.derivatives_state.get("squeeze_risk"),
        }
