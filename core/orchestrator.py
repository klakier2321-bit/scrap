"""Main coordination module for the control layer."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from time import monotonic
import uuid
from typing import Any

from ai_agents.runtime.service import AgentRuntimeService
from ai_agents.runtime.context_packets import (
    build_executive_packet as build_agent_executive_packet,
    build_runtime_state_packet,
)
from opentelemetry import trace

from .bot_manager import BotManager
from .autopilot import AutopilotService
from .coding_service import CodingSupervisorService
from .config import AppSettings
from .derivatives_feed import DerivativesFeed
from .dry_run_manager import DryRunManager
from .executive_report import ExecutiveReportService
from .freqtrade_runtime import FreqtradeRuntimeClient, FreqtradeRuntimeError
from .metrics import (
    record_blocked_call,
    record_cache_hit,
    record_cache_miss,
    record_dry_run_bridge_error,
    record_dry_run_smoke_failure,
    record_human_escalation,
    record_review_required,
    record_run_created,
    record_run_failed,
    record_run_started,
    record_run_succeeded,
    record_scope_violation,
)
from .operator_home import build_operator_home
from .observability_summary import (
    build_observability_summary,
    load_latest_observability_summary,
    load_observability_summary_history,
    persist_observability_summary,
)
from .regime_detector import RegimeDetector
from .risk_manager import RiskManager
from .runtime_flags import load_runtime_flags, merge_runtime_flags
from .runtime_artifacts import (
    aggregate_portfolio_snapshots,
    aggregate_strategy_layer_reports,
    publish_global_portfolio,
    publish_risk_decision as publish_runtime_risk_decision,
    publish_strategy_report as publish_runtime_strategy_report,
    strategy_id_from_bot_id,
)
from .storage import RunStore
from .strategy_layer import StrategyLayerService
from .strategy_manager import StrategyManager
from .system_resource_guard import SystemResourceGuard
from monitoring.control_status import create_report as create_control_status_report
from monitoring.control_status import write_report_files as write_control_status_files


logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class Orchestrator:
    """Coordinates bot actions, agent runs, metrics, and persistence."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.bot_manager = BotManager(docker_base_url=settings.docker_socket_path)
        self.risk_manager = RiskManager(risk_output_dir=settings.risk_decisions_dir)
        self.strategy_manager = StrategyManager(
            user_data_dir=settings.freqtrade_user_data_path,
            reports_dir=settings.strategy_reports_dir,
            dry_run_snapshots_dir=settings.dry_run_snapshots_dir,
            strategy_signals_dir=settings.strategy_signals_dir,
        )
        self.strategy_layer = StrategyLayerService(
            manifests_dir=settings.repo_checkout_path / "research" / "strategies" / "manifests",
            output_dir=settings.strategy_signals_dir,
            telemetry_dir=settings.strategy_telemetry_dir,
        )
        self.regime_detector = RegimeDetector(
            user_data_dir=settings.freqtrade_user_data_path,
            output_dir=settings.regime_reports_dir,
            replay_dir=settings.regime_replay_dir,
            research_dir=settings.repo_checkout_path / "research",
        )
        self.derivatives_feed = DerivativesFeed(
            user_data_dir=settings.freqtrade_user_data_path,
            output_dir=settings.derivatives_reports_dir,
            vendor_input_dir=settings.derivatives_vendor_input_dir,
            binance_enabled=settings.derivatives_binance_enabled,
            binance_base_url=settings.derivatives_binance_base_url,
            binance_timeout_seconds=settings.derivatives_binance_timeout_seconds,
            binance_history_limit=settings.derivatives_binance_history_limit,
            binance_period=settings.derivatives_binance_period,
            stale_after_seconds=settings.derivatives_stale_seconds,
        )
        self.freqtrade_runtime_client = FreqtradeRuntimeClient(
            base_url=settings.freqtrade_api_base_url,
            username=settings.freqtrade_api_username,
            password=settings.freqtrade_api_password,
            timeout_seconds=settings.freqtrade_api_timeout_seconds,
        )
        self.dry_run_manager = DryRunManager(
            client=self.freqtrade_runtime_client,
            snapshots_dir=settings.dry_run_snapshots_dir,
            smoke_dir=settings.dry_run_smoke_dir,
            stale_after_seconds=settings.dry_run_snapshot_stale_seconds,
        )
        self.resource_guard = SystemResourceGuard(
            settings=settings,
            docker_base_url=settings.docker_socket_path,
        )
        self._runtime_flags = load_runtime_flags(settings.runtime_flags_path)
        self.store = RunStore(settings.database_path)
        stale_runs = self.store.reconcile_stale_runs()
        self.agent_runtime = AgentRuntimeService(
            settings=settings,
            resource_guard_provider=self.operation_guard_snapshot,
        )
        self.executive_report = ExecutiveReportService(settings.repo_checkout_path)
        self.coding_supervisor = CodingSupervisorService(
            settings=settings,
            store=self.store,
            agent_runtime=self.agent_runtime,
            executive_report_provider=self.get_executive_report,
            resource_guard_provider=self.operation_guard_snapshot,
        )
        self.executor = ThreadPoolExecutor(max_workers=settings.agent_max_parallel_runs)
        self.futures: dict[str, Future[Any]] = {}
        self.autopilot = AutopilotService(
            orchestrator=self,
            config_path=settings.autopilot_config_path,
            poll_interval_seconds=settings.agent_autopilot_poll_interval_seconds,
        )
        if stale_runs["queued"] or stale_runs["running"]:
            logger.warning(
                "Reconciled stale agent runs after startup.",
                extra={
                    "event": "reconcile_stale_runs",
                    "queued_count": stale_runs["queued"],
                    "running_count": stale_runs["running"],
                },
            )

    def health(self) -> dict[str, Any]:
        agent_runtime = self.agent_runtime_status()
        return {
            "status": "ok",
            "agent_mode": self.settings.agent_mode,
            "mock_llm": self.settings.agent_use_mock_llm,
            "litellm_url": self.settings.agent_litellm_base_url,
            "kill_switch": self.effective_kill_switch_enabled(),
            "runtime_freeze": self.effective_runtime_freeze_enabled(),
            "docker_available": self.bot_manager.docker_available(),
            "agents_status": agent_runtime["agents_status"],
            "agents_reason": agent_runtime.get("agents_reason"),
            "resource_guard": self.operation_guard_snapshot(),
        }

    def _operator_runtime_flags(self) -> dict[str, bool]:
        self._runtime_flags = load_runtime_flags(self.settings.runtime_flags_path)
        return dict(self._runtime_flags)

    def get_runtime_flags(self) -> dict[str, Any]:
        operator_flags = self._operator_runtime_flags()
        return {
            "kill_switch": {
                "flag_name": "kill_switch",
                "env_enabled": bool(self.settings.agent_kill_switch),
                "operator_enabled": bool(operator_flags.get("kill_switch")),
                "effective_enabled": bool(self.settings.agent_kill_switch or operator_flags.get("kill_switch")),
            },
            "runtime_freeze": {
                "flag_name": "runtime_freeze",
                "env_enabled": bool(self.settings.agent_runtime_freeze),
                "operator_enabled": bool(operator_flags.get("runtime_freeze")),
                "effective_enabled": bool(
                    self.settings.agent_runtime_freeze or operator_flags.get("runtime_freeze")
                ),
            },
        }

    def update_runtime_flags(
        self,
        *,
        kill_switch: bool | None = None,
        runtime_freeze: bool | None = None,
    ) -> dict[str, Any]:
        self._runtime_flags = merge_runtime_flags(
            self.settings.runtime_flags_path,
            kill_switch=kill_switch,
            runtime_freeze=runtime_freeze,
        )
        return self.get_runtime_flags()

    def effective_kill_switch_enabled(self) -> bool:
        flags = self.get_runtime_flags()
        return bool((flags.get("kill_switch") or {}).get("effective_enabled"))

    def effective_runtime_freeze_enabled(self) -> bool:
        flags = self.get_runtime_flags()
        return bool((flags.get("runtime_freeze") or {}).get("effective_enabled"))

    def operation_guard_snapshot(self) -> dict[str, Any]:
        snapshot = dict(self.resource_guard.snapshot() or {})
        snapshot.setdefault("enabled", True)
        snapshot.setdefault("allow_new_runs", True)
        snapshot.setdefault("allow_coding_dispatch", True)
        snapshot.setdefault("blocked_reasons", [])
        snapshot.setdefault("notes", [])
        snapshot.setdefault("resources", {})
        if self.effective_kill_switch_enabled():
            snapshot["allow_new_runs"] = False
            snapshot["allow_coding_dispatch"] = False
            snapshot["primary_reason"] = "kill_switch_enabled"
            snapshot["operator_message"] = "Kill switch jest aktywny i blokuje nowe akcje AI."
            snapshot["blocked_reasons"] = list(
                dict.fromkeys(list(snapshot.get("blocked_reasons") or []) + ["kill_switch_enabled"])
            )
            snapshot["notes"] = list(
                dict.fromkeys(list(snapshot.get("notes") or []) + ["Operator kill switch blokuje nowe runy i dispatch."])
            )
            return snapshot
        if self.effective_runtime_freeze_enabled():
            snapshot["allow_new_runs"] = False
            snapshot["allow_coding_dispatch"] = False
            snapshot["primary_reason"] = "runtime_freeze_enabled"
            snapshot["operator_message"] = "Runtime freeze jest aktywny i blokuje nowe akcje AI."
            snapshot["blocked_reasons"] = list(
                dict.fromkeys(list(snapshot.get("blocked_reasons") or []) + ["runtime_freeze_enabled"])
            )
            snapshot["notes"] = list(
                dict.fromkeys(list(snapshot.get("notes") or []) + ["Operator runtime freeze pauzuje nowe runy i dispatch."])
            )
        return snapshot

    def _has_valid_llm_key(self) -> bool:
        key = str(self.settings.agent_litellm_api_key or "").strip()
        if not key:
            return False
        lowered = key.lower()
        if lowered in {"change_me", "disabled", "none", "null"}:
            return False
        if key.startswith("DISABLED_TEMP_"):
            return False
        return True

    def agent_runtime_status(self) -> dict[str, Any]:
        if self.effective_kill_switch_enabled():
            return {
                "agents_status": "agents_disabled",
                "agents_reason": "kill_switch_enabled",
            }
        if self.effective_runtime_freeze_enabled():
            return {
                "agents_status": "agents_disabled",
                "agents_reason": "runtime_freeze_enabled",
            }
        if not self.settings.agent_use_mock_llm and not self._has_valid_llm_key():
            return {
                "agents_status": "agents_disabled",
                "agents_reason": "missing_valid_api_key",
            }
        resource_guard = self.operation_guard_snapshot()
        if not bool(resource_guard.get("allow_new_runs", True)):
            return {
                "agents_status": "agents_guarded",
                "agents_reason": f"host_resource_guard:{resource_guard.get('primary_reason') or 'blocked'}",
                "resource_guard": resource_guard,
            }
        if self.settings.agent_use_mock_llm or not self.settings.agent_autopilot_enabled:
            return {
                "agents_status": "agents_guarded",
                "agents_reason": "manual_or_mock_mode",
                "resource_guard": resource_guard,
            }
        return {
            "agents_status": "agents_active_limited",
            "agents_reason": "budget_guarded_runtime",
            "resource_guard": resource_guard,
        }

    def list_bots(self) -> list[dict[str, Any]]:
        return self.bot_manager.list_bots()

    def get_bot_status(self, bot_id: str) -> dict[str, Any]:
        return self.bot_manager.get_bot_status(bot_id)

    def start_bot(self, bot_id: str) -> dict[str, Any]:
        bot_status = self.bot_manager.get_bot_status(bot_id)
        self.risk_manager.ensure_bot_start_allowed(bot_status)
        return self.bot_manager.start_bot(bot_id)

    def stop_bot(self, bot_id: str) -> dict[str, Any]:
        return self.bot_manager.stop_bot(bot_id)

    def get_bot_logs(self, bot_id: str, tail: int | None = None) -> list[str]:
        return self.bot_manager.get_bot_logs(bot_id, tail=tail)

    def _runtime_client_for_bot(self, bot_id: str) -> FreqtradeRuntimeClient:
        runtime_connection = self.bot_manager.get_runtime_connection(bot_id)
        return FreqtradeRuntimeClient(
            base_url=runtime_connection["base_url"],
            username=runtime_connection["username"],
            password=runtime_connection["password"],
            timeout_seconds=runtime_connection["timeout_seconds"],
        )

    def _runtime_manager_for_bot(self, bot_id: str) -> DryRunManager:
        return DryRunManager(
            client=self._runtime_client_for_bot(bot_id),
            snapshots_dir=self.settings.dry_run_snapshots_dir,
            smoke_dir=self.settings.dry_run_smoke_dir,
            stale_after_seconds=self.settings.dry_run_snapshot_stale_seconds,
        )

    def _canonical_futures_bot_configs(self) -> list[dict[str, Any]]:
        return [
            bot
            for bot in self.bot_manager.list_bot_configs()
            if str(bot.get("runtime_group") or "") == "futures_canonical"
        ]

    def _canonical_futures_bot_ids(self) -> list[str]:
        return [str(bot.get("bot_id")) for bot in self._canonical_futures_bot_configs() if bot.get("bot_id")]

    def _is_canonical_futures_bot(self, bot_id: str) -> bool:
        return bot_id in set(self._canonical_futures_bot_ids())

    def _strategy_filter_for_bot(self, bot_id: str) -> list[str] | None:
        strategy_id = strategy_id_from_bot_id(bot_id)
        if strategy_id:
            return [strategy_id]
        return None

    def get_futures_cluster_health(self, *, refresh_runtime: bool = True) -> dict[str, Any]:
        bot_ids = self._canonical_futures_bot_ids()
        healths = [
            self.get_dry_run_health(bot_id=bot_id, refresh_runtime=refresh_runtime)
            for bot_id in bot_ids
        ]
        if not healths:
            return {}
        ready_all = all(bool(item.get("ready")) for item in healths)
        warnings: list[str] = []
        for item in healths:
            warnings.extend(list(item.get("warnings") or []))
        snapshot_ages = [
            float(item.get("snapshot_age_seconds"))
            for item in healths
            if item.get("snapshot_age_seconds") is not None
        ]
        snapshot_timestamps = []
        smoke_timestamps = []
        for item in healths:
            last_snapshot_at = item.get("last_snapshot_at")
            if last_snapshot_at:
                try:
                    snapshot_timestamps.append(
                        datetime.fromisoformat(str(last_snapshot_at).replace("Z", "+00:00"))
                    )
                except ValueError:
                    pass
            last_smoke_at = item.get("last_smoke_at")
            if last_smoke_at:
                try:
                    smoke_timestamps.append(
                        datetime.fromisoformat(str(last_smoke_at).replace("Z", "+00:00"))
                    )
                except ValueError:
                    pass
        return {
            "bot_id": "futures_canonical_cluster",
            "runtime_group": "futures_canonical",
            "member_bot_ids": bot_ids,
            "bot_state": "running" if ready_all else "degraded",
            "dry_run": True,
            "runtime_mode": "futures_cluster",
            "bridge_status": "ok" if ready_all else "degraded",
            "api_authenticated": all(bool(item.get("api_authenticated")) for item in healths),
            "ready": ready_all,
            "blocking_reason": None if ready_all else "cluster_member_not_ready",
            "snapshot_available": all(bool(item.get("snapshot_available")) for item in healths),
            "snapshot_age_seconds": max(snapshot_ages) if snapshot_ages else None,
            "last_snapshot_at": min(snapshot_timestamps).isoformat() if snapshot_timestamps else None,
            "last_smoke_status": "pass" if all(item.get("last_smoke_status") == "pass" for item in healths) else "degraded",
            "last_smoke_at": min(smoke_timestamps).isoformat() if smoke_timestamps else None,
            "warnings": list(dict.fromkeys(warnings))[:10],
            "members": healths,
        }

    def get_futures_cluster_snapshot(self, *, refresh_if_stale: bool = False) -> dict[str, Any] | None:
        bot_ids = self._canonical_futures_bot_ids()
        snapshots: list[dict[str, Any]] = []
        for bot_id in bot_ids:
            snapshot = self.get_latest_dry_run_snapshot(bot_id=bot_id, refresh_if_stale=refresh_if_stale)
            if snapshot is not None:
                snapshots.append(snapshot)
        if not snapshots:
            return None
        aggregated = aggregate_portfolio_snapshots(snapshots, bot_ids=bot_ids)
        publish_global_portfolio(self.settings.futures_runtime_artifacts_dir, aggregated)
        return aggregated

    def get_dry_run_health(
        self,
        bot_id: str = "freqtrade",
        *,
        refresh_runtime: bool = True,
    ) -> dict[str, Any]:
        bot_status = self.bot_manager.get_bot_status(bot_id)
        logs = self.bot_manager.get_bot_logs(bot_id, tail=200)
        runtime_manager = self._runtime_manager_for_bot(bot_id)
        if refresh_runtime:
            return runtime_manager.health(bot_status=bot_status, logs=logs)
        return runtime_manager.cached_health(bot_status=bot_status, logs=logs)

    def create_dry_run_snapshot(self, bot_id: str = "freqtrade") -> dict[str, Any]:
        bot_status = self.bot_manager.get_bot_status(bot_id)
        logs = self.bot_manager.get_bot_logs(bot_id, tail=200)
        try:
            return self._runtime_manager_for_bot(bot_id).create_snapshot(bot_status=bot_status, logs=logs)
        except FreqtradeRuntimeError as exc:
            record_dry_run_bridge_error(exc.code)
            raise

    def get_latest_dry_run_snapshot(
        self,
        bot_id: str = "freqtrade",
        *,
        refresh_if_stale: bool = False,
    ) -> dict[str, Any] | None:
        if not refresh_if_stale:
            return self.dry_run_manager.latest_snapshot(bot_id=bot_id)
        bot_status = self.bot_manager.get_bot_status(bot_id)
        logs = self.bot_manager.get_bot_logs(bot_id, tail=200)
        try:
            return self._runtime_manager_for_bot(bot_id).sync_snapshot_if_stale(
                bot_status=bot_status,
                logs=logs,
            )
        except FreqtradeRuntimeError as exc:
            record_dry_run_bridge_error(exc.code)
            logger.warning(
                "Dry run snapshot refresh failed.",
                extra={
                    "bot_id": bot_id,
                    "event": "dry_run_snapshot_refresh_failed",
                    "blocked_reason": exc.code,
                },
            )
            return self.dry_run_manager.latest_snapshot(bot_id=bot_id)

    def list_dry_run_snapshot_history(
        self,
        bot_id: str = "freqtrade",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.dry_run_manager.list_snapshots(bot_id=bot_id, limit=limit)

    def run_dry_run_smoke_test(self, bot_id: str = "freqtrade") -> dict[str, Any]:
        bot_status = self.bot_manager.get_bot_status(bot_id)
        logs = self.bot_manager.get_bot_logs(bot_id, tail=200)
        result = self._runtime_manager_for_bot(bot_id).run_smoke_test(bot_status=bot_status, logs=logs)
        if result.get("status") != "pass":
            record_dry_run_smoke_failure(
                bot_id,
                result.get("blocking_reason") or "unknown",
            )
        return result

    def get_latest_dry_run_smoke(self, bot_id: str = "freqtrade") -> dict[str, Any] | None:
        return self.dry_run_manager.latest_smoke(bot_id=bot_id)

    def get_latest_strategy_report(self, strategy_name: str | None = None) -> dict[str, Any] | None:
        return self.strategy_manager.latest_strategy_report(strategy_name=strategy_name)

    def _load_strategy_context(
        self,
        strategy_name: str | None = None,
        *,
        refresh_runtime: bool = True,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
        report = self.strategy_manager.latest_strategy_report(strategy_name=strategy_name)
        if report is None:
            return None, None, None, None

        latest_snapshot = self.get_latest_dry_run_snapshot(refresh_if_stale=refresh_runtime)
        assessment = self.strategy_manager.latest_strategy_assessment(
            strategy_name=report["strategy_name"]
        )
        if (
            assessment is not None
            and (
                assessment.get("source_run_id") != report.get("source_run_id")
                or assessment.get("source_archive") != report.get("source_archive")
            )
        ):
            assessment = None

        readiness_gate = self.risk_manager.evaluate_strategy_readiness(
            strategy_report=report,
            dry_run_snapshot=latest_snapshot,
            strategy_assessment=assessment,
        )
        return report, latest_snapshot, assessment, readiness_gate

    def get_latest_strategy_report_with_assessment(
        self,
        strategy_name: str | None = None,
        *,
        refresh_runtime: bool = True,
    ) -> dict[str, Any] | None:
        report, latest_snapshot, assessment, readiness_gate = self._load_strategy_context(
            strategy_name=strategy_name,
            refresh_runtime=refresh_runtime,
        )
        if report is None:
            return None
        if assessment is None and refresh_runtime:
            assessment = self.generate_strategy_assessment(strategy_name=report["strategy_name"])
        readiness_gate = self.risk_manager.evaluate_strategy_readiness(
            strategy_report=report,
            dry_run_snapshot=latest_snapshot,
            strategy_assessment=assessment,
        )
        return self.strategy_manager.merge_report_with_assessment(
            report,
            assessment,
            readiness_gate,
        )

    def list_strategy_report_history(
        self,
        strategy_name: str | None = None,
        limit: int = 20,
        *,
        refresh_runtime: bool = True,
    ) -> list[dict[str, Any]]:
        history = self.strategy_manager.list_strategy_reports(
            strategy_name=strategy_name,
            limit=limit,
        )
        latest_snapshot = self.get_latest_dry_run_snapshot(refresh_if_stale=refresh_runtime)
        merged: list[dict[str, Any]] = []
        for report in history:
            assessment = self.strategy_manager.get_assessment_for_report(
                report["strategy_name"],
                report.get("source_run_id"),
                report.get("source_archive"),
            )
            readiness_gate = self.risk_manager.evaluate_strategy_readiness(
                strategy_report=report,
                dry_run_snapshot=latest_snapshot,
                strategy_assessment=assessment,
            )
            merged.append(
                self.strategy_manager.merge_report_with_assessment(
                    report,
                    assessment,
                    readiness_gate,
                )
            )
        return merged

    def get_latest_regime_report(self) -> dict[str, Any] | None:
        report = self.regime_detector.latest_report()
        if report is None:
            return None
        replay_report = self.regime_detector.latest_replay_report()
        if (
            not isinstance(report.get("derivatives_state"), dict)
            or "risk_regime" not in report
            or (
                replay_report is not None
                and report.get("outcome_tracking_status") != "replay_backfilled"
            )
        ):
            return self.generate_regime_report()
        return report

    def list_regime_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.regime_detector.list_reports(limit=limit)

    def generate_regime_report(self) -> dict[str, Any]:
        derivatives_report = self.get_latest_derivatives_report()
        if derivatives_report is None:
            derivatives_report = self.generate_derivatives_report()
        return self.regime_detector.generate_report(derivatives_report=derivatives_report)

    def get_latest_derivatives_report(self) -> dict[str, Any] | None:
        return self.derivatives_feed.latest_report()

    def list_derivatives_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.derivatives_feed.list_reports(limit=limit)

    def generate_derivatives_report(self) -> dict[str, Any]:
        return self.derivatives_feed.generate_report()

    def get_latest_risk_decision(self, bot_id: str = "ft_trend_pullback_continuation_v1") -> dict[str, Any] | None:
        decision = self.risk_manager.latest_risk_decision(bot_id=bot_id)
        if decision is None:
            return None
        if self._is_canonical_futures_bot(bot_id):
            enforcement_path = self.settings.futures_runtime_artifacts_dir / bot_id / "risk" / "enforcement-latest.json"
            if enforcement_path.exists():
                try:
                    enforcement = json.loads(enforcement_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    enforcement = {}
                for key in (
                    "hard_enforcement_enabled",
                    "enforced_by",
                    "last_enforcement_status",
                    "last_blocked_order_reason_codes",
                    "last_strategy_id",
                    "last_pair",
                    "last_side",
                    "last_final_stake",
                    "last_final_leverage",
                    "enforcement_counters",
                ):
                    if key in enforcement:
                        decision[key] = enforcement[key]
        return decision

    def generate_risk_decision(self, bot_id: str = "ft_trend_pullback_continuation_v1") -> dict[str, Any]:
        regime_report = self.get_latest_regime_report()
        if regime_report is None:
            regime_report = self.generate_regime_report()
        dry_run_snapshot = None
        if self._is_canonical_futures_bot(bot_id):
            dry_run_snapshot = self.get_futures_cluster_snapshot(refresh_if_stale=True)
        else:
            try:
                dry_run_snapshot = self.get_latest_dry_run_snapshot(
                    bot_id=bot_id,
                    refresh_if_stale=True,
                )
            except KeyError:
                dry_run_snapshot = None
        portfolio_state = self.risk_manager.build_portfolio_state_from_snapshot(dry_run_snapshot)
        decision = self.risk_manager.evaluate_risk(
            regime_report=regime_report,
            strategy_manifests=self.strategy_manager.list_strategy_manifests(),
            portfolio_state=portfolio_state,
            bot_id=bot_id,
        )
        if self._is_canonical_futures_bot(bot_id):
            publish_runtime_risk_decision(self.settings.futures_runtime_artifacts_dir, bot_id, decision)
        return decision

    def get_latest_regime_replay(self) -> dict[str, Any] | None:
        return self.regime_detector.latest_replay_report()

    def list_regime_replay_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.regime_detector.list_replay_reports(limit=limit)

    def generate_regime_replay(self) -> dict[str, Any]:
        return self.regime_detector.generate_replay_report()

    def generate_strategy_assessment(
        self,
        strategy_name: str | None = None,
    ) -> dict[str, Any]:
        report, latest_snapshot, _assessment, readiness_gate = self._load_strategy_context(
            strategy_name=strategy_name
        )
        if report is None:
            raise KeyError("No strategy report is available yet.")
        assessment = self.agent_runtime.generate_strategy_assessment(
            report,
            dry_run_snapshot=latest_snapshot,
            readiness_gate=readiness_gate,
        )
        return self.strategy_manager.persist_strategy_assessment(report, assessment)

    def get_latest_strategy_layer_report(
        self,
        bot_id: str = "ft_trend_pullback_continuation_v1",
    ) -> dict[str, Any] | None:
        return self.strategy_manager.latest_strategy_layer_report(bot_id=bot_id)

    def get_latest_futures_cluster_strategy_layer_report(self) -> dict[str, Any] | None:
        bot_ids = self._canonical_futures_bot_ids()
        reports = [
            report
            for bot_id in bot_ids
            for report in [self.get_latest_strategy_layer_report(bot_id=bot_id)]
            if report is not None
        ]
        if not reports:
            return None
        return aggregate_strategy_layer_reports(reports, bot_ids=bot_ids)

    def generate_strategy_layer_report(
        self,
        bot_id: str = "ft_trend_pullback_continuation_v1",
    ) -> dict[str, Any]:
        regime_report = self.get_latest_regime_report()
        if regime_report is None:
            regime_report = self.generate_regime_report()
        risk_decision = self.get_latest_risk_decision(bot_id=bot_id)
        if risk_decision is None:
            risk_decision = self.generate_risk_decision(bot_id=bot_id)
        report = self.strategy_layer.generate_report(
            regime_report=regime_report,
            risk_decision=risk_decision,
            bot_id=bot_id,
            strategy_filter_ids=self._strategy_filter_for_bot(bot_id),
        )
        if self._is_canonical_futures_bot(bot_id):
            publish_runtime_strategy_report(self.settings.futures_runtime_artifacts_dir, bot_id, report)
        return report

    def list_agents(self) -> list[dict[str, Any]]:
        return self.agent_runtime.list_agents()

    def get_agent_runtime_overrides(self) -> dict[str, Any]:
        return self.agent_runtime.get_runtime_overrides()

    def update_agent_runtime_override(
        self,
        *,
        agent_name: str,
        enabled: bool | None = None,
        daily_budget_usd: float | None = None,
        per_run_budget_usd: float | None = None,
    ) -> dict[str, Any]:
        return self.agent_runtime.update_agent_override(
            agent_name=agent_name,
            enabled=enabled,
            daily_budget_usd=daily_budget_usd,
            per_run_budget_usd=per_run_budget_usd,
        )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_runs(limit=limit)

    def _is_chat_run(self, run: dict[str, Any]) -> bool:
        metadata = dict((run.get("payload_json") or {}).get("metadata") or {})
        return bool(metadata.get("chat_mode"))

    def _chat_thread_id_for_run(self, run: dict[str, Any]) -> str | None:
        metadata = dict((run.get("payload_json") or {}).get("metadata") or {})
        thread_id = metadata.get("chat_thread_id")
        return str(thread_id) if thread_id else None

    def _find_active_chat_run(self, thread_id: str) -> dict[str, Any] | None:
        for run in self.store.list_runs(limit=200):
            if self._chat_thread_id_for_run(run) != thread_id:
                continue
            if run.get("status") in {"queued", "running", "awaiting_approval"}:
                return run
        return None

    @staticmethod
    def _summarize_run_for_chat(run: dict[str, Any]) -> dict[str, Any]:
        result_json = dict(run.get("result_json") or {})
        review_json = dict(run.get("review_json") or {})
        summary = ""
        if result_json:
            summary = str(
                result_json.get("summary")
                or result_json.get("reply")
                or result_json.get("current_focus")
                or ""
            ).strip()
        if not summary and review_json:
            summary = str(
                review_json.get("decision")
                or review_json.get("main_findings")
                or ""
            ).strip()
        return {
            "run_id": run.get("run_id"),
            "status": run.get("status"),
            "goal": run.get("goal"),
            "created_at": run.get("created_at"),
            "finished_at": run.get("finished_at"),
            "blocked_reason": run.get("blocked_reason"),
            "summary": summary[:280] if summary else None,
        }

    def _build_agent_chat_context(self, agent_name: str) -> dict[str, Any]:
        agent = next(
            (item for item in self.list_agents() if item.get("name") == agent_name),
            None,
        )
        observability_summary = self.get_latest_observability_summary() or {}
        current_work = [
            item
            for item in list(observability_summary.get("current_work") or [])
            if str(item.get("owner_name") or "") == agent_name
        ][:4]
        recent_runs = [
            self._summarize_run_for_chat(run)
            for run in self.store.list_runs(limit=100)
            if run.get("agent_name") == agent_name
        ][:5]
        coding_tasks = [
            {
                "task_id": task.get("task_id"),
                "module_id": task.get("module_id"),
                "status": task.get("status"),
                "goal": task.get("goal"),
            }
            for task in self.store.list_coding_tasks(limit=50)
            if task.get("owner_agent") == agent_name
        ][:5]
        runtime_status = self.agent_runtime_status()
        return {
            "agent": {
                "name": agent_name,
                "role": (agent or {}).get("role"),
                "domain": (agent or {}).get("domain"),
                "activation_mode": (agent or {}).get("activation_mode"),
                "operational_state": (agent or {}).get("operational_state"),
                "handoff_targets": list((agent or {}).get("handoff_targets") or [])[:8],
                "strategy_scope": (agent or {}).get("strategy_scope"),
            },
            "current_work": current_work,
            "recent_runs": recent_runs,
            "coding_tasks": coding_tasks,
            "runtime": {
                "agents_status": runtime_status.get("agents_status"),
                "agents_reason": runtime_status.get("agents_reason"),
                "autopilot_running": bool(self.autopilot.status().get("running")),
                "coding_supervisor_running": bool(self.coding_status().get("running")),
                "resource_guard_primary_reason": (
                    self.operation_guard_snapshot().get("primary_reason")
                ),
            },
            "observability_operator_attention": list(
                observability_summary.get("operator_attention") or []
            )[:5],
        }

    def list_chat_threads(self, limit: int = 50) -> list[dict[str, Any]]:
        threads = self.store.list_chat_threads(limit=limit)
        summaries: list[dict[str, Any]] = []
        for thread in threads:
            messages = self.store.list_chat_messages(thread["thread_id"], limit=1)
            active_run = self._find_active_chat_run(thread["thread_id"])
            last_message = messages[-1] if messages else None
            summaries.append(
                {
                    **thread,
                    "last_message_preview": (
                        str(last_message.get("content") or "")[:160] if last_message else None
                    ),
                    "message_count": len(self.store.list_chat_messages(thread["thread_id"], limit=200)),
                    "active_run_id": (active_run or {}).get("run_id"),
                    "active_run_status": (active_run or {}).get("status"),
                }
            )
        return summaries

    def get_chat_thread(self, thread_id: str, *, limit: int = 200) -> dict[str, Any]:
        thread = self.store.get_chat_thread(thread_id)
        if thread is None:
            raise KeyError(f"Unknown chat thread: {thread_id}")
        messages = self.store.list_chat_messages(thread_id, limit=limit)
        active_run = self._find_active_chat_run(thread_id)
        last_message = messages[-1] if messages else None
        return {
            **thread,
            "last_message_preview": (
                str(last_message.get("content") or "")[:160] if last_message else None
            ),
            "message_count": len(messages),
            "active_run_id": (active_run or {}).get("run_id"),
            "active_run_status": (active_run or {}).get("status"),
            "messages": messages,
        }

    def create_chat_thread(
        self,
        *,
        agent_name: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        if agent_name not in {item.get("name") for item in self.list_agents()}:
            raise KeyError(f"Unknown agent: {agent_name}")
        thread_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        safe_title = (title or "").strip() or (
            f"{agent_name} · {now.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        self.store.create_chat_thread(
            {
                "thread_id": thread_id,
                "agent_name": agent_name,
                "title": safe_title[:120],
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "last_message_at": None,
                "last_run_id": None,
            }
        )
        return self.get_chat_thread(thread_id)

    def send_chat_message(self, *, thread_id: str, content: str) -> dict[str, Any]:
        thread = self.store.get_chat_thread(thread_id)
        if thread is None:
            raise KeyError(f"Unknown chat thread: {thread_id}")
        message = str(content or "").strip()
        if not message:
            raise ValueError("Chat message cannot be empty.")
        active_run = self._find_active_chat_run(thread_id)
        if active_run is not None:
            raise RuntimeError(
                f"Agent is still replying in this thread ({active_run['status']})."
            )
        self.store.add_chat_message(
            {
                "message_id": str(uuid.uuid4()),
                "thread_id": thread_id,
                "role": "user",
                "content": message,
                "run_id": None,
                "metadata_json": {},
            }
        )
        history = [
            {
                "role": item.get("role"),
                "content": item.get("content"),
            }
            for item in self.store.list_chat_messages(thread_id, limit=8)
        ]
        chat_context = self._build_agent_chat_context(str(thread.get("agent_name")))
        run = self.create_agent_run(
            {
                "agent_name": str(thread["agent_name"]),
                "goal": f"Respond to the operator in chat thread {thread_id}.",
                "business_reason": message[:500],
                "requested_paths": [],
                "risk_level": "low",
                "cross_layer": False,
                "does_touch_contract": False,
                "does_touch_runtime": False,
                "force_strong_model": False,
                "metadata": {
                    "chat_mode": True,
                    "chat_thread_id": thread_id,
                    "chat_latest_user_message": message,
                    "chat_history": history,
                    "chat_context": chat_context,
                    "idempotency_key": f"chat:{uuid.uuid4()}",
                },
            }
        )
        if run.get("status") in {"blocked", "awaiting_approval"}:
            system_content = (
                "Nie mogę jeszcze odpowiedzieć w tym wątku. "
                f"Status runu: {run.get('status')}. "
                f"Powód: {run.get('blocked_reason') or run.get('error') or 'unknown'}."
            )
            self.store.add_chat_message(
                {
                    "message_id": str(uuid.uuid4()),
                    "thread_id": thread_id,
                    "role": "system",
                    "content": system_content,
                    "run_id": run.get("run_id"),
                    "metadata_json": {
                        "run_status": run.get("status"),
                        "blocked_reason": run.get("blocked_reason"),
                    },
                }
            )
        return self.get_chat_thread(thread_id)

    def get_latest_observability_summary(self) -> dict[str, Any] | None:
        return load_latest_observability_summary(self.settings)

    def list_observability_summary_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return load_observability_summary_history(self.settings, limit=limit)

    def get_candidate_assessment(self, candidate_id: str) -> dict[str, Any]:
        manifest = self.strategy_manager.get_candidate_manifest(candidate_id)
        if manifest is None:
            raise KeyError(f"Unknown candidate_id: {candidate_id}")
        regime_report = self.get_latest_regime_report()
        if regime_report is None:
            regime_report = self.generate_regime_report()
        bot_id = manifest.get("candidate_bot_id")
        dry_run_health = None
        dry_run_snapshot = None
        if bot_id:
            try:
                dry_run_health = self.get_dry_run_health(bot_id=bot_id)
                dry_run_snapshot = self.get_latest_dry_run_snapshot(
                    bot_id=bot_id,
                    refresh_if_stale=True,
                )
            except KeyError:
                dry_run_health = None
                dry_run_snapshot = None
        selector_allowed = candidate_id in list((regime_report or {}).get("eligible_candidate_ids") or [])
        risk_decision = self.risk_manager.evaluate_risk(
            regime_report=regime_report,
            candidate_manifests=self.strategy_manager.list_candidate_manifests(),
            portfolio_state=self.risk_manager.build_portfolio_state_from_snapshot(dry_run_snapshot),
            bot_id=bot_id or f"candidate-{candidate_id}",
        )
        runtime_policy = self.risk_manager.build_candidate_runtime_policy(
            risk_decision=risk_decision,
            candidate_id=candidate_id,
            selector_allowed=selector_allowed,
        )
        return self.strategy_manager.build_candidate_assessment(
            candidate_id,
            dry_run_health=dry_run_health,
            dry_run_snapshot=dry_run_snapshot,
            regime_report=regime_report,
            runtime_policy=runtime_policy,
            risk_decision=risk_decision,
        )

    def list_candidate_assessments(self) -> list[dict[str, Any]]:
        assessments: list[dict[str, Any]] = []
        for manifest in self.strategy_manager.list_candidate_manifests():
            candidate_id = manifest.get("strategy_id")
            if not candidate_id:
                continue
            assessments.append(self.get_candidate_assessment(str(candidate_id)))
        assessments.sort(
            key=lambda item: (
                0
                if item.get("lifecycle_status") in {"limited_dry_run_candidate", "frozen_pending_regime_engine"}
                and item.get("candidate_bot_id")
                else 1,
                item.get("candidate_id", ""),
            )
        )
        return assessments

    def get_candidate_dry_run(self, candidate_id: str) -> dict[str, Any]:
        manifest = self.strategy_manager.get_candidate_manifest(candidate_id)
        if manifest is None:
            raise KeyError(f"Unknown candidate_id: {candidate_id}")
        bot_id = manifest.get("candidate_bot_id")
        if not bot_id:
            raise KeyError(f"Candidate '{candidate_id}' has no dedicated dry-run bot.")
        return {
            "candidate_id": candidate_id,
            "bot_id": bot_id,
            "health": self.get_dry_run_health(bot_id=bot_id),
            "latest_snapshot": self.get_latest_dry_run_snapshot(
                bot_id=bot_id,
                refresh_if_stale=True,
            ),
            "latest_smoke": self.get_latest_dry_run_smoke(bot_id=bot_id),
        }

    def get_executive_report(self, *, refresh_runtime: bool = True) -> dict[str, Any]:
        agent_catalog = self.list_agents()
        runs = self.store.list_runs(limit=200)
        self.agent_runtime.write_agent_catalog_packets(runs=runs)
        latest_snapshot = self.get_futures_cluster_snapshot(refresh_if_stale=refresh_runtime)
        dry_run_health = self.get_futures_cluster_health(refresh_runtime=refresh_runtime)
        dry_run_smoke = {
            "bot_id": "futures_canonical_cluster",
            "status": "pass" if dry_run_health.get("ready") else "fail",
            "members": [
                self.get_latest_dry_run_smoke(bot_id=bot_id)
                for bot_id in self._canonical_futures_bot_ids()
            ],
        }
        candidate_assessments: list[dict[str, Any]] = []
        regime_report = (
            self.get_latest_regime_report()
            if refresh_runtime
            else self.regime_detector.latest_report()
        )
        if regime_report is None and refresh_runtime:
            try:
                regime_report = self.generate_regime_report()
            except Exception:
                regime_report = None
        derivatives_report = (
            self.get_latest_derivatives_report()
            if refresh_runtime
            else self.derivatives_feed.latest_report()
        )
        if derivatives_report is None and refresh_runtime:
            try:
                derivatives_report = self.generate_derivatives_report()
            except Exception:
                derivatives_report = None
        replay_report = self.get_latest_regime_replay()
        strategy_layer_report = self.get_latest_futures_cluster_strategy_layer_report()
        if strategy_layer_report is None and refresh_runtime:
            try:
                strategy_layer_report = aggregate_strategy_layer_reports(
                    [
                        self.generate_strategy_layer_report(bot_id=bot_id)
                        for bot_id in self._canonical_futures_bot_ids()
                    ],
                    bot_ids=self._canonical_futures_bot_ids(),
                )
            except Exception:
                strategy_layer_report = None
        representative_bot_id = next(iter(self._canonical_futures_bot_ids()), "ft_trend_pullback_continuation_v1")
        risk_decision = self.get_latest_risk_decision(bot_id=representative_bot_id)
        if risk_decision is None and refresh_runtime:
            try:
                risk_decision = self.generate_risk_decision(bot_id=representative_bot_id)
            except Exception:
                risk_decision = None
        candidate_dry_run = None
        autopilot_status = self.autopilot_status()
        coding_status = self.coding_supervisor.status()
        coding_tasks = self.store.list_coding_tasks(limit=100)
        coding_workspaces = self.store.list_coding_workspaces()
        report = self.executive_report.build_report(
            runs=runs,
            autopilot_status=autopilot_status,
            strategy_report=self.get_latest_strategy_report_with_assessment(
                refresh_runtime=refresh_runtime
            ),
            dry_run_health=dry_run_health,
            dry_run_snapshot=latest_snapshot,
            dry_run_smoke=dry_run_smoke,
            candidate_assessments=candidate_assessments,
            candidate_dry_run=candidate_dry_run,
            regime_report=regime_report,
            derivatives_report=derivatives_report,
            risk_decision=risk_decision,
            regime_replay_report=replay_report,
            strategy_layer_report=strategy_layer_report,
            control_status=self.get_control_status(refresh_if_missing=True),
            coding_status=coding_status,
            coding_tasks=coding_tasks,
            coding_workspaces=coding_workspaces,
            agents=agent_catalog,
        )
        observability_summary = build_observability_summary(
            executive_report=report,
            bot_states=self.list_bots(),
            runs=runs,
        )
        observability_summary = persist_observability_summary(self.settings, observability_summary)
        report["observability_summary"] = observability_summary
        self.agent_runtime.context_packet_store.write_packet(
            packet_type="runtime",
            packet_name="state",
            payload=build_runtime_state_packet(
                health=self.health(),
                autopilot_status=autopilot_status,
                coding_status=coding_status,
                resource_guard=self.operation_guard_snapshot(),
            ),
        )
        self.agent_runtime.context_packet_store.write_packet(
            packet_type="runtime",
            packet_name="executive",
            payload=build_agent_executive_packet(report),
        )
        self.agent_runtime.context_packet_store.write_packet(
            packet_type="runtime",
            packet_name="observability",
            payload=observability_summary,
        )
        return report

    def get_control_status(self, *, refresh_if_missing: bool = False) -> dict[str, Any] | None:
        report_path = self.settings.repo_checkout_path / "monitoring" / "reports" / "control_status.json"
        if not report_path.exists():
            if not refresh_if_missing:
                return None
            return self.generate_control_status()
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if not refresh_if_missing:
                return None
            return self.generate_control_status()

    def generate_control_status(self) -> dict[str, Any]:
        report = create_control_status_report()
        write_control_status_files(report)
        return report

    def autopilot_status(self) -> dict[str, Any]:
        return {
            **self.autopilot.status(),
            **self.agent_runtime_status(),
            "runtime_freeze": self.effective_runtime_freeze_enabled(),
        }

    def start_autopilot(self) -> dict[str, Any]:
        runtime_status = self.agent_runtime_status()
        if runtime_status["agents_status"] == "agents_disabled":
            raise RuntimeError(
                f"Autopilot cannot start while agents are disabled: {runtime_status.get('agents_reason') or 'unknown'}."
            )
        return self.autopilot.start()

    def stop_autopilot(self) -> dict[str, Any]:
        return self.autopilot.stop()

    def coding_status(self) -> dict[str, Any]:
        return self.coding_supervisor.status()

    def start_coding_supervisor(self) -> dict[str, Any]:
        if self.effective_kill_switch_enabled():
            raise RuntimeError("Coding supervisor cannot start while kill switch is enabled.")
        if self.effective_runtime_freeze_enabled():
            raise RuntimeError("Coding supervisor cannot start while runtime freeze is enabled.")
        return self.coding_supervisor.start()

    def stop_coding_supervisor(self) -> dict[str, Any]:
        return self.coding_supervisor.stop()

    def list_coding_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.coding_supervisor.list_coding_tasks(limit=limit)

    def get_coding_task(self, task_id: str) -> dict[str, Any]:
        return self.coding_supervisor.get_coding_task(task_id)

    def create_coding_task(
        self,
        *,
        module_id: str,
        goal_override: str | None = None,
        business_reason: str | None = None,
        target_files_override: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.coding_supervisor.create_manual_task(
            module_id=module_id,
            goal_override=goal_override,
            business_reason=business_reason,
            target_files_override=target_files_override,
        )

    def approve_coding_review(self, task_id: str) -> dict[str, Any]:
        return self.coding_supervisor.approve_review(task_id)

    def reject_coding_review(self, task_id: str, reason: str = "Manual review rejection.") -> dict[str, Any]:
        return self.coding_supervisor.reject_review(task_id, reason=reason)

    def supersede_coding_task(
        self,
        task_id: str,
        *,
        reason: str,
        superseded_by_commit: str | None = None,
    ) -> dict[str, Any]:
        return self.coding_supervisor.supersede_task(
            task_id,
            reason=reason,
            superseded_by_commit=superseded_by_commit,
        )

    def list_workspaces(self) -> list[dict[str, Any]]:
        return self.coding_supervisor.list_workspaces()

    def get_workspace_diff(self, task_id: str) -> dict[str, Any]:
        return self.coding_supervisor.get_workspace_diff(task_id)

    def reset_workspace(self, task_id: str) -> dict[str, Any]:
        return self.coding_supervisor.reset_workspace(task_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return run

    def start_futures_cluster(self) -> dict[str, Any]:
        bot_ids = self._canonical_futures_bot_ids()
        results: dict[str, Any] = {}
        failures: dict[str, str] = {}
        for bot_id in bot_ids:
            try:
                results[bot_id] = self.start_bot(bot_id)
            except Exception as exc:  # noqa: BLE001
                failures[bot_id] = str(exc)
        message = "Futures cluster started." if not failures else "Futures cluster start completed with failures."
        return {
            "accepted": not failures,
            "message": message,
            "payload": {
                "cluster_id": "futures_canonical",
                "member_bot_ids": bot_ids,
                "member_states": {
                    bot_id: (
                        failures.get(bot_id)
                        or str((results.get(bot_id) or {}).get("state") or "unknown")
                    )
                    for bot_id in bot_ids
                },
                "failures": failures,
            },
        }

    def stop_futures_cluster(self) -> dict[str, Any]:
        bot_ids = self._canonical_futures_bot_ids()
        results: dict[str, Any] = {}
        failures: dict[str, str] = {}
        for bot_id in bot_ids:
            try:
                results[bot_id] = self.stop_bot(bot_id)
            except Exception as exc:  # noqa: BLE001
                failures[bot_id] = str(exc)
        message = "Futures cluster stopped." if not failures else "Futures cluster stop completed with failures."
        return {
            "accepted": not failures,
            "message": message,
            "payload": {
                "cluster_id": "futures_canonical",
                "member_bot_ids": bot_ids,
                "member_states": {
                    bot_id: (
                        failures.get(bot_id)
                        or str((results.get(bot_id) or {}).get("state") or "unknown")
                    )
                    for bot_id in bot_ids
                },
                "failures": failures,
            },
        }

    def run_futures_cluster_smoke(self) -> dict[str, Any]:
        bot_ids = self._canonical_futures_bot_ids()
        results: dict[str, Any] = {}
        failures: dict[str, str] = {}
        for bot_id in bot_ids:
            try:
                results[bot_id] = self.run_dry_run_smoke_test(bot_id=bot_id)
            except Exception as exc:  # noqa: BLE001
                failures[bot_id] = str(exc)
        passed = all(str((results.get(bot_id) or {}).get("status")) == "pass" for bot_id in bot_ids if bot_id in results)
        message = "Futures cluster smoke completed." if not failures else "Futures cluster smoke completed with failures."
        return {
            "accepted": not failures and passed,
            "message": message,
            "payload": {
                "cluster_id": "futures_canonical",
                "member_results": results,
                "failures": failures,
            },
        }

    def refresh_futures_cluster_snapshot(self) -> dict[str, Any]:
        bot_ids = self._canonical_futures_bot_ids()
        snapshots: dict[str, Any] = {}
        failures: dict[str, str] = {}
        for bot_id in bot_ids:
            try:
                snapshots[bot_id] = self.create_dry_run_snapshot(bot_id=bot_id)
            except Exception as exc:  # noqa: BLE001
                failures[bot_id] = str(exc)
        aggregated = None
        if snapshots:
            aggregated = self.get_futures_cluster_snapshot(refresh_if_stale=False)
        message = "Futures snapshots refreshed." if not failures else "Futures snapshot refresh completed with failures."
        return {
            "accepted": not failures,
            "message": message,
            "payload": {
                "cluster_id": "futures_canonical",
                "member_bot_ids": bot_ids,
                "failures": failures,
                "cluster_snapshot": aggregated,
            },
        }

    def get_operator_home(self) -> dict[str, Any]:
        futures_bots = [
            self.bot_manager.get_bot_status(bot_id)
            for bot_id in self._canonical_futures_bot_ids()
        ]
        futures_health = self.get_futures_cluster_health(refresh_runtime=False)
        futures_snapshot = self.get_futures_cluster_snapshot(refresh_if_stale=False)
        representative_bot_id = next(iter(self._canonical_futures_bot_ids()), "ft_trend_pullback_continuation_v1")
        risk_decision = self.get_latest_risk_decision(bot_id=representative_bot_id)
        strategy_layer_report = self.get_latest_futures_cluster_strategy_layer_report()
        autopilot_status = self.autopilot_status()
        coding_status = self.coding_status()
        agents = self.list_agents()
        observability_summary = self.get_latest_observability_summary()
        if observability_summary is None:
            observability_summary = self.get_executive_report(refresh_runtime=False).get("observability_summary") or {}
        recent_runs = self.list_runs(limit=50)
        return build_operator_home(
            health=self.health(),
            futures_bots=futures_bots,
            futures_health=futures_health,
            futures_snapshot=futures_snapshot,
            risk_decision=risk_decision,
            strategy_layer_report=strategy_layer_report,
            autopilot_status=autopilot_status,
            coding_status=coding_status,
            agents=agents,
            observability_summary=observability_summary,
            runtime_flags=self.get_runtime_flags(),
            recent_runs=recent_runs,
            settings=self.settings,
        )

    def create_agent_run(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        with tracer.start_as_current_span("Orchestrator.create_agent_run") as span:
            span.set_attribute("crypto.agent_name", request_payload["agent_name"])
            request_fingerprint = self._compute_request_fingerprint(request_payload)
            existing_run = self.store.find_active_run_by_fingerprint(request_fingerprint)
            if existing_run is not None:
                span.set_attribute("crypto.idempotent_hit", True)
                span.set_attribute("crypto.run_id", existing_run["run_id"])
                return existing_run
            span.set_attribute("crypto.idempotent_hit", False)

            if self.effective_kill_switch_enabled():
                run_id = str(uuid.uuid4())
                task_id = f"task-{uuid.uuid4()}"
                now = datetime.now(timezone.utc).isoformat()
                record = {
                    "run_id": run_id,
                    "task_id": task_id,
                    "agent_name": request_payload["agent_name"],
                    "goal": request_payload["goal"],
                    "business_reason": request_payload.get("business_reason", ""),
                    "payload_json": request_payload,
                    "request_fingerprint": request_fingerprint,
                    "status": "blocked",
                    "risk_level": request_payload["risk_level"],
                    "model": None,
                    "model_tier": None,
                    "review_required": True,
                    "human_decision_required": True,
                    "approval_required": False,
                    "approval_granted": False,
                    "stop_requested": False,
                    "cross_layer": bool(request_payload.get("cross_layer")),
                    "does_touch_contract": bool(request_payload.get("does_touch_contract")),
                    "does_touch_runtime": bool(request_payload.get("does_touch_runtime")),
                    "estimated_cost_usd": 0.0,
                    "warnings_json": ["Agent kill switch is enabled."],
                    "blocked_reason": "kill_switch_enabled",
                    "max_iterations": 0,
                    "max_retry_limit": 0,
                    "created_at": now,
                    "started_at": None,
                    "finished_at": now,
                    "result_json": None,
                    "review_json": None,
                    "error": "AI control layer is disabled by kill switch.",
                }
                self.store.create_run(record)
                record_run_created(record["agent_name"], "blocked")
                record_blocked_call(record["agent_name"], "kill_switch_enabled")
                record_human_escalation(record["agent_name"])
                return self.get_run(run_id)

            if self.effective_runtime_freeze_enabled():
                run_id = str(uuid.uuid4())
                task_id = f"task-{uuid.uuid4()}"
                now = datetime.now(timezone.utc).isoformat()
                record = {
                    "run_id": run_id,
                    "task_id": task_id,
                    "agent_name": request_payload["agent_name"],
                    "goal": request_payload["goal"],
                    "business_reason": request_payload.get("business_reason", ""),
                    "payload_json": request_payload,
                    "request_fingerprint": request_fingerprint,
                    "status": "blocked",
                    "risk_level": request_payload["risk_level"],
                    "model": None,
                    "model_tier": None,
                    "review_required": True,
                    "human_decision_required": True,
                    "approval_required": False,
                    "approval_granted": False,
                    "stop_requested": False,
                    "cross_layer": bool(request_payload.get("cross_layer")),
                    "does_touch_contract": bool(request_payload.get("does_touch_contract")),
                    "does_touch_runtime": bool(request_payload.get("does_touch_runtime")),
                    "estimated_cost_usd": 0.0,
                    "warnings_json": ["Runtime freeze is enabled."],
                    "blocked_reason": "runtime_freeze_enabled",
                    "max_iterations": 0,
                    "max_retry_limit": 0,
                    "created_at": now,
                    "started_at": None,
                    "finished_at": now,
                    "result_json": None,
                    "review_json": None,
                    "error": "AI runtime is paused by runtime freeze.",
                }
                self.store.create_run(record)
                record_run_created(record["agent_name"], "blocked")
                record_blocked_call(record["agent_name"], "runtime_freeze_enabled")
                record_human_escalation(record["agent_name"])
                return self.get_run(run_id)

            current_agent_spend = self.store.get_today_spend(request_payload["agent_name"])
            current_total_spend = self.store.get_today_total_spend()
            current_agent_active_runs = sum(
                1
                for run in self.store.list_runs(limit=200)
                if run.get("agent_name") == request_payload["agent_name"]
                and run.get("status") in {"queued", "running", "awaiting_approval"}
            )
            risk_decision = self.risk_manager.evaluate_request_risk(request_payload)
            sensitive_paths = self.risk_manager.validate_requested_paths(
                request_payload.get("requested_paths", [])
            )
            for _ in sensitive_paths:
                record_scope_violation(request_payload["agent_name"])

            decision = self.agent_runtime.prepare_run(
                request_payload=request_payload,
                current_agent_spend=current_agent_spend,
                current_total_spend=current_total_spend,
                risk_overrides=risk_decision,
                sensitive_path_violations=sensitive_paths,
                current_agent_active_runs=current_agent_active_runs,
            )

            run_id = str(uuid.uuid4())
            task_id = f"task-{uuid.uuid4()}"
            now = datetime.now(timezone.utc).isoformat()

            status = "queued"
            if not decision["allowed"]:
                status = "blocked"
            elif decision["approval_required"]:
                status = "awaiting_approval"

            record = {
                "run_id": run_id,
                "task_id": task_id,
                "agent_name": request_payload["agent_name"],
                "goal": request_payload["goal"],
                "business_reason": request_payload.get("business_reason", ""),
                "payload_json": request_payload,
                "request_fingerprint": request_fingerprint,
                "status": status,
                "risk_level": request_payload["risk_level"],
                "model": decision["selected_model"],
                "model_tier": decision["selected_model_tier"],
                "review_required": decision["review_required"],
                "human_decision_required": decision["human_decision_required"],
                "approval_required": decision["approval_required"],
                "approval_granted": False,
                "stop_requested": False,
                "cross_layer": bool(request_payload.get("cross_layer")),
                "does_touch_contract": bool(request_payload.get("does_touch_contract")),
                "does_touch_runtime": bool(request_payload.get("does_touch_runtime")),
                "estimated_cost_usd": decision["estimated_cost_usd"],
                "warnings_json": decision["warnings"],
                "blocked_reason": decision["blocked_reason"],
                "max_iterations": decision["max_iterations"],
                "max_retry_limit": decision["max_retry_limit"],
                "created_at": now,
                "started_at": None,
                "finished_at": None,
                "result_json": None,
                "review_json": None,
                "error": None,
            }
            self.store.create_run(record)
            record_run_created(record["agent_name"], status)

            if decision["review_required"]:
                record_review_required(record["agent_name"])
            if decision["human_decision_required"]:
                record_human_escalation(record["agent_name"])
            if not decision["allowed"]:
                record_blocked_call(record["agent_name"], decision["blocked_reason"] or "blocked")
                return self.get_run(run_id)

            if status == "queued":
                self._submit_run(run_id)
            span.set_attribute("crypto.run_id", run_id)
            return self.get_run(run_id)

    def approve_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "awaiting_approval":
            return run
        self.store.update_run(
            run_id,
            approval_granted=True,
            status="queued",
            error=None,
        )
        self._submit_run(run_id)
        return self.get_run(run_id)

    def stop_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        self.store.update_run(run_id, stop_requested=True)
        future = self.futures.get(run_id)
        if future and future.cancel():
            self.store.update_run(
                run_id,
                status="stopped",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error="Run was cancelled before it started.",
            )
            return self.get_run(run_id)

        if run["status"] in {"queued", "awaiting_approval"}:
            self.store.update_run(
                run_id,
                status="stopped",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error="Run was stopped before execution.",
            )
        return self.get_run(run_id)

    def _submit_run(self, run_id: str) -> None:
        if self.settings.agent_max_parallel_runs <= 1:
            self._execute_run(run_id)
            return
        future = self.executor.submit(self._execute_run, run_id)
        self.futures[run_id] = future

    def _execute_run(self, run_id: str) -> None:
        run = self.get_run(run_id)
        chat_mode = self._is_chat_run(run)
        chat_thread_id = self._chat_thread_id_for_run(run)
        if run.get("stop_requested"):
            self.store.update_run(
                run_id,
                status="stopped",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error="Run was stopped before execution.",
            )
            if chat_mode and chat_thread_id:
                self.store.add_chat_message(
                    {
                        "message_id": str(uuid.uuid4()),
                        "thread_id": chat_thread_id,
                        "role": "system",
                        "content": "Rozmowa została zatrzymana zanim agent zdążył odpowiedzieć.",
                        "run_id": run_id,
                        "metadata_json": {"run_status": "stopped"},
                    }
                )
            return

        if self.effective_kill_switch_enabled():
            self.store.update_run(
                run_id,
                status="blocked",
                finished_at=datetime.now(timezone.utc).isoformat(),
                blocked_reason="kill_switch_enabled",
                error="Run was blocked because kill switch is enabled.",
            )
            record_blocked_call(run["agent_name"], "kill_switch_enabled")
            if chat_mode and chat_thread_id:
                self.store.add_chat_message(
                    {
                        "message_id": str(uuid.uuid4()),
                        "thread_id": chat_thread_id,
                        "role": "system",
                        "content": "Odpowiedź została zablokowana, bo kill switch jest aktywny.",
                        "run_id": run_id,
                        "metadata_json": {"run_status": "blocked", "blocked_reason": "kill_switch_enabled"},
                    }
                )
            return
        if self.effective_runtime_freeze_enabled():
            self.store.update_run(
                run_id,
                status="blocked",
                finished_at=datetime.now(timezone.utc).isoformat(),
                blocked_reason="runtime_freeze_enabled",
                error="Run was blocked because runtime freeze is enabled.",
            )
            record_blocked_call(run["agent_name"], "runtime_freeze_enabled")
            if chat_mode and chat_thread_id:
                self.store.add_chat_message(
                    {
                        "message_id": str(uuid.uuid4()),
                        "thread_id": chat_thread_id,
                        "role": "system",
                        "content": "Odpowiedź została zablokowana, bo runtime freeze jest aktywny.",
                        "run_id": run_id,
                        "metadata_json": {"run_status": "blocked", "blocked_reason": "runtime_freeze_enabled"},
                    }
                )
            return

        resource_guard = self.operation_guard_snapshot()
        if not bool(resource_guard.get("allow_new_runs", True)):
            finished_at = datetime.now(timezone.utc).isoformat()
            primary_reason = str(
                resource_guard.get("primary_reason") or "resource_guard_blocked"
            )
            blocked_reason = f"host_resource_guard:{primary_reason}"
            self.store.update_run(
                run_id,
                status="blocked",
                finished_at=finished_at,
                blocked_reason=blocked_reason,
                error=str(
                    resource_guard.get("operator_message")
                    or "Run was blocked by the host resource guard."
                ),
            )
            record_blocked_call(run["agent_name"], blocked_reason)
            if chat_mode and chat_thread_id:
                self.store.add_chat_message(
                    {
                        "message_id": str(uuid.uuid4()),
                        "thread_id": chat_thread_id,
                        "role": "system",
                        "content": str(
                            resource_guard.get("operator_message")
                            or "Odpowiedź została zablokowana przez host resource guard."
                        ),
                        "run_id": run_id,
                        "metadata_json": {"run_status": "blocked", "blocked_reason": blocked_reason},
                    }
                )
            return

        started_at = datetime.now(timezone.utc)
        deadline = monotonic() + self.settings.agent_run_timeout_seconds
        self.store.update_run(run_id, status="running", started_at=started_at.isoformat())
        record_run_started(run["agent_name"])

        try:
            cache_enabled = self._is_cacheable_run(run)
            current_run = self.get_run(run_id)
            stop_requested = lambda: bool(
                (self.store.get_run(run_id) or {}).get("stop_requested")
            ) or monotonic() >= deadline
            if chat_mode:
                result = self.agent_runtime.execute_chat(
                    run_record=current_run,
                    stop_requested_callback=stop_requested,
                )
            else:
                result = self.agent_runtime.execute(
                    run_record=current_run,
                    stop_requested_callback=stop_requested,
                    cache_lookup=self.store.get_cached_response if cache_enabled else None,
                    cache_store=self.store.set_cached_response if cache_enabled else None,
                    cache_hit_callback=record_cache_hit if cache_enabled else None,
                    cache_miss_callback=record_cache_miss if cache_enabled else None,
                )
            finished_at = datetime.now(timezone.utc)
            duration_seconds = max((finished_at - started_at).total_seconds(), 0.0)
            self.store.update_run(
                run_id,
                status="completed",
                finished_at=finished_at.isoformat(),
                result_json=result["result_json"],
                review_json=result["review_json"],
                actual_cost_usd=result["actual_cost_usd"],
                prompt_tokens=result["prompt_tokens"],
                completion_tokens=result["completion_tokens"],
                total_tokens=result["total_tokens"],
                successful_requests=result["successful_requests"],
                retry_like_requests=result["retry_like_requests"],
                duration_seconds=duration_seconds,
                error=None,
            )
            record_run_succeeded(
                agent_name=run["agent_name"],
                model=result["model"],
                duration_seconds=duration_seconds,
                prompt_tokens=result["prompt_tokens"],
                completion_tokens=result["completion_tokens"],
                total_tokens=result["total_tokens"],
                successful_requests=result["successful_requests"],
                retry_like_requests=result["retry_like_requests"],
                estimated_cost_usd=result["actual_cost_usd"],
            )
            if chat_mode and chat_thread_id:
                chat_result = dict(result.get("result_json") or {})
                self.store.add_chat_message(
                    {
                        "message_id": str(uuid.uuid4()),
                        "thread_id": chat_thread_id,
                        "role": "assistant",
                        "content": str(chat_result.get("reply") or "").strip()
                        or "Agent zakończył odpowiedź bez treści.",
                        "run_id": run_id,
                        "metadata_json": chat_result,
                    }
                )
            logger.info(
                "Agent run completed.",
                extra={
                    "run_id": run_id,
                    "task_id": run["task_id"],
                    "agent_name": run["agent_name"],
                    "model": result["model"],
                    "status": "completed",
                    "event": "agent_run_completed",
                },
            )
        except Exception as exc:  # noqa: BLE001
            finished_at = datetime.now(timezone.utc)
            duration_seconds = max((finished_at - started_at).total_seconds(), 0.0)
            self.store.update_run(
                run_id,
                status="failed",
                finished_at=finished_at.isoformat(),
                error=str(exc),
                duration_seconds=duration_seconds,
            )
            record_run_failed(run["agent_name"], duration_seconds, reason="exception")
            if chat_mode and chat_thread_id:
                self.store.add_chat_message(
                    {
                        "message_id": str(uuid.uuid4()),
                        "thread_id": chat_thread_id,
                        "role": "system",
                        "content": f"Agent nie odpowiedział poprawnie: {exc}",
                        "run_id": run_id,
                        "metadata_json": {"run_status": "failed", "error": str(exc)},
                    }
                )
            logger.exception(
                "Agent run failed.",
                extra={
                    "run_id": run_id,
                    "task_id": run["task_id"],
                    "agent_name": run["agent_name"],
                    "status": "failed",
                    "event": "agent_run_failed",
                },
            )
        finally:
            self.futures.pop(run_id, None)

    @staticmethod
    def _compute_request_fingerprint(request_payload: dict[str, Any]) -> str:
        metadata = request_payload.get("metadata") or {}
        idempotency_key = metadata.get("idempotency_key")
        if idempotency_key:
            raw_value = f"idempotency_key:{idempotency_key}"
        else:
            raw_value = json.dumps(
                request_payload,
                sort_keys=True,
                separators=(",", ":"),
            )
        return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_cacheable_run(run: dict[str, Any]) -> bool:
        metadata = dict((run.get("payload_json") or {}).get("metadata") or {})
        return (
            run.get("risk_level") == "low"
            and not run.get("cross_layer")
            and not run.get("does_touch_runtime")
            and not run.get("human_decision_required")
            and not run.get("approval_required")
            and run.get("model_tier") == "cheap"
            and not bool(metadata.get("chat_mode"))
        )
