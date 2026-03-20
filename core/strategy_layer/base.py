"""Base strategy interface for regime-aware strategy modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
import uuid

from .models import (
    ApplicabilityResult,
    ExitTemplateSpec,
    InvalidationSpec,
    SetupEvaluation,
    StrategyContext,
    StrategyManifest,
    StrategySignal,
    now_iso,
)


class BaseStrategy(ABC):
    """Common interface for every strategy module in the canonical layer."""

    def __init__(self, manifest: StrategyManifest) -> None:
        self.manifest = manifest
        self.params = dict(manifest.parameter_schema or {})

    @property
    def strategy_id(self) -> str:
        return self.manifest.strategy_id

    def load_manifest(self) -> StrategyManifest:
        return self.manifest

    @abstractmethod
    def is_applicable(self, context: StrategyContext) -> ApplicabilityResult:
        """Fast gating based on regime mandate and available data."""

    @abstractmethod
    def evaluate_setup(self, context: StrategyContext) -> SetupEvaluation:
        """Score the current setup and collect evidence."""

    @abstractmethod
    def invalidation_logic(
        self,
        context: StrategyContext,
        setup: SetupEvaluation,
    ) -> InvalidationSpec:
        """Describe when the setup becomes invalid."""

    @abstractmethod
    def exit_template(
        self,
        context: StrategyContext,
        setup: SetupEvaluation,
    ) -> ExitTemplateSpec:
        """Describe the exit template used by the strategy."""

    @abstractmethod
    def telemetry_snapshot(
        self,
        context: StrategyContext,
        setup: SetupEvaluation,
        signal: StrategySignal | None,
    ) -> dict[str, Any]:
        """Emit a structured snapshot for telemetry and replay."""

    def build_signal(
        self,
        context: StrategyContext,
        setup: SetupEvaluation,
    ) -> StrategySignal | None:
        """Build the canonical signal once a setup passes its threshold."""

        if not setup.setup_detected or setup.advisory_only:
            return None

        invalidation = self.invalidation_logic(context, setup)
        exit_template = self.exit_template(context, setup)
        signal_direction = self._resolve_direction(context)
        if signal_direction is None:
            return None

        return StrategySignal(
            strategy_id=self.strategy_id,
            strategy_version=self.manifest.version,
            signal_id=f"{self.strategy_id}-{uuid.uuid4().hex[:12]}",
            signal_status="candidate",
            generated_at=now_iso(),
            pair=self._resolve_pair(context),
            direction=signal_direction,
            setup_quality=round(setup.setup_quality, 4),
            entry_type=setup.entry_type,
            entry_zone=self._entry_zone(context, setup),
            confirmation_requirements=self._confirmation_requirements(context, setup),
            invalidation=invalidation.to_dict(),
            exit_logic_template=exit_template.name,
            time_horizon=self._time_horizon(),
            aggressiveness_tag=setup.aggressiveness_tag,
            supporting_evidence=list(setup.evidence),
            regime_alignment=self._regime_alignment(context),
            data_dependencies_used=list(self.manifest.required_data_inputs),
            expected_trade_profile=self._expected_trade_profile(context, setup),
            strategy_notes=[],
        )

    def _resolve_direction(self, context: StrategyContext) -> str | None:
        if context.htf_bias == "long":
            return "long"
        if context.htf_bias == "short":
            return "short"
        allowed = context.allowed_directions
        if len(allowed) == 1:
            return allowed[0]
        return None

    def _resolve_pair(self, context: StrategyContext) -> str:
        lead_symbol = str(context.regime_report.get("lead_symbol") or "BTC")
        if lead_symbol == "ETH":
            return "ETH/USDT:USDT"
        return "BTC/USDT:USDT"

    def _entry_zone(self, context: StrategyContext, setup: SetupEvaluation) -> dict[str, Any]:
        reference_price = float((context.symbol_features or {}).get("reference_price") or 0.0)
        return {
            "reference_price": reference_price,
            "entry_min": reference_price,
            "entry_max": reference_price,
        }

    def _confirmation_requirements(
        self,
        context: StrategyContext,
        setup: SetupEvaluation,
    ) -> list[str]:
        del context, setup
        return []

    def _time_horizon(self) -> str:
        return "intraday_medium"

    def _regime_alignment(self, context: StrategyContext) -> dict[str, Any]:
        return {
            "primary_regime": context.primary_regime,
            "market_state": context.market_state,
            "market_phase": context.market_phase,
            "volatility_phase": context.volatility_phase,
            "bias_alignment": context.htf_bias,
            "consensus_alignment": context.regime_report.get("market_consensus"),
        }

    def _expected_trade_profile(
        self,
        context: StrategyContext,
        setup: SetupEvaluation,
    ) -> dict[str, Any]:
        del context, setup
        return {
            "expected_holding_bars": 12,
            "expected_mfe_profile": "moderate",
            "expected_mae_profile": "controlled",
        }
