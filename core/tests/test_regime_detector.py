from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.regime_detector import PRIMARY_REGIMES, RegimeDetector


def _definition() -> dict[str, object]:
    return {
        "asof_timeframe": "1h",
        "htf_timeframe": "1h",
        "ltf_timeframe": "5m",
        "freeze_build_mode": "freeze_build_keep_dry_run",
        "universe": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        "thresholds": {
            "score_normalization_max": 6.5,
            "smoothing_alpha": 0.45,
            "enter_score_threshold": 0.75,
            "exit_score_threshold": 0.55,
            "min_bars_in_regime": 3,
            "switch_cooldown_bars": 2,
            "mature_regime_bars": 6,
            "bar_minutes": 5,
            "trend_spread_min_pct": 0.12,
            "slope_min_pct": 0.08,
            "adx_trend_min": 22.0,
            "adx_range_max": 18.0,
            "range_spread_max_pct": 0.08,
            "htf_bias_spread_min_pct": 0.10,
            "htf_bias_slope_min_pct": 0.06,
            "ltf_transition_spread_max_pct": 0.03,
            "pullback_distance_min_pct": 0.05,
            "late_move_abs_pct": 0.9,
            "noise_adx_max": 16.0,
            "low_volatility_ratio_max": 0.85,
            "compression_volatility_ratio_max": 0.90,
            "compression_std_ratio_max": 0.95,
            "compression_recent_move_abs_pct_max": 0.45,
            "compression_volume_spike_max": 1.55,
            "compression_range_spread_max_pct": 0.18,
            "high_volatility_ratio_min": 1.2,
            "expansion_volatility_ratio_min": 1.15,
            "cooling_volatility_ratio_max": 1.05,
            "extreme_volatility_ratio_min": 1.8,
            "stress_volatility_ratio_min": 1.8,
            "high_std_ratio_min": 1.15,
            "low_candle_spread_max": 0.003,
            "low_volume_spike_max": 1.0,
            "volume_spike_high": 1.25,
            "stress_volume_spike_min": 1.8,
            "stress_move_abs_pct_min": 1.6,
            "squeeze_move_abs_pct_min": 1.2,
            "funding_elevated_bps": 4.0,
            "funding_extreme_bps": 8.0,
        },
    }


def _base_snapshot() -> dict[str, object]:
    return {
        "trend_spread_pct": 0.0,
        "slope_pct": 0.0,
        "adx": 15.0,
        "volatility_ratio": 1.0,
        "std_ratio": 1.0,
        "candle_spread_ratio": 0.003,
        "volume_spike": 1.0,
        "recent_move_pct": 0.1,
        "recent_move_abs_pct": 0.1,
        "funding_abs_bps": None,
        "funding_mean_bps": 0.0,
        "ltf_trend_spread_pct": 0.0,
        "ltf_slope_pct": 0.0,
        "pullback_distance_pct": 0.0,
        "trend_strength": 0.4,
        "volatility_level": "normal",
        "volume_state": "normal",
        "derivatives_state": {
            "feed_status": "unavailable",
            "source": "funding_only",
            "vendor_available": False,
            "vendor_name": None,
            "fetch_errors": [],
            "fetched_at": None,
            "source_timestamp": None,
            "age_seconds": None,
            "is_stale": False,
            "event_reliability": "low",
            "positioning_state": "unknown",
            "squeeze_risk": "unknown",
            "oi_price_agreement": "unknown",
            "open_interest_change_pct": None,
            "oi_acceleration": None,
            "funding_extreme_flag": False,
            "liquidation_pressure_proxy": 0.0,
            "liquidation_source_type": "proxy_from_local_market_data",
            "liquidation_event_confidence": "low",
            "symbols": [],
        },
        "symbols": [],
    }


class RegimeDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        repo_root = Path(self.tempdir.name)
        self.detector = RegimeDetector(
            user_data_dir=repo_root / "trading" / "freqtrade" / "user_data",
            output_dir=repo_root / "data" / "ai_control" / "regime",
            replay_dir=repo_root / "data" / "ai_control" / "regime_replay",
            research_dir=repo_root / "research",
        )
        self.definition = _definition()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_primary_regimes_set_is_stable(self) -> None:
        self.assertEqual(
            PRIMARY_REGIMES,
            (
                "trend_up",
                "trend_down",
                "range",
                "low_vol",
                "high_vol",
                "stress_panic",
            ),
        )

    def test_classifies_trend_up(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "trend_spread_pct": 0.35,
            "slope_pct": 0.22,
            "adx": 31.0,
        }
        result = self.detector._classify(snapshot, self.definition)
        self.assertEqual(result["primary_regime"], "trend_up")
        self.assertEqual(result["risk_level"], "low")
        self.assertGreater(result["confidence"], 0.5)

    def test_classifies_trend_down(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "trend_spread_pct": -0.31,
            "slope_pct": -0.19,
            "adx": 29.0,
        }
        result = self.detector._classify(snapshot, self.definition)
        self.assertEqual(result["primary_regime"], "trend_down")
        self.assertEqual(result["risk_level"], "medium")

    def test_classifies_range(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "trend_spread_pct": 0.03,
            "slope_pct": 0.01,
            "adx": 11.0,
            "volume_spike": 1.0,
        }
        result = self.detector._classify(snapshot, self.definition)
        self.assertEqual(result["primary_regime"], "range")

    def test_classifies_low_vol(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "volatility_ratio": 0.72,
            "candle_spread_ratio": 0.0017,
            "volume_spike": 0.74,
        }
        result = self.detector._classify(snapshot, self.definition)
        self.assertEqual(result["primary_regime"], "low_vol")

    def test_compression_can_outweigh_stale_trend_signal(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "trend_spread_pct": -0.22,
            "slope_pct": -0.12,
            "adx": 25.0,
            "volatility_ratio": 0.82,
            "std_ratio": 0.84,
            "candle_spread_ratio": 0.0021,
            "volume_spike": 1.2,
            "recent_move_pct": -0.12,
            "recent_move_abs_pct": 0.12,
        }
        result = self.detector._classify(snapshot, self.definition)
        self.assertEqual(result["primary_regime"], "low_vol")

    def test_classifies_high_vol(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "volatility_ratio": 1.42,
            "std_ratio": 1.32,
            "volume_spike": 1.42,
            "adx": 19.0,
        }
        result = self.detector._classify(snapshot, self.definition)
        self.assertEqual(result["primary_regime"], "high_vol")
        self.assertEqual(result["risk_level"], "high")

    def test_classifies_stress_panic_even_without_derivatives(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "volatility_ratio": 2.05,
            "std_ratio": 1.45,
            "volume_spike": 2.35,
            "recent_move_pct": -2.1,
            "recent_move_abs_pct": 2.1,
            "funding_abs_bps": None,
        }
        result = self.detector._classify(snapshot, self.definition)
        self.assertEqual(result["primary_regime"], "stress_panic")
        self.assertEqual(result["risk_level"], "high")
        self.assertGreaterEqual(result["confidence"], 0.6)

    def test_derives_htf_bias_and_market_layers_for_downtrend_pullback(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "trend_spread_pct": -0.40,
            "slope_pct": -0.21,
            "adx": 32.0,
            "ltf_trend_spread_pct": -0.08,
            "ltf_slope_pct": -0.07,
            "pullback_distance_pct": 0.12,
        }
        htf_bias = self.detector._derive_htf_bias(snapshot, self.definition)
        market_state = self.detector._derive_market_state(
            feature_snapshot=snapshot,
            primary_regime="trend_down",
            htf_bias=htf_bias,
            definition=self.definition,
        )
        ltf_state = self.detector._derive_ltf_execution_state(
            feature_snapshot=snapshot,
            primary_regime="trend_down",
            htf_bias=htf_bias,
            market_state=market_state,
            definition=self.definition,
        )
        self.assertEqual(htf_bias, "short")
        self.assertEqual(market_state, "pullback")
        self.assertEqual(ltf_state, "momentum_resuming")

    def test_derives_transition_and_noisy_execution_state(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "trend_spread_pct": 0.02,
            "slope_pct": 0.01,
            "adx": 12.0,
            "ltf_trend_spread_pct": 0.01,
            "ltf_slope_pct": 0.01,
        }
        market_state = self.detector._derive_market_state(
            feature_snapshot=snapshot,
            primary_regime="range",
            htf_bias="neutral",
            definition=self.definition,
        )
        ltf_state = self.detector._derive_ltf_execution_state(
            feature_snapshot=snapshot,
            primary_regime="range",
            htf_bias="neutral",
            market_state=market_state,
            definition=self.definition,
        )
        self.assertEqual(market_state, "range")
        self.assertEqual(ltf_state, "noisy")

    def test_hysteresis_keeps_previous_regime_when_new_signal_is_not_strong_enough(self) -> None:
        raw = {
            "primary_regime": "high_vol",
            "confidence": 0.72,
            "risk_level": "high",
            "scores": {
                "trend_up": 0.0,
                "trend_down": 2.5,
                "range": 0.5,
                "low_vol": 0.0,
                "high_vol": 4.1,
                "stress_panic": 0.0,
            },
            "reasons_by_regime": {key: [key] for key in PRIMARY_REGIMES},
            "reasons": ["high_vol"],
        }
        previous_report = {
            "generated_at": "2026-03-19T17:00:00+00:00",
            "primary_regime": "trend_down",
            "smoothed_scores": {
                "trend_up": 0.10,
                "trend_down": 0.78,
                "range": 0.20,
                "low_vol": 0.10,
                "high_vol": 0.40,
                "stress_panic": 0.10,
            },
            "regime_persistence": {
                "bars_in_regime": 2,
                "minutes_in_regime": 10,
                "cooldown_remaining_bars": 1,
            },
        }
        result = self.detector._apply_hysteresis(
            raw_classification=raw,
            previous_report=previous_report,
            definition=self.definition,
        )
        self.assertEqual(result["primary_regime"], "trend_down")
        self.assertGreaterEqual(result["regime_persistence"]["bars_in_regime"], 3)
        self.assertIn("Hysteresis", " ".join(result["reasons"]))

    def test_hysteresis_uses_supplied_generated_at_for_replay_deltas(self) -> None:
        raw = {
            "primary_regime": "trend_down",
            "confidence": 0.72,
            "risk_level": "medium",
            "scores": {
                "trend_up": 0.1,
                "trend_down": 4.4,
                "range": 0.2,
                "low_vol": 0.0,
                "high_vol": 0.0,
                "stress_panic": 0.0,
            },
            "reasons_by_regime": {key: [key] for key in PRIMARY_REGIMES},
            "reasons": ["trend_down"],
        }
        previous_report = {
            "generated_at": "2026-03-19T10:00:00+00:00",
            "primary_regime": "trend_down",
            "smoothed_scores": {
                "trend_down": 0.8,
            },
            "regime_persistence": {
                "bars_in_regime": 3,
                "minutes_in_regime": 180,
                "cooldown_remaining_bars": 0,
            },
        }
        result = self.detector._apply_hysteresis(
            raw_classification=raw,
            previous_report=previous_report,
            definition=self.definition,
            current_generated_at="2026-03-19T11:00:00+00:00",
        )
        self.assertEqual(result["regime_persistence"]["bars_in_regime"], 15)
        self.assertEqual(result["regime_persistence"]["minutes_in_regime"], 240)

    def test_builds_execution_constraints_and_position_size(self) -> None:
        constraints = self.detector._derive_execution_constraints(
            primary_regime="range",
            market_state="range",
            ltf_execution_state="noisy",
            market_phase="compression",
            risk_level="medium",
            consensus_strength=0.32,
            active_event_flags={
                "panic_flush": False,
                "short_squeeze": False,
                "long_squeeze": False,
                "capitulation": False,
                "deleveraging": False,
            },
            cooldown_remaining_bars=0,
        )
        size = self.detector._derive_position_size_multiplier(
            risk_level="medium",
            alignment_score=0.38,
            execution_constraints=constraints,
        )
        self.assertTrue(constraints["no_trade_zone"])
        self.assertEqual(size, 0.0)

    def test_builds_structured_signals(self) -> None:
        snapshot = {
            **_base_snapshot(),
            "adx": 31.0,
            "slope_pct": -0.15,
            "volume_spike": 1.5,
            "funding_abs_bps": 9.0,
        }
        signals = self.detector._build_signals(
            feature_snapshot=snapshot,
            primary_regime="trend_down",
            htf_bias="short",
            market_state="pullback",
            ltf_execution_state="momentum_resuming",
            market_phase="pullback",
            volatility_phase="expanding",
            consensus_strength=0.7,
            definition=self.definition,
        )
        self.assertTrue(signals["trend_strength_high"])
        self.assertTrue(signals["down_slope_confirmed"])
        self.assertTrue(signals["volume_spike"])
        self.assertTrue(signals["funding_extreme"])
        self.assertTrue(signals["htf_ltf_aligned"])

    def test_symbol_consensus_can_be_weak_bearish(self) -> None:
        symbol_features = [
            {
                "pair": "BTC/USDT:USDT",
                **_base_snapshot(),
                "trend_spread_pct": -0.35,
                "slope_pct": -0.18,
                "adx": 28.0,
            },
            {
                "pair": "ETH/USDT:USDT",
                **_base_snapshot(),
                "trend_spread_pct": 0.01,
                "slope_pct": 0.0,
                "adx": 14.0,
            },
        ]
        consensus = self.detector._derive_symbol_states(symbol_features, self.definition)
        self.assertEqual(consensus["btc_state"]["bias"], "short")
        self.assertEqual(consensus["eth_state"]["bias"], "neutral")
        self.assertEqual(consensus["market_consensus"], "weak_bearish")

    def test_candidate_eligibility_uses_regime_market_state_and_constraints(self) -> None:
        eligible, blocked = self.detector._candidate_eligibility(
            [
                {
                    "strategy_id": "baseline",
                    "allowed_primary_regimes": ["trend_up", "trend_down"],
                    "allowed_market_states": ["trend", "pullback"],
                    "allowed_htf_biases": ["long", "short"],
                    "execution_constraints_policy": {"no_trade_zone": "block"},
                },
                {
                    "strategy_id": "short_breakdown",
                    "allowed_primary_regimes": ["trend_down", "high_vol", "stress_panic"],
                    "allowed_market_states": ["trend", "pullback", "transition"],
                    "allowed_htf_biases": ["short"],
                    "execution_constraints_policy": {"no_trade_zone": "block"},
                },
                {
                    "strategy_id": "range_candidate",
                    "allowed_primary_regimes": ["range"],
                    "allowed_market_states": ["range"],
                },
            ],
            primary_regime="trend_down",
            htf_bias="short",
            market_state="pullback",
            market_phase="pullback",
            execution_constraints={
                "no_trade_zone": False,
                "reduced_exposure_only": True,
                "high_noise_environment": False,
                "post_shock_cooldown": False,
            },
        )
        self.assertEqual(sorted(eligible), ["baseline", "short_breakdown"])
        self.assertEqual(sorted(blocked), ["range_candidate"])

    def test_rank_candidates_prefers_short_candidate_in_bearish_pullback(self) -> None:
        ranked = self.detector._rank_candidates(
            manifests=[
                {
                    "strategy_id": "structured_futures_baseline_v1",
                    "allowed_primary_regimes": ["trend_up", "trend_down"],
                    "allowed_htf_biases": ["long", "short"],
                    "allowed_market_states": ["trend", "pullback"],
                    "preferred_market_phases": ["pullback", "mature_trend"],
                },
                {
                    "strategy_id": "structured_futures_short_breakdown_v1",
                    "allowed_primary_regimes": ["trend_down", "high_vol", "stress_panic"],
                    "allowed_htf_biases": ["short"],
                    "allowed_market_states": ["trend", "pullback", "transition"],
                    "preferred_market_phases": ["pullback", "expansion"],
                },
            ],
            eligible_candidate_ids=[
                "structured_futures_baseline_v1",
                "structured_futures_short_breakdown_v1",
            ],
            bias="short",
            primary_regime="trend_down",
            market_state="pullback",
            market_phase="pullback",
        )
        self.assertEqual(ranked[0], "structured_futures_short_breakdown_v1")

    def test_derives_risk_regime_and_quality(self) -> None:
        risk_regime = self.detector._derive_risk_regime(
            primary_regime="trend_down",
            risk_level="medium",
            execution_constraints={
                "no_trade_zone": False,
                "reduced_exposure_only": True,
                "high_noise_environment": False,
                "post_shock_cooldown": False,
            },
            active_event_flags={
                "panic_flush": False,
                "short_squeeze": False,
                "long_squeeze": False,
                "capitulation": False,
                "deleveraging": False,
            },
            consensus_strength=0.7,
        )
        quality = self.detector._derive_regime_quality(
            alignment_score=0.82,
            execution_constraints={
                "no_trade_zone": False,
                "reduced_exposure_only": True,
                "high_noise_environment": False,
                "post_shock_cooldown": False,
            },
            market_phase="compression",
            active_event_flags={
                "panic_flush": False,
                "short_squeeze": False,
                "long_squeeze": False,
                "capitulation": False,
                "deleveraging": False,
            },
            derivatives_state={
                "event_reliability": "medium",
                "is_stale": False,
            },
        )
        self.assertEqual(risk_regime, "elevated")
        self.assertGreater(quality, 0.0)
        self.assertLess(quality, 0.82)

    def test_low_reliability_keeps_derivatives_events_soft_only(self) -> None:
        actionable = self.detector._derive_actionable_event_flags(
            {
                "panic_flush": True,
                "short_squeeze": True,
                "long_squeeze": True,
                "capitulation": True,
                "deleveraging": True,
            },
            {"event_reliability": "low"},
        )
        self.assertTrue(actionable["panic_flush"])
        self.assertFalse(actionable["short_squeeze"])
        self.assertFalse(actionable["capitulation"])

    def test_derivatives_multiplier_penalizes_stale_proxy_feed(self) -> None:
        multiplier = self.detector._derive_derivatives_confidence_multiplier(
            {
                "source": "external_vendor_proxy_fallback",
                "feed_status": "degraded_proxy",
                "event_reliability": "low",
                "is_stale": True,
            }
        )
        self.assertLess(multiplier, 0.8)

    def test_replay_summary_tracks_switches_and_no_trade_share(self) -> None:
        summary = self.detector._summarize_replay_reports(
            reports=[
                {
                    "primary_regime": "trend_up",
                    "bias": "long",
                    "market_phase": "compression",
                    "market_consensus": "strong_bullish",
                    "execution_constraints": {"no_trade_zone": False},
                    "regime_persistence": {"minutes_in_regime": 15},
                    "active_event_flags": {"panic_flush": False, "short_squeeze": False, "long_squeeze": False, "capitulation": False, "deleveraging": False},
                    "feature_snapshot": {"recent_move_pct": 0.2},
                },
                {
                    "primary_regime": "trend_down",
                    "bias": "short",
                    "market_phase": "expansion",
                    "market_consensus": "weak_bearish",
                    "execution_constraints": {"no_trade_zone": True},
                    "regime_persistence": {"minutes_in_regime": 20},
                    "active_event_flags": {"panic_flush": True, "short_squeeze": False, "long_squeeze": False, "capitulation": False, "deleveraging": False},
                    "feature_snapshot": {"recent_move_pct": -0.3},
                },
            ],
            bar_minutes=5,
            definition=self.definition,
        )
        self.assertEqual(summary["regime_switches_total"], 1)
        self.assertEqual(summary["compression_to_expansion_count"], 1)
        self.assertEqual(summary["no_trade_zone_share"], 0.5)
