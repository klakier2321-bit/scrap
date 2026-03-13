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
    ) -> None:
        self.config_path = config_path or Path(__file__).with_name("config") / "bots.yaml"
        self.docker_base_url = docker_base_url
        self._client: docker.DockerClient | None = None
        self._bots = self._load_config()

    def _load_config(self) -> dict[str, dict[str, Any]]:
        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        return {bot["bot_id"]: bot for bot in raw.get("bots", [])}

    def _get_client(self) -> docker.DockerClient:
        if self._client is None:
            if self.docker_base_url:
                self._client = docker.DockerClient(base_url=self.docker_base_url)
            else:
                self._client = docker.from_env()
        return self._client

    def docker_available(self) -> bool:
        try:
            self._get_client().ping()
            return True
        except DockerException:
            return False

    def list_bots(self) -> list[dict[str, Any]]:
        return [self.get_bot_status(bot_id) for bot_id in self._bots]

    def get_bot(self, bot_id: str) -> dict[str, Any]:
        if bot_id not in self._bots:
            raise KeyError(f"Unknown bot_id: {bot_id}")
        return self._bots[bot_id]

    def _read_runtime_dry_run(self, bot: dict[str, Any]) -> bool:
        runtime_config = bot.get("runtime_config")
        if not runtime_config:
            return bool(bot.get("dry_run", True))

        config_path = Path(runtime_config)
        if not config_path.exists():
            return bool(bot.get("dry_run", True))

        with config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        return bool(config.get("dry_run", bot.get("dry_run", True)))

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
        return {
            "bot_id": bot_id,
            "container_name": bot["container_name"],
            "description": bot.get("description", ""),
            "strategy": bot.get("strategy"),
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
