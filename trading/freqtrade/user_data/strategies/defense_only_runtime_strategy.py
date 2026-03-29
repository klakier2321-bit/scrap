# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa: F401
# isort: skip_file
from __future__ import annotations

from canonical_runtime_base import CanonicalRuntimeStrategyBase


class DefenseOnlyV1RuntimeStrategy(CanonicalRuntimeStrategyBase):
    can_short = False
    risk_strategy_id = "defense_only_v1"
    risk_bot_id = "ft_defense_only_v1"
    default_signal_profile = "defensive"
    max_holding_minutes = 60
