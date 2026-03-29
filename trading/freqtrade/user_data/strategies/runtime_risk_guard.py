from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


EXECUTION_RISK_DECISION_MISSING = "EXECUTION_RISK_DECISION_MISSING"
EXECUTION_RISK_ARTIFACT_STALE = "EXECUTION_RISK_ARTIFACT_STALE"
EXECUTION_SIGNAL_REPORT_STALE = "EXECUTION_SIGNAL_REPORT_STALE"
EXECUTION_HARD_BLOCK_ALLOW_TRADING = "EXECUTION_HARD_BLOCK_ALLOW_TRADING"
EXECUTION_HARD_BLOCK_NEW_ENTRIES = "EXECUTION_HARD_BLOCK_NEW_ENTRIES"
EXECUTION_FORCE_REDUCE_ONLY = "EXECUTION_FORCE_REDUCE_ONLY"
EXECUTION_COOLDOWN_ACTIVE = "EXECUTION_COOLDOWN_ACTIVE"
EXECUTION_BLOCKED_DIRECTION = "EXECUTION_BLOCKED_DIRECTION"
EXECUTION_BLOCKED_STRATEGY = "EXECUTION_BLOCKED_STRATEGY"
EXECUTION_AGGRESSIVE_ENTRY_BLOCKED = "EXECUTION_AGGRESSIVE_ENTRY_BLOCKED"
EXECUTION_PORTFOLIO_FULL = "EXECUTION_PORTFOLIO_FULL"
EXECUTION_SYMBOL_LIMIT = "EXECUTION_SYMBOL_LIMIT"
EXECUTION_CORRELATION_LIMIT = "EXECUTION_CORRELATION_LIMIT"
EXECUTION_STAKE_BLOCKED = "EXECUTION_STAKE_BLOCKED"
EXECUTION_STAKE_CLAMPED = "EXECUTION_STAKE_CLAMPED"
EXECUTION_LEVERAGE_CLAMPED = "EXECUTION_LEVERAGE_CLAMPED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class LocalRuntimeRiskGuard:
    def __init__(self, *, bot_id: str) -> None:
        self.bot_id = bot_id
        self.user_data_dir = Path(__file__).resolve().parents[1]
        self.futures_dir = self.user_data_dir / "runtime_artifacts" / "futures"

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    def risk_decision_path(self) -> Path:
        return self.futures_dir / self.bot_id / "risk" / "latest.json"

    def enforcement_path(self) -> Path:
        return self.futures_dir / self.bot_id / "risk" / "enforcement-latest.json"

    def signals_path(self) -> Path:
        return self.futures_dir / self.bot_id / "signals" / "latest.json"

    def global_portfolio_path(self) -> Path:
        return self.futures_dir / "global" / "portfolio" / "latest.json"

    def load_risk_decision(self) -> dict[str, Any] | None:
        return self._read_json(self.risk_decision_path())

    def load_signal_report(self) -> dict[str, Any] | None:
        return self._read_json(self.signals_path())

    def load_global_portfolio(self) -> dict[str, Any] | None:
        return self._read_json(self.global_portfolio_path())

    def risk_decision_fresh(
        self,
        decision: dict[str, Any] | None,
        *,
        max_age_seconds: int = 600,
    ) -> bool:
        generated_at = _parse_iso((decision or {}).get("generated_at"))
        if generated_at is None:
            return False
        age_seconds = (datetime.now(timezone.utc) - generated_at).total_seconds()
        return age_seconds <= max_age_seconds

    def latest_signal(
        self,
        *,
        strategy_id: str,
        pair: str,
        side: str | None = None,
        max_age_seconds: int = 600,
    ) -> dict[str, Any] | None:
        report = self.load_signal_report() or {}
        generated_dt = _parse_iso(report.get("generated_at"))
        if generated_dt is None:
            return None
        age_seconds = (datetime.now(timezone.utc) - generated_dt).total_seconds()
        if age_seconds > max_age_seconds:
            return None
        for signal in list(report.get("built_signals") or []):
            if str(signal.get("strategy_id") or "") != strategy_id:
                continue
            if not bool(signal.get("risk_admissible")):
                continue
            if str(signal.get("pair") or "") != pair:
                continue
            if side and str(signal.get("direction") or "") != side:
                continue
            return signal
        return None

    def enforce_entry(
        self,
        *,
        strategy_id: str,
        pair: str,
        side: str,
        signal_profile: str,
    ) -> dict[str, Any]:
        decision = self.load_risk_decision()
        trace: list[dict[str, Any]] = []
        codes: list[str] = []

        if not decision:
            codes.append(EXECUTION_RISK_DECISION_MISSING)
            self._record_enforcement("blocked", codes, strategy_id, pair, side)
            return {
                "entry_allowed": False,
                "blocked_reason_codes": codes,
                "enforcement_trace": [{"rule": "risk_decision_missing", "outcome": "blocked"}],
            }
        if not self.risk_decision_fresh(decision):
            codes.append(EXECUTION_RISK_ARTIFACT_STALE)
            self._record_enforcement("blocked", codes, strategy_id, pair, side)
            return {
                "entry_allowed": False,
                "blocked_reason_codes": codes,
                "enforcement_trace": [{"rule": "risk_artifact_stale", "outcome": "blocked"}],
            }

        if not bool(decision.get("allow_trading")):
            codes.append(EXECUTION_HARD_BLOCK_ALLOW_TRADING)
        if not bool(decision.get("new_entries_allowed")):
            codes.append(EXECUTION_HARD_BLOCK_NEW_ENTRIES)
        if bool(decision.get("force_reduce_only")):
            codes.append(EXECUTION_FORCE_REDUCE_ONLY)
        if bool(decision.get("cooldown_active")):
            codes.append(EXECUTION_COOLDOWN_ACTIVE)
        if side not in list(decision.get("allowed_directions") or []):
            codes.append(EXECUTION_BLOCKED_DIRECTION)
        allowed_strategy_ids = list(decision.get("allowed_strategy_ids") or [])
        blocked_strategy_ids = list(decision.get("blocked_strategy_ids") or [])
        if strategy_id in blocked_strategy_ids:
            codes.append(EXECUTION_BLOCKED_STRATEGY)
        elif allowed_strategy_ids and strategy_id not in allowed_strategy_ids:
            codes.append(EXECUTION_BLOCKED_STRATEGY)

        protective = dict(decision.get("protective_overrides") or {})
        if (
            protective.get("disable_aggressive_entries")
            or protective.get("force_conservative_execution")
        ) and signal_profile != "standard":
            codes.append(EXECUTION_AGGRESSIVE_ENTRY_BLOCKED)

        snapshot = self.load_global_portfolio() or {}
        open_trades = list(snapshot.get("open_trades") or [])
        open_trades_count = int(snapshot.get("open_trades_count") or len(open_trades))
        pair_count = sum(1 for trade in open_trades if str(trade.get("pair") or "") == pair)
        base = pair.split("/")[0] if "/" in pair else pair.split(":")[0]
        correlated_count = 0
        for trade in open_trades:
            trade_pair = str(trade.get("pair") or "")
            trade_base = trade_pair.split("/")[0] if "/" in trade_pair else trade_pair.split(":")[0]
            if trade_base == base:
                correlated_count += 1

        max_positions_total = int(decision.get("max_positions_total") or 0)
        max_positions_per_symbol = int(decision.get("max_positions_per_symbol") or 0)
        max_correlated_positions = int(decision.get("max_correlated_positions") or 0)
        if max_positions_total >= 0 and open_trades_count >= max_positions_total:
            codes.append(EXECUTION_PORTFOLIO_FULL)
        if max_positions_per_symbol > 0 and pair_count >= max_positions_per_symbol:
            codes.append(EXECUTION_SYMBOL_LIMIT)
        if max_correlated_positions > 0 and correlated_count >= max_correlated_positions:
            codes.append(EXECUTION_CORRELATION_LIMIT)

        status = "allowed" if not codes else "blocked"
        for code in codes:
            trace.append({"rule": code, "outcome": "blocked"})
        self._record_enforcement(status, codes, strategy_id, pair, side)
        return {
            "entry_allowed": not codes,
            "blocked_reason_codes": codes,
            "enforcement_trace": trace,
        }

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
    ) -> dict[str, Any]:
        decision = self.load_risk_decision()
        if not decision:
            self._record_enforcement("blocked", [EXECUTION_RISK_DECISION_MISSING], strategy_id, pair, side)
            return {
                "final_stake": 0.0,
                "blocked_reason_codes": [EXECUTION_RISK_DECISION_MISSING],
                "enforcement_trace": [{"rule": "risk_decision_missing", "outcome": "blocked"}],
            }
        if not self.risk_decision_fresh(decision):
            self._record_enforcement("blocked", [EXECUTION_RISK_ARTIFACT_STALE], strategy_id, pair, side)
            return {
                "final_stake": 0.0,
                "blocked_reason_codes": [EXECUTION_RISK_ARTIFACT_STALE],
                "enforcement_trace": [{"rule": "risk_artifact_stale", "outcome": "blocked"}],
            }

        trace: list[dict[str, Any]] = []
        codes: list[str] = []
        snapshot = self.load_global_portfolio() or {}
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
        if bool((decision.get("protective_overrides") or {}).get("disable_aggressive_entries")) and signal_profile != "standard":
            codes.append(EXECUTION_AGGRESSIVE_ENTRY_BLOCKED)

        execution_budget_multiplier = float(decision.get("execution_budget_multiplier") or 1.0)
        final_stake *= execution_budget_multiplier
        if execution_budget_multiplier < 1.0:
            trace.append({"rule": "execution_budget_multiplier", "value": execution_budget_multiplier, "outcome": "tightened"})

        try:
            per_position_pct = float(decision.get("max_position_size_pct") or 0.0)
        except (TypeError, ValueError):
            per_position_pct = 0.0
        if per_position_pct <= 0:
            codes.append(EXECUTION_STAKE_BLOCKED)
        elif total_equity and total_equity > 0:
            final_stake = min(final_stake, total_equity * (per_position_pct / 100.0))
            trace.append({"rule": "max_position_size_pct", "value": per_position_pct, "outcome": "capped"})

        try:
            total_exposure_pct = float(decision.get("max_total_exposure_pct") or 0.0)
        except (TypeError, ValueError):
            total_exposure_pct = 0.0
        if total_equity and total_equity > 0 and total_exposure_pct > 0:
            remaining = max(0.0, (total_equity * (total_exposure_pct / 100.0)) - current_open_stakes)
            final_stake = min(final_stake, remaining)
            trace.append({"rule": "max_total_exposure_pct", "value": total_exposure_pct, "outcome": "capped"})

        final_stake = min(final_stake, float(max_stake))
        if min_stake is not None and final_stake < float(min_stake):
            codes.append(EXECUTION_STAKE_BLOCKED)
            final_stake = 0.0

        status = "allowed"
        if final_stake <= 0:
            status = "blocked"
        elif final_stake < float(proposed_stake):
            status = "clamped"
            codes.append(EXECUTION_STAKE_CLAMPED)

        self._record_enforcement(status, codes, strategy_id, pair, side, final_stake=round(max(0.0, final_stake), 8))
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
            self._record_enforcement("blocked", [EXECUTION_RISK_DECISION_MISSING], strategy_id, pair, side)
            return {
                "final_leverage": 1.0,
                "blocked_reason_codes": [EXECUTION_RISK_DECISION_MISSING],
                "enforcement_trace": [{"rule": "risk_decision_missing", "outcome": "blocked"}],
            }
        if not self.risk_decision_fresh(decision):
            self._record_enforcement("blocked", [EXECUTION_RISK_ARTIFACT_STALE], strategy_id, pair, side)
            return {
                "final_leverage": 1.0,
                "blocked_reason_codes": [EXECUTION_RISK_ARTIFACT_STALE],
                "enforcement_trace": [{"rule": "risk_artifact_stale", "outcome": "blocked"}],
            }

        codes: list[str] = []
        leverage_cap = min(float(decision.get("leverage_cap") or 1.0), float(max_leverage))
        final_leverage = min(float(proposed_leverage or 1.0), leverage_cap)
        if final_leverage < float(proposed_leverage or 1.0):
            codes.append(EXECUTION_LEVERAGE_CLAMPED)
            status = "clamped"
        else:
            status = "allowed"
        self._record_enforcement(status, codes, strategy_id, pair, side, final_leverage=round(max(1.0, final_leverage), 4))
        return {
            "final_leverage": round(max(1.0, final_leverage), 4),
            "blocked_reason_codes": codes,
            "enforcement_trace": [{"rule": "leverage_cap", "value": leverage_cap, "outcome": status}],
        }

    def _record_enforcement(
        self,
        status: str,
        reason_codes: list[str],
        strategy_id: str,
        pair: str,
        side: str,
        final_stake: float | None = None,
        final_leverage: float | None = None,
    ) -> None:
        payload = self._read_json(self.enforcement_path()) or {
            "hard_enforcement_enabled": True,
            "enforced_by": ["freqtrade_strategy_hook_local"],
            "last_enforcement_status": "unknown",
            "last_blocked_order_reason_codes": [],
            "enforcement_counters": {},
        }
        counters = dict(payload.get("enforcement_counters") or {})
        if status == "blocked":
            counters["blocked_total"] = int(counters.get("blocked_total") or 0) + 1
        if status == "clamped" and final_stake is not None:
            counters["clamped_stake_total"] = int(counters.get("clamped_stake_total") or 0) + 1
        if status == "clamped" and final_leverage is not None:
            counters["clamped_leverage_total"] = int(counters.get("clamped_leverage_total") or 0) + 1
        if EXECUTION_BLOCKED_DIRECTION in reason_codes:
            counters["blocked_by_direction"] = int(counters.get("blocked_by_direction") or 0) + 1
        if EXECUTION_BLOCKED_STRATEGY in reason_codes:
            counters["blocked_by_strategy"] = int(counters.get("blocked_by_strategy") or 0) + 1
        if any(code in reason_codes for code in (EXECUTION_PORTFOLIO_FULL, EXECUTION_SYMBOL_LIMIT, EXECUTION_CORRELATION_LIMIT)):
            counters["blocked_by_portfolio_limit"] = int(counters.get("blocked_by_portfolio_limit") or 0) + 1
        if EXECUTION_COOLDOWN_ACTIVE in reason_codes:
            counters["blocked_by_cooldown"] = int(counters.get("blocked_by_cooldown") or 0) + 1
        if EXECUTION_FORCE_REDUCE_ONLY in reason_codes:
            counters["blocked_by_reduce_only"] = int(counters.get("blocked_by_reduce_only") or 0) + 1
        if EXECUTION_RISK_ARTIFACT_STALE in reason_codes:
            counters["blocked_by_stale_artifact"] = int(counters.get("blocked_by_stale_artifact") or 0) + 1

        payload.update(
            {
                "generated_at": _now_iso(),
                "hard_enforcement_enabled": True,
                "enforced_by": ["freqtrade_strategy_hook_local"],
                "last_enforcement_status": status,
                "last_blocked_order_reason_codes": list(reason_codes),
                "last_strategy_id": strategy_id,
                "last_pair": pair,
                "last_side": side,
                "enforcement_counters": counters,
            }
        )
        if final_stake is not None:
            payload["last_final_stake"] = final_stake
        if final_leverage is not None:
            payload["last_final_leverage"] = final_leverage
        self._write_json(self.enforcement_path(), payload)
