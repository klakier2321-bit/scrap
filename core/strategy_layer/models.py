"""Typed helpers for the canonical strategy layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


TRUST_LEVEL_ORDER = {
    "broken": 0,
    "low_trust": 1,
    "limited_trust": 2,
    "full_trust": 3,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def trust_level_rank(value: str | None) -> int:
    return TRUST_LEVEL_ORDER.get(str(value or "broken"), 0)


def manifest_allows_direction(manifest_direction: str, signal_direction: str) -> bool:
    normalized = str(manifest_direction or "both")
    if normalized == "both":
        return signal_direction in {"long", "short"}
    return normalized == signal_direction


@dataclass(slots=True)
class StrategyManifest:
    strategy_id: str
    display_name: str
    version: str
    strategy_family: str
    risk_profile: str
    execution_style: str
    archetype: str
    status: str
    supported_regimes: list[str] = field(default_factory=list)
    supported_market_states: list[str] = field(default_factory=list)
    supported_market_phases: list[str] = field(default_factory=list)
    supported_volatility_phases: list[str] = field(default_factory=list)
    supported_biases: list[str] = field(default_factory=list)
    supported_event_contexts: list[str] = field(default_factory=list)
    minimum_data_trust: str = "low_trust"
    disallowed_conditions: list[str] = field(default_factory=list)
    required_data_inputs: list[str] = field(default_factory=list)
    optional_data_inputs: list[str] = field(default_factory=list)
    signal_contract: dict[str, Any] = field(default_factory=dict)
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    entry_semantics: dict[str, Any] = field(default_factory=dict)
    exit_semantics: dict[str, Any] = field(default_factory=dict)
    telemetry_requirements: list[str] = field(default_factory=list)
    backtest_priority: str = "medium"
    steward_agent_role: str = ""
    owner_team: str = ""
    dependencies: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    implementation_status: str = "planned"
    manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StrategyContext:
    bot_id: str
    generated_at: str
    regime_report: dict[str, Any]
    risk_decision: dict[str, Any]
    symbol_features: dict[str, Any] = field(default_factory=dict)
    derivatives_state: dict[str, Any] = field(default_factory=dict)
    market_microstructure: dict[str, Any] = field(default_factory=dict)
    portfolio_hint: dict[str, Any] = field(default_factory=dict)

    @property
    def primary_regime(self) -> str:
        return str(self.regime_report.get("primary_regime") or "unknown")

    @property
    def market_state(self) -> str:
        return str(self.regime_report.get("market_state") or "unknown")

    @property
    def market_phase(self) -> str:
        return str(self.regime_report.get("market_phase") or "unknown")

    @property
    def volatility_phase(self) -> str:
        return str(self.regime_report.get("volatility_phase") or "unknown")

    @property
    def htf_bias(self) -> str:
        return str(self.regime_report.get("htf_bias") or "neutral")

    @property
    def consensus_strength(self) -> float:
        try:
            return float(self.regime_report.get("consensus_strength") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def regime_quality(self) -> float:
        try:
            return float(self.regime_report.get("regime_quality") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def confidence(self) -> float:
        try:
            return float(self.regime_report.get("confidence") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def alignment_score(self) -> float:
        try:
            return float(self.regime_report.get("alignment_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def data_trust_level(self) -> str:
        return str(self.risk_decision.get("data_trust_level") or "broken")

    @property
    def trading_mode(self) -> str:
        return str(self.risk_decision.get("trading_mode") or "blocked")

    @property
    def allowed_directions(self) -> list[str]:
        return list(self.risk_decision.get("allowed_directions") or [])

    @property
    def actionable_event_flags(self) -> dict[str, bool]:
        return dict(self.regime_report.get("actionable_event_flags") or {})

    @property
    def active_event_flags(self) -> dict[str, bool]:
        return dict(self.regime_report.get("active_event_flags") or {})

    @property
    def execution_constraints(self) -> dict[str, bool]:
        return dict(self.regime_report.get("execution_constraints") or {})


@dataclass(slots=True)
class ApplicabilityResult:
    applicable: bool
    reasons: list[str] = field(default_factory=list)
    soft_blocks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SetupEvaluation:
    setup_detected: bool
    setup_quality: float = 0.0
    entry_type: str = ""
    aggressiveness_tag: str = "standard"
    evidence: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    advisory_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InvalidationSpec:
    type: str
    price: float | None = None
    condition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExitTemplateSpec:
    name: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, **self.details}


@dataclass(slots=True)
class StrategySignal:
    strategy_id: str
    strategy_version: str
    signal_id: str
    signal_status: str
    generated_at: str
    pair: str
    direction: str
    setup_quality: float
    entry_type: str
    entry_zone: dict[str, Any]
    confirmation_requirements: list[str]
    invalidation: dict[str, Any]
    exit_logic_template: str
    time_horizon: str
    aggressiveness_tag: str
    supporting_evidence: list[str]
    regime_alignment: dict[str, Any]
    data_dependencies_used: list[str] = field(default_factory=list)
    expected_trade_profile: dict[str, Any] = field(default_factory=dict)
    strategy_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
