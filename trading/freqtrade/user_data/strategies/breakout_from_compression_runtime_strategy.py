# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa: F401
# isort: skip_file
from __future__ import annotations

from canonical_runtime_base import CanonicalRuntimeStrategyBase


class BreakoutFromCompressionV1RuntimeStrategy(CanonicalRuntimeStrategyBase):
    can_short = True
    risk_strategy_id = "breakout_from_compression_v1"
    risk_bot_id = "ft_breakout_from_compression_v1"
    default_signal_profile = "aggressive"
    max_holding_minutes = 180
