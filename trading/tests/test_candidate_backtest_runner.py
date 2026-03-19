from __future__ import annotations

import unittest

from trading.analysis.candidate_backtest_runner import WindowResult, build_summary, derive_verdict


class CandidateBacktestRunnerTests(unittest.TestCase):
    def test_long_biased_candidate_can_pass_with_parked_short(self) -> None:
        manifest = {
            "strategy_id": "structured_futures_baseline_v1",
            "strategy_name": "StructuredFuturesBaselineStrategy",
            "market_type": "futures",
            "active_side_policy": "long_biased_with_parked_short",
        }
        windows = [
            WindowResult("full_window", "20251119-20260319", 23, 0.10, 0.27, 0.10, -0.80),
            WindowResult("historical_window", "20251119-20251231", 5, 0.02, 0.10, 0.02, -0.10),
            WindowResult("mid_window", "20260101-20260214", 10, 0.01, 0.12, 0.01, -0.30),
            WindowResult("recent_window", "20260215-20260319", 8, 0.19, 0.11, 0.19, -0.40),
        ]
        verdict, notes = derive_verdict(manifest, windows)
        self.assertEqual(verdict, "pass_for_limited_dry_run")
        self.assertEqual(notes, [])
        summary = build_summary(manifest, windows)
        self.assertEqual(summary["result"], "pass_for_limited_dry_run")

    def test_active_short_side_failing_forces_needs_rework(self) -> None:
        manifest = {
            "strategy_id": "structured_futures_short_breakdown_v1",
            "strategy_name": "StructuredFuturesShortBreakdownStrategy",
            "market_type": "futures",
            "allowed_sides": "short",
        }
        windows = [
            WindowResult("full_window", "20251119-20260319", 23, -0.20, 0.27, 0.0, -0.20),
            WindowResult("historical_window", "20251119-20251231", 5, -0.10, 0.10, 0.0, -0.10),
            WindowResult("mid_window", "20260101-20260214", 10, -0.05, 0.12, 0.0, -0.05),
            WindowResult("recent_window", "20260215-20260319", 8, -0.01, 0.11, 0.0, -0.01),
        ]
        verdict, notes = derive_verdict(manifest, windows)
        self.assertEqual(verdict, "needs_rework")
        self.assertTrue(any("short" in note.lower() or "ujemny" in note.lower() for note in notes))
