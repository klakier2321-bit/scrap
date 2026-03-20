from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.risk_manager import RiskManager


BASE_CANDIDATES = [
    {
        "strategy_id": "trend_long",
        "strategy_family": "trend_continuation",
        "risk_profile": "balanced",
        "allowed_sides": "long",
    },
    {
        "strategy_id": "pullback_short",
        "strategy_family": "pullback_trend",
        "risk_profile": "balanced",
        "allowed_sides": "short",
    },
    {
        "strategy_id": "breakout_short",
        "strategy_family": "breakout",
        "risk_profile": "aggressive",
        "allowed_sides": "short",
    },
    {
        "strategy_id": "mean_revert",
        "strategy_family": "mean_reversion",
        "risk_profile": "balanced",
        "allowed_sides": "both",
    },
    {
        "strategy_id": "panic_reversal",
        "strategy_family": "panic_reversal",
        "risk_profile": "defensive",
        "allowed_sides": "both",
    },
    {
        "strategy_id": "defense_only",
        "strategy_family": "defense_only",
        "risk_profile": "defensive",
        "allowed_sides": "both",
    },
]


def _base_derivatives() -> dict:
    return {
        "feed_status": "ok",
        "source": "binance_futures_public_api",
        "vendor_available": True,
        "event_reliability": "medium",
        "liquidation_event_confidence": "medium",
        "age_seconds": 60,
        "is_stale": False,
        "squeeze_risk": "low",
        "positioning_state": "neutral",
        "oi_price_agreement": "neutral",
    }


def _base_regime() -> dict:
    return {
        "primary_regime": "trend_up",
        "confidence": 0.8,
        "risk_level": "low",
        "risk_regime": "normal",
        "regime_quality": 0.8,
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
        "consensus_strength": 0.8,
        "eligible_candidate_ids": [item["strategy_id"] for item in BASE_CANDIDATES],
        "blocked_candidate_ids": [],
        "active_event_flags": {},
        "actionable_event_flags": {},
        "active_event_flags_reliability": "medium",
        "derivatives_state": _base_derivatives(),
        "btc_state": {"primary_regime": "trend_up", "bias": "long"},
        "eth_state": {"primary_regime": "trend_up", "bias": "long"},
    }


class RiskEngineScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.manager = RiskManager(risk_output_dir=Path(self.tmpdir.name))

    def _decision(self, regime_report: dict, portfolio_state=None) -> dict:
        return self.manager.evaluate_risk(
            regime_report=regime_report,
            candidate_manifests=BASE_CANDIDATES,
            portfolio_state=portfolio_state,
            bot_id="scenario_bot",
        )

    def test_scenario_matrix(self) -> None:
        portfolio_full = self.manager.build_portfolio_state_from_snapshot(
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
        portfolio_corr = self.manager.build_portfolio_state_from_snapshot(
            {
                "bot_id": "freqtrade_candidate",
                "balance_summary": {"total": 1000.0},
                "trade_count_summary": {
                    "current_open_trades": 2,
                    "max_open_trades": 4,
                    "total_open_trades_stakes": 180.0,
                },
                "open_trades_count": 2,
                "open_trades": [
                    {"pair": "BTC/USDT:USDT", "side": "short", "stake_amount": 90.0},
                    {"pair": "BTC/USDC:USDC", "side": "short", "stake_amount": 90.0},
                ],
            }
        )
        cases = [
            {
                "name": "trend_down_elevated_risk",
                "patch": {
                    "primary_regime": "trend_down",
                    "risk_regime": "elevated",
                    "htf_bias": "short",
                    "market_consensus": "strong_bearish",
                    "consensus_strength": 0.78,
                    "execution_constraints": {
                        "no_trade_zone": False,
                        "reduced_exposure_only": True,
                        "high_noise_environment": False,
                        "post_shock_cooldown": False,
                    },
                    "eligible_candidate_ids": ["pullback_short", "breakout_short"],
                    "btc_state": {"primary_regime": "trend_down", "bias": "short"},
                    "eth_state": {"primary_regime": "trend_down", "bias": "short"},
                },
                "expected_mode": "reduced_risk",
                "allowed_direction": "short",
                "reason_code": "RISK_ELEVATED",
            },
            {
                "name": "trend_up_full_trust",
                "patch": {},
                "expected_mode": "selective_offense",
                "allowed_direction": "long",
                "reason_code": None,
            },
            {
                "name": "stress_panic_actionable_capitulation",
                "patch": {
                    "primary_regime": "stress_panic",
                    "risk_regime": "high",
                    "regime_quality": 0.65,
                    "actionable_event_flags": {"capitulation": True},
                    "active_event_flags_reliability": "high",
                },
                "expected_mode": "capital_protection",
                "allowed_direction": None,
                "reason_code": "ACTIONABLE_CAPITULATION",
            },
            {
                "name": "stress_panic_soft_event_only",
                "patch": {
                    "primary_regime": "stress_panic",
                    "risk_regime": "high",
                    "regime_quality": 0.65,
                    "actionable_event_flags": {"capitulation": True},
                    "active_event_flags_reliability": "low",
                    "derivatives_state": {
                        **_base_derivatives(),
                        "event_reliability": "low",
                    },
                },
                "expected_mode": "capital_protection",
                "allowed_direction": "long",
                "reason_code": "LOW_EVENT_RELIABILITY",
            },
            {
                "name": "range_low_consensus",
                "patch": {
                    "primary_regime": "range",
                    "market_state": "range",
                    "market_phase": "compression",
                    "market_consensus": "mixed",
                    "consensus_strength": 0.3,
                    "regime_quality": 0.52,
                },
                "expected_mode": "reduced_risk",
                "allowed_direction": None,
                "reason_code": "WEAK_MARKET_CONSENSUS",
            },
            {
                "name": "low_vol_no_trade_zone",
                "patch": {
                    "primary_regime": "low_vol",
                    "market_state": "range",
                    "execution_constraints": {
                        "no_trade_zone": True,
                        "reduced_exposure_only": True,
                        "high_noise_environment": True,
                        "post_shock_cooldown": False,
                    },
                    "market_consensus": "neutral",
                    "consensus_strength": 0.2,
                },
                "expected_mode": "blocked",
                "allowed_direction": None,
                "reason_code": "NO_TRADE_ZONE_HARD_BLOCK",
            },
            {
                "name": "stale_feed_bullish",
                "patch": {
                    "derivatives_state": {
                        **_base_derivatives(),
                        "age_seconds": 1300,
                        "is_stale": True,
                        "event_reliability": "low",
                    },
                },
                "expected_mode": "reduced_risk",
                "allowed_direction": "long",
                "reason_code": "STALE_DERIVATIVES_FEED",
            },
            {
                "name": "broken_feed",
                "patch": {
                    "derivatives_state": {
                        **_base_derivatives(),
                        "feed_status": "error",
                        "vendor_available": False,
                        "age_seconds": 2200,
                    },
                },
                "expected_mode": "blocked",
                "allowed_direction": None,
                "reason_code": "DATA_FEED_BROKEN",
            },
            {
                "name": "high_vol_short_squeeze_actionable",
                "patch": {
                    "primary_regime": "high_vol",
                    "risk_regime": "elevated",
                    "htf_bias": "short",
                    "market_consensus": "strong_bearish",
                    "consensus_strength": 0.76,
                    "actionable_event_flags": {"short_squeeze": True},
                    "derivatives_state": {
                        **_base_derivatives(),
                        "squeeze_risk": "high",
                        "positioning_state": "short_build",
                        "oi_price_agreement": "short_build",
                    },
                },
                "expected_mode": "reduced_risk",
                "allowed_direction": None,
                "reason_code": "SHORT_SQUEEZE_RISK",
            },
            {
                "name": "high_vol_short_squeeze_soft_only",
                "patch": {
                    "primary_regime": "high_vol",
                    "risk_regime": "elevated",
                    "htf_bias": "short",
                    "actionable_event_flags": {"short_squeeze": True},
                    "active_event_flags_reliability": "low",
                    "derivatives_state": {
                        **_base_derivatives(),
                        "event_reliability": "low",
                    },
                },
                "expected_mode": "reduced_risk",
                "allowed_direction": None,
                "reason_code": "LOW_EVENT_RELIABILITY",
            },
            {
                "name": "mixed_consensus_btc_leads_bearish",
                "patch": {
                    "primary_regime": "trend_down",
                    "htf_bias": "short",
                    "market_consensus": "mixed",
                    "consensus_strength": 0.45,
                    "btc_state": {"primary_regime": "trend_down", "bias": "short"},
                    "eth_state": {"primary_regime": "range", "bias": "neutral"},
                },
                "expected_mode": "normal",
                "allowed_direction": None,
                "reason_code": None,
            },
            {
                "name": "post_shock_cooldown",
                "patch": {
                    "execution_constraints": {
                        "no_trade_zone": False,
                        "reduced_exposure_only": True,
                        "high_noise_environment": True,
                        "post_shock_cooldown": True,
                    },
                    "active_event_flags_reliability": "high",
                },
                "expected_mode": "capital_protection",
                "allowed_direction": "long",
                "reason_code": "POST_SHOCK_COOLDOWN",
            },
            {
                "name": "portfolio_full",
                "patch": {},
                "portfolio_state": portfolio_full,
                "expected_mode": "selective_offense",
                "allowed_direction": "long",
                "reason_code": "PORTFOLIO_POSITION_LIMIT_REACHED",
            },
            {
                "name": "portfolio_correlated_positions_full",
                "patch": {
                    "primary_regime": "trend_down",
                    "risk_regime": "elevated",
                    "htf_bias": "short",
                    "market_consensus": "strong_bearish",
                    "consensus_strength": 0.78,
                    "execution_constraints": {
                        "no_trade_zone": False,
                        "reduced_exposure_only": True,
                        "high_noise_environment": False,
                        "post_shock_cooldown": False,
                    },
                    "eligible_candidate_ids": ["pullback_short"],
                },
                "portfolio_state": portfolio_corr,
                "expected_mode": "reduced_risk",
                "allowed_direction": "short",
                "reason_code": "PORTFOLIO_CORRELATION_CAP_REACHED",
            },
            {
                "name": "panic_reversal_only",
                "patch": {
                    "primary_regime": "stress_panic",
                    "risk_regime": "high",
                    "regime_quality": 0.7,
                    "actionable_event_flags": {"panic_flush": True},
                    "active_event_flags": {"panic_flush": True},
                    "active_event_flags_reliability": "high",
                },
                "expected_mode": "capital_protection",
                "allowed_direction": None,
                "reason_code": "ACTIONABLE_PANIC_FLUSH",
            },
            {
                "name": "mean_reversion_allowed_in_range",
                "patch": {
                    "primary_regime": "range",
                    "risk_regime": "normal",
                    "regime_quality": 0.65,
                    "market_state": "range",
                    "market_phase": "transition",
                    "market_consensus": "neutral",
                    "consensus_strength": 0.6,
                    "eligible_candidate_ids": ["mean_revert"],
                },
                "expected_mode": "normal",
                "allowed_direction": None,
                "reason_code": None,
            },
            {
                "name": "aggressive_strategy_blocked_in_reduced_risk",
                "patch": {
                    "primary_regime": "trend_down",
                    "risk_regime": "elevated",
                    "htf_bias": "short",
                    "market_consensus": "strong_bearish",
                    "consensus_strength": 0.72,
                    "eligible_candidate_ids": ["breakout_short", "pullback_short"],
                    "execution_constraints": {
                        "no_trade_zone": False,
                        "reduced_exposure_only": True,
                        "high_noise_environment": False,
                        "post_shock_cooldown": False,
                    },
                },
                "expected_mode": "reduced_risk",
                "allowed_direction": "short",
                "reason_code": "STRATEGY_BLOCKED_BY_RISK_PROFILE",
                "blocked_strategy_id": "breakout_short",
            },
            {
                "name": "breakout_blocked_in_compression",
                "patch": {
                    "primary_regime": "trend_down",
                    "htf_bias": "short",
                    "market_phase": "compression",
                    "eligible_candidate_ids": ["breakout_short", "pullback_short"],
                    "market_consensus": "strong_bearish",
                    "consensus_strength": 0.8,
                },
                "expected_mode": "selective_offense",
                "allowed_direction": "short",
                "reason_code": "STRATEGY_BLOCKED_BY_FAMILY",
                "blocked_strategy_id": "breakout_short",
            },
            {
                "name": "mean_reversion_blocked_in_trend",
                "patch": {
                    "primary_regime": "trend_up",
                    "market_state": "trend",
                    "eligible_candidate_ids": ["mean_revert"],
                },
                "expected_mode": "selective_offense",
                "allowed_direction": "long",
                "reason_code": "STRATEGY_BLOCKED_BY_FAMILY",
                "blocked_strategy_id": "mean_revert",
            },
            {
                "name": "force_reduce_only_active",
                "patch": {
                    "primary_regime": "stress_panic",
                    "risk_regime": "high",
                    "regime_quality": 0.7,
                    "actionable_event_flags": {"deleveraging": True},
                    "active_event_flags_reliability": "high",
                },
                "expected_mode": "capital_protection",
                "allowed_direction": None,
                "reason_code": "FORCE_REDUCE_ONLY",
                "force_reduce_only": True,
            },
            {
                "name": "tighter_risk_budget_active",
                "patch": {
                    "primary_regime": "trend_down",
                    "risk_regime": "elevated",
                    "htf_bias": "short",
                    "market_consensus": "strong_bearish",
                    "consensus_strength": 0.8,
                    "execution_constraints": {
                        "no_trade_zone": False,
                        "reduced_exposure_only": True,
                        "high_noise_environment": False,
                        "post_shock_cooldown": False,
                    },
                },
                "expected_mode": "reduced_risk",
                "allowed_direction": "short",
                "reason_code": "REDUCED_EXPOSURE_ONLY",
                "execution_budget_multiplier": 0.5,
            },
            {
                "name": "disable_aggressive_entries_active",
                "patch": {
                    "primary_regime": "trend_down",
                    "risk_regime": "elevated",
                    "htf_bias": "short",
                    "market_consensus": "strong_bearish",
                    "consensus_strength": 0.8,
                },
                "expected_mode": "reduced_risk",
                "allowed_direction": "short",
                "reason_code": "RISK_ELEVATED",
                "disable_aggressive_entries": True,
            },
        ]

        for case in cases:
            with self.subTest(case["name"]):
                regime = _base_regime()
                regime.update(case["patch"])
                decision = self._decision(regime, portfolio_state=case.get("portfolio_state"))
                self.assertEqual(decision["trading_mode"], case["expected_mode"])
                if case["allowed_direction"] is not None:
                    self.assertIn(case["allowed_direction"], decision["allowed_directions"])
                if case["reason_code"] is not None:
                    self.assertIn(case["reason_code"], decision["risk_reason_codes"])
                if case.get("blocked_strategy_id") is not None:
                    self.assertIn(case["blocked_strategy_id"], decision["blocked_strategy_ids"])
                if case.get("force_reduce_only") is not None:
                    self.assertEqual(decision["force_reduce_only"], case["force_reduce_only"])
                if case.get("execution_budget_multiplier") is not None:
                    self.assertEqual(decision["execution_budget_multiplier"], case["execution_budget_multiplier"])
                if case.get("disable_aggressive_entries") is not None:
                    self.assertEqual(
                        bool((decision.get("protective_overrides") or {}).get("disable_aggressive_entries")),
                        case["disable_aggressive_entries"],
                    )
