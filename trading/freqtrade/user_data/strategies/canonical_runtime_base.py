# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa: F401
# isort: skip_file
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pandas import DataFrame

from freqtrade.strategy import IStrategy, Trade

from futures_risk_guard_mixin import FuturesRiskGuardMixin


class CanonicalRuntimeStrategyBase(FuturesRiskGuardMixin, IStrategy):
    INTERFACE_VERSION = 3

    can_short: bool = True
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count: int = 1
    minimal_roi = {"120": 0.0, "0": 0.01}
    stoploss = -0.03
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}
    signal_max_age_seconds: int = 600
    max_holding_minutes: int = 360

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        del current_time, current_rate, entry_tag, kwargs
        return self.enforce_risk_leverage(
            pair=pair,
            side=side,
            proposed_leverage=proposed_leverage or 1.0,
            max_leverage=max_leverage,
        )

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        del current_time, current_rate, leverage, kwargs
        return self.enforce_risk_stake(
            pair=pair,
            side=side,
            entry_tag=entry_tag,
            proposed_stake=proposed_stake,
            min_stake=min_stake,
            max_stake=max_stake,
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["canonical_runtime_marker"] = 1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0
        dataframe.loc[:, "enter_tag"] = None

        signal = self._risk_guard().latest_signal(
            strategy_id=str(self.risk_strategy_id),
            pair=metadata["pair"],
            max_age_seconds=self.signal_max_age_seconds,
        )
        if signal is None or dataframe.empty:
            return dataframe

        direction = str(signal.get("direction") or "")
        entry_tag = str(signal.get("entry_type") or self.risk_strategy_id)
        if direction == "long":
            dataframe.loc[dataframe.index[-1], ["enter_long", "enter_tag"]] = (1, entry_tag)
        elif direction == "short" and self.can_short:
            dataframe.loc[dataframe.index[-1], ["enter_short", "enter_tag"]] = (1, entry_tag)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0
        dataframe.loc[:, "exit_tag"] = None
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        del pair, current_rate, current_profit, kwargs
        opened_at = trade.open_date_utc
        if opened_at is None:
            return None
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        if current_time - opened_at >= timedelta(minutes=int(self.max_holding_minutes)):
            return f"time_stop_{self.max_holding_minutes}m"
        return None
