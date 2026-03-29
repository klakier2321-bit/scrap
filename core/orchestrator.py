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
from .regime_detector import RegimeDetector
from .risk_manager import RiskManager
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
        self.store = RunStore(settings.database_path)
        stale_runs = self.store.reconcile_stale_runs()
        self.agent_runtime = AgentRuntimeService(settings=settings)
        self.executive_report = ExecutiveReportService(settings.repo_checkout_path)
        self.coding_supervisor = CodingSupervisorService(
            settings=settings,
            store=self.store,
            agent_runtime=self.agent_runtime,
            executive_report_provider=self.get_executive_report,
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
            "kill_switch": self.settings.agent_kill_switch,
            "runtime_freeze": self.settings.agent_runtime_freeze,
            "docker_available": self.bot_manager.docker_available(),
            "agents_status": agent_runtime["agents_status"],
            "agents_reason": agent_runtime.get("agents_reason"),
        }

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
        if self.settings.agent_kill_switch:
            return {
                "agents_status": "agents_disabled",
                "agents_reason": "kill_switch_enabled",
            }
        if self.settings.agent_runtime_freeze:
            return {
                "agents_status": "agents_disabled",
                "agents_reason": "runtime_freeze_enabled",
            }
        if not self.settings.agent_use_mock_llm and not self._has_valid_llm_key():
            return {
                "agents_status": "agents_disabled",
                "agents_reason": "missing_valid_api_key",
            }
        if self.settings.agent_use_mock_llm or not self.settings.agent_autopilot_enabled:
            return {
                "agents_status": "agents_guarded",
                "agents_reason": "manual_or_mock_mode",
            }
        return {
            "agents_status": "agents_active_limited",
            "agents_reason": "budget_guarded_runtime",
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

    def get_futures_cluster_health(self) -> dict[str, Any]:
        bot_ids = self._canonical_futures_bot_ids()
        healths = [self.get_dry_run_health(bot_id=bot_id) for bot_id in bot_ids]
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
            "last_snapshot_at": None,
            "last_smoke_status": "pass" if all(item.get("last_smoke_status") == "pass" for item in healths) else "degraded",
            "last_smoke_at": None,
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

    def get_dry_run_health(self, bot_id: str = "freqtrade") -> dict[str, Any]:
        bot_status = self.bot_manager.get_bot_status(bot_id)
        logs = self.bot_manager.get_bot_logs(bot_id, tail=200)
        return self._runtime_manager_for_bot(bot_id).health(bot_status=bot_status, logs=logs)

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
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
        report = self.strategy_manager.latest_strategy_report(strategy_name=strategy_name)
        if report is None:
            return None, None, None, None

        latest_snapshot = self.get_latest_dry_run_snapshot(refresh_if_stale=True)
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
    ) -> dict[str, Any] | None:
        report, latest_snapshot, assessment, readiness_gate = self._load_strategy_context(
            strategy_name=strategy_name
        )
        if report is None:
            return None
        if assessment is None:
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
    ) -> list[dict[str, Any]]:
        history = self.strategy_manager.list_strategy_reports(
            strategy_name=strategy_name,
            limit=limit,
        )
        merged: list[dict[str, Any]] = []
        for report in history:
            assessment = self.strategy_manager.get_assessment_for_report(
                report["strategy_name"],
                report.get("source_run_id"),
                report.get("source_archive"),
            )
            readiness_gate = self.risk_manager.evaluate_strategy_readiness(
                strategy_report=report,
                dry_run_snapshot=self.get_latest_dry_run_snapshot(refresh_if_stale=True),
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

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_runs(limit=limit)

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

    def get_executive_report(self) -> dict[str, Any]:
        latest_snapshot = self.get_futures_cluster_snapshot(refresh_if_stale=True)
        dry_run_health = self.get_futures_cluster_health()
        dry_run_smoke = {
            "bot_id": "futures_canonical_cluster",
            "status": "pass" if dry_run_health.get("ready") else "fail",
            "members": [
                self.get_latest_dry_run_smoke(bot_id=bot_id)
                for bot_id in self._canonical_futures_bot_ids()
            ],
        }
        candidate_assessments: list[dict[str, Any]] = []
        regime_report = self.get_latest_regime_report()
        if regime_report is None:
            try:
                regime_report = self.generate_regime_report()
            except Exception:
                regime_report = None
        derivatives_report = self.get_latest_derivatives_report()
        if derivatives_report is None:
            try:
                derivatives_report = self.generate_derivatives_report()
            except Exception:
                derivatives_report = None
        replay_report = self.get_latest_regime_replay()
        strategy_layer_report = self.get_latest_futures_cluster_strategy_layer_report()
        if strategy_layer_report is None:
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
        if risk_decision is None:
            try:
                risk_decision = self.generate_risk_decision(bot_id=representative_bot_id)
            except Exception:
                risk_decision = None
        candidate_dry_run = None
        return self.executive_report.build_report(
            runs=self.store.list_runs(limit=200),
            autopilot_status=self.autopilot.status(),
            strategy_report=self.get_latest_strategy_report_with_assessment(),
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
            coding_status=self.coding_supervisor.status(),
            coding_tasks=self.store.list_coding_tasks(limit=100),
            coding_workspaces=self.store.list_coding_workspaces(),
        )

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
            "runtime_freeze": self.settings.agent_runtime_freeze,
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

            if self.settings.agent_kill_switch:
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

            current_agent_spend = self.store.get_today_spend(request_payload["agent_name"])
            current_total_spend = self.store.get_today_total_spend()
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
        if run.get("stop_requested"):
            self.store.update_run(
                run_id,
                status="stopped",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error="Run was stopped before execution.",
            )
            return

        started_at = datetime.now(timezone.utc)
        deadline = monotonic() + self.settings.agent_run_timeout_seconds
        self.store.update_run(run_id, status="running", started_at=started_at.isoformat())
        record_run_started(run["agent_name"])

        try:
            cache_enabled = self._is_cacheable_run(run)
            result = self.agent_runtime.execute(
                run_record=self.get_run(run_id),
                stop_requested_callback=lambda: bool(
                    (self.store.get_run(run_id) or {}).get("stop_requested")
                )
                or monotonic() >= deadline,
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
        return (
            run.get("risk_level") == "low"
            and not run.get("cross_layer")
            and not run.get("does_touch_runtime")
            and not run.get("human_decision_required")
            and not run.get("approval_required")
            and run.get("model_tier") == "cheap"
        )
