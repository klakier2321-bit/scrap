from __future__ import annotations

import unittest

from core.risk_manager import RiskManager


class RiskManagerStrategyReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = RiskManager()

    def test_strategy_readiness_blocks_rejected_backtest_and_negative_dry_run(self) -> None:
        strategy_report = {
            "strategy_name": "SampleStrategy",
            "evaluation_status": "rejected",
            "rejection_reasons": [
                "Profit strategy is not positive.",
                "Drawdown exceeds the rejection threshold of 5%.",
            ],
            "stage_candidate": False,
            "profit_pct": -0.006,
            "drawdown_pct": 0.067,
            "total_trades": 27,
            "win_rate": 0.85,
            "stability_score": 0.41,
        }
        dry_run_snapshot = {
            "dry_run": True,
            "runmode": "dry_run",
            "snapshot_status": "ok",
            "profit_summary": {
                "trade_count": 3,
                "profit_all_ratio": -0.046,
            },
            "trade_count_summary": {
                "current_open_trades": 3,
                "max_open_trades": 3,
                "total_open_trades_stakes": 963.0,
            },
            "balance_summary": {
                "total": 956.0,
            },
            "open_trades_count": 3,
        }
        assessment = {"risk_level": "medium"}

        gate = self.manager.evaluate_strategy_readiness(
            strategy_report=strategy_report,
            dry_run_snapshot=dry_run_snapshot,
            strategy_assessment=assessment,
        )

        self.assertEqual(gate["overall_status"], "blocked")
        self.assertEqual(gate["overall_decision"], "improve_risk_before_promotion")
        self.assertEqual(gate["gates"]["backtest"]["status"], "fail")
        self.assertEqual(gate["gates"]["risk"]["status"], "fail")
        self.assertEqual(gate["gates"]["dry_run"]["status"], "warn")

    def test_strategy_readiness_can_mark_next_stage_review_when_all_signals_pass(self) -> None:
        strategy_report = {
            "strategy_name": "StableStrategy",
            "evaluation_status": "candidate_for_next_stage",
            "rejection_reasons": [],
            "stage_candidate": True,
            "profit_pct": 0.021,
            "drawdown_pct": 0.018,
            "total_trades": 45,
            "win_rate": 0.58,
            "stability_score": 0.72,
        }
        dry_run_snapshot = {
            "dry_run": True,
            "runmode": "dry_run",
            "snapshot_status": "ok",
            "profit_summary": {
                "trade_count": 12,
                "profit_all_ratio": 0.014,
            },
            "trade_count_summary": {
                "current_open_trades": 1,
                "max_open_trades": 3,
                "total_open_trades_stakes": 150.0,
            },
            "balance_summary": {
                "total": 1000.0,
            },
            "open_trades_count": 1,
        }
        assessment = {"risk_level": "low"}

        gate = self.manager.evaluate_strategy_readiness(
            strategy_report=strategy_report,
            dry_run_snapshot=dry_run_snapshot,
            strategy_assessment=assessment,
        )

        self.assertEqual(gate["overall_status"], "ready_for_next_stage_review")
        self.assertEqual(
            gate["overall_decision"],
            "consider_promotion_after_human_review",
        )
        self.assertEqual(gate["gates"]["backtest"]["status"], "pass")
        self.assertEqual(gate["gates"]["risk"]["status"], "pass")
        self.assertEqual(gate["gates"]["dry_run"]["status"], "pass")

    def test_build_regime_runtime_policy_blocks_when_selector_disallows_candidate(self) -> None:
        policy = self.manager.build_regime_runtime_policy(
            regime_report={
                "risk_regime": "elevated",
                "position_size_multiplier": 0.64,
                "entry_aggressiveness": "moderate",
                "execution_constraints": {
                    "no_trade_zone": False,
                    "reduced_exposure_only": True,
                    "high_noise_environment": False,
                    "post_shock_cooldown": False,
                },
            },
            selector_allowed=False,
        )
        self.assertFalse(policy["entry_allowed"])
        self.assertEqual(policy["position_size_multiplier"], 0.0)

    def test_build_regime_runtime_policy_respects_no_trade_zone(self) -> None:
        policy = self.manager.build_regime_runtime_policy(
            regime_report={
                "risk_level": "high",
                "position_size_multiplier": 0.42,
                "entry_aggressiveness": "low",
                "execution_constraints": {
                    "no_trade_zone": True,
                    "reduced_exposure_only": True,
                    "high_noise_environment": True,
                    "post_shock_cooldown": False,
                },
            },
            selector_allowed=True,
        )
        self.assertFalse(policy["entry_allowed"])
        self.assertEqual(policy["risk_regime"], "high")
