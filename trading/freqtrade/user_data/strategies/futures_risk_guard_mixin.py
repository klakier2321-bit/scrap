from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.risk_management.execution_guard import RiskExecutionGuard


class FuturesRiskGuardMixin:
    risk_bot_id: str = "freqtrade_candidate"
    risk_strategy_id: str = "unknown_strategy"
    default_signal_profile: str = "aggressive"

    def _risk_guard(self) -> RiskExecutionGuard:
        guard = getattr(self, "_cached_risk_execution_guard", None)
        if guard is None:
            guard = RiskExecutionGuard(bot_id=str(self.risk_bot_id))
            self._cached_risk_execution_guard = guard
        return guard

    def resolve_signal_profile(self, entry_tag: str | None) -> str:
        tag = str(entry_tag or "").lower()
        if any(marker in tag for marker in ("breakout", "breakdown", "reversal", "panic", "squeeze")):
            return "aggressive"
        if any(marker in tag for marker in ("pullback", "continuation", "trend", "confirmation")):
            return "standard"
        return str(getattr(self, "default_signal_profile", "aggressive"))

    def _current_total_equity(self) -> float | None:
        wallets = getattr(self, "wallets", None)
        if not wallets:
            return None
        for method_name in ("get_total_stake_amount", "get_starting_balance"):
            getter = getattr(wallets, method_name, None)
            if getter is None:
                continue
            try:
                value = float(getter())
            except Exception:
                continue
            if value > 0:
                return value
        return None

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        del order_type, amount, rate, time_in_force, current_time, kwargs
        outcome = self._risk_guard().enforce_entry(
            strategy_id=str(self.risk_strategy_id),
            pair=pair,
            side=side,
            entry_tag=entry_tag,
            signal_profile=self.resolve_signal_profile(entry_tag),
        )
        return bool(outcome.get("entry_allowed"))

    def enforce_risk_stake(
        self,
        *,
        pair: str,
        side: str,
        entry_tag: str | None,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
    ) -> float:
        outcome = self._risk_guard().enforce_stake(
            strategy_id=str(self.risk_strategy_id),
            pair=pair,
            side=side,
            proposed_stake=proposed_stake,
            min_stake=min_stake,
            max_stake=max_stake,
            signal_profile=self.resolve_signal_profile(entry_tag),
            total_equity=self._current_total_equity(),
        )
        return float(outcome.get("final_stake") or 0.0)

    def enforce_risk_leverage(
        self,
        *,
        pair: str,
        side: str,
        proposed_leverage: float,
        max_leverage: float,
    ) -> float:
        outcome = self._risk_guard().enforce_leverage(
            strategy_id=str(self.risk_strategy_id),
            pair=pair,
            side=side,
            proposed_leverage=proposed_leverage,
            max_leverage=max_leverage,
        )
        return float(outcome.get("final_leverage") or 1.0)
