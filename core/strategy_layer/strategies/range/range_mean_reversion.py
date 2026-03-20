"""Range mean reversion strategy."""

from __future__ import annotations

from ...base import BaseStrategy
from ...models import ApplicabilityResult, ExitTemplateSpec, InvalidationSpec, SetupEvaluation, StrategyContext


class RangeMeanReversionStrategy(BaseStrategy):
    """Fade extremes inside a balanced range."""

    def is_applicable(self, context: StrategyContext) -> ApplicabilityResult:
        reasons: list[str] = []
        if context.primary_regime not in {"range", "low_vol"}:
            reasons.append("primary_regime_out_of_scope")
        if context.htf_bias in {"long", "short"} and context.consensus_strength >= 0.65:
            reasons.append("directional_bias_too_strong")
        if context.market_phase == "expansion":
            reasons.append("market_phase_expansion")
        return ApplicabilityResult(applicable=not reasons, reasons=reasons)

    def evaluate_setup(self, context: StrategyContext) -> SetupEvaluation:
        score = 0.50
        evidence: list[str] = ["range_rotation_context"]
        if context.consensus_strength <= 0.55:
            score += 0.10
            evidence.append("consensus_balanced")
        if context.volatility_phase == "compression":
            score += 0.05
            evidence.append("volatility_compressed")
        if any(bool(context.active_event_flags.get(name)) for name in ("panic_flush", "short_squeeze", "long_squeeze")):
            score -= 0.30
        return SetupEvaluation(
            setup_detected=score >= 0.62,
            setup_quality=max(0.0, min(score, 0.90)),
            entry_type="market_confirmation",
            aggressiveness_tag="defensive",
            evidence=evidence,
            reasons=[] if score >= 0.62 else ["range_rotation_not_clean_enough"],
        )

    def invalidation_logic(self, context: StrategyContext, setup: SetupEvaluation) -> InvalidationSpec:
        del context, setup
        return InvalidationSpec(type="range_break", condition="range_boundary_acceptance")

    def exit_template(self, context: StrategyContext, setup: SetupEvaluation) -> ExitTemplateSpec:
        del context, setup
        return ExitTemplateSpec(name="return_to_mid_or_opposite_boundary", details={"exit_style": "fade"})

    def telemetry_snapshot(self, context: StrategyContext, setup: SetupEvaluation, signal) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "primary_regime": context.primary_regime,
            "market_consensus": context.regime_report.get("market_consensus"),
            "setup_quality": round(setup.setup_quality, 4),
            "signal_id": signal.signal_id if signal else None,
        }
