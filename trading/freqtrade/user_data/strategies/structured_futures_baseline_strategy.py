# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa: F401
# isort: skip_file
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pandas import DataFrame

from freqtrade.strategy import IStrategy, Trade, merge_informative_pair

import talib.abstract as ta
from technical import qtpylib


class StructuredFuturesBaselineStrategy(IStrategy):
    """
    First structured futures baseline candidate.

    The goal is not to maximize profit immediately, but to produce a clean,
    futures-aware candidate that can move through `backtest + risk + dry_run`.
    """

    INTERFACE_VERSION = 3

    can_short: bool = True
    timeframe = "5m"
    informative_timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count: int = 240

    minimal_roi = {
        "360": 0.0,
        "120": 0.012,
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

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 6},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 72,
                "trade_limit": 2,
                "stop_duration_candles": 18,
                "only_per_pair": False,
            },
        ]

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
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean_20"] = dataframe["volume"].rolling(20).mean().fillna(0.0)
        dataframe["pullback_long"] = dataframe["low"] <= dataframe["ema_fast"] * 1.002
        dataframe["pullback_short"] = dataframe["high"] >= dataframe["ema_fast"] * 0.998

        if self.dp:
            informative = self.dp.get_pair_dataframe(
                pair=metadata["pair"],
                timeframe=self.informative_timeframe,
            )
            informative["ema_fast"] = ta.EMA(informative, timeperiod=50)
            informative["ema_slow"] = ta.EMA(informative, timeperiod=200)
            informative["rsi"] = ta.RSI(informative, timeperiod=14)
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

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0

        long_conditions = [
            dataframe["volume"] > dataframe["volume_mean_20"],
            dataframe["adx"] > 18,
            dataframe["ema_fast_1h"] > dataframe["ema_slow_1h"],
            dataframe["rsi_1h"] > 52,
            dataframe["close"] > dataframe["ema_trend"],
            dataframe["close"] > dataframe["ema_fast"],
            dataframe["pullback_long"],
            qtpylib.crossed_above(dataframe["rsi"], 52),
        ]
        if long_conditions:
            dataframe.loc[
                long_conditions[0]
                & long_conditions[1]
                & long_conditions[2]
                & long_conditions[3]
                & long_conditions[4]
                & long_conditions[5]
                & long_conditions[6]
                & long_conditions[7],
                ["enter_long", "enter_tag"],
            ] = (1, "trend_pullback_long")

        short_conditions = [
            dataframe["volume"] > dataframe["volume_mean_20"],
            dataframe["adx"] > 18,
            dataframe["ema_fast_1h"] < dataframe["ema_slow_1h"],
            dataframe["rsi_1h"] < 48,
            dataframe["close"] < dataframe["ema_trend"],
            dataframe["close"] < dataframe["ema_fast"],
            dataframe["pullback_short"],
            qtpylib.crossed_below(dataframe["rsi"], 48),
        ]
        if short_conditions:
            dataframe.loc[
                short_conditions[0]
                & short_conditions[1]
                & short_conditions[2]
                & short_conditions[3]
                & short_conditions[4]
                & short_conditions[5]
                & short_conditions[6]
                & short_conditions[7],
                ["enter_short", "enter_tag"],
            ] = (1, "trend_pullback_short")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0

        long_exit = (
            (dataframe["close"] < dataframe["ema_slow"])
            | (dataframe["rsi"] > 68)
            | (dataframe["rsi_1h"] < 48)
        )
        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (1, "trend_invalidation_long")

        short_exit = (
            (dataframe["close"] > dataframe["ema_slow"])
            | (dataframe["rsi"] < 32)
            | (dataframe["rsi_1h"] > 52)
        )
        dataframe.loc[short_exit, ["exit_short", "exit_tag"]] = (1, "trend_invalidation_short")

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
