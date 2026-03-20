"""Risk and safety validation for the control layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .risk_management import RiskEngine


class RiskManager:
    """Centralizes runtime safety checks and approval rules."""

    def __init__(
        self,
        sensitive_paths: list[str] | None = None,
        *,
        risk_output_dir: Path | None = None,
    ) -> None:
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
        self.backtest_rejection_drawdown_pct = 0.05
        self.backtest_warning_drawdown_pct = 0.03
        self.dry_run_warning_loss_ratio = 0.0
        self.dry_run_fail_loss_ratio = -0.05
        self.warning_open_trade_exposure_ratio = 0.75
        self.fail_open_trade_exposure_ratio = 0.95
        self.engine = RiskEngine(output_dir=risk_output_dir)

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

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _merge_status(current: str, new: str) -> str:
        order = {"pass": 0, "warn": 1, "fail": 2}
        return new if order.get(new, 0) > order.get(current, 0) else current

    def _evaluate_backtest_gate(self, strategy_report: dict[str, Any] | None) -> dict[str, Any]:
        if not strategy_report:
            return {
                "status": "fail",
                "reason": "Brakuje raportu backtestu, więc nie ma twardego punktu odniesienia dla strategii.",
                "signals": [],
                "evidence": {},
            }

        evaluation_status = str(strategy_report.get("evaluation_status", "needs_manual_review"))
        rejection_reasons = list(strategy_report.get("rejection_reasons") or [])
        signals = [
            f"profit_pct={self._to_float(strategy_report.get('profit_pct')):.4f}",
            f"drawdown_pct={self._to_float(strategy_report.get('drawdown_pct')):.4f}",
            f"total_trades={self._to_int(strategy_report.get('total_trades'))}",
            f"win_rate={self._to_float(strategy_report.get('win_rate')):.4f}",
            f"stability_score={strategy_report.get('stability_score')}",
        ]

        if evaluation_status == "candidate_for_next_stage":
            status = "pass"
            reason = "Backtest przeszedł bramkę jakości i może iść dalej tylko po potwierdzeniu człowieka."
        elif evaluation_status == "needs_manual_review":
            status = "warn"
            reason = (
                "Backtest daje część sygnałów jakości, ale nadal wymaga ręcznego review i mocniejszego potwierdzenia."
            )
        else:
            status = "fail"
            reason = "Backtest nie spełnia dziś minimalnych progów jakości."
            if rejection_reasons:
                reason = f"{reason} Powody: {' '.join(rejection_reasons)}"

        return {
            "status": status,
            "reason": reason,
            "signals": signals,
            "evidence": {
                "evaluation_status": evaluation_status,
                "stage_candidate": bool(strategy_report.get("stage_candidate")),
            },
        }

    def _evaluate_dry_run_gate(self, dry_run_snapshot: dict[str, Any] | None) -> dict[str, Any]:
        if not dry_run_snapshot:
            return {
                "status": "fail",
                "reason": "Brakuje snapshotu dry_run, więc strategia nie ma potwierdzenia na danych runtime.",
                "signals": [],
                "evidence": {},
            }

        if not dry_run_snapshot.get("dry_run") or dry_run_snapshot.get("runmode") != "dry_run":
            return {
                "status": "fail",
                "reason": "Snapshot nie pochodzi z prawdziwego dry_run.",
                "signals": [],
                "evidence": {
                    "runmode": dry_run_snapshot.get("runmode"),
                    "snapshot_status": dry_run_snapshot.get("snapshot_status"),
                },
            }

        if dry_run_snapshot.get("snapshot_status") != "ok":
            return {
                "status": "fail",
                "reason": "Snapshot dry_run nie jest oznaczony jako poprawny.",
                "signals": [],
                "evidence": {
                    "snapshot_status": dry_run_snapshot.get("snapshot_status"),
                },
            }

        trade_count = self._to_int(dry_run_snapshot.get("profit_summary", {}).get("trade_count"))
        profit_all_ratio = self._to_float(
            dry_run_snapshot.get("profit_summary", {}).get("profit_all_ratio")
        )
        signals = [
            f"trade_count={trade_count}",
            f"profit_all_ratio={profit_all_ratio:.4f}",
            f"open_trades_count={self._to_int(dry_run_snapshot.get('open_trades_count'))}",
        ]

        if trade_count < 1:
            status = "warn"
            reason = "Dry run działa, ale nie ma jeszcze historii transakcji potrzebnej do sensownej oceny."
        elif profit_all_ratio < self.dry_run_warning_loss_ratio:
            status = "warn"
            reason = "Dry run dostarcza już dane, ale bieżący wynik nadal jest ujemny."
        else:
            status = "pass"
            reason = "Dry run daje świeże dane runtime i można je traktować jako realne potwierdzenie zachowania strategii."

        return {
            "status": status,
            "reason": reason,
            "signals": signals,
            "evidence": {
                "trade_count": trade_count,
                "profit_all_ratio": profit_all_ratio,
                "open_trades_count": self._to_int(dry_run_snapshot.get("open_trades_count")),
            },
        }

    def _evaluate_risk_gate(
        self,
        strategy_report: dict[str, Any] | None,
        dry_run_snapshot: dict[str, Any] | None,
        strategy_assessment: dict[str, Any] | None,
    ) -> dict[str, Any]:
        status = "pass"
        reasons: list[str] = []
        signals: list[str] = []

        if not strategy_report:
            return {
                "status": "fail",
                "reason": "Brakuje raportu strategii, więc nie można policzyć bramki ryzyka.",
                "signals": [],
                "evidence": {},
            }

        drawdown_pct = self._to_float(strategy_report.get("drawdown_pct"))
        stability_score = strategy_report.get("stability_score")
        signals.append(f"backtest_drawdown_pct={drawdown_pct:.4f}")
        signals.append(f"stability_score={stability_score}")

        if drawdown_pct > self.backtest_rejection_drawdown_pct:
            status = self._merge_status(status, "fail")
            reasons.append("Backtest drawdown jest ponad twardym limitem 5%.")
        elif drawdown_pct > self.backtest_warning_drawdown_pct:
            status = self._merge_status(status, "warn")
            reasons.append("Backtest drawdown jest powyżej bezpiecznego progu 3% i wymaga dyscypliny ryzyka.")

        if stability_score is not None and self._to_float(stability_score) < 0.60:
            status = self._merge_status(status, "warn")
            reasons.append("Stability score jest zbyt niski, żeby ufać strategii bez dodatkowych zabezpieczeń.")

        if strategy_assessment:
            assessment_risk = str(strategy_assessment.get("risk_level", "medium"))
            signals.append(f"assessment_risk_level={assessment_risk}")
            if assessment_risk == "high":
                status = self._merge_status(status, "fail")
                reasons.append("Ostatni assessment strategii oznaczył ryzyko jako wysokie.")
            elif assessment_risk == "medium":
                status = self._merge_status(status, "warn")
                reasons.append("Assessment strategii nadal widzi średnie ryzyko i nie daje podstaw do promocji.")

        if dry_run_snapshot:
            profit_all_ratio = self._to_float(
                dry_run_snapshot.get("profit_summary", {}).get("profit_all_ratio")
            )
            total_equity = self._to_float(
                dry_run_snapshot.get("balance_summary", {}).get("total"),
                default=0.0,
            )
            open_trade_stakes = self._to_float(
                dry_run_snapshot.get("trade_count_summary", {}).get("total_open_trades_stakes")
            )
            open_trades = self._to_int(
                dry_run_snapshot.get("trade_count_summary", {}).get("current_open_trades")
            )
            max_open_trades = self._to_int(
                dry_run_snapshot.get("trade_count_summary", {}).get("max_open_trades")
            )
            exposure_ratio = (open_trade_stakes / total_equity) if total_equity > 0 else 0.0

            signals.extend(
                [
                    f"dry_run_profit_all_ratio={profit_all_ratio:.4f}",
                    f"open_trade_exposure_ratio={exposure_ratio:.4f}",
                    f"open_trades={open_trades}/{max_open_trades}",
                ]
            )

            if profit_all_ratio <= self.dry_run_fail_loss_ratio:
                status = self._merge_status(status, "fail")
                reasons.append("Dry run traci więcej niż bezpieczny limit obserwacyjny 5%.")
            elif profit_all_ratio < self.dry_run_warning_loss_ratio:
                status = self._merge_status(status, "warn")
                reasons.append("Dry run nadal pokazuje stratę, więc ryzyko nie jest jeszcze pod kontrolą.")

            if exposure_ratio >= self.fail_open_trade_exposure_ratio:
                status = self._merge_status(status, "fail")
                reasons.append("Otwarte pozycje zużywają niemal cały kapitał i zostawiają zbyt mały margines bezpieczeństwa.")
            elif exposure_ratio >= self.warning_open_trade_exposure_ratio:
                status = self._merge_status(status, "warn")
                reasons.append("Ekspozycja na otwartych pozycjach jest wysoka i wymaga twardszego zarządzania ryzykiem.")

            if max_open_trades > 0 and open_trades >= max_open_trades:
                status = self._merge_status(status, "warn")
                reasons.append("Dry run wykorzystuje pełny limit otwartych pozycji, więc selekcja wejść musi być ostrzejsza.")

        if not reasons:
            reasons.append("Ryzyko jest na dziś pod kontrolą w backteście i dry_run.")

        reason = reasons[0] if len(reasons) == 1 else " ".join(reasons)
        return {
            "status": status,
            "reason": reason,
            "signals": signals,
            "evidence": {
                "drawdown_pct": drawdown_pct,
                "assessment_risk_level": (strategy_assessment or {}).get("risk_level"),
            },
        }

    def evaluate_strategy_readiness(
        self,
        *,
        strategy_report: dict[str, Any] | None,
        dry_run_snapshot: dict[str, Any] | None,
        strategy_assessment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        backtest_gate = self._evaluate_backtest_gate(strategy_report)
        dry_run_gate = self._evaluate_dry_run_gate(dry_run_snapshot)
        risk_gate = self._evaluate_risk_gate(
            strategy_report,
            dry_run_snapshot,
            strategy_assessment,
        )

        statuses = {
            "backtest": backtest_gate["status"],
            "dry_run": dry_run_gate["status"],
            "risk": risk_gate["status"],
        }
        status_values = set(statuses.values())
        if "fail" in status_values:
            overall_status = "blocked"
            overall_decision = "improve_risk_before_promotion"
            summary = (
                "Strategia nie przechodzi jeszcze wspólnej bramki backtest + risk + dry_run. "
                "Najpierw trzeba poprawić jakość i ryzyko, a dopiero potem myśleć o promocji."
            )
        elif status_values == {"pass"}:
            overall_status = "ready_for_next_stage_review"
            overall_decision = "consider_promotion_after_human_review"
            summary = (
                "Strategia przechodzi wspólną bramkę jakości. Można rozważyć kolejny etap, "
                "ale nadal tylko po review człowieka."
            )
        else:
            overall_status = "iterate_in_dry_run"
            overall_decision = "continue_dry_run_iteration"
            summary = (
                "Strategia ma już część sygnałów jakości, ale wspólna bramka nadal każe uczyć się dalej na dry_run "
                "i poprawiać risk-adjusted wynik."
            )

        reasons = [
            backtest_gate["reason"],
            risk_gate["reason"],
            dry_run_gate["reason"],
        ]
        return {
            "overall_status": overall_status,
            "overall_decision": overall_decision,
            "summary": summary,
            "reasons": reasons,
            "gates": {
                "backtest": backtest_gate,
                "risk": risk_gate,
                "dry_run": dry_run_gate,
            },
            "evidence_sources": {
                "uses_backtest_report": bool(strategy_report),
                "uses_dry_run_snapshot": bool(dry_run_snapshot),
                "uses_strategy_assessment": bool(strategy_assessment),
            },
        }

    def build_regime_runtime_policy(
        self,
        *,
        regime_report: dict[str, Any] | None,
        selector_allowed: bool,
    ) -> dict[str, Any]:
        if not regime_report:
            return self._default_runtime_policy(selector_allowed=False)

        risk_decision = self.evaluate_risk(
            regime_report=regime_report,
            candidate_manifests=[],
            portfolio_state=None,
            bot_id="runtime_compat",
        )
        return self.build_candidate_runtime_policy(
            risk_decision=risk_decision,
            candidate_id=None,
            selector_allowed=selector_allowed,
        )

    def evaluate_risk(
        self,
        *,
        regime_report: dict[str, Any] | None,
        candidate_manifests: list[dict[str, Any]],
        portfolio_state: Any = None,
        bot_id: str = "runtime",
    ) -> dict[str, Any]:
        return self.engine.evaluate(
            regime_report=regime_report,
            candidate_manifests=candidate_manifests,
            portfolio_state=portfolio_state,
            bot_id=bot_id,
        )

    def latest_risk_decision(self, *, bot_id: str = "runtime") -> dict[str, Any] | None:
        return self.engine.latest_decision(bot_id=bot_id)

    def build_portfolio_state_from_snapshot(self, snapshot: dict[str, Any] | None) -> Any:
        return self.engine.build_portfolio_state(snapshot)

    def build_candidate_runtime_policy(
        self,
        *,
        risk_decision: dict[str, Any] | None,
        candidate_id: str | None,
        selector_allowed: bool,
    ) -> dict[str, Any]:
        if not risk_decision:
            return self._default_runtime_policy(selector_allowed=False)

        execution_constraints = {
            "no_trade_zone": risk_decision.get("trading_mode") == "blocked",
            "reduced_exposure_only": risk_decision.get("trading_mode") in {"capital_protection", "reduced_risk"},
            "high_noise_environment": rc_bool(risk_decision, "HIGH_NOISE_ENVIRONMENT"),
            "post_shock_cooldown": bool(risk_decision.get("cooldown_active")),
        }
        strategy_allowed = True
        if candidate_id:
            strategy_allowed = candidate_id in list(risk_decision.get("allowed_strategy_ids") or [])

        mode = str(risk_decision.get("trading_mode") or "blocked")
        max_position_size_pct = float(risk_decision.get("max_position_size_pct") or 0.0)
        size_multiplier = min(1.25, max(0.0, max_position_size_pct))
        entry_allowed = bool(
            selector_allowed
            and strategy_allowed
            and risk_decision.get("allow_trading", False)
            and risk_decision.get("new_entries_allowed", False)
            and not execution_constraints["no_trade_zone"]
        )

        if not entry_allowed:
            size_multiplier = 0.0

        return {
            "entry_allowed": entry_allowed,
            "risk_regime": str(risk_decision.get("risk_state") or "unknown"),
            "position_size_multiplier": round(max(0.0, size_multiplier), 4),
            "entry_aggressiveness": "blocked" if not entry_allowed else self._runtime_entry_aggressiveness(risk_decision),
            "execution_constraints": execution_constraints,
            "selector_allowed": selector_allowed,
            "strategy_allowed": strategy_allowed,
            "trading_mode": mode,
            "leverage_cap": float(risk_decision.get("leverage_cap") or 1.0),
            "force_reduce_only": bool(risk_decision.get("force_reduce_only")),
            "cooldown_active": bool(risk_decision.get("cooldown_active")),
            "max_total_exposure_pct": float(risk_decision.get("max_total_exposure_pct") or 0.0),
        }

    @staticmethod
    def _runtime_entry_aggressiveness(risk_decision: dict[str, Any]) -> str:
        if bool((risk_decision.get("protective_overrides") or {}).get("disable_aggressive_entries")):
            mode = str(risk_decision.get("trading_mode") or "blocked")
            if mode in {"blocked", "capital_protection"}:
                return "blocked" if mode == "blocked" else "low"
            return "moderate"
        mode = str(risk_decision.get("trading_mode") or "blocked")
        return {
            "blocked": "blocked",
            "capital_protection": "low",
            "reduced_risk": "moderate",
            "normal": "moderate",
            "selective_offense": "high",
        }.get(mode, "blocked")

    def _default_runtime_policy(self, *, selector_allowed: bool) -> dict[str, Any]:
        return {
            "entry_allowed": False,
            "risk_regime": "unknown",
            "position_size_multiplier": 0.0,
            "entry_aggressiveness": "blocked",
            "execution_constraints": {
                "no_trade_zone": True,
                "reduced_exposure_only": True,
                "high_noise_environment": True,
                "post_shock_cooldown": False,
            },
            "selector_allowed": selector_allowed,
            "strategy_allowed": False,
            "trading_mode": "blocked",
            "leverage_cap": 1.0,
            "force_reduce_only": True,
            "cooldown_active": False,
            "max_total_exposure_pct": 0.0,
        }


def rc_bool(risk_decision: dict[str, Any], code: str) -> bool:
    return code in list(risk_decision.get("risk_reason_codes") or [])
