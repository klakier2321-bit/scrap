from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.system_backtest import run as replay_cli
from core.system_backtest.execution_simulator import ExecutionSimulator
from core.system_backtest.loop import SystemReplayLoop
from core.system_backtest.market_replay import HistoricalMarketReplayProvider
from core.system_backtest.models import ReplayPosition, SystemBacktestConfig, parse_timerange


REPO_ROOT = Path(__file__).resolve().parents[2]


def _config(output_root: Path, *, max_bars: int | None = 24) -> SystemBacktestConfig:
    return SystemBacktestConfig(
        universe=["BTC/USDT:USDT", "ETH/USDT:USDT"],
        base_timeframe="5m",
        htf_timeframe="1h",
        starting_equity=10000.0,
        fee_rate=0.0004,
        slippage_rate=0.0002,
        replay_warmup_bars=288,
        replay_warmup_1h_bars=72,
        enabled_strategy_ids=[
            "trend_pullback_continuation_v1",
            "breakout_from_compression_v1",
            "range_mean_reversion_v1",
            "panic_reversal_v1",
            "defense_only_v1",
        ],
        output_root=output_root,
        user_data_dir=REPO_ROOT / "trading" / "freqtrade" / "user_data",
        research_dir=REPO_ROOT / "research",
        max_bars=max_bars,
    )


class HistoricalMarketReplayProviderTests(unittest.TestCase):
    def test_provider_does_not_leak_future_bars(self) -> None:
        config = _config(Path(tempfile.gettempdir()) / "system_replay_test_provider", max_bars=2)
        provider = HistoricalMarketReplayProvider(config=config)
        start, end = parse_timerange("2026-02-15:2026-02-16")

        windows = list(provider.iter_windows(start=start, end=end))

        self.assertTrue(windows)
        window = windows[0]
        first_pair = config.universe[0]
        latest_5m_time = max(row["date"] for row in window.base_frames[first_pair])
        latest_1h_time = max(row["date"] for row in window.htf_frames[first_pair])
        self.assertLessEqual(latest_5m_time, window.timestamp)
        self.assertLess(latest_1h_time, window.timestamp.replace(minute=0, second=0, microsecond=0))
        self.assertGreater(window.next_bars[first_pair]["date"], window.timestamp)


class ExecutionSimulatorTests(unittest.TestCase):
    def test_portfolio_snapshot_is_global_across_positions(self) -> None:
        simulator = ExecutionSimulator(starting_equity=10000.0, fee_rate=0.0004, slippage_rate=0.0002)
        simulator.open_positions = [
            ReplayPosition(
                trade_id="t1",
                signal_id="s1",
                strategy_id="trend_pullback_continuation_v1",
                bot_id="ft_trend_pullback_continuation_v1",
                pair="BTC/USDT:USDT",
                side="short",
                entry_type="pullback_limit",
                entry_time="2026-02-15T00:00:00+00:00",
                entry_price=80000.0,
                stake=100.0,
                leverage=2.0,
                quantity=0.0025,
                stop_price=80400.0,
                target_price=79200.0,
                max_hold_bars=12,
            ),
            ReplayPosition(
                trade_id="t2",
                signal_id="s2",
                strategy_id="range_mean_reversion_v1",
                bot_id="ft_range_mean_reversion_v1",
                pair="ETH/USDT:USDT",
                side="long",
                entry_type="market_confirmation",
                entry_time="2026-02-15T00:05:00+00:00",
                entry_price=2200.0,
                stake=80.0,
                leverage=1.0,
                quantity=0.03636,
                stop_price=2189.0,
                target_price=2215.0,
                max_hold_bars=8,
            ),
        ]

        snapshot = simulator.build_portfolio_snapshot(
            timestamp="2026-02-15T00:10:00+00:00",
            current_bars={
                "BTC/USDT:USDT": {"close": 79800.0},
                "ETH/USDT:USDT": {"close": 2205.0},
            },
        )

        self.assertEqual(snapshot["bot_id"], "futures_canonical_cluster")
        self.assertEqual(snapshot["open_trades_count"], 2)
        self.assertEqual(snapshot["trade_count_summary"]["current_open_trades"], 2)
        self.assertAlmostEqual(snapshot["trade_count_summary"]["total_open_trades_stakes"], 180.0)


class SystemReplayLoopTests(unittest.TestCase):
    def test_cli_parser_supports_diagnostic_mode_override(self) -> None:
        parser = replay_cli.build_parser()
        parsed = parser.parse_args(
            [
                "--config",
                "research/system_backtests/futures_cluster_v1.yaml",
                "--timerange",
                "2026-02-15:2026-02-16",
                "--diagnostic-mode",
                "fast",
            ]
        )
        self.assertEqual(parsed.diagnostic_mode, "fast")

    def test_loop_generates_system_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(Path(tmpdir) / "backtests" / "system", max_bars=18)
            loop = SystemReplayLoop(config=config)

            result = loop.run(timerange="2026-02-15:2026-02-16")

            run_dir = Path(result["run_dir"])
            summary = result["summary"]
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertTrue((run_dir / "equity_curve.json").exists())
            self.assertTrue((run_dir / "trades.json").exists())
            self.assertTrue((run_dir / "bar_log.jsonl").exists())
            self.assertTrue((run_dir / "execution_events.jsonl").exists())
            self.assertTrue((run_dir / "regime_reports").exists())
            self.assertTrue((run_dir / "risk_decisions").exists())
            self.assertTrue((run_dir / "strategy_reports").exists())
            self.assertEqual(summary["pairs"], config.universe)
            self.assertEqual(summary["strategies_enabled"], config.enabled_strategy_ids)
            self.assertIn("blocked_reason_breakdown", summary)
            self.assertIn("strategy_breakdown", summary)
            self.assertIn("regime_breakdown", summary)

    def test_fast_mode_skips_detailed_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(Path(tmpdir) / "backtests" / "system", max_bars=10)
            config.write_detailed_reports = False
            loop = SystemReplayLoop(config=config)

            result = loop.run(timerange="2026-02-15:2026-02-16")

            run_dir = Path(result["run_dir"])
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertEqual(list((run_dir / "regime_reports").glob("*.json")), [])
            self.assertEqual(list((run_dir / "risk_decisions").glob("*.json")), [])
            strategy_files = list((run_dir / "strategy_reports").rglob("*.json"))
            self.assertEqual(strategy_files, [])


if __name__ == "__main__":
    unittest.main()
