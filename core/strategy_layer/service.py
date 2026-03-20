"""Canonical orchestrator for regime-aware strategy manifests and signals."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ManifestValidationError
from .models import (
    StrategyContext,
    StrategyManifest,
    manifest_allows_direction,
    now_iso,
    trust_level_rank,
)
from .registry import STRATEGY_REGISTRY


class StrategyLayerService:
    """Loads strategy manifests, evaluates starter strategies, and persists reports."""

    ACTIVE_STATUSES = {"experimental", "shadow", "active", "restricted"}

    def __init__(
        self,
        *,
        manifests_dir: Path,
        output_dir: Path,
        telemetry_dir: Path,
    ) -> None:
        self.manifests_dir = manifests_dir
        self.output_dir = output_dir
        self.telemetry_dir = telemetry_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)

    def list_manifests(self) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for path in sorted(self.manifests_dir.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            manifest = self._validate_manifest(payload, path)
            manifests.append(manifest.to_dict())
        return manifests

    def latest_report(self, *, bot_id: str = "ft_trend_pullback_continuation_v1") -> dict[str, Any] | None:
        path = self.output_dir / f"latest-{bot_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def generate_report(
        self,
        *,
        regime_report: dict[str, Any] | None,
        risk_decision: dict[str, Any] | None,
        bot_id: str = "ft_trend_pullback_continuation_v1",
        strategy_filter_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        generated_at = now_iso()
        manifests = self.list_manifests()
        if strategy_filter_ids:
            allowed_ids = set(strategy_filter_ids)
            manifests = [manifest for manifest in manifests if str(manifest.get("strategy_id") or "") in allowed_ids]
        if not regime_report:
            report = {
                "generated_at": generated_at,
                "bot_id": bot_id,
                "status": "blocked",
                "reason": "regime_report_missing",
                "manifests_total": len(manifests),
                "strategy_evaluations": [],
                "built_signals": [],
                "preferred_strategy_id": None,
                "preferred_risk_admitted_strategy_id": None,
                "ranking": [],
                "advisory_strategy_ids": [],
                "risk_admitted_strategy_ids": [],
                "blocked_by_risk_strategy_ids": [],
                "applicable_strategy_ids": [],
                "blocked_strategy_ids": [],
            }
            self._persist(bot_id, report)
            return report

        context = self._build_context(
            bot_id=bot_id,
            regime_report=regime_report,
            risk_decision=risk_decision or {},
        )

        evaluations: list[dict[str, Any]] = []
        built_signals: list[dict[str, Any]] = []
        ranking: list[dict[str, Any]] = []
        advisory_strategy_ids: list[str] = []
        risk_admitted_strategy_ids: list[str] = []
        blocked_by_risk_strategy_ids: list[str] = []

        for manifest_payload in manifests:
            manifest = self._validate_manifest(manifest_payload, None)
            if manifest.status == "deprecated":
                evaluations.append(self._blocked_evaluation(manifest, "deprecated"))
                continue
            if manifest.status not in self.ACTIVE_STATUSES:
                evaluations.append(self._blocked_evaluation(manifest, f"status_{manifest.status}"))
                continue

            manifest_mismatch_reasons = self._manifest_mismatch_reasons(manifest, context)
            if manifest_mismatch_reasons:
                blocked = self._blocked_evaluation(manifest, "manifest_scope_mismatch")
                blocked["applicability"]["reasons"] = manifest_mismatch_reasons
                blocked["risk_gate"] = {"allowed": False, "reasons": manifest_mismatch_reasons}
                evaluations.append(blocked)
                self._emit_telemetry(
                    manifest.strategy_id,
                    {
                        "generated_at": generated_at,
                        "event_type": "setup_rejected",
                        "strategy_id": manifest.strategy_id,
                        "reasons": manifest_mismatch_reasons,
                        "risk_gate": blocked["risk_gate"],
                    },
                )
                continue

            strategy_cls = STRATEGY_REGISTRY.get(manifest.strategy_id)
            if strategy_cls is None:
                evaluations.append(self._blocked_evaluation(manifest, "implementation_missing"))
                continue

            strategy = strategy_cls(manifest)
            applicability = strategy.is_applicable(context)
            risk_gate = self._risk_gate(manifest, context)
            evaluation: dict[str, Any] = {
                "strategy_id": manifest.strategy_id,
                "display_name": manifest.display_name,
                "strategy_family": manifest.strategy_family,
                "risk_profile": manifest.risk_profile,
                "execution_style": manifest.execution_style,
                "status": manifest.status,
                "implementation_status": manifest.implementation_status,
                "applicable": applicability.applicable,
                "applicability": applicability.to_dict(),
                "risk_gate": risk_gate,
            }

            if not applicability.applicable:
                evaluations.append(evaluation)
                self._emit_telemetry(
                    manifest.strategy_id,
                    {
                        "generated_at": generated_at,
                        "event_type": "setup_rejected",
                        "strategy_id": manifest.strategy_id,
                        "reasons": applicability.reasons,
                        "risk_gate": risk_gate,
                    },
                )
                continue

            setup = strategy.evaluate_setup(context)
            evaluation["setup_evaluation"] = setup.to_dict()
            signal = strategy.build_signal(context, setup)
            telemetry_snapshot = strategy.telemetry_snapshot(context, setup, signal)

            if setup.advisory_only:
                advisory_strategy_ids.append(manifest.strategy_id)

            if signal is not None:
                signal_payload = signal.to_dict()
                signal_risk_reasons = list(risk_gate["reasons"])
                if signal_payload["direction"] not in context.allowed_directions:
                    signal_risk_reasons.append("direction_not_allowed_by_risk")
                if not manifest_allows_direction(
                    manifest.entry_semantics.get("allowed_directions", "both")
                    if isinstance(manifest.entry_semantics, dict)
                    else "both",
                    signal_payload["direction"],
                ):
                    signal_risk_reasons.append("direction_not_allowed_by_manifest")
                signal_payload["risk_admissible"] = len(signal_risk_reasons) == 0
                signal_payload["risk_block_reasons"] = signal_risk_reasons
                signal_payload["rank_score"] = round(
                    signal.setup_quality + self._ranking_bonus(manifest, context, signal_payload),
                    4,
                )
                built_signals.append(signal_payload)
                ranking.append(
                    {
                        "strategy_id": manifest.strategy_id,
                        "rank_score": signal_payload["rank_score"],
                    }
                )
                evaluation["signal"] = signal_payload
                if signal_payload["risk_admissible"]:
                    risk_admitted_strategy_ids.append(manifest.strategy_id)
                else:
                    blocked_by_risk_strategy_ids.append(manifest.strategy_id)
            elif applicability.applicable and not risk_gate["allowed"]:
                blocked_by_risk_strategy_ids.append(manifest.strategy_id)

            evaluations.append(evaluation)
            self._emit_telemetry(
                manifest.strategy_id,
                {
                    "generated_at": generated_at,
                    "event_type": "signal_built" if signal else "setup_evaluated",
                    "strategy_id": manifest.strategy_id,
                    "telemetry_snapshot": telemetry_snapshot,
                    "risk_gate": risk_gate,
                },
            )

        built_signals.sort(
            key=lambda item: (
                0 if item.get("risk_admissible") else 1,
                -float(item.get("rank_score") or 0.0),
                item.get("strategy_id", ""),
            )
        )
        ranking.sort(key=lambda item: (-float(item["rank_score"]), item["strategy_id"]))
        preferred_risk_admitted_strategy_id = next(
            (item["strategy_id"] for item in built_signals if item.get("risk_admissible")),
            None,
        )

        report = {
            "generated_at": generated_at,
            "bot_id": bot_id,
            "status": "ok",
            "primary_regime": context.primary_regime,
            "market_state": context.market_state,
            "market_phase": context.market_phase,
            "volatility_phase": context.volatility_phase,
            "trading_mode": context.trading_mode,
            "data_trust_level": context.data_trust_level,
            "allowed_directions": context.allowed_directions,
            "manifests_total": len(manifests),
            "implemented_strategies_total": sum(1 for item in evaluations if item["implementation_status"] == "implemented"),
            "applicable_strategy_ids": [item["strategy_id"] for item in evaluations if item.get("applicable")],
            "blocked_strategy_ids": [item["strategy_id"] for item in evaluations if not item.get("applicable")],
            "risk_admitted_strategy_ids": sorted(set(risk_admitted_strategy_ids)),
            "blocked_by_risk_strategy_ids": sorted(set(blocked_by_risk_strategy_ids)),
            "advisory_strategy_ids": advisory_strategy_ids,
            "strategy_evaluations": evaluations,
            "built_signals": built_signals,
            "preferred_strategy_id": preferred_risk_admitted_strategy_id,
            "preferred_risk_admitted_strategy_id": preferred_risk_admitted_strategy_id,
            "ranking": ranking,
        }
        self._persist(bot_id, report)
        return report

    def _build_context(
        self,
        *,
        bot_id: str,
        regime_report: dict[str, Any],
        risk_decision: dict[str, Any],
    ) -> StrategyContext:
        symbol_features = dict(regime_report.get("feature_snapshot") or {})
        derivatives_state = dict(regime_report.get("derivatives_state") or regime_report.get("derivatives_state_global") or {})
        market_microstructure = {
            "btc_state": regime_report.get("btc_state"),
            "eth_state": regime_report.get("eth_state"),
            "market_consensus": regime_report.get("market_consensus"),
            "consensus_strength": regime_report.get("consensus_strength"),
            "lead_symbol": regime_report.get("lead_symbol"),
            "lag_confirmation": regime_report.get("lag_confirmation"),
        }
        return StrategyContext(
            bot_id=bot_id,
            generated_at=now_iso(),
            regime_report=dict(regime_report),
            risk_decision=dict(risk_decision),
            symbol_features=symbol_features,
            derivatives_state=derivatives_state,
            market_microstructure=market_microstructure,
        )

    def _risk_gate(
        self,
        manifest: StrategyManifest,
        context: StrategyContext,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        is_event_exception = (
            manifest.strategy_family == "panic_reversal"
            and any(bool(context.actionable_event_flags.get(name)) for name in ("panic_flush", "capitulation"))
            and context.data_trust_level in {"full_trust", "limited_trust"}
        )
        if context.trading_mode == "blocked":
            reasons.append("trading_mode_blocked")
        if trust_level_rank(context.data_trust_level) < trust_level_rank(manifest.minimum_data_trust):
            reasons.append("data_trust_below_manifest_minimum")
        if (
            context.risk_decision.get("protective_overrides", {}).get("disable_aggressive_entries")
            and manifest.risk_profile == "aggressive"
            and not is_event_exception
        ):
            reasons.append("aggressive_family_blocked_by_risk")
        if (
            context.trading_mode in {"capital_protection", "reduced_risk"}
            and manifest.risk_profile == "aggressive"
            and not is_event_exception
        ):
            reasons.append("risk_mode_blocks_aggressive_strategy")
        if context.execution_constraints.get("no_trade_zone") and manifest.strategy_family != "defense_only":
            reasons.append("no_trade_zone")
        if context.execution_constraints.get("post_shock_cooldown") and manifest.strategy_family not in {"defense_only", "panic_reversal"}:
            reasons.append("post_shock_cooldown")
        allowed_ids = list(context.risk_decision.get("allowed_strategy_ids") or [])
        blocked_ids = list(context.risk_decision.get("blocked_strategy_ids") or [])
        allowed_families = list(context.risk_decision.get("allowed_strategy_families") or [])
        blocked_families = list(context.risk_decision.get("blocked_strategy_families") or [])
        if manifest.strategy_id in blocked_ids:
            reasons.append("blocked_by_risk_decision")
        if allowed_ids and manifest.strategy_id not in allowed_ids:
            reasons.append("not_in_allowed_strategy_ids")
        if manifest.strategy_family in blocked_families:
            reasons.append("blocked_family_by_risk_decision")
        if allowed_families and manifest.strategy_family not in allowed_families:
            reasons.append("not_in_allowed_strategy_families")
        return {
            "allowed": not reasons,
            "reasons": reasons,
        }

    def _manifest_mismatch_reasons(
        self,
        manifest: StrategyManifest,
        context: StrategyContext,
    ) -> list[str]:
        reasons: list[str] = []
        if manifest.supported_regimes and context.primary_regime not in manifest.supported_regimes:
            reasons.append("unsupported_primary_regime")
        if manifest.supported_market_states and context.market_state not in manifest.supported_market_states:
            reasons.append("unsupported_market_state")
        if manifest.supported_market_phases and context.market_phase not in manifest.supported_market_phases:
            reasons.append("unsupported_market_phase")
        if (
            manifest.supported_volatility_phases
            and context.volatility_phase not in manifest.supported_volatility_phases
        ):
            reasons.append("unsupported_volatility_phase")
        if manifest.supported_biases and context.htf_bias not in manifest.supported_biases:
            reasons.append("unsupported_bias")
        if manifest.supported_event_contexts and not any(
            bool(context.actionable_event_flags.get(name) or context.active_event_flags.get(name))
            for name in manifest.supported_event_contexts
        ):
            reasons.append("required_event_context_missing")
        reasons.extend(
            f"required_input_missing:{input_name}"
            for input_name in self._missing_required_inputs(manifest, context)
        )
        for condition in manifest.disallowed_conditions:
            if bool(context.execution_constraints.get(condition)):
                reasons.append(f"disallowed_condition:{condition}")
        return reasons

    def _missing_required_inputs(
        self,
        manifest: StrategyManifest,
        context: StrategyContext,
    ) -> list[str]:
        missing: list[str] = []
        for input_name in manifest.required_data_inputs:
            name = str(input_name or "")
            if name == "regime_report" and not context.regime_report:
                missing.append(name)
            elif name == "risk_decision" and not context.risk_decision:
                missing.append(name)
            elif name == "feature_snapshot" and not context.symbol_features:
                missing.append(name)
            elif name in {"derivatives_state", "derivatives_state_global"} and not context.derivatives_state:
                missing.append(name)
            elif name == "market_consensus" and context.regime_report.get("market_consensus") is None:
                missing.append(name)
            elif name == "btc_state" and context.regime_report.get("btc_state") is None:
                missing.append(name)
            elif name == "eth_state" and context.regime_report.get("eth_state") is None:
                missing.append(name)
        return missing

    def _ranking_bonus(
        self,
        manifest: StrategyManifest,
        context: StrategyContext,
        signal_payload: dict[str, Any],
    ) -> float:
        bonus = 0.0
        if manifest.strategy_family == "pullback_trend" and context.market_phase == "pullback":
            bonus += 0.12
        if manifest.strategy_family == "breakout" and context.market_phase == "compression":
            bonus += 0.10
        if manifest.strategy_family == "mean_reversion" and context.primary_regime in {"range", "low_vol"}:
            bonus += 0.08
        if manifest.strategy_family == "panic_reversal" and context.primary_regime == "stress_panic":
            bonus += 0.18
        if signal_payload.get("direction") == context.htf_bias:
            bonus += 0.05
        return bonus

    def _validate_manifest(
        self,
        payload: dict[str, Any],
        path: Path | None,
    ) -> StrategyManifest:
        required = (
            "strategy_id",
            "display_name",
            "version",
            "strategy_family",
            "risk_profile",
            "execution_style",
            "archetype",
            "status",
        )
        missing = [field for field in required if not payload.get(field)]
        if missing:
            location = str(path) if path else "manifest"
            raise ManifestValidationError(f"Missing required manifest fields {missing} in {location}")
        return StrategyManifest(
            strategy_id=str(payload["strategy_id"]),
            display_name=str(payload["display_name"]),
            version=str(payload["version"]),
            strategy_family=str(payload["strategy_family"]),
            risk_profile=str(payload["risk_profile"]),
            execution_style=str(payload["execution_style"]),
            archetype=str(payload["archetype"]),
            status=str(payload["status"]),
            supported_regimes=list(payload.get("supported_regimes") or []),
            supported_market_states=list(payload.get("supported_market_states") or []),
            supported_market_phases=list(payload.get("supported_market_phases") or []),
            supported_volatility_phases=list(payload.get("supported_volatility_phases") or []),
            supported_biases=list(payload.get("supported_biases") or []),
            supported_event_contexts=list(payload.get("supported_event_contexts") or []),
            minimum_data_trust=str(payload.get("minimum_data_trust") or "low_trust"),
            disallowed_conditions=list(payload.get("disallowed_conditions") or []),
            required_data_inputs=list(payload.get("required_data_inputs") or []),
            optional_data_inputs=list(payload.get("optional_data_inputs") or []),
            signal_contract=dict(payload.get("signal_contract") or {}),
            parameter_schema=dict(payload.get("parameter_schema") or {}),
            entry_semantics=dict(payload.get("entry_semantics") or {}),
            exit_semantics=dict(payload.get("exit_semantics") or {}),
            telemetry_requirements=list(payload.get("telemetry_requirements") or []),
            backtest_priority=str(payload.get("backtest_priority") or "medium"),
            steward_agent_role=str(payload.get("steward_agent_role") or ""),
            owner_team=str(payload.get("owner_team") or ""),
            dependencies=list(payload.get("dependencies") or []),
            notes=list(payload.get("notes") or []),
            implementation_status=str(payload.get("implementation_status") or "planned"),
            manifest_path=str(path) if path else payload.get("manifest_path"),
        )

    def _blocked_evaluation(self, manifest: StrategyManifest, reason: str) -> dict[str, Any]:
        return {
            "strategy_id": manifest.strategy_id,
            "display_name": manifest.display_name,
            "strategy_family": manifest.strategy_family,
            "risk_profile": manifest.risk_profile,
            "execution_style": manifest.execution_style,
            "status": manifest.status,
            "implementation_status": manifest.implementation_status,
            "applicable": False,
            "applicability": {"applicable": False, "reasons": [reason], "soft_blocks": []},
            "risk_gate": {"allowed": False, "reasons": [reason]},
        }

    def _persist(self, bot_id: str, report: dict[str, Any]) -> None:
        latest_path = self.output_dir / f"latest-{bot_id}.json"
        latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        history_name = f"{bot_id}-{str(report.get('generated_at', '')).replace(':', '').replace('+00:00', 'Z')}.json"
        (self.output_dir / history_name).write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    def _emit_telemetry(self, strategy_id: str, payload: dict[str, Any]) -> None:
        path = self.telemetry_dir / f"{strategy_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
