"""Central futures risk engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import PortfolioState, empty_risk_decision, now_iso
from .policies.data_quality import evaluate_data_quality
from .policies.direction import evaluate_direction_permissions
from .policies.events import evaluate_event_overrides
from .policies.leverage import derive_leverage_cap
from .policies.portfolio import build_portfolio_state, evaluate_portfolio_overlay
from .policies.protective_overrides import derive_protective_overrides
from .policies.sizing import apply_event_caps, apply_regime_modifiers, derive_base_risk_budget
from .policies.strategies import evaluate_strategy_permissions
from .policies.trade_permission import evaluate_market_viability


class RiskEngine:
    """Evaluates market risk and produces a runtime decision."""

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_portfolio_state(self, snapshot: dict[str, Any] | None) -> PortfolioState | None:
        return build_portfolio_state(snapshot)

    def latest_decision(self, *, bot_id: str = "runtime") -> dict[str, Any] | None:
        if self.output_dir is None:
            return None
        path = self.output_dir / f"latest-{bot_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def evaluate(
        self,
        *,
        regime_report: dict[str, Any] | None,
        candidate_manifests: list[dict[str, Any]],
        portfolio_state: PortfolioState | None = None,
        bot_id: str = "runtime",
    ) -> dict[str, Any]:
        decision = empty_risk_decision()
        decision["generated_at"] = now_iso()
        decision["context"] = {"bot_id": bot_id}

        if not regime_report:
            decision["risk_reason_codes"].append("REGIME_REPORT_MISSING")
            decision["risk_notes"].append("Brakuje regime_report, wiec risk engine przechodzi w tryb blocked.")
            self._persist(bot_id, decision)
            return decision

        derivatives_state = dict(regime_report.get("derivatives_state") or regime_report.get("derivatives_state_global") or {})
        data_quality = evaluate_data_quality(derivatives_state)
        decision["data_validation_status"] = data_quality.validation_status
        decision["data_trust_level"] = data_quality.trust_level
        decision["degradation_flags"].update(data_quality.degradation_flags)
        decision["risk_reason_codes"].extend(data_quality.reason_codes)
        decision["risk_notes"].extend(data_quality.notes)
        self._trace(decision, "data_quality_gate", {
            "trust_level": data_quality.trust_level,
            "validation_status": data_quality.validation_status,
        })

        viability = evaluate_market_viability(
            primary_regime=str(regime_report.get("primary_regime") or "unknown"),
            risk_regime=str(regime_report.get("risk_regime") or regime_report.get("risk_level") or "unknown"),
            regime_quality=float(regime_report.get("regime_quality") or 0.0),
            execution_constraints=dict(regime_report.get("execution_constraints") or {}),
            actionable_event_flags=dict(regime_report.get("actionable_event_flags") or {}),
            event_reliability=str(regime_report.get("active_event_flags_reliability") or "low"),
            data_trust_level=data_quality.trust_level,
            consensus=regime_report.get("market_consensus"),
            consensus_strength=regime_report.get("consensus_strength"),
        )
        decision["allow_trading"] = bool(viability["allow_trading"])
        decision["trading_mode"] = str(viability["trading_mode"])
        decision["cooldown_active"] = bool(viability["cooldown_active"])
        decision["risk_reason_codes"].extend(viability["reason_codes"])
        decision["risk_notes"].extend(viability["notes"])
        self._trace(decision, "market_viability_gate", viability)

        event_overrides = evaluate_event_overrides(
            actionable_event_flags=dict(regime_report.get("actionable_event_flags") or {}),
            active_event_flags=dict(regime_report.get("active_event_flags") or {}),
            event_reliability=str(regime_report.get("active_event_flags_reliability") or "low"),
            data_trust_level=data_quality.trust_level,
        )
        decision["risk_reason_codes"].extend(event_overrides["reason_codes"])
        decision["risk_notes"].extend(event_overrides["notes"])
        self._trace(decision, "event_override_gate", event_overrides)

        if event_overrides["force_capital_protection"] and decision["trading_mode"] != "blocked":
            decision["trading_mode"] = "capital_protection"
        if event_overrides["force_reduce_only"]:
            decision["force_reduce_only"] = True

        direction_permissions = evaluate_direction_permissions(
            primary_regime=str(regime_report.get("primary_regime") or "unknown"),
            htf_bias=regime_report.get("htf_bias"),
            market_state=regime_report.get("market_state"),
            market_phase=regime_report.get("market_phase"),
            btc_state=regime_report.get("btc_state"),
            eth_state=regime_report.get("eth_state"),
            market_consensus=regime_report.get("market_consensus"),
            consensus_strength=regime_report.get("consensus_strength"),
            actionable_event_flags=dict(regime_report.get("actionable_event_flags") or {}),
            derivatives=derivatives_state,
            hard_block=decision["trading_mode"] == "blocked",
        )
        blocked_directions = set(direction_permissions["blocked_directions"]) | set(event_overrides.get("blocked_directions") or [])
        allowed_directions = [item for item in direction_permissions["allowed_directions"] if item not in blocked_directions]
        if not allowed_directions:
            decision["allow_trading"] = False if decision["trading_mode"] == "blocked" else decision["allow_trading"]
        decision["allowed_directions"] = allowed_directions
        decision["blocked_directions"] = sorted(blocked_directions)
        decision["risk_reason_codes"].extend(direction_permissions["reason_codes"])
        decision["risk_notes"].extend(direction_permissions["notes"])
        self._trace(decision, "directional_permission_gate", direction_permissions)

        strategy_permissions = evaluate_strategy_permissions(
            candidate_manifests=candidate_manifests,
            regime_report=regime_report,
            allowed_directions=allowed_directions,
            trading_mode=decision["trading_mode"],
            data_trust_level=data_quality.trust_level,
            event_overrides=event_overrides,
        )
        decision.update({
            "allowed_strategy_ids": strategy_permissions["allowed_strategy_ids"],
            "blocked_strategy_ids": strategy_permissions["blocked_strategy_ids"],
            "allowed_strategy_families": strategy_permissions["allowed_strategy_families"],
            "blocked_strategy_families": strategy_permissions["blocked_strategy_families"],
        })
        decision["risk_reason_codes"].extend(strategy_permissions["reason_codes"])
        decision["risk_notes"].extend(strategy_permissions["notes"])
        self._trace(decision, "strategy_permission_gate", strategy_permissions)

        budget = derive_base_risk_budget(decision["trading_mode"])
        budget = apply_regime_modifiers(
            budget,
            position_size_multiplier=regime_report.get("position_size_multiplier"),
            regime_quality=regime_report.get("regime_quality"),
            confidence=regime_report.get("confidence"),
            execution_constraints=dict(regime_report.get("execution_constraints") or {}),
            volatility_phase=regime_report.get("volatility_phase"),
            data_trust_level=data_quality.trust_level,
        )
        budget = apply_event_caps(
            budget,
            actionable_event_flags=dict(regime_report.get("actionable_event_flags") or {}),
            event_reliability=str(regime_report.get("active_event_flags_reliability") or "low"),
        )

        if portfolio_state is None:
            decision["degradation_flags"]["portfolio_state_missing"] = True
            decision["risk_reason_codes"].append("PORTFOLIO_STATE_MISSING")
            decision["risk_notes"].append("Portfolio state nie byl dostepny, wiec overlay portfela nie zaostrzyl limitow.")
            self._trace(decision, "portfolio_overlay", {"status": "missing"})
        else:
            overlay = evaluate_portfolio_overlay(
                portfolio_state=portfolio_state,
                allowed_directions=allowed_directions,
                base_budget=budget,
            )
            budget = overlay["adjusted_budget"]
            decision["risk_reason_codes"].extend(overlay["reason_codes"])
            decision["risk_notes"].extend(overlay["notes"])
            self._trace(decision, "portfolio_overlay", overlay)

        leverage_cap, leverage_codes, leverage_notes = derive_leverage_cap(
            trading_mode=decision["trading_mode"],
            risk_regime=str(regime_report.get("risk_regime") or regime_report.get("risk_level") or "unknown"),
            volatility_phase=regime_report.get("volatility_phase"),
            derivatives=derivatives_state,
            consensus_strength=regime_report.get("consensus_strength"),
            data_trust_level=data_quality.trust_level,
            actionable_event_flags=dict(regime_report.get("actionable_event_flags") or {}),
        )
        decision["risk_reason_codes"].extend(leverage_codes)
        decision["risk_notes"].extend(leverage_notes)

        protective = derive_protective_overrides(
            trading_mode=decision["trading_mode"],
            execution_constraints=dict(regime_report.get("execution_constraints") or {}),
            data_trust_level=data_quality.trust_level,
            actionable_event_flags=dict(regime_report.get("actionable_event_flags") or {}),
        )
        decision["protective_overrides"] = protective
        self._trace(decision, "protective_overrides", protective)

        decision["max_position_size_pct"] = round(float(budget["max_position_size_pct"]), 4)
        decision["max_total_exposure_pct"] = round(float(budget["max_total_exposure_pct"]), 4)
        decision["max_positions_total"] = int(budget["max_positions_total"])
        decision["max_positions_per_symbol"] = int(budget["max_positions_per_symbol"])
        decision["max_correlated_positions"] = int(budget["max_correlated_positions"])
        decision["leverage_cap"] = float(min(leverage_cap, float(budget["leverage_cap"])))
        decision["force_reduce_only"] = bool(decision["force_reduce_only"] or budget["force_reduce_only"] or event_overrides["force_reduce_only"])
        decision["new_entries_allowed"] = bool(
            decision["allow_trading"]
            and budget["new_entries_allowed"]
            and bool(allowed_directions)
            and bool(decision["allowed_strategy_ids"])
            and decision["trading_mode"] != "blocked"
        )
        decision["risk_state"] = str(regime_report.get("risk_regime") or regime_report.get("risk_level") or "unknown")
        decision["risk_score"] = self._derive_risk_score(
            trading_mode=decision["trading_mode"],
            risk_state=decision["risk_state"],
            data_trust_level=data_quality.trust_level,
            regime_quality=float(regime_report.get("regime_quality") or 0.0),
            consensus_strength=float(regime_report.get("consensus_strength") or 0.0),
            cooldown_active=bool(decision["cooldown_active"]),
        )
        self._trace(decision, "position_sizing_gate", budget)
        self._trace(decision, "leverage_gate", {"leverage_cap": decision["leverage_cap"]})

        self._dedupe_lists(decision)
        self._persist(bot_id, decision)
        return decision

    @staticmethod
    def _derive_risk_score(
        *,
        trading_mode: str,
        risk_state: str,
        data_trust_level: str,
        regime_quality: float,
        consensus_strength: float,
        cooldown_active: bool,
    ) -> int:
        score = 50
        if trading_mode == "blocked":
            score += 35
        elif trading_mode == "capital_protection":
            score += 20
        elif trading_mode == "reduced_risk":
            score += 10
        if risk_state == "high":
            score += 20
        elif risk_state == "elevated":
            score += 10
        if data_trust_level == "broken":
            score += 25
        elif data_trust_level == "low_trust":
            score += 15
        elif data_trust_level == "limited_trust":
            score += 8
        score += int(max(0.0, 0.60 - regime_quality) * 40)
        score += int(max(0.0, 0.55 - consensus_strength) * 30)
        if cooldown_active:
            score += 10
        return max(0, min(100, score))

    @staticmethod
    def _trace(decision: dict[str, Any], layer: str, payload: dict[str, Any]) -> None:
        decision.setdefault("decision_trace", []).append({"layer": layer, "payload": payload})

    @staticmethod
    def _dedupe_lists(decision: dict[str, Any]) -> None:
        for key in (
            "allowed_directions",
            "blocked_directions",
            "allowed_strategy_ids",
            "blocked_strategy_ids",
            "allowed_strategy_families",
            "blocked_strategy_families",
            "risk_reason_codes",
        ):
            decision[key] = list(dict.fromkeys(decision.get(key) or []))
        decision["risk_notes"] = list(dict.fromkeys(decision.get("risk_notes") or []))

    def _persist(self, bot_id: str, decision: dict[str, Any]) -> None:
        if self.output_dir is None:
            return
        path = self.output_dir / f"latest-{bot_id}.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(decision, indent=2, ensure_ascii=True), encoding="utf-8")
