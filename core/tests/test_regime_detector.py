from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.regime_detector import PRIMARY_REGIMES, RegimeDetector


def _definition() -> dict[str, object]:
    return {
        "asof_timeframe": "1h",
        "universe": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        "thresholds": {
            "trend_spread_min_pct": 0.12,
            "slope_min_pct": 0.08,
            "adx_trend_min": 22.0,
            "adx_range_max": 18.0,
            "range_spread_max_pct": 0.08,
            "low_volatility_ratio_max": 0.85,
            "low_candle_spread_max": 0.0025,
            "low_volume_spike_max": 0.9,
            "high_volatility_ratio_min": 1.2,
            "high_std_ratio_min": 1.15,
            "volume_spike_high": 1.25,
            "stress_move_abs_pct_min": 1.6,
            "stress_volatility_ratio_min": 1.8,
            "stress_volume_spike_min": 1.8,
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
        "recent_move_abs_pct": 0.6,
        "funding_abs_bps": None,
        "trend_strength": 0.4,
        "volatility_level": "normal",
        "volume_state": "normal",
        "derivatives_state": "unavailable",
        "symbols": [],
    }


class RegimeDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        repo_root = Path(self.tempdir.name)
        self.detector = RegimeDetector(
            user_data_dir=repo_root / "trading" / "freqtrade" / "user_data",
            output_dir=repo_root / "data" / "ai_control" / "regime",
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
            "recent_move_abs_pct": 2.1,
            "funding_abs_bps": None,
        }
        result = self.detector._classify(snapshot, self.definition)
        self.assertEqual(result["primary_regime"], "stress_panic")
        self.assertEqual(result["risk_level"], "high")
        self.assertGreaterEqual(result["confidence"], 0.6)

    def test_candidate_eligibility_uses_allowed_and_blocked_regimes(self) -> None:
        eligible, blocked = self.detector._candidate_eligibility(
            [
                {
                    "strategy_id": "baseline",
                    "allowed_primary_regimes": ["trend_up", "trend_down"],
                    "blocked_primary_regimes": ["range"],
                },
                {
                    "strategy_id": "short_breakdown",
                    "allowed_primary_regimes": ["trend_down", "high_vol", "stress_panic"],
                    "blocked_primary_regimes": ["trend_up", "low_vol"],
                },
                {
                    "strategy_id": "range_candidate",
                    "allowed_primary_regimes": ["range"],
                    "blocked_primary_regimes": [],
                },
            ],
            primary_regime="trend_down",
        )
        self.assertEqual(sorted(eligible), ["baseline", "short_breakdown"])
        self.assertEqual(sorted(blocked), ["range_candidate"])
