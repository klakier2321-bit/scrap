from __future__ import annotations

import unittest

from core.runtime_artifacts import aggregate_portfolio_snapshots


class RuntimeArtifactsTests(unittest.TestCase):
    def test_aggregate_portfolio_snapshots_uses_single_cluster_equity_and_union_of_positions(self) -> None:
        snapshot = aggregate_portfolio_snapshots(
            [
                {
                    "bot_id": "ft_trend_pullback_continuation_v1",
                    "strategy": "TrendPullbackContinuationV1RuntimeStrategy",
                    "balance_summary": {"total": 1000.0},
                    "trade_count_summary": {
                        "current_open_trades": 1,
                        "max_open_trades": 2,
                        "total_open_trades_stakes": 100.0,
                    },
                    "open_trades_count": 1,
                    "open_trades": [{"pair": "BTC/USDT:USDT", "side": "short", "stake_amount": 100.0}],
                },
                {
                    "bot_id": "ft_range_mean_reversion_v1",
                    "strategy": "RangeMeanReversionV1RuntimeStrategy",
                    "balance_summary": {"total": 1000.0},
                    "trade_count_summary": {
                        "current_open_trades": 1,
                        "max_open_trades": 2,
                        "total_open_trades_stakes": 80.0,
                    },
                    "open_trades_count": 1,
                    "open_trades": [{"pair": "ETH/USDT:USDT", "side": "long", "stake_amount": 80.0}],
                },
            ],
            bot_ids=[
                "ft_trend_pullback_continuation_v1",
                "ft_range_mean_reversion_v1",
            ],
        )

        self.assertEqual(snapshot["balance_summary"]["total"], 1000.0)
        self.assertEqual(snapshot["trade_count_summary"]["total_open_trades_stakes"], 180.0)
        self.assertIsNone(snapshot["trade_count_summary"]["max_open_trades"])
        self.assertEqual(snapshot["open_trades_count"], 2)
        self.assertEqual(snapshot["aggregation_mode"]["balance_total"], "max_member_balance")
