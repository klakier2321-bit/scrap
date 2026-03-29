# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa: F401
# isort: skip_file
from __future__ import annotations

from canonical_runtime_base import CanonicalRuntimeStrategyBase


class PanicReversalV1RuntimeStrategy(CanonicalRuntimeStrategyBase):
    can_short = False
    risk_strategy_id = "panic_reversal_v1"
    risk_bot_id = "ft_panic_reversal_v1"
    default_signal_profile = "aggressive"
    max_holding_minutes = 120
