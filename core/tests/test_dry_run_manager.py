"""Testy read-only bridge i snapshotów dry run."""

from __future__ import annotations

from pathlib import Path
import io
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

from core.dry_run_manager import DryRunManager
from core.freqtrade_runtime import FreqtradeRuntimeClient, FreqtradeRuntimeError


class FakeRuntimeClient:
    def __init__(
        self,
        *,
        runmode: str = "dry_run",
        dry_run: bool = True,
        trades: list[dict] | None = None,
        status_trades: list[dict] | None = None,
    ) -> None:
        self.runmode = runmode
        self.dry_run = dry_run
        self._trades = trades or []
        self._status_trades = status_trades if status_trades is not None else self._trades

    def ping(self) -> dict:
        return {"status": "pong"}

    def show_config(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "runmode": self.runmode,
            "strategy": "SampleStrategy",
            "exchange": "binance",
            "stake_currency": "USDT",
            "stake_amount": "unlimited",
            "timeframe": "5m",
            "max_open_trades": 3,
            "short_allowed": False,
            "pair_whitelist": ["BTC/USDT", "ETH/USDT"],
            "pair_blacklist": ["BNB/.*"],
        }

    def balance(self) -> dict:
        return {
            "currencies": [{"currency": "USDT", "free": 1000.0, "balance": 1000.0}],
            "total": 1000.0,
            "available_capital": 1000.0,
        }

    def profit(self) -> dict:
        return {
            "closed_trade_count": 2,
            "profit_closed_coin": 10.0,
            "profit_closed_ratio": 0.01,
            "profit_all_coin": 12.0,
            "profit_all_ratio": 0.012,
            "bot_start_date": "2026-03-15T00:00:00+00:00",
        }

    def trades(self) -> list[dict]:
        return self._trades

    def count(self) -> dict:
        open_count = sum(1 for trade in self._status_trades if trade.get("is_open"))
        return {
            "current": open_count,
            "max": 3,
            "total_stake": 50.0 if open_count else 0.0,
        }

    def performance(self) -> list[dict]:
        return [{"pair": "BTC/USDT", "profit_ratio": 0.01, "profit_abs": 10.0, "count": 2}]

    def status(self) -> list[dict]:
        return self._status_trades


class FailingRuntimeClient(FakeRuntimeClient):
    def ping(self) -> dict:
        raise FreqtradeRuntimeError("runtime_unavailable", "bridge timeout")

    def show_config(self) -> dict:
        raise FreqtradeRuntimeError("runtime_unavailable", "bridge timeout")


class DryRunManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.manager = DryRunManager(
            client=FakeRuntimeClient(
                trades=[
                    {
                        "trade_id": 7,
                        "pair": "BTC/USDT",
                        "is_open": True,
                        "stake_amount": 50.0,
                        "amount": 0.001,
                        "open_rate": 50000.0,
                        "current_rate": 50500.0,
                        "profit_ratio": 0.01,
                        "profit_abs": 0.5,
                        "open_date": "2026-03-15T12:00:00+00:00",
                    }
                ],
            ),
            snapshots_dir=root / "snapshots",
            smoke_dir=root / "smoke",
            stale_after_seconds=180,
        )
        self.bot_status = {
            "bot_id": "freqtrade",
            "state": "running",
            "strategy": "SampleStrategy",
            "dry_run": True,
        }
        self.logs = [
            "2026-03-15 12:00:00,000 - freqtrade - INFO - Bot started",
            "2026-03-15 12:00:05,000 - freqtrade - WARNING - Example warning",
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_snapshot_persists_latest_and_normalizes_open_trades(self) -> None:
        snapshot = self.manager.create_snapshot(bot_status=self.bot_status, logs=self.logs)

        self.assertEqual(snapshot["snapshot_status"], "ok")
        self.assertEqual(snapshot["strategy"], "SampleStrategy")
        self.assertEqual(snapshot["open_trades_count"], 1)
        self.assertEqual(snapshot["open_trades"][0]["pair"], "BTC/USDT")
        latest = self.manager.latest_snapshot(bot_id="freqtrade")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["open_trades_count"], 1)

    def test_create_snapshot_prefers_status_endpoint_for_open_trades(self) -> None:
        manager = DryRunManager(
            client=FakeRuntimeClient(
                trades=[
                    {
                        "trade_id": 7,
                        "pair": "BTC/USDT",
                        "is_open": False,
                    }
                ],
                status_trades=[
                    {
                        "trade_id": 8,
                        "pair": "ETH/USDT",
                        "is_open": True,
                        "stake_amount": 40.0,
                        "amount": 0.02,
                        "open_rate": 2000.0,
                        "current_rate": 2010.0,
                        "profit_ratio": 0.005,
                        "profit_abs": 0.2,
                        "open_date": "2026-03-15T13:00:00+00:00",
                    },
                    {
                        "trade_id": 9,
                        "pair": "SOL/USDT",
                        "is_open": True,
                        "stake_amount": 45.0,
                        "amount": 1.0,
                        "open_rate": 90.0,
                        "current_rate": 91.0,
                        "profit_ratio": 0.011,
                        "profit_abs": 0.5,
                        "open_date": "2026-03-15T13:05:00+00:00",
                    },
                ],
            ),
            snapshots_dir=Path(self.temp_dir.name) / "snapshots-status",
            smoke_dir=Path(self.temp_dir.name) / "smoke-status",
            stale_after_seconds=180,
        )

        snapshot = manager.create_snapshot(bot_status=self.bot_status, logs=self.logs)

        self.assertEqual(snapshot["trade_count_summary"]["current_open_trades"], 2)
        self.assertEqual(snapshot["trade_count_summary"]["total_open_trades_stakes"], 50.0)
        self.assertEqual(snapshot["open_trades_count"], 2)
        self.assertEqual(snapshot["open_trades"][0]["pair"], "ETH/USDT")
        self.assertEqual(snapshot["open_trades"][1]["pair"], "SOL/USDT")

    def test_health_is_ready_with_fresh_snapshot_and_trade_mode(self) -> None:
        self.manager.create_snapshot(bot_status=self.bot_status, logs=self.logs)

        health = self.manager.health(bot_status=self.bot_status, logs=self.logs)

        self.assertTrue(health["ready"])
        self.assertEqual(health["bridge_status"], "ok")
        self.assertEqual(health["runtime_mode"], "dry_run")

    def test_health_reports_webserver_only_when_runtime_not_trading(self) -> None:
        manager = DryRunManager(
            client=FakeRuntimeClient(runmode="webserver"),
            snapshots_dir=Path(self.temp_dir.name) / "snapshots-webserver",
            smoke_dir=Path(self.temp_dir.name) / "smoke-webserver",
            stale_after_seconds=180,
        )

        health = manager.health(bot_status=self.bot_status, logs=self.logs)

        self.assertFalse(health["ready"])
        self.assertEqual(health["bridge_status"], "webserver_only")
        self.assertEqual(health["blocking_reason"], "webserver_only")

    def test_cached_health_uses_latest_snapshot_without_live_runtime_calls(self) -> None:
        manager = DryRunManager(
            client=FakeRuntimeClient(),
            snapshots_dir=Path(self.temp_dir.name) / "snapshots-cached-health",
            smoke_dir=Path(self.temp_dir.name) / "smoke-cached-health",
            stale_after_seconds=180,
        )
        manager.create_snapshot(bot_status=self.bot_status, logs=self.logs)
        manager.client = FailingRuntimeClient()

        health = manager.cached_health(bot_status=self.bot_status, logs=self.logs)

        self.assertTrue(health["ready"])
        self.assertEqual(health["bridge_status"], "cached_ok")
        self.assertEqual(health["runtime_mode"], "dry_run")

    def test_smoke_test_passes_when_runtime_and_snapshot_are_available(self) -> None:
        result = self.manager.run_smoke_test(bot_status=self.bot_status, logs=self.logs)

        self.assertEqual(result["status"], "pass")
        self.assertIsNotNone(result["snapshot_path"])
        self.assertEqual(self.manager.latest_smoke(bot_id="freqtrade")["status"], "pass")

    def test_smoke_test_fails_for_webserver_only_runtime(self) -> None:
        manager = DryRunManager(
            client=FakeRuntimeClient(runmode="webserver"),
            snapshots_dir=Path(self.temp_dir.name) / "snapshots-fail",
            smoke_dir=Path(self.temp_dir.name) / "smoke-fail",
            stale_after_seconds=180,
        )

        result = manager.run_smoke_test(bot_status=self.bot_status, logs=self.logs)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["blocking_reason"], "webserver_only")

    def test_runtime_warning_filter_ignores_uvicorn_error_logger_info_lines(self) -> None:
        logs = [
            "2026-03-15 05:53:31,544 - uvicorn.error - INFO - Started server process [1]",
            "2026-03-15 05:53:31,545 - uvicorn.error - INFO - Waiting for application startup.",
            "2026-03-15 05:53:32,195 - freqtrade.rpc.rpc_manager - INFO - Sending rpc message: {'type': warning, 'status': 'Dry run is enabled. All trades are simulated.'}",
            "2026-03-15 05:53:33,000 - freqtrade - WARNING - Pairlist refresh delayed",
        ]

        warnings = self.manager._extract_runtime_warnings(logs)

        self.assertEqual(
            warnings,
            [
                "2026-03-15 05:53:32,195 - freqtrade.rpc.rpc_manager - INFO - Sending rpc message: {'type': warning, 'status': 'Dry run is enabled. All trades are simulated.'}",
                "2026-03-15 05:53:33,000 - freqtrade - WARNING - Pairlist refresh delayed",
            ],
        )


class FreqtradeRuntimeClientTests(unittest.TestCase):
    def test_token_login_uses_post_and_basic_auth(self) -> None:
        client = FreqtradeRuntimeClient(
            base_url="http://freqtrade:8080/api/v1",
            username="freqtrader",
            password="change_me_local",
        )

        captured_request = None

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"access_token":"abc","refresh_token":"def"}'

        def _fake_urlopen(req, timeout=0):
            nonlocal captured_request
            captured_request = req
            return _Response()

        with patch("core.freqtrade_runtime.request.urlopen", side_effect=_fake_urlopen):
            payload = client.token_login()

        self.assertEqual(payload["access_token"], "abc")
        self.assertIsNotNone(captured_request)
        self.assertEqual(captured_request.get_method(), "POST")
        self.assertEqual(
            captured_request.full_url,
            "http://freqtrade:8080/api/v1/token/login",
        )
        self.assertTrue(
            str(captured_request.get_header("Authorization", "")).startswith("Basic ")
        )

    def test_http_401_maps_to_auth_failed(self) -> None:
        client = FreqtradeRuntimeClient(
            base_url="http://freqtrade:8080/api/v1",
            username="user",
            password="pass",
        )

        with patch("core.freqtrade_runtime.request.urlopen") as mocked_urlopen:
            mocked_urlopen.side_effect = error.HTTPError(
                url="http://freqtrade:8080/api/v1/show_config",
                code=401,
                msg="Unauthorized",
                hdrs=None,
                fp=io.BytesIO(b""),
            )
            with self.assertRaises(FreqtradeRuntimeError) as ctx:
                client.show_config()

        self.assertEqual(ctx.exception.code, "auth_failed")

    def test_missing_bridge_credentials_raise_bridge_misconfigured(self) -> None:
        client = FreqtradeRuntimeClient(
            base_url="http://freqtrade:8080/api/v1",
            username="",
            password="",
        )

        with self.assertRaises(FreqtradeRuntimeError) as ctx:
            client.show_config()

        self.assertEqual(ctx.exception.code, "bridge_misconfigured")

    def test_timeout_maps_to_runtime_unavailable(self) -> None:
        client = FreqtradeRuntimeClient(
            base_url="http://freqtrade:8080/api/v1",
            username="user",
            password="pass",
        )

        with patch("core.freqtrade_runtime.request.urlopen") as mocked_urlopen:
            mocked_urlopen.side_effect = TimeoutError("timed out")
            with self.assertRaises(FreqtradeRuntimeError) as ctx:
                client.show_config()

        self.assertEqual(ctx.exception.code, "runtime_unavailable")
