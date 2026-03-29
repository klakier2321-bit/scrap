from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "trading"
    / "freqtrade"
    / "user_data"
    / "strategies"
    / "runtime_risk_guard.py"
)


def _load_runtime_guard_module():
    spec = importlib.util.spec_from_file_location("runtime_risk_guard", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load runtime_risk_guard module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalRuntimeRiskGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_runtime_guard_module()

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.guard = self.module.LocalRuntimeRiskGuard(bot_id="ft_trend_pullback_continuation_v1")
        self.guard.futures_dir = self.root / "runtime_artifacts" / "futures"

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_decision(self, payload: dict) -> None:
        payload = {"generated_at": self.module._now_iso(), **payload}
        self._write_json(self.guard.risk_decision_path(), payload)

    def _write_portfolio(self, payload: dict) -> None:
        self._write_json(self.guard.global_portfolio_path(), payload)

    def test_blocks_when_allow_trading_is_false(self) -> None:
        self._write_decision(
            {
                "allow_trading": False,
                "new_entries_allowed": True,
                "allowed_directions": ["long"],
                "allowed_strategy_ids": ["trend_pullback_continuation_v1"],
                "blocked_strategy_ids": [],
                "max_positions_total": 2,
                "max_positions_per_symbol": 1,
                "max_correlated_positions": 1,
                "force_reduce_only": False,
                "cooldown_active": False,
                "protective_overrides": {},
            }
        )

        result = self.guard.enforce_entry(
            strategy_id="trend_pullback_continuation_v1",
            pair="BTC/USDT:USDT",
            side="long",
            signal_profile="standard",
        )

        self.assertFalse(result["entry_allowed"])
        self.assertIn(self.module.EXECUTION_HARD_BLOCK_ALLOW_TRADING, result["blocked_reason_codes"])

    def test_empty_allowed_strategy_ids_do_not_block_entry(self) -> None:
        self._write_decision(
            {
                "allow_trading": True,
                "new_entries_allowed": True,
                "allowed_directions": ["long"],
                "allowed_strategy_ids": [],
                "blocked_strategy_ids": [],
                "max_positions_total": 2,
                "max_positions_per_symbol": 1,
                "max_correlated_positions": 1,
                "force_reduce_only": False,
                "cooldown_active": False,
                "protective_overrides": {},
            }
        )

        result = self.guard.enforce_entry(
            strategy_id="trend_pullback_continuation_v1",
            pair="BTC/USDT:USDT",
            side="long",
            signal_profile="standard",
        )

        self.assertTrue(result["entry_allowed"])
        self.assertNotIn(self.module.EXECUTION_BLOCKED_STRATEGY, result["blocked_reason_codes"])

    def test_blocked_strategy_id_is_enforced(self) -> None:
        self._write_decision(
            {
                "allow_trading": True,
                "new_entries_allowed": True,
                "allowed_directions": ["long"],
                "allowed_strategy_ids": [],
                "blocked_strategy_ids": ["trend_pullback_continuation_v1"],
                "max_positions_total": 2,
                "max_positions_per_symbol": 1,
                "max_correlated_positions": 1,
                "force_reduce_only": False,
                "cooldown_active": False,
                "protective_overrides": {},
            }
        )

        result = self.guard.enforce_entry(
            strategy_id="trend_pullback_continuation_v1",
            pair="BTC/USDT:USDT",
            side="long",
            signal_profile="standard",
        )

        self.assertFalse(result["entry_allowed"])
        self.assertIn(self.module.EXECUTION_BLOCKED_STRATEGY, result["blocked_reason_codes"])

    def test_stale_risk_artifact_blocks_entry(self) -> None:
        self._write_decision(
            {
                "generated_at": "2026-03-20T00:00:00+00:00",
                "allow_trading": True,
                "new_entries_allowed": True,
                "allowed_directions": ["long"],
                "allowed_strategy_ids": ["trend_pullback_continuation_v1"],
                "blocked_strategy_ids": [],
                "max_positions_total": 2,
                "max_positions_per_symbol": 1,
                "max_correlated_positions": 1,
                "force_reduce_only": False,
                "cooldown_active": False,
                "protective_overrides": {},
            }
        )

        result = self.guard.enforce_entry(
            strategy_id="trend_pullback_continuation_v1",
            pair="BTC/USDT:USDT",
            side="long",
            signal_profile="standard",
        )

        self.assertFalse(result["entry_allowed"])
        self.assertIn(self.module.EXECUTION_RISK_ARTIFACT_STALE, result["blocked_reason_codes"])

    def test_stake_and_leverage_are_clamped_from_local_artifacts(self) -> None:
        self._write_decision(
            {
                "allow_trading": True,
                "new_entries_allowed": True,
                "allowed_directions": ["long"],
                "allowed_strategy_ids": ["trend_pullback_continuation_v1"],
                "blocked_strategy_ids": [],
                "max_positions_total": 3,
                "max_positions_per_symbol": 1,
                "max_correlated_positions": 1,
                "max_position_size_pct": 1.0,
                "max_total_exposure_pct": 10.0,
                "leverage_cap": 2.0,
                "force_reduce_only": False,
                "cooldown_active": False,
                "execution_budget_multiplier": 0.5,
                "protective_overrides": {
                    "disable_aggressive_entries": False,
                    "force_conservative_execution": False,
                    "tighter_risk_budget": True,
                },
            }
        )
        self._write_portfolio(
            {
                "balance_summary": {"total": 1000.0},
                "trade_count_summary": {
                    "current_open_trades": 0,
                    "max_open_trades": 3,
                    "total_open_trades_stakes": 0.0,
                },
                "open_trades_count": 0,
                "open_trades": [],
            }
        )

        stake = self.guard.enforce_stake(
            strategy_id="trend_pullback_continuation_v1",
            pair="BTC/USDT:USDT",
            side="long",
            proposed_stake=50.0,
            min_stake=None,
            max_stake=50.0,
            signal_profile="standard",
            total_equity=1000.0,
        )
        leverage = self.guard.enforce_leverage(
            strategy_id="trend_pullback_continuation_v1",
            pair="BTC/USDT:USDT",
            side="long",
            proposed_leverage=5.0,
            max_leverage=10.0,
        )

        self.assertEqual(stake["final_stake"], 10.0)
        self.assertIn(self.module.EXECUTION_STAKE_CLAMPED, stake["blocked_reason_codes"])
        self.assertEqual(leverage["final_leverage"], 2.0)
        self.assertIn(self.module.EXECUTION_LEVERAGE_CLAMPED, leverage["blocked_reason_codes"])
