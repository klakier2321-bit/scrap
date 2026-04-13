from __future__ import annotations

import json
import tempfile
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

    def test_get_runtime_connection_prefers_runtime_config_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_config = root / "runtime.json"
            runtime_config.write_text(
                json.dumps(
                    {
                        "strategy": "DefenseOnlyV1RuntimeStrategy",
                        "api_server": {
                            "username": "runtime_user",
                            "password": "runtime_pass",
                        },
                    }
                ),
                encoding="utf-8",
            )
            config_path = root / "bots.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "bots:",
                        '  - bot_id: "ft_defense_only_v1"',
                        '    container_name: "crypto_ft_defense_only_v1"',
                        '    strategy: "DefenseOnlyV1RuntimeStrategy"',
                        f'    runtime_config: "{runtime_config.as_posix()}"',
                        '    runtime_api_base_url: "http://ft_defense_only_v1:8080/api/v1"',
                        '    runtime_api_username: "fallback_user"',
                        '    runtime_api_password: "fallback_pass"',
                    ]
                ),
                encoding="utf-8",
            )
            manager = BotManager(config_path=config_path)

            runtime_connection = manager.get_runtime_connection("ft_defense_only_v1")

            self.assertEqual(runtime_connection["username"], "runtime_user")
            self.assertEqual(runtime_connection["password"], "runtime_pass")
