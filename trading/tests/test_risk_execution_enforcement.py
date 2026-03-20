from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.risk_management.execution_guard import RiskExecutionGuard


class RiskExecutionEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        root = Path(self.tmpdir.name)
        self.risk_dir = root / "risk"
        self.snapshots_dir = root / "snapshots"
        self.guard = RiskExecutionGuard(
            bot_id="freqtrade_candidate",
            risk_dir=self.risk_dir,
            snapshots_dir=self.snapshots_dir,
        )

    def _write_decision(self, payload: dict) -> None:
        self.risk_dir.mkdir(parents=True, exist_ok=True)
        (self.risk_dir / "latest-freqtrade_candidate.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _write_snapshot(self, payload: dict) -> None:
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        (self.snapshots_dir / "latest-freqtrade_candidate.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _base_decision(self) -> dict:
        return {
            "allow_trading": True,
            "new_entries_allowed": True,
            "allowed_directions": ["short"],
            "allowed_strategy_ids": ["structured_futures_short_breakdown_v1"],
            "max_positions_total": 2,
            "max_positions_per_symbol": 1,
            "max_correlated_positions": 1,
            "max_position_size_pct": 1.0,
            "max_total_exposure_pct": 25.0,
            "leverage_cap": 2.0,
            "force_reduce_only": False,
            "cooldown_active": False,
            "execution_budget_multiplier": 1.0,
            "protective_overrides": {
                "force_conservative_execution": False,
                "disable_aggressive_entries": False,
                "tighter_risk_budget": False,
            },
        }

    def test_blocks_when_allow_trading_is_false(self) -> None:
        decision = self._base_decision()
        decision["allow_trading"] = False
        self._write_decision(decision)

        result = self.guard.enforce_entry(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="BTC/USDT:USDT",
            side="short",
            entry_tag="breakdown_short_candidate",
            signal_profile="aggressive",
        )

        self.assertFalse(result["entry_allowed"])
        self.assertIn("EXECUTION_HARD_BLOCK_ALLOW_TRADING", result["blocked_reason_codes"])

    def test_blocks_disallowed_direction(self) -> None:
        self._write_decision(self._base_decision())
        result = self.guard.enforce_entry(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="BTC/USDT:USDT",
            side="long",
            entry_tag="continuation_long_candidate",
            signal_profile="standard",
        )
        self.assertFalse(result["entry_allowed"])
        self.assertIn("EXECUTION_BLOCKED_DIRECTION", result["blocked_reason_codes"])

    def test_blocks_strategy_outside_allowed_ids(self) -> None:
        self._write_decision(self._base_decision())
        result = self.guard.enforce_entry(
            strategy_id="structured_futures_baseline_v1",
            pair="BTC/USDT:USDT",
            side="short",
            entry_tag="trend_pullback_long",
            signal_profile="standard",
        )
        self.assertFalse(result["entry_allowed"])
        self.assertIn("EXECUTION_BLOCKED_STRATEGY", result["blocked_reason_codes"])

    def test_blocks_when_portfolio_is_full(self) -> None:
        self._write_decision(self._base_decision())
        self._write_snapshot(
            {
                "open_trades_count": 2,
                "open_trades": [
                    {"pair": "BTC/USDT:USDT", "side": "short"},
                    {"pair": "ETH/USDT:USDT", "side": "short"},
                ],
            }
        )
        result = self.guard.enforce_entry(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="SOL/USDT:USDT",
            side="short",
            entry_tag="breakdown_short_candidate",
            signal_profile="aggressive",
        )
        self.assertFalse(result["entry_allowed"])
        self.assertIn("EXECUTION_PORTFOLIO_FULL", result["blocked_reason_codes"])

    def test_caps_stake_to_risk_budget(self) -> None:
        self._write_decision(self._base_decision())
        result = self.guard.enforce_stake(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="BTC/USDT:USDT",
            side="short",
            proposed_stake=50.0,
            min_stake=None,
            max_stake=50.0,
            signal_profile="aggressive",
            total_equity=1000.0,
        )
        self.assertEqual(result["final_stake"], 10.0)
        self.assertIn("EXECUTION_STAKE_CLAMPED", result["blocked_reason_codes"])

    def test_caps_leverage_to_leverage_cap(self) -> None:
        self._write_decision(self._base_decision())
        result = self.guard.enforce_leverage(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="BTC/USDT:USDT",
            side="short",
            proposed_leverage=5.0,
            max_leverage=20.0,
        )
        self.assertEqual(result["final_leverage"], 2.0)
        self.assertIn("EXECUTION_LEVERAGE_CLAMPED", result["blocked_reason_codes"])

    def test_blocks_force_reduce_only(self) -> None:
        decision = self._base_decision()
        decision["force_reduce_only"] = True
        self._write_decision(decision)
        result = self.guard.enforce_entry(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="BTC/USDT:USDT",
            side="short",
            entry_tag="breakdown_short_candidate",
            signal_profile="aggressive",
        )
        self.assertFalse(result["entry_allowed"])
        self.assertIn("EXECUTION_FORCE_REDUCE_ONLY", result["blocked_reason_codes"])

    def test_blocks_cooldown_active(self) -> None:
        decision = self._base_decision()
        decision["cooldown_active"] = True
        self._write_decision(decision)
        result = self.guard.enforce_entry(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="BTC/USDT:USDT",
            side="short",
            entry_tag="breakdown_short_candidate",
            signal_profile="aggressive",
        )
        self.assertFalse(result["entry_allowed"])
        self.assertIn("EXECUTION_COOLDOWN_ACTIVE", result["blocked_reason_codes"])

    def test_blocks_aggressive_entry_when_disabled(self) -> None:
        decision = self._base_decision()
        decision["protective_overrides"]["disable_aggressive_entries"] = True
        self._write_decision(decision)
        result = self.guard.enforce_entry(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="BTC/USDT:USDT",
            side="short",
            entry_tag="breakdown_short_candidate",
            signal_profile="aggressive",
        )
        self.assertFalse(result["entry_allowed"])
        self.assertIn("EXECUTION_AGGRESSIVE_ENTRY_BLOCKED", result["blocked_reason_codes"])

    def test_tighter_risk_budget_halves_stake(self) -> None:
        decision = self._base_decision()
        decision["execution_budget_multiplier"] = 0.5
        decision["protective_overrides"]["tighter_risk_budget"] = True
        self._write_decision(decision)
        result = self.guard.enforce_stake(
            strategy_id="structured_futures_short_breakdown_v1",
            pair="BTC/USDT:USDT",
            side="short",
            proposed_stake=8.0,
            min_stake=None,
            max_stake=20.0,
            signal_profile="standard",
            total_equity=1000.0,
        )
        self.assertEqual(result["final_stake"], 4.0)

