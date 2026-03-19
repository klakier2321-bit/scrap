from __future__ import annotations

import json
from pathlib import Path
import tempfile
from datetime import datetime, timezone
import unittest

from core.derivatives_feed import DerivativesFeed


class StubBinanceDerivativesFeed(DerivativesFeed):
    def __init__(
        self,
        *,
        root: Path,
        responses: dict[tuple[str, str], object],
        price_contexts: dict[str, dict[str, float | None]],
    ) -> None:
        super().__init__(
            user_data_dir=root / "trading" / "freqtrade" / "user_data",
            output_dir=root / "data" / "ai_control" / "derivatives",
            vendor_input_dir=root / "data" / "ai_control" / "derivatives_vendor",
            universe=list(price_contexts.keys()),
        )
        self.responses = responses
        self.price_contexts = price_contexts

    def _fetch_json(self, path: str, params: dict[str, object]) -> object:
        return self.responses[(path, str(params["symbol"]))]

    def _load_price_context(self, pair: str) -> dict[str, float | None]:
        return self.price_contexts[pair]


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
                binance_enabled=False,
            )
            report = feed.generate_report()
            self.assertEqual(report["source"], "external_vendor")
            self.assertEqual(report["feed_status"], "ok")
            self.assertTrue(report["vendor_available"])
            self.assertEqual(report["event_reliability"], "medium")
            self.assertEqual(report["liquidation_event_confidence"], "medium")
            symbol = report["symbols"][0]
            self.assertEqual(symbol["oi_price_agreement"], "trend_supported_down")
            self.assertEqual(symbol["positioning_state"], "short_build")

    def test_binance_payload_is_canonicalized_from_public_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "trading" / "freqtrade" / "user_data").mkdir(parents=True)
            (root / "data" / "ai_control" / "derivatives_vendor").mkdir(parents=True)
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            responses: dict[tuple[str, str], object] = {
                ("/fapi/v1/openInterest", "BTCUSDT"): {"openInterest": "112.0", "time": now_ms},
                (
                    "/futures/data/openInterestHist",
                    "BTCUSDT",
                ): [
                    {"sumOpenInterest": "100.0", "timestamp": now_ms - 600000},
                    {"sumOpenInterest": "105.0", "timestamp": now_ms - 300000},
                    {"sumOpenInterest": "110.0", "timestamp": now_ms},
                ],
                (
                    "/fapi/v1/fundingRate",
                    "BTCUSDT",
                ): [
                    {"fundingRate": "-0.0008", "fundingTime": now_ms},
                ],
                (
                    "/futures/data/takerlongshortRatio",
                    "BTCUSDT",
                ): [
                    {
                        "buySellRatio": "0.75",
                        "buyVol": "90.0",
                        "sellVol": "120.0",
                        "timestamp": now_ms,
                    }
                ],
                (
                    "/futures/data/globalLongShortAccountRatio",
                    "BTCUSDT",
                ): [
                    {
                        "longShortRatio": "0.82",
                        "longAccount": "0.45",
                        "shortAccount": "0.55",
                        "timestamp": now_ms,
                    }
                ],
            }
            feed = StubBinanceDerivativesFeed(
                root=root,
                responses=responses,
                price_contexts={
                    "BTC/USDT:USDT": {"price_change_pct": -1.2},
                },
            )

            report = feed.generate_report()

            self.assertEqual(report["source"], "binance_futures_public_api")
            self.assertEqual(report["feed_status"], "ok")
            self.assertTrue(report["vendor_available"])
            self.assertEqual(report["event_reliability"], "medium")
            self.assertFalse(report["is_stale"])
            symbol = report["symbols"][0]
            self.assertEqual(symbol["binance_symbol"], "BTCUSDT")
            self.assertEqual(symbol["oi_price_agreement"], "trend_supported_down")
            self.assertEqual(symbol["positioning_state"], "short_build")
            self.assertEqual(symbol["funding_extreme_flag"], True)
            self.assertAlmostEqual(symbol["open_interest_change_pct"], 4.7619, places=4)
            self.assertAlmostEqual(symbol["oi_acceleration"], -0.2381, places=4)
            self.assertLess(symbol["taker_imbalance"], 0.0)
            self.assertEqual(symbol["liquidation_source_type"], "proxy_from_binance_public_api")
