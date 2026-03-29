"""Artifact writer for system replay runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReplayArtifactWriter:
    """Writes replay artifacts into a dedicated, non-live output tree."""

    def __init__(self, *, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.regime_dir = self.run_dir / "regime_reports"
        self.risk_dir = self.run_dir / "risk_decisions"
        self.strategy_dir = self.run_dir / "strategy_reports"
        self.regime_dir.mkdir(parents=True, exist_ok=True)
        self.risk_dir.mkdir(parents=True, exist_ok=True)
        self.strategy_dir.mkdir(parents=True, exist_ok=True)
        self.execution_events_path = self.run_dir / "execution_events.jsonl"
        self.bar_log_path = self.run_dir / "bar_log.jsonl"

    def write_summary(self, summary: dict[str, Any]) -> Path:
        path = self.run_dir / "summary.json"
        path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
        return path

    def write_equity_curve(self, points: list[dict[str, Any]]) -> Path:
        path = self.run_dir / "equity_curve.json"
        path.write_text(json.dumps(points, indent=2, ensure_ascii=True), encoding="utf-8")
        return path

    def write_trades(self, trades: list[dict[str, Any]]) -> Path:
        path = self.run_dir / "trades.json"
        path.write_text(json.dumps(trades, indent=2, ensure_ascii=True), encoding="utf-8")
        return path

    def append_bar_event(self, payload: dict[str, Any]) -> None:
        with self.bar_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def append_execution_event(self, payload: dict[str, Any]) -> None:
        with self.execution_events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def write_regime_report(self, timestamp: str, report: dict[str, Any]) -> None:
        name = self._safe_timestamp(timestamp)
        (self.regime_dir / f"{name}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def write_risk_decision(self, timestamp: str, decision: dict[str, Any]) -> None:
        name = self._safe_timestamp(timestamp)
        (self.risk_dir / f"{name}.json").write_text(
            json.dumps(decision, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def write_strategy_report(self, timestamp: str, bot_id: str, report: dict[str, Any]) -> None:
        name = self._safe_timestamp(timestamp)
        bot_dir = self.strategy_dir / bot_id
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / f"{name}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_timestamp(value: str) -> str:
        return str(value).replace(":", "").replace("+00:00", "Z")
