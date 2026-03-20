"""Registry for implemented strategy modules."""

from __future__ import annotations

from .base import BaseStrategy
from .strategies.breakout.breakout_from_compression import BreakoutFromCompressionStrategy
from .strategies.defense.defense_only import DefenseOnlyStrategy
from .strategies.event.panic_reversal import PanicReversalStrategy
from .strategies.range.range_mean_reversion import RangeMeanReversionStrategy
from .strategies.trend.trend_pullback_continuation import TrendPullbackContinuationStrategy


STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "trend_pullback_continuation_v1": TrendPullbackContinuationStrategy,
    "breakout_from_compression_v1": BreakoutFromCompressionStrategy,
    "range_mean_reversion_v1": RangeMeanReversionStrategy,
    "panic_reversal_v1": PanicReversalStrategy,
    "defense_only_v1": DefenseOnlyStrategy,
}
