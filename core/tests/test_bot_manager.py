from __future__ import annotations

import unittest
from pathlib import Path

from core.bot_manager import BotManager


class BotManagerTests(unittest.TestCase):
    def test_get_bot_status_exposes_runtime_metadata_for_futures_cluster(self) -> None:
        manager = BotManager(
            config_path=Path("/home/debian/crypto-system/core/config/bots.yaml")
        )
        manager._get_container = lambda bot_id: None  # type: ignore[method-assign]

        status = manager.get_bot_status("ft_trend_pullback_continuation_v1")

        self.assertEqual(status["state"], "missing")
        self.assertEqual(status["strategy_id"], "trend_pullback_continuation_v1")
        self.assertEqual(status["market_type"], "futures")
        self.assertEqual(status["runtime_group"], "futures_canonical")
        self.assertEqual(
            status["artifact_scope"],
            "futures/trend_pullback_continuation_v1",
        )

