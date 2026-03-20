"""Bot lifecycle management for the control layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, NotFound
import yaml


class BotManager:
    """Handles bot start, stop, logs, and state inspection."""

    def __init__(
        self,
        config_path: Path | None = None,
        docker_base_url: str | None = None,
        docker_timeout_seconds: int = 2,
    ) -> None:
        self.config_path = config_path or Path(__file__).with_name("config") / "bots.yaml"
        self.docker_base_url = docker_base_url
        self.docker_timeout_seconds = docker_timeout_seconds
        self._client: docker.DockerClient | None = None
        self._bots = self._load_config()

    def _load_config(self) -> dict[str, dict[str, Any]]:
        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        return {bot["bot_id"]: bot for bot in raw.get("bots", [])}

    def _get_client(self) -> docker.DockerClient:
        if self._client is None:
            if self.docker_base_url:
                self._client = docker.DockerClient(
                    base_url=self.docker_base_url,
                    timeout=self.docker_timeout_seconds,
                )
            else:
                self._client = docker.from_env(timeout=self.docker_timeout_seconds)
        return self._client

    def docker_available(self) -> bool:
        try:
            self._get_client().ping()
            return True
        except DockerException:
            return False

    def list_bots(self) -> list[dict[str, Any]]:
        return [self.get_bot_status(bot_id) for bot_id in self._bots]

    def list_bot_configs(self) -> list[dict[str, Any]]:
        return [dict(bot) for bot in self._bots.values()]

    def get_bot(self, bot_id: str) -> dict[str, Any]:
        if bot_id not in self._bots:
            raise KeyError(f"Unknown bot_id: {bot_id}")
        return self._bots[bot_id]

    def _read_runtime_dry_run(self, bot: dict[str, Any]) -> bool:
        config = self._read_runtime_config(bot)
        if not config:
            return bool(bot.get("dry_run", True))
        return bool(config.get("dry_run", bot.get("dry_run", True)))

    def _read_runtime_config(self, bot: dict[str, Any]) -> dict[str, Any]:
        runtime_config = bot.get("runtime_config")
        if not runtime_config:
            return {}

        config_path = self._resolve_runtime_config_path(str(runtime_config))
        if not config_path.exists():
            return {}

        with config_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _resolve_runtime_config_path(self, runtime_config: str) -> Path:
        config_path = Path(runtime_config)
        if config_path.exists():
            return config_path
        if runtime_config.startswith("/app/") and not Path("/app").exists():
            repo_root = self.config_path.resolve().parents[2]
            return repo_root / runtime_config.removeprefix("/app/")
        return config_path

    def get_runtime_connection(self, bot_id: str) -> dict[str, Any]:
        bot = self.get_bot(bot_id)
        runtime_config = self._read_runtime_config(bot)
        api_server = runtime_config.get("api_server") or {}
        return {
            "base_url": bot.get("runtime_api_base_url", "").rstrip("/"),
            "username": bot.get("runtime_api_username") or api_server.get("username", ""),
            "password": bot.get("runtime_api_password") or api_server.get("password", ""),
            "timeout_seconds": int(bot.get("runtime_api_timeout_seconds", 5)),
            "strategy": runtime_config.get("strategy") or bot.get("strategy"),
        }

    def _get_container(self, bot_id: str):
        bot = self.get_bot(bot_id)
        try:
            return self._get_client().containers.get(bot["container_name"])
        except NotFound:
            return None

    def get_bot_status(self, bot_id: str) -> dict[str, Any]:
        bot = self.get_bot(bot_id)
        container = self._get_container(bot_id)
        state = container.status if container is not None else "missing"
        runtime_connection = self.get_runtime_connection(bot_id)
        return {
            "bot_id": bot_id,
            "container_name": bot["container_name"],
            "description": bot.get("description", ""),
            "strategy": runtime_connection.get("strategy") or bot.get("strategy"),
            "dry_run": self._read_runtime_dry_run(bot),
            "state": state,
            "logs_tail_default": bot.get("logs_tail_default", 200),
        }

    def start_bot(self, bot_id: str) -> dict[str, Any]:
        container = self._get_container(bot_id)
        if container is None:
            raise RuntimeError(f"Container for bot '{bot_id}' was not found.")
        if container.status != "running":
            container.start()
        return self.get_bot_status(bot_id)

    def stop_bot(self, bot_id: str) -> dict[str, Any]:
        container = self._get_container(bot_id)
        if container is None:
            raise RuntimeError(f"Container for bot '{bot_id}' was not found.")
        if container.status == "running":
            container.stop(timeout=10)
        return self.get_bot_status(bot_id)

    def get_bot_logs(self, bot_id: str, tail: int | None = None) -> list[str]:
        bot = self.get_bot(bot_id)
        container = self._get_container(bot_id)
        if container is None:
            return [f"Container for bot '{bot_id}' was not found."]
        lines = tail or bot.get("logs_tail_default", 200)
        raw = container.logs(tail=lines).decode("utf-8", errors="replace")
        return [line for line in raw.splitlines() if line]
