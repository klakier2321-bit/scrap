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
    base_risk_per_trade_pct: float = 0.006
    min_risk_per_trade_pct: float = 0.0025
    max_risk_per_trade_pct: float = 0.009
    min_position_factor: float = 0.35
    max_position_factor: float = 1.35
    target_atr_ratio: float = 0.012

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

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _get_latest_candle(self, pair: str) -> dict | None:
        if not self.dp:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        return dataframe.iloc[-1].to_dict()

    def _estimate_signal_quality(self, candle: dict | None, side: str) -> float:
        if not candle:
            return 0.85

        adx = float(candle.get("adx", 0.0) or 0.0)
        trend_spread = abs(float(candle.get("trend_spread", 0.0) or 0.0))
        macd = float(candle.get("macd", 0.0) or 0.0)
        macdsignal = float(candle.get("macdsignal", 0.0) or 0.0)
        rsi_1h = float(candle.get("rsi_1h", 50.0) or 50.0)

        quality = 0.75
        quality += self._clamp((adx - 18.0) / 20.0, 0.0, 0.25)
        quality += self._clamp(trend_spread / 0.01, 0.0, 0.18)
        quality += 0.08 if macd > macdsignal else -0.04

        if side == "long":
            quality += self._clamp((rsi_1h - 50.0) / 25.0, -0.05, 0.15)
        else:
            quality += self._clamp((50.0 - rsi_1h) / 25.0, -0.05, 0.12)
            # Shorts are still the weaker side in broad tests, so size them more cautiously.
            quality *= 0.72

        return self._clamp(quality, 0.45, 1.20)

    def _estimate_volatility_factor(self, candle: dict | None, current_rate: float) -> float:
        if not candle or current_rate <= 0:
            return 0.8

        atr = float(candle.get("atr", 0.0) or 0.0)
        if atr <= 0:
            return 0.8

        atr_ratio = atr / current_rate
        if atr_ratio <= 0:
            return 0.8

        factor = self.target_atr_ratio / atr_ratio
        return self._clamp(factor, 0.45, 1.25)

    def _estimate_drawdown_factor(self) -> float:
        if not getattr(self, "wallets", None):
            return 1.0

        try:
            current_balance = float(self.wallets.get_total_stake_amount())
            starting_balance = float(self.wallets.get_starting_balance())
        except Exception:
            return 1.0

        if current_balance <= 0 or starting_balance <= 0:
            return 1.0

        peak_balance = getattr(self, "_peak_stake_balance", starting_balance)
        peak_balance = max(peak_balance, current_balance, starting_balance)
        self._peak_stake_balance = peak_balance

        drawdown_ratio = max(0.0, (peak_balance - current_balance) / peak_balance)
        factor = 1.0 - (drawdown_ratio * 4.0)
        return self._clamp(factor, 0.35, 1.0)

    def _calculate_dynamic_stake(
        self,
        *,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        current_rate: float,
        side: str,
        pair: str,
    ) -> float:
        candle = self._get_latest_candle(pair)
        signal_quality = self._estimate_signal_quality(candle, side)
        volatility_factor = self._estimate_volatility_factor(candle, current_rate)
        drawdown_factor = self._estimate_drawdown_factor()

        position_factor = self._clamp(
            signal_quality * volatility_factor * drawdown_factor,
            self.min_position_factor,
            self.max_position_factor,
        )

        starting_balance = None
        if getattr(self, "wallets", None):
            try:
                starting_balance = float(self.wallets.get_starting_balance())
            except Exception:
                starting_balance = None
        if not starting_balance or starting_balance <= 0:
            starting_balance = max(proposed_stake * 5.0, max_stake)

        dynamic_risk_pct = self._clamp(
            self.base_risk_per_trade_pct * signal_quality * drawdown_factor,
            self.min_risk_per_trade_pct,
            self.max_risk_per_trade_pct,
        )

        stop_distance = abs(self.stoploss)
        effective_leverage = max(leverage, 1.0)
        risk_capped_stake = max_stake
        if stop_distance > 0:
            risk_budget = starting_balance * dynamic_risk_pct
            risk_capped_stake = risk_budget / (stop_distance * effective_leverage)

        desired_stake = proposed_stake * position_factor
        final_stake = min(desired_stake, risk_capped_stake, max_stake)
        if min_stake is not None:
            final_stake = max(final_stake, min_stake)
        return final_stake

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
        del current_time, entry_tag, kwargs
        return self._calculate_dynamic_stake(
            proposed_stake=proposed_stake,
            min_stake=min_stake,
            max_stake=max_stake,
            leverage=leverage,
            current_rate=current_rate,
            side=side,
            pair=pair,
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=55)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["volume_mean_20"] = dataframe["volume"].rolling(20).mean().fillna(0.0)
        dataframe["pullback_long"] = dataframe["low"] <= dataframe["ema_fast"] * 1.002
        dataframe["pullback_short"] = dataframe["high"] >= dataframe["ema_fast"] * 0.999
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
            dataframe["rsi_1h"] > 54,
            dataframe["macd_1h"] > dataframe["macdsignal_1h"],
            dataframe["close"] > dataframe["ema_trend"],
            dataframe["close"] > dataframe["ema_fast"],
            dataframe["ema_fast"] > dataframe["ema_slow"],
            dataframe["pullback_long"],
            dataframe["macd"] > dataframe["macdsignal"],
            qtpylib.crossed_above(dataframe["rsi"], 54),
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
                & long_conditions[7]
                & long_conditions[8]
                & long_conditions[9]
                & long_conditions[10],
                ["enter_long", "enter_tag"],
            ] = (1, "trend_pullback_long")

        short_conditions = [
            dataframe["volume"] > dataframe["volume_mean_20"],
            dataframe["adx"] > 24,
            dataframe["ema_fast_1h"] < dataframe["ema_slow_1h"] * 0.995,
            dataframe["rsi_1h"] < 43,
            dataframe["macd_1h"] < dataframe["macdsignal_1h"],
            dataframe["close"] < dataframe["ema_trend"] * 0.996,
            dataframe["close"] < dataframe["ema_fast"],
            dataframe["close"] < dataframe["ema_slow"],
            dataframe["ema_fast"] < dataframe["ema_slow"],
            dataframe["pullback_short"],
            dataframe["macd"] < dataframe["macdsignal"],
            dataframe["trend_spread"] < -0.002,
            qtpylib.crossed_below(dataframe["rsi"], 42),
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
                & short_conditions[7]
                & short_conditions[8]
                & short_conditions[9]
                & short_conditions[10]
                & short_conditions[11],
                ["enter_short", "enter_tag"],
            ] = (1, "trend_pullback_short")

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0

        long_exit = (
            (dataframe["close"] < dataframe["ema_fast"])
            | (dataframe["rsi"] > 68)
            | (dataframe["macd"] < dataframe["macdsignal"])
            | (dataframe["rsi_1h"] < 48)
        )
        dataframe.loc[long_exit, ["exit_long", "exit_tag"]] = (1, "trend_invalidation_long")

        short_exit = (
            (dataframe["close"] > dataframe["ema_fast"])
            | (dataframe["rsi"] < 35)
            | (dataframe["macd"] > dataframe["macdsignal"])
            | (dataframe["rsi_1h"] > 48)
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
