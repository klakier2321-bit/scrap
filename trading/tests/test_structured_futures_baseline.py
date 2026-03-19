"""Artifact and syntax checks for the first futures baseline candidate."""

from __future__ import annotations

import json
import py_compile
from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
STRATEGY_PATH = (
    REPO_ROOT
    / "trading"
    / "freqtrade"
    / "user_data"
    / "strategies"
    / "structured_futures_baseline_strategy.py"
)


class StructuredFuturesBaselineTests(unittest.TestCase):
    def test_strategy_file_compiles(self) -> None:
        py_compile.compile(str(STRATEGY_PATH), doraise=True)

    def test_backtest_config_is_futures_specific(self) -> None:
        config_path = (
            REPO_ROOT
            / "trading"
            / "freqtrade"
            / "user_data"
            / "config.backtest.futures.baseline.json"
        )
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["strategy"], "StructuredFuturesBaselineStrategy")
        self.assertEqual(payload["trading_mode"], "futures")
        self.assertEqual(payload["margin_mode"], "isolated")
        self.assertEqual(
            payload["exchange"]["pair_whitelist"],
            ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        )

    def test_candidate_manifest_references_foundation_artifacts(self) -> None:
        manifest_path = (
            REPO_ROOT
            / "research"
            / "candidates"
            / "structured_futures_baseline_v1"
            / "strategy_manifest.yaml"
        )
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["market_type"], "futures")
        self.assertEqual(manifest["allowed_sides"], "both")
        self.assertIn(manifest["status"], {"hypothesis", "needs_rework", "dry_run_candidate"})
        for key in (
            "hypothesis_path",
            "dataset_spec_path",
            "feature_manifest_path",
            "risk_report_path",
            "promotion_decision_path",
        ):
            self.assertTrue((REPO_ROOT / manifest[key]).exists(), key)

    def test_risk_report_has_first_candidate_limits(self) -> None:
        risk_report_path = (
            REPO_ROOT / "research" / "risk" / "structured_futures_baseline_v1_risk_report.json"
        )
        payload = json.loads(risk_report_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["strategy_id"], "structured_futures_baseline_v1")
        self.assertEqual(payload["margin_mode"], "isolated")
        self.assertLessEqual(payload["leverage_cap"], 2.0)
        self.assertLessEqual(payload["max_open_trades"], 2)

    def test_strategy_source_contains_dynamic_stake_controls(self) -> None:
        source = STRATEGY_PATH.read_text(encoding="utf-8")
        for marker in (
            "def custom_stake_amount(",
            "base_risk_per_trade_pct",
            "target_atr_ratio",
            "signal_quality",
            "volatility_factor",
            "drawdown_factor",
            "risk_capped_stake",
            "get_starting_balance",
            "get_total_stake_amount",
        ):
            self.assertIn(marker, source)
