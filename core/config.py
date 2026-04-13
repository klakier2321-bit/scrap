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
    agent_max_parallel_runs: int = 3
    agent_global_daily_budget_usd: float = 5.0
    agent_global_per_run_budget_usd: float = 0.5
    agent_allow_mock_fallback: bool = True
    agent_kill_switch: bool = False
    agent_runtime_freeze: bool = False
    agent_resource_guard_enabled: bool = True
    agent_resource_guard_min_available_memory_mb: int = 1536
    agent_resource_guard_min_available_memory_pct: float = 0.18
    agent_resource_guard_max_load_per_cpu: float = 1.5
    agent_resource_guard_cache_seconds: int = 5
    agent_resource_guard_block_backtests: bool = True
    agent_autopilot_enabled: bool = False
    agent_autopilot_poll_interval_seconds: int = 300
    agent_autopilot_max_cycles: int = 0
    agent_autopilot_config: str = "/app/ai_agents/config/autopilot.yaml"
    crewai_disable_telemetry: bool = True
    agent_tracing_enabled: bool = True
    agent_otlp_http_endpoint: str = "http://tempo:4318/v1/traces"
    repo_checkout_dir: str = "/workspace"
    agent_worktree_root_dir: str = "/workspace/data/agent_worktrees"
    agent_coding_enabled: bool = True
    agent_coding_auto_start: bool = True
    agent_lead_queue_refresh_interval_seconds: int = 300
    agent_coding_dispatcher_poll_interval_seconds: int = 60
    agent_coding_task_timeout_seconds: int = 180
    agent_git_author_name: str = "Crypto System Agent"
    agent_git_author_email: str = "agents@crypto-system.local"
    agent_coding_modules_config: str = "/app/ai_agents/config/coding_modules.yaml"
    # Legacy single-bot bridge settings. Runtime auth should come from the
    # per-bot registry/runtime config via BotManager, not from these globals.
    freqtrade_api_base_url: str = "http://freqtrade:8080/api/v1"
    freqtrade_api_username: str = ""
    freqtrade_api_password: str = ""
    freqtrade_api_timeout_seconds: int = 5
    dry_run_snapshot_stale_seconds: int = 180
    derivatives_binance_enabled: bool = True
    derivatives_binance_base_url: str = "https://fapi.binance.com"
    derivatives_binance_timeout_seconds: int = 8
    derivatives_binance_history_limit: int = 3
    derivatives_binance_period: str = "5m"
    derivatives_stale_seconds: int = 900

    model_config = SettingsConfigDict(
        env_file=".env.ai.control.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def repo_checkout_path(self) -> Path:
        checkout_path = Path(self.repo_checkout_dir)
        if checkout_path.exists():
            return checkout_path
        return self.repo_root

    def _resolve_app_relative_path(self, raw_path: str, *, fallback_relative: str) -> Path:
        path = Path(raw_path)
        if raw_path.startswith("/app/"):
            workspace_candidate = Path("/workspace") / path.relative_to("/app")
            if workspace_candidate.exists() or workspace_candidate.parent.exists():
                return workspace_candidate
            if not Path("/app").exists():
                return self.repo_root / fallback_relative
        return path

    @property
    def log_dir(self) -> Path:
        if self.control_api_log_dir.startswith("/app/"):
            path = Path(self.control_api_log_dir)
            if path.exists() or path.parent.exists():
                return path
            if not Path("/app").exists():
                return self.repo_root / "monitoring" / "logs"
        return Path(self.control_api_log_dir)

    @property
    def data_dir(self) -> Path:
        return self._resolve_app_relative_path(
            self.control_api_data_dir,
            fallback_relative="data/ai_control",
        )

    @property
    def freqtrade_user_data_path(self) -> Path:
        return self._resolve_app_relative_path(
            self.freqtrade_user_data_dir,
            fallback_relative="trading/freqtrade/user_data",
        )

    @property
    def log_file(self) -> Path:
        return self.log_dir / "ai_control.log"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ai_control.db"

    @property
    def strategy_reports_dir(self) -> Path:
        return self.data_dir / "strategy_reports"

    @property
    def strategy_signals_dir(self) -> Path:
        return self.data_dir / "strategy_signals"

    @property
    def strategy_telemetry_dir(self) -> Path:
        return self.data_dir / "strategy_telemetry"

    @property
    def runtime_artifacts_dir(self) -> Path:
        return self.freqtrade_user_data_path / "runtime_artifacts"

    @property
    def futures_runtime_artifacts_dir(self) -> Path:
        return self.runtime_artifacts_dir / "futures"

    @property
    def futures_runtime_global_dir(self) -> Path:
        return self.futures_runtime_artifacts_dir / "global"

    @property
    def dry_run_snapshots_dir(self) -> Path:
        return self.data_dir / "dry_run_snapshots"

    @property
    def dry_run_smoke_dir(self) -> Path:
        return self.data_dir / "dry_run_smoke"

    @property
    def regime_reports_dir(self) -> Path:
        return self.data_dir / "regime"

    @property
    def derivatives_reports_dir(self) -> Path:
        return self.data_dir / "derivatives"

    @property
    def risk_decisions_dir(self) -> Path:
        return self.data_dir / "risk_decisions"

    @property
    def derivatives_vendor_input_dir(self) -> Path:
        return self.data_dir / "derivatives_vendor"

    @property
    def regime_replay_dir(self) -> Path:
        return self.data_dir / "regime_replay"

    @property
    def agent_context_packets_dir(self) -> Path:
        return self.data_dir / "agent_context" / "packets"

    @property
    def agent_runtime_overrides_path(self) -> Path:
        return self.data_dir / "agent_runtime_overrides.json"

    @property
    def runtime_flags_path(self) -> Path:
        return self.data_dir / "runtime_flags.json"

    @property
    def observability_dir(self) -> Path:
        return self.data_dir / "observability"

    @property
    def observability_latest_path(self) -> Path:
        return self.observability_dir / "combined_dashboard.latest.json"

    @property
    def observability_history_path(self) -> Path:
        return self.observability_dir / "combined_dashboard.history.jsonl"

    @property
    def observability_log_path(self) -> Path:
        return self.log_dir / "observability_summary.log"

    @property
    def autopilot_config_path(self) -> Path:
        if self.agent_autopilot_config.startswith("/app/") and not Path("/app").exists():
            return self.repo_root / self.agent_autopilot_config.removeprefix("/app/")
        return Path(self.agent_autopilot_config)

    @property
    def agent_worktree_root_path(self) -> Path:
        worktree_root = Path(self.agent_worktree_root_dir)
        if worktree_root.exists() or self.agent_worktree_root_dir.startswith("/workspace/"):
            return worktree_root
        return self.repo_root / self.agent_worktree_root_dir.lstrip("./")

    @property
    def coding_modules_config_path(self) -> Path:
        if self.agent_coding_modules_config.startswith("/app/") and not Path("/app").exists():
            return self.repo_root / self.agent_coding_modules_config.removeprefix("/app/")
        return Path(self.agent_coding_modules_config)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached settings instance."""
    return AppSettings()
