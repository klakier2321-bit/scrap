from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.risk_manager import RiskManager


class RiskManagerStrategyReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.manager = RiskManager(risk_output_dir=Path(self.tmpdir.name))

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

    def test_evaluate_risk_reduced_risk_short_only_in_bearish_market(self) -> None:
        decision = self.manager.evaluate_risk(
            regime_report={
                "primary_regime": "trend_down",
                "confidence": 0.74,
                "risk_level": "medium",
                "risk_regime": "elevated",
                "regime_quality": 0.58,
                "htf_bias": "short",
                "market_state": "trend",
                "market_phase": "pullback",
                "volatility_phase": "expanding",
                "execution_constraints": {
                    "no_trade_zone": False,
                    "reduced_exposure_only": True,
                    "high_noise_environment": False,
                    "post_shock_cooldown": False,
                },
                "position_size_multiplier": 0.8,
                "entry_aggressiveness": "moderate",
                "market_consensus": "strong_bearish",
                "consensus_strength": 0.78,
                "eligible_candidate_ids": ["short_candidate", "baseline_candidate"],
                "blocked_candidate_ids": [],
                "active_event_flags": {},
                "actionable_event_flags": {},
                "active_event_flags_reliability": "medium",
                "derivatives_state": {
                    "feed_status": "ok",
                    "source": "binance_futures_public_api",
                    "vendor_available": True,
                    "event_reliability": "medium",
                    "liquidation_event_confidence": "medium",
                    "age_seconds": 120,
                    "is_stale": False,
                    "squeeze_risk": "low",
                    "positioning_state": "short_build",
                    "oi_price_agreement": "short_build",
                },
            },
            candidate_manifests=[
                {
                    "strategy_id": "short_candidate",
                    "strategy_family": "breakout",
                    "risk_profile": "balanced",
                    "allowed_sides": "short",
                },
                {
                    "strategy_id": "baseline_candidate",
                    "strategy_family": "pullback_trend",
                    "risk_profile": "balanced",
                    "allowed_sides": "both",
                },
            ],
            portfolio_state=None,
            bot_id="test_bot",
        )

        self.assertEqual(decision["trading_mode"], "reduced_risk")
        self.assertEqual(decision["allowed_directions"], ["short"])
        self.assertIn("long", decision["blocked_directions"])
        self.assertGreater(decision["max_total_exposure_pct"], 0.0)
        self.assertLessEqual(decision["leverage_cap"], 2.0)
        self.assertIn("short_candidate", decision["allowed_strategy_ids"])
        self.assertFalse(decision["force_reduce_only"])

    def test_evaluate_risk_blocks_no_trade_zone(self) -> None:
        decision = self.manager.evaluate_risk(
            regime_report={
                "primary_regime": "low_vol",
                "confidence": 0.91,
                "risk_level": "low",
                "risk_regime": "normal",
                "regime_quality": 0.80,
                "htf_bias": "neutral",
                "market_state": "range",
                "market_phase": "compression",
                "volatility_phase": "compression",
                "execution_constraints": {
                    "no_trade_zone": True,
                    "reduced_exposure_only": True,
                    "high_noise_environment": True,
                    "post_shock_cooldown": False,
                },
                "position_size_multiplier": 0.1,
                "entry_aggressiveness": "low",
                "market_consensus": "neutral",
                "consensus_strength": 0.2,
                "eligible_candidate_ids": ["candidate_v1"],
                "blocked_candidate_ids": [],
                "active_event_flags": {},
                "actionable_event_flags": {},
                "active_event_flags_reliability": "low",
                "derivatives_state": {
                    "feed_status": "ok",
                    "source": "binance_futures_public_api",
                    "vendor_available": True,
                    "event_reliability": "medium",
                    "liquidation_event_confidence": "medium",
                    "age_seconds": 45,
                    "is_stale": False,
                },
            },
            candidate_manifests=[
                {
                    "strategy_id": "candidate_v1",
                    "strategy_family": "mean_reversion",
                    "risk_profile": "balanced",
                    "allowed_sides": "both",
                }
            ],
        )
        self.assertFalse(decision["allow_trading"])
        self.assertEqual(decision["trading_mode"], "blocked")
        self.assertTrue(decision["force_reduce_only"])
        self.assertIn("NO_TRADE_ZONE_HARD_BLOCK", decision["risk_reason_codes"])

    def test_evaluate_risk_degrades_on_stale_feed(self) -> None:
        decision = self.manager.evaluate_risk(
            regime_report={
                "primary_regime": "trend_up",
                "confidence": 0.80,
                "risk_level": "low",
                "risk_regime": "normal",
                "regime_quality": 0.82,
                "htf_bias": "long",
                "market_state": "trend",
                "market_phase": "mature_trend",
                "volatility_phase": "cooling",
                "execution_constraints": {
                    "no_trade_zone": False,
                    "reduced_exposure_only": False,
                    "high_noise_environment": False,
                    "post_shock_cooldown": False,
                },
                "position_size_multiplier": 1.0,
                "entry_aggressiveness": "high",
                "market_consensus": "strong_bullish",
                "consensus_strength": 0.82,
                "eligible_candidate_ids": ["candidate_v1"],
                "blocked_candidate_ids": [],
                "active_event_flags": {},
                "actionable_event_flags": {},
                "active_event_flags_reliability": "low",
                "derivatives_state": {
                    "feed_status": "ok",
                    "source": "binance_futures_public_api",
                    "vendor_available": True,
                    "event_reliability": "low",
                    "liquidation_event_confidence": "low",
                    "age_seconds": 1300,
                    "is_stale": True,
                },
            },
            candidate_manifests=[
                {
                    "strategy_id": "candidate_v1",
                    "strategy_family": "trend_continuation",
                    "risk_profile": "balanced",
                    "allowed_sides": "long",
                }
            ],
        )
        self.assertIn(decision["data_trust_level"], {"low_trust", "limited_trust"})
        self.assertTrue(decision["degradation_flags"]["stale_feed"])
        self.assertLessEqual(decision["leverage_cap"], 2.0)
        self.assertIn("STALE_DERIVATIVES_FEED", decision["risk_reason_codes"])

    def test_evaluate_risk_uses_portfolio_overlay(self) -> None:
        portfolio_state = self.manager.build_portfolio_state_from_snapshot(
            {
                "bot_id": "freqtrade_candidate",
                "balance_summary": {"total": 1000.0},
                "trade_count_summary": {
                    "current_open_trades": 2,
                    "max_open_trades": 2,
                    "total_open_trades_stakes": 300.0,
                },
                "open_trades_count": 2,
                "open_trades": [
                    {"pair": "BTC/USDT:USDT", "side": "long", "stake_amount": 150.0},
                    {"pair": "ETH/USDT:USDT", "side": "long", "stake_amount": 150.0},
                ],
            }
        )
        decision = self.manager.evaluate_risk(
            regime_report={
                "primary_regime": "trend_up",
                "confidence": 0.79,
                "risk_level": "low",
                "risk_regime": "normal",
                "regime_quality": 0.77,
                "htf_bias": "long",
                "market_state": "trend",
                "market_phase": "pullback",
                "volatility_phase": "cooling",
                "execution_constraints": {
                    "no_trade_zone": False,
                    "reduced_exposure_only": False,
                    "high_noise_environment": False,
                    "post_shock_cooldown": False,
                },
                "position_size_multiplier": 1.0,
                "entry_aggressiveness": "moderate",
                "market_consensus": "strong_bullish",
                "consensus_strength": 0.81,
                "eligible_candidate_ids": ["candidate_v1"],
                "blocked_candidate_ids": [],
                "active_event_flags": {},
                "actionable_event_flags": {},
                "active_event_flags_reliability": "medium",
                "derivatives_state": {
                    "feed_status": "ok",
                    "source": "binance_futures_public_api",
                    "vendor_available": True,
                    "event_reliability": "medium",
                    "liquidation_event_confidence": "medium",
                    "age_seconds": 60,
                    "is_stale": False,
                },
            },
            candidate_manifests=[
                {
                    "strategy_id": "candidate_v1",
                    "strategy_family": "pullback_trend",
                    "risk_profile": "balanced",
                    "allowed_sides": "long",
                }
            ],
            portfolio_state=portfolio_state,
        )
        self.assertEqual(decision["max_position_size_pct"], 0.0)
        self.assertIn(
            "PORTFOLIO_POSITION_LIMIT_REACHED",
            decision["risk_reason_codes"],
        )

    def test_evaluate_risk_treats_replay_proxy_as_limited_trust(self) -> None:
        decision = self.manager.evaluate_risk(
            regime_report={
                "primary_regime": "trend_up",
                "confidence": 0.78,
                "risk_level": "low",
                "risk_regime": "normal",
                "regime_quality": 0.74,
                "htf_bias": "long",
                "market_state": "trend",
                "market_phase": "pullback",
                "volatility_phase": "cooling",
                "execution_constraints": {
                    "no_trade_zone": False,
                    "reduced_exposure_only": False,
                    "high_noise_environment": False,
                    "post_shock_cooldown": False,
                },
                "position_size_multiplier": 1.0,
                "entry_aggressiveness": "moderate",
                "market_consensus": "strong_bullish",
                "consensus_strength": 0.72,
                "eligible_candidate_ids": ["candidate_v1"],
                "blocked_candidate_ids": [],
                "active_event_flags": {},
                "actionable_event_flags": {},
                "active_event_flags_reliability": "low",
                "derivatives_state": {
                    "feed_status": "replay_proxy",
                    "source": "replay_proxy",
                    "vendor_available": False,
                    "event_reliability": "low",
                    "liquidation_event_confidence": "low",
                    "age_seconds": 0,
                    "is_stale": False,
                    "squeeze_risk": "low",
                    "positioning_state": "long_build",
                    "oi_price_agreement": "long_build",
                },
            },
            candidate_manifests=[
                {
                    "strategy_id": "candidate_v1",
                    "strategy_family": "pullback_trend",
                    "risk_profile": "balanced",
                    "allowed_sides": "long",
                }
            ],
            portfolio_state=None,
        )

        self.assertEqual(decision["data_trust_level"], "limited_trust")
        self.assertEqual(decision["data_validation_status"], "valid_with_degradation")
        self.assertIn("LOW_EVENT_RELIABILITY", decision["risk_reason_codes"])

    def test_build_candidate_runtime_policy_blocks_strategy_filtered_by_risk_engine(self) -> None:
        policy = self.manager.build_candidate_runtime_policy(
            risk_decision={
                "allow_trading": True,
                "new_entries_allowed": True,
                "trading_mode": "normal",
                "risk_state": "normal",
                "allowed_strategy_ids": ["candidate_a"],
                "risk_reason_codes": [],
                "protective_overrides": {"disable_aggressive_entries": False},
                "max_position_size_pct": 1.0,
                "leverage_cap": 3.0,
                "cooldown_active": False,
            },
            candidate_id="candidate_b",
            selector_allowed=True,
        )
        self.assertFalse(policy["entry_allowed"])
        self.assertFalse(policy["strategy_allowed"])
