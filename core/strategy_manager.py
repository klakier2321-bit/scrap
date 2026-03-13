"""Strategy and backtest data helpers for the control layer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class StrategyManager:
    """Provides read-only access to strategy and backtest assets."""

    def __init__(self, user_data_dir: Path | None = None) -> None:
        self.user_data_dir = user_data_dir or (
            Path(__file__).resolve().parents[1]
            / "trading"
            / "freqtrade"
            / "user_data"
        )

    def list_data_files(self) -> list[str]:
        data_dir = self.user_data_dir / "data"
        if not data_dir.exists():
            return []
        return sorted(
            str(path.relative_to(self.user_data_dir))
            for path in data_dir.rglob("*")
            if path.is_file()
        )

    def list_strategies(self) -> list[str]:
        strategies_dir = self.user_data_dir / "strategies"
        if not strategies_dir.exists():
            return []
        return sorted(path.name for path in strategies_dir.glob("*.py"))

    def discover_sample_strategy_name(self) -> str | None:
        sample_strategy = self.user_data_dir / "strategies" / "sample_strategy.py"
        if not sample_strategy.exists():
            return None
        content = sample_strategy.read_text(encoding="utf-8")
        match = re.search(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", content)
        return match.group(1) if match else None

    def summary(self) -> dict[str, Any]:
        return {
            "data_files": self.list_data_files(),
            "strategies": self.list_strategies(),
            "sample_strategy": self.discover_sample_strategy_name(),
        }
