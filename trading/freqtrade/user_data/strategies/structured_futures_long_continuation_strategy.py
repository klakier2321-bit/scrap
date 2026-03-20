# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa: F401
# isort: skip_file
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pandas import DataFrame

from freqtrade.strategy import IStrategy, Trade, merge_informative_pair

import talib.abstract as ta
from technical import qtpylib
from futures_risk_guard_mixin import FuturesRiskGuardMixin


class StructuredFuturesLongContinuationStrategy(FuturesRiskGuardMixin, IStrategy):
    """
    Dedicated long continuation candidate.

    This is the cleaner long-only sibling of the baseline candidate.
    """

    INTERFACE_VERSION = 3

    can_short: bool = False
    risk_strategy_id: str = "structured_futures_long_continuation_v1"
    risk_bot_id: str = "freqtrade_candidate"
    default_signal_profile: str = "aggressive"
    timeframe = "5m"
    informative_timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count: int = 240

    minimal_roi = {
        "240": 0.0,
        "90": 0.012,
        "0": 0.025,
    }
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

    def informative_pairs(self):
        if not self.dp:
            return []
        return [(pair, self.informative_timeframe) for pair in self.dp.current_whitelist()]

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
            proposed_leverage=min(2.0, proposed_leverage or max_leverage),
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
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=55)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe)
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["volume_mean_20"] = dataframe["volume"].rolling(20).mean().fillna(0.0)
        dataframe["swing_high_6"] = dataframe["high"].shift(1).rolling(6).max()
        dataframe["trend_spread"] = (dataframe["ema_fast"] - dataframe["ema_slow"]) / dataframe["close"]

        if self.dp:
            informative = self.dp.get_pair_dataframe(
                pair=metadata["pair"],
                timeframe=self.informative_timeframe,
            )
            informative["ema_fast"] = ta.EMA(informative, timeperiod=50)
            informative["ema_slow"] = ta.EMA(informative, timeperiod=200)
            informative["rsi"] = ta.RSI(informative, timeperiod=14)
            informative_macd = ta.MACD(informative)
            informative["macd"] = informative_macd["macd"]
            informative["macdsignal"] = informative_macd["macdsignal"]
            dataframe = merge_informative_pair(
                dataframe,
                informative,
                self.timeframe,
                self.informative_timeframe,
                ffill=True,
            )

        if "ema_fast_1h" not in dataframe:
            dataframe["ema_fast_1h"] = dataframe["ema_fast"]
        if "ema_slow_1h" not in dataframe:
            dataframe["ema_slow_1h"] = dataframe["ema_trend"]
        if "rsi_1h" not in dataframe:
            dataframe["rsi_1h"] = dataframe["rsi"]
        if "macd_1h" not in dataframe:
            dataframe["macd_1h"] = dataframe["macd"]
        if "macdsignal_1h" not in dataframe:
            dataframe["macdsignal_1h"] = dataframe["macdsignal"]

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0

        long_conditions = [
            dataframe["volume"] > dataframe["volume_mean_20"],
            dataframe["adx"] > 20,
            dataframe["ema_fast_1h"] > dataframe["ema_slow_1h"],
            dataframe["rsi_1h"] > 55,
            dataframe["macd_1h"] > dataframe["macdsignal_1h"],
            dataframe["close"] > dataframe["ema_trend"],
            dataframe["close"] > dataframe["ema_fast"],
            dataframe["close"] > dataframe["swing_high_6"],
            dataframe["trend_spread"] > 0.002,
            qtpylib.crossed_above(dataframe["rsi"], 55),
        ]
        dataframe.loc[
            long_conditions[0]
            & long_conditions[1]
            & long_conditions[2]
            & long_conditions[3]
            & long_conditions[4]
            & long_conditions[5]
            & long_conditions[6]
            & long_conditions[7]
            & long_conditions[8]
            & long_conditions[9],
            ["enter_long", "enter_tag"],
        ] = (1, "continuation_long_candidate")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0

        long_exit = (
            (dataframe["close"] < dataframe["ema_fast"])
            | (dataframe["macd"] < dataframe["macdsignal"])
            | (dataframe["rsi_1h"] < 50)
        )
        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (1, "continuation_long_invalidation")
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
        if current_time - opened_at >= timedelta(hours=12):
            return "time_stop_12h"
        return None
