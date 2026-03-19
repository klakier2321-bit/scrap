from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core.derivatives_feed import DerivativesFeed


class DerivativesFeedTests(unittest.TestCase):
    def test_external_vendor_payload_is_canonicalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vendor_dir = root / "data" / "ai_control" / "derivatives_vendor"
            output_dir = root / "data" / "ai_control" / "derivatives"
            vendor_dir.mkdir(parents=True)
            (root / "trading" / "freqtrade" / "user_data").mkdir(parents=True)
            (vendor_dir / "latest.json").write_text(
                json.dumps(
                    {
                        "symbols": [
                            {
                                "pair": "BTC/USDT:USDT",
                                "open_interest": 100.0,
                                "open_interest_change_pct": 2.4,
                                "oi_acceleration": 0.8,
                                "price_change_pct": -1.2,
                                "funding_bps": -3.5,
                                "liquidation_pressure_proxy": 0.7,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            feed = DerivativesFeed(
                user_data_dir=root / "trading" / "freqtrade" / "user_data",
                output_dir=output_dir,
                vendor_input_dir=vendor_dir,
            )
            report = feed.generate_report()
            self.assertEqual(report["source"], "external_vendor")
            self.assertEqual(report["feed_status"], "ok")
            self.assertTrue(report["vendor_available"])
            symbol = report["symbols"][0]
            self.assertEqual(symbol["oi_price_agreement"], "trend_supported_down")
            self.assertEqual(symbol["positioning_state"], "short_build")

