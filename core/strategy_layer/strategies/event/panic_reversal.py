"""Panic reversal strategy."""

from __future__ import annotations

from ...base import BaseStrategy
from ...models import ApplicabilityResult, ExitTemplateSpec, InvalidationSpec, SetupEvaluation, StrategyContext


class PanicReversalStrategy(BaseStrategy):
    """Reversal after capitulation or panic flush with confirmation."""

    def is_applicable(self, context: StrategyContext) -> ApplicabilityResult:
        reasons: list[str] = []
        if context.primary_regime != "stress_panic":
            reasons.append("primary_regime_not_stress_panic")
        if not any(bool(context.actionable_event_flags.get(name)) for name in ("panic_flush", "capitulation")):
            reasons.append("actionable_event_missing")
        if context.data_trust_level == "broken":
            reasons.append("data_trust_broken")
        return ApplicabilityResult(applicable=not reasons, reasons=reasons)

    def evaluate_setup(self, context: StrategyContext) -> SetupEvaluation:
        score = 0.55
        evidence: list[str] = []
        if context.actionable_event_flags.get("panic_flush"):
            score += 0.12
            evidence.append("panic_flush")
        if context.actionable_event_flags.get("capitulation"):
            score += 0.14
            evidence.append("capitulation")
        if str(context.regime_report.get("active_event_flags_reliability") or "") in {"medium", "high"}:
            score += 0.08
            evidence.append("event_reliability_ok")
        if str(context.derivatives_state.get("liquidation_event_confidence") or "") in {"medium", "high"}:
            score += 0.06
            evidence.append("liquidation_proxy_supportive")
        if context.execution_constraints.get("post_shock_cooldown"):
            score -= 0.20
        return SetupEvaluation(
            setup_detected=score >= 0.74,
            setup_quality=max(0.0, min(score, 0.98)),
            entry_type="reversal_confirmation",
            aggressiveness_tag="aggressive",
            evidence=evidence,
            reasons=[] if score >= 0.74 else ["panic_reversal_not_confirmed"],
        )

    def invalidation_logic(self, context: StrategyContext, setup: SetupEvaluation) -> InvalidationSpec:
        del context, setup
        return InvalidationSpec(type="reversal_failure", condition="reclaim_level_lost")

    def exit_template(self, context: StrategyContext, setup: SetupEvaluation) -> ExitTemplateSpec:
        del context, setup
        return ExitTemplateSpec(name="fast_shock_reversion", details={"time_stop_bars": 4})

    def telemetry_snapshot(self, context: StrategyContext, setup: SetupEvaluation, signal) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "primary_regime": context.primary_regime,
            "actionable_event_flags": context.actionable_event_flags,
            "setup_quality": round(setup.setup_quality, 4),
            "signal_id": signal.signal_id if signal else None,
        }

    def _resolve_direction(self, context: StrategyContext) -> str | None:
        if context.actionable_event_flags.get("panic_flush") or context.actionable_event_flags.get("capitulation"):
            return "long"
        return super()._resolve_direction(context)
