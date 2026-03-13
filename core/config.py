"""Configuration helpers for the control layer and AI runtime."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application settings loaded from environment variables."""

    agent_use_mock_llm: bool = True
    agent_mode: str = "plan_first"
    agent_litellm_base_url: str = "http://litellm:4000/v1"
    agent_litellm_api_key: str = "change_me"
    control_api_host: str = "0.0.0.0"
    control_api_port: int = 8000
    control_api_log_level: str = "INFO"
    control_api_log_dir: str = "/app/logs"
    control_api_data_dir: str = "/app/data/ai_control"
    docker_socket_path: str = "unix:///var/run/docker.sock"
    freqtrade_user_data_dir: str = "/app/trading/freqtrade/user_data"
    agent_run_timeout_seconds: int = 180
    agent_max_parallel_runs: int = 1
    agent_global_daily_budget_usd: float = 5.0
    agent_global_per_run_budget_usd: float = 0.5
    agent_allow_mock_fallback: bool = True
    agent_kill_switch: bool = False
    crewai_disable_telemetry: bool = True
    agent_tracing_enabled: bool = True
    agent_otlp_http_endpoint: str = "http://tempo:4318/v1/traces"

    model_config = SettingsConfigDict(
        env_file=".env.ai.control.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def log_dir(self) -> Path:
        if self.control_api_log_dir.startswith("/app/") and not Path("/app").exists():
            return self.repo_root / "monitoring" / "logs"
        return Path(self.control_api_log_dir)

    @property
    def data_dir(self) -> Path:
        if self.control_api_data_dir.startswith("/app/") and not Path("/app").exists():
            return self.repo_root / "data" / "ai_control"
        return Path(self.control_api_data_dir)

    @property
    def freqtrade_user_data_path(self) -> Path:
        if self.freqtrade_user_data_dir.startswith("/app/") and not Path("/app").exists():
            return self.repo_root / "trading" / "freqtrade" / "user_data"
        return Path(self.freqtrade_user_data_dir)

    @property
    def log_file(self) -> Path:
        return self.log_dir / "ai_control.log"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ai_control.db"

    @property
    def strategy_reports_dir(self) -> Path:
        return self.data_dir / "strategy_reports"


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached settings instance."""
    return AppSettings()
