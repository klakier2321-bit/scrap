# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa: F401
# isort: skip_file
from __future__ import annotations

from canonical_runtime_base import CanonicalRuntimeStrategyBase


class TrendPullbackContinuationV1RuntimeStrategy(CanonicalRuntimeStrategyBase):
    can_short = True
    risk_strategy_id = "trend_pullback_continuation_v1"
    risk_bot_id = "ft_trend_pullback_continuation_v1"
    default_signal_profile = "standard"
    max_holding_minutes = 480
