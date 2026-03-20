"""Hard runtime enforcement for strategy-level execution."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import reason_codes as rc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RiskExecutionGuard:
    """Read-only guard that enforces the latest risk decision in strategy hooks."""

    def __init__(self, *, bot_id: str, risk_dir: Path | None = None, snapshots_dir: Path | None = None) -> None:
        settings = get_settings()
        self.bot_id = bot_id
        self.risk_dir = risk_dir or settings.risk_decisions_dir
        self.snapshots_dir = snapshots_dir or settings.dry_run_snapshots_dir
        self.risk_dir.mkdir(parents=True, exist_ok=True)

    def decision_path(self) -> Path:
        return self.risk_dir / f"latest-{self.bot_id}.json"

    def enforcement_path(self) -> Path:
        return self.risk_dir / f"enforcement-latest-{self.bot_id}.json"

    def snapshot_path(self) -> Path:
        return self.snapshots_dir / f"latest-{self.bot_id}.json"

    def load_risk_decision(self) -> dict[str, Any] | None:
        path = self.decision_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def load_portfolio_snapshot(self) -> dict[str, Any] | None:
        path = self.snapshot_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def enforce_entry(
        self,
        *,
        strategy_id: str,
        pair: str,
        side: str,
        entry_tag: str | None,
        signal_profile: str,
        portfolio_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = self.load_risk_decision()
        trace: list[dict[str, Any]] = []
        blocked_reason_codes: list[str] = []
        status = "allowed"
        enforcement = {
            "entry_allowed": True,
            "blocked_reason_codes": blocked_reason_codes,
            "enforcement_trace": trace,
            "risk_decision_found": decision is not None,
        }

        if not decision:
            blocked_reason_codes.append(rc.EXECUTION_RISK_DECISION_MISSING)
            trace.append({"rule": "risk_decision_missing", "outcome": "blocked"})
            self._record_telemetry(
                status="blocked",
                reason_codes=blocked_reason_codes,
                side=side,
                strategy_id=strategy_id,
                pair=pair,
            )
            enforcement["entry_allowed"] = False
            return enforcement

        trace.append({"rule": "risk_decision_loaded", "outcome": "ok"})
        if not bool(decision.get("allow_trading")):
            blocked_reason_codes.append(rc.EXECUTION_HARD_BLOCK_ALLOW_TRADING)
        if not bool(decision.get("new_entries_allowed")):
            blocked_reason_codes.append(rc.EXECUTION_HARD_BLOCK_NEW_ENTRIES)
        if bool(decision.get("force_reduce_only")):
            blocked_reason_codes.append(rc.EXECUTION_FORCE_REDUCE_ONLY)
        if bool(decision.get("cooldown_active")):
            blocked_reason_codes.append(rc.EXECUTION_COOLDOWN_ACTIVE)
        if side not in list(decision.get("allowed_directions") or []):
            blocked_reason_codes.append(rc.EXECUTION_BLOCKED_DIRECTION)
        if strategy_id not in list(decision.get("allowed_strategy_ids") or []):
            blocked_reason_codes.append(rc.EXECUTION_BLOCKED_STRATEGY)

        protective = dict(decision.get("protective_overrides") or {})
        if (
            protective.get("disable_aggressive_entries")
            or protective.get("force_conservative_execution")
        ) and signal_profile != "standard":
            blocked_reason_codes.append(rc.EXECUTION_AGGRESSIVE_ENTRY_BLOCKED)

        snapshot = portfolio_snapshot or self.load_portfolio_snapshot() or {}
        open_trades = list(snapshot.get("open_trades") or [])
        open_trades_count = int(snapshot.get("open_trades_count") or len(open_trades))
        pair_count = sum(1 for trade in open_trades if str(trade.get("pair")) == pair)
        base = pair.split("/")[0] if "/" in pair else pair.split(":")[0]
        correlated_count = sum(
            1
            for trade in open_trades
            if (
                (str(trade.get("pair") or "").split("/")[0] if "/" in str(trade.get("pair") or "") else str(trade.get("pair") or "").split(":")[0])
                == base
            )
        )

        if open_trades_count >= int(decision.get("max_positions_total") or 0):
            blocked_reason_codes.append(rc.EXECUTION_PORTFOLIO_FULL)
        if pair_count >= int(decision.get("max_positions_per_symbol") or 0) and int(decision.get("max_positions_per_symbol") or 0) > 0:
            blocked_reason_codes.append(rc.EXECUTION_SYMBOL_LIMIT)
        if correlated_count >= int(decision.get("max_correlated_positions") or 0) and int(decision.get("max_correlated_positions") or 0) > 0:
            blocked_reason_codes.append(rc.EXECUTION_CORRELATION_LIMIT)

        enforcement["entry_allowed"] = len(blocked_reason_codes) == 0
        for code in blocked_reason_codes:
            trace.append({"rule": code, "outcome": "blocked"})
        if blocked_reason_codes:
            status = "blocked"
        self._record_telemetry(
            status=status,
            reason_codes=blocked_reason_codes,
            side=side,
            strategy_id=strategy_id,
            pair=pair,
        )
        return enforcement

    def enforce_stake(
        self,
        *,
        strategy_id: str,
        pair: str,
        side: str,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        signal_profile: str,
        total_equity: float | None = None,
        portfolio_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = self.load_risk_decision()
        if not decision:
            self._record_telemetry(
                status="blocked",
                reason_codes=[rc.EXECUTION_RISK_DECISION_MISSING],
                side=side,
                strategy_id=strategy_id,
                pair=pair,
            )
            return {
                "final_stake": 0.0,
                "blocked_reason_codes": [rc.EXECUTION_RISK_DECISION_MISSING],
                "enforcement_trace": [{"rule": "risk_decision_missing", "outcome": "blocked"}],
            }

        trace: list[dict[str, Any]] = []
        codes: list[str] = []
        snapshot = portfolio_snapshot or self.load_portfolio_snapshot() or {}
        trade_summary = dict(snapshot.get("trade_count_summary") or {})
        if total_equity is None:
            balance_summary = dict(snapshot.get("balance_summary") or {})
            try:
                total_equity = float(balance_summary.get("total") or 0.0)
            except (TypeError, ValueError):
                total_equity = 0.0
        try:
            current_open_stakes = float(trade_summary.get("total_open_trades_stakes") or 0.0)
        except (TypeError, ValueError):
            current_open_stakes = 0.0

        final_stake = min(float(proposed_stake), float(max_stake))
        if bool((decision.get("protective_overrides") or {}).get("force_conservative_execution")):
            final_stake = min(final_stake, float(proposed_stake))
            trace.append({"rule": "force_conservative_execution", "outcome": "capped_to_proposed"})

        if bool((decision.get("protective_overrides") or {}).get("disable_aggressive_entries")) and signal_profile != "standard":
            codes.append(rc.EXECUTION_AGGRESSIVE_ENTRY_BLOCKED)

        execution_budget_multiplier = float(decision.get("execution_budget_multiplier") or 1.0)
        final_stake *= execution_budget_multiplier
        if execution_budget_multiplier < 1.0:
            trace.append({"rule": "execution_budget_multiplier", "value": execution_budget_multiplier, "outcome": "tightened"})

        try:
            per_position_pct = float(decision.get("max_position_size_pct") or 0.0)
        except (TypeError, ValueError):
            per_position_pct = 0.0
        if per_position_pct <= 0:
            codes.append(rc.EXECUTION_STAKE_BLOCKED)
        elif total_equity and total_equity > 0:
            absolute_cap = total_equity * (per_position_pct / 100.0)
            final_stake = min(final_stake, absolute_cap)
            trace.append({"rule": "max_position_size_pct", "value": per_position_pct, "outcome": "capped"})

        try:
            total_exposure_pct = float(decision.get("max_total_exposure_pct") or 0.0)
        except (TypeError, ValueError):
            total_exposure_pct = 0.0
        if total_equity and total_equity > 0 and total_exposure_pct > 0:
            remaining_exposure_cap = max(0.0, (total_equity * (total_exposure_pct / 100.0)) - current_open_stakes)
            final_stake = min(final_stake, remaining_exposure_cap)
            trace.append({"rule": "max_total_exposure_pct", "value": total_exposure_pct, "outcome": "capped"})

        final_stake = min(final_stake, float(max_stake))
        if min_stake is not None and final_stake < float(min_stake):
            codes.append(rc.EXECUTION_STAKE_BLOCKED)
            final_stake = 0.0

        status = "allowed"
        if final_stake <= 0:
            status = "blocked"
        elif final_stake < float(proposed_stake):
            status = "clamped"
            codes.append(rc.EXECUTION_STAKE_CLAMPED)

        self._record_telemetry(
            status=status,
            reason_codes=codes,
            side=side,
            strategy_id=strategy_id,
            pair=pair,
            final_stake=round(final_stake, 8),
        )
        return {
            "final_stake": round(max(0.0, final_stake), 8),
            "blocked_reason_codes": codes,
            "enforcement_trace": trace,
        }

    def enforce_leverage(
        self,
        *,
        strategy_id: str,
        pair: str,
        side: str,
        proposed_leverage: float,
        max_leverage: float,
    ) -> dict[str, Any]:
        decision = self.load_risk_decision()
        if not decision:
            self._record_telemetry(
                status="blocked",
                reason_codes=[rc.EXECUTION_RISK_DECISION_MISSING],
                side=side,
                strategy_id=strategy_id,
                pair=pair,
            )
            return {
                "final_leverage": 1.0,
                "blocked_reason_codes": [rc.EXECUTION_RISK_DECISION_MISSING],
                "enforcement_trace": [{"rule": "risk_decision_missing", "outcome": "blocked"}],
            }

        leverage_cap = float(decision.get("leverage_cap") or 1.0)
        final_leverage = min(float(max_leverage), float(proposed_leverage), leverage_cap)
        codes: list[str] = []
        trace: list[dict[str, Any]] = []
        status = "allowed"
        if final_leverage < float(proposed_leverage):
            codes.append(rc.EXECUTION_LEVERAGE_CLAMPED)
            trace.append({"rule": "leverage_cap", "value": leverage_cap, "outcome": "clamped"})
            status = "clamped"
        self._record_telemetry(
            status=status,
            reason_codes=codes,
            side=side,
            strategy_id=strategy_id,
            pair=pair,
            final_leverage=round(final_leverage, 8),
        )
        return {
            "final_leverage": round(max(1.0, final_leverage), 8),
            "blocked_reason_codes": codes,
            "enforcement_trace": trace,
        }

    def _record_telemetry(
        self,
        *,
        status: str,
        reason_codes: list[str],
        side: str,
        strategy_id: str,
        pair: str,
        final_stake: float | None = None,
        final_leverage: float | None = None,
    ) -> None:
        path = self.enforcement_path()
        payload = self._load_enforcement_payload(path)
        counters = dict(payload.get("enforcement_counters") or {})
        counters["total_checks"] = int(counters.get("total_checks", 0)) + 1
        if status == "blocked":
            counters["blocked_total"] = int(counters.get("blocked_total", 0)) + 1
        if rc.EXECUTION_STAKE_CLAMPED in reason_codes:
            counters["clamped_stake_total"] = int(counters.get("clamped_stake_total", 0)) + 1
        if rc.EXECUTION_LEVERAGE_CLAMPED in reason_codes:
            counters["clamped_leverage_total"] = int(counters.get("clamped_leverage_total", 0)) + 1
        reason_to_counter = {
            rc.EXECUTION_BLOCKED_DIRECTION: "blocked_by_direction",
            rc.EXECUTION_BLOCKED_STRATEGY: "blocked_by_strategy",
            rc.EXECUTION_PORTFOLIO_FULL: "blocked_by_portfolio_limit",
            rc.EXECUTION_COOLDOWN_ACTIVE: "blocked_by_cooldown",
            rc.EXECUTION_FORCE_REDUCE_ONLY: "blocked_by_reduce_only",
        }
        for code in reason_codes:
            counter_key = reason_to_counter.get(code)
            if counter_key:
                counters[counter_key] = int(counters.get(counter_key, 0)) + 1
        payload.update(
            {
                "generated_at": _now_iso(),
                "hard_enforcement_enabled": True,
                "enforced_by": ["control_layer_preselection", "freqtrade_strategy_hook"],
                "last_enforcement_status": status,
                "last_blocked_order_reason_codes": list(reason_codes),
                "last_strategy_id": strategy_id,
                "last_pair": pair,
                "last_side": side,
                "last_final_stake": final_stake,
                "last_final_leverage": final_leverage,
                "enforcement_counters": counters,
            }
        )
        self._atomic_write(path, payload)

    @staticmethod
    def _load_enforcement_payload(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {
                "hard_enforcement_enabled": True,
                "enforced_by": ["control_layer_preselection", "freqtrade_strategy_hook"],
                "last_enforcement_status": "unknown",
                "last_blocked_order_reason_codes": [],
                "enforcement_counters": {},
            }
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "hard_enforcement_enabled": True,
                "enforced_by": ["control_layer_preselection", "freqtrade_strategy_hook"],
                "last_enforcement_status": "unknown",
                "last_blocked_order_reason_codes": [],
                "enforcement_counters": {},
            }

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        tmp_path.replace(path)
