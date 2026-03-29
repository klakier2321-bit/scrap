"""Main event loop for canonical system replay backtests."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..regime_detector import RegimeDetector
from ..risk_manager import RiskManager
from ..strategy_layer.service import StrategyLayerService
from ..runtime_artifacts import canonical_futures_bot_id
from .artifacts import ReplayArtifactWriter
from .execution_simulator import ExecutionSimulator
from .market_replay import HistoricalMarketReplayProvider
from .models import (
    SystemBacktestBarEvent,
    SystemBacktestConfig,
    SystemBacktestSummary,
    now_iso,
    parse_timerange,
)


class SystemReplayLoop:
    """Runs a complete live-like replay across regime, risk, strategy, and execution."""

    def __init__(self, *, config: SystemBacktestConfig) -> None:
        self.config = config
        settings = get_settings()
        self.detector = RegimeDetector(
            user_data_dir=config.user_data_dir,
            output_dir=settings.regime_reports_dir,
            replay_dir=settings.regime_replay_dir,
            research_dir=config.research_dir,
        )
        self.risk_manager = RiskManager(risk_output_dir=settings.risk_decisions_dir)
        self.strategy_layer = StrategyLayerService(
            manifests_dir=config.research_dir / "strategies" / "manifests",
            output_dir=settings.strategy_signals_dir,
            telemetry_dir=settings.strategy_telemetry_dir,
        )
        self.provider = HistoricalMarketReplayProvider(config=config)
        self.execution = ExecutionSimulator(
            starting_equity=config.starting_equity,
            fee_rate=config.fee_rate,
            slippage_rate=config.slippage_rate,
        )

    def run(self, *, timerange: str) -> dict[str, Any]:
        start, end = parse_timerange(timerange)
        run_id = f"system-replay-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        run_dir = (self.config.output_root / run_id).resolve()
        writer = ReplayArtifactWriter(run_dir=run_dir)
        strategy_manifests = self.strategy_layer.list_manifests()
        enabled_strategy_ids = set(self.config.enabled_strategy_ids)
        strategy_manifests = [
            manifest for manifest in strategy_manifests if str(manifest.get("strategy_id") or "") in enabled_strategy_ids
        ]

        previous_regime_report: dict[str, Any] | None = None
        windows = self.provider.iter_windows(start=start, end=end)
        total_signals_built = 0
        total_signals_risk_admitted = 0
        total_entries_attempted = 0
        total_entries_filled = 0
        total_entries_blocked_by_risk = 0
        total_entries_blocked_by_execution = 0
        regime_breakdown: Counter[str] = Counter()
        blocked_reason_breakdown: Counter[str] = Counter()
        strategy_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        equity_curve: list[dict[str, Any]] = []

        for window in windows:
            filled_now = self.execution.fill_pending_orders(
                timestamp=window.asof_iso,
                current_bars=window.current_bars,
            )
            total_entries_filled += filled_now
            closed_now = self.execution.evaluate_exits(
                timestamp=window.asof_iso,
                current_bars=window.current_bars,
                primary_regime=(previous_regime_report or {}).get("primary_regime", "unknown"),
            )

            portfolio_snapshot = self.execution.build_portfolio_snapshot(
                timestamp=window.asof_iso,
                current_bars=window.current_bars,
            )
            portfolio_state = self.risk_manager.build_portfolio_state_from_snapshot(portfolio_snapshot)
            regime_report = self.provider.build_regime_report(
                detector=self.detector,
                window=window,
                previous_report=previous_regime_report,
            )
            risk_decision = self.risk_manager.evaluate_risk(
                regime_report=regime_report,
                strategy_manifests=strategy_manifests,
                portfolio_state=portfolio_state,
                bot_id="futures_canonical_cluster",
                persist=False,
            )

            strategy_reports: list[dict[str, Any]] = []
            preferred_strategy_id: str | None = None
            for strategy_id in self.config.enabled_strategy_ids:
                bot_id = canonical_futures_bot_id(strategy_id)
                report = self.strategy_layer.generate_report(
                    regime_report=regime_report,
                    risk_decision=risk_decision,
                    bot_id=bot_id,
                    strategy_filter_ids=[strategy_id],
                    persist=False,
                    emit_telemetry=False,
                )
                strategy_reports.append(report)
                if self.config.write_detailed_reports:
                    writer.write_strategy_report(window.asof_iso, bot_id, report)
                if preferred_strategy_id is None and report.get("preferred_risk_admitted_strategy_id"):
                    preferred_strategy_id = str(report.get("preferred_risk_admitted_strategy_id"))

            signal_metrics = self.execution.process_new_signals(
                timestamp=window.asof_iso,
                risk_decision=risk_decision,
                strategy_reports=strategy_reports,
                current_bars=window.current_bars,
            )
            total_signals_built += int(signal_metrics["signals_built"])
            total_signals_risk_admitted += int(signal_metrics["signals_risk_admitted"])
            total_entries_attempted += int(signal_metrics["entries_attempted"])
            total_entries_blocked_by_risk += int(signal_metrics["entries_blocked_by_risk"])
            total_entries_blocked_by_execution += int(signal_metrics["entries_blocked_by_execution"])
            blocked_reason_breakdown.update(signal_metrics["blocked_reason_codes"])
            regime_breakdown.update([str(regime_report.get("primary_regime") or "unknown")])

            for report in strategy_reports:
                for signal in list(report.get("built_signals") or []):
                    bucket = strategy_breakdown[str(signal.get("strategy_id") or "unknown")]
                    bucket["signals_built"] += 1
                    if signal.get("risk_admissible"):
                        bucket["signals_risk_admitted"] += 1
            current_execution_events = [
                event for event in self.execution.execution_events if event.get("timestamp") == window.asof_iso
            ]
            for event in current_execution_events:
                strategy_id = str(event.get("strategy_id") or "")
                if strategy_id:
                    bucket = strategy_breakdown[strategy_id]
                    if event.get("event_type") == "entry_scheduled":
                        bucket["entries_scheduled"] += 1
                    elif event.get("event_type") == "entry_filled":
                        bucket["entries_filled"] += 1
                    elif event.get("event_type") == "position_closed":
                        bucket["closed_trades"] += 1

            if self.config.write_detailed_reports:
                writer.write_regime_report(window.asof_iso, regime_report)
                writer.write_risk_decision(window.asof_iso, risk_decision)
            for event in current_execution_events:
                writer.append_execution_event(event)

            current_equity = self.execution.current_total_equity(window.current_bars)
            equity_curve.append(
                {
                    "timestamp": window.asof_iso,
                    "equity": current_equity,
                    "open_positions": len(self.execution.open_positions),
                    "closed_now": closed_now,
                }
            )
            bar_event = SystemBacktestBarEvent(
                timestamp=window.asof_iso,
                primary_regime=str(regime_report.get("primary_regime") or "unknown"),
                trading_mode=str(risk_decision.get("trading_mode") or "blocked"),
                signals_built=int(signal_metrics["signals_built"]),
                signals_risk_admitted=int(signal_metrics["signals_risk_admitted"]),
                entries_attempted=int(signal_metrics["entries_attempted"]),
                entries_filled=filled_now,
                entries_blocked_by_risk=int(signal_metrics["entries_blocked_by_risk"]),
                entries_blocked_by_execution=int(signal_metrics["entries_blocked_by_execution"]),
                open_positions=len(self.execution.open_positions),
                total_equity=current_equity,
                preferred_strategy_id=preferred_strategy_id,
                blocked_reason_codes=list(signal_metrics["blocked_reason_codes"]),
            )
            writer.append_bar_event(bar_event.to_dict())
            previous_regime_report = regime_report

        peak_equity = self.config.starting_equity
        max_drawdown_pct = 0.0
        for point in equity_curve:
            equity = float(point["equity"])
            peak_equity = max(peak_equity, equity)
            if peak_equity > 0:
                drawdown_pct = ((peak_equity - equity) / peak_equity) * 100.0
                max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        final_equity = float(equity_curve[-1]["equity"]) if equity_curve else self.config.starting_equity
        net_profit_pct = (
            ((final_equity - self.config.starting_equity) / self.config.starting_equity) * 100.0
            if self.config.starting_equity > 0
            else 0.0
        )
        exposure_values = [
            float(point["open_positions"]) for point in equity_curve
        ]
        exposure_efficiency = (
            float(len(self.execution.closed_trades)) / max(1.0, sum(exposure_values) / max(len(exposure_values), 1))
            if exposure_values
            else 0.0
        )
        summary = SystemBacktestSummary(
            run_id=run_id,
            generated_at=now_iso(),
            timerange=timerange,
            pairs=self.config.universe,
            strategies_enabled=self.config.enabled_strategy_ids,
            total_signals_built=total_signals_built,
            total_signals_risk_admitted=total_signals_risk_admitted,
            total_entries_attempted=total_entries_attempted,
            total_entries_filled=total_entries_filled,
            total_entries_blocked_by_risk=total_entries_blocked_by_risk,
            total_entries_blocked_by_execution=total_entries_blocked_by_execution,
            total_closed_trades=len(self.execution.closed_trades),
            net_profit_pct=round(net_profit_pct, 6),
            max_drawdown_pct=round(max_drawdown_pct, 6),
            exposure_efficiency=round(exposure_efficiency, 6),
            blocked_reason_breakdown=dict(blocked_reason_breakdown),
            strategy_breakdown={key: dict(value) for key, value in strategy_breakdown.items()},
            regime_breakdown=dict(regime_breakdown),
        )

        writer.write_summary(summary.to_dict())
        writer.write_equity_curve(equity_curve)
        writer.write_trades([trade.to_dict() for trade in self.execution.closed_trades])
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "summary": summary.to_dict(),
        }
