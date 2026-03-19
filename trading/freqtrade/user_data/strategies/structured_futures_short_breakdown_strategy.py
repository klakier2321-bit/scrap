# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa: F401
# isort: skip_file
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pandas import DataFrame

from freqtrade.strategy import IStrategy, Trade, merge_informative_pair

import talib.abstract as ta
from technical import qtpylib


class StructuredFuturesShortBreakdownStrategy(IStrategy):
    """
    Dedicated short-side candidate.

    This candidate is intentionally separate from the baseline so the short edge
    can be validated or rejected without contaminating the long-biased baseline.
    """

    INTERFACE_VERSION = 3

    can_short: bool = True
    timeframe = "5m"
    informative_timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count: int = 240

    minimal_roi = {
        "180": 0.0,
        "60": 0.01,
        "0": 0.02,
    }
    stoploss = -0.025
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
        del pair, current_time, current_rate, proposed_leverage, entry_tag, side, kwargs
        return min(2.0, max_leverage)

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
        dataframe["swing_low_6"] = dataframe["low"].shift(1).rolling(6).min()
        dataframe["breakdown_short"] = dataframe["close"] < dataframe["swing_low_6"]
        dataframe["trend_spread"] = (dataframe["ema_fast"] - dataframe["ema_slow"]) / dataframe["close"]

        if self.dp:
            informative = self.dp.get_pair_dataframe(
                pair=metadata["pair"],
                timeframe=self.informative_timeframe,
            )
            informative["ema_fast"] = ta.EMA(informative, timeperiod=50)
            informative["ema_slow"] = ta.EMA(informative, timeperiod=200)
            informative["rsi"] = ta.RSI(informative, timeperiod=14)
            informative["adx"] = ta.ADX(informative)
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
        if "adx_1h" not in dataframe:
            dataframe["adx_1h"] = dataframe["adx"]
        if "macd_1h" not in dataframe:
            dataframe["macd_1h"] = dataframe["macd"]
        if "macdsignal_1h" not in dataframe:
            dataframe["macdsignal_1h"] = dataframe["macdsignal"]

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0

        short_conditions = [
            dataframe["volume"] > dataframe["volume_mean_20"],
            dataframe["adx"] > 24,
            dataframe["adx_1h"] > 18,
            dataframe["ema_fast_1h"] < dataframe["ema_slow_1h"] * 0.992,
            dataframe["rsi_1h"] < 45,
            dataframe["macd_1h"] < dataframe["macdsignal_1h"],
            dataframe["close"] < dataframe["ema_trend"] * 0.995,
            dataframe["close"] < dataframe["ema_fast"],
            dataframe["close"] < dataframe["ema_slow"],
            dataframe["breakdown_short"],
            dataframe["trend_spread"] < -0.003,
            qtpylib.crossed_below(dataframe["rsi"], 44),
        ]
        dataframe.loc[
            short_conditions[0]
            & short_conditions[1]
            & short_conditions[2]
            & short_conditions[3]
            & short_conditions[4]
            & short_conditions[5]
            & short_conditions[6]
            & short_conditions[7]
            & short_conditions[8]
            & short_conditions[9]
            & short_conditions[10]
            & short_conditions[11],
            ["enter_short", "enter_tag"],
        ] = (1, "breakdown_short_candidate")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0

        short_exit = (
            (dataframe["close"] > dataframe["ema_fast"])
            | (dataframe["macd"] > dataframe["macdsignal"])
            | (dataframe["rsi"] < 34)
            | (dataframe["rsi_1h"] > 48)
        )
        dataframe.loc[short_exit, ["exit_short", "exit_tag"]] = (1, "breakdown_short_invalidation")
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
        del pair, current_rate, kwargs
        opened_at = trade.open_date_utc
        if opened_at is None:
            return None
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        if current_profit >= 0.012:
            return "short_profit_take"
        if current_time - opened_at >= timedelta(hours=6):
            return "time_stop_short_6h"
        return None
