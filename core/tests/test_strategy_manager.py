from __future__ import annotations

import unittest

from core.strategy_manager import StrategyManager


class StrategyManagerMergeTests(unittest.TestCase):
    def test_merge_report_with_assessment_and_readiness_gate(self) -> None:
        report = {
            "strategy_name": "SampleStrategy",
            "evaluation_status": "rejected",
            "generated_at": "2026-03-16T00:00:00+00:00",
        }
        assessment = {
            "summary": "Assessment summary",
            "recommendation": "reject",
            "risk_level": "high",
            "generated_at": "2026-03-16T00:10:00+00:00",
        }
        readiness_gate = {
            "overall_status": "blocked",
            "overall_decision": "improve_risk_before_promotion",
            "summary": "Combined gate is blocked.",
            "gates": {
                "backtest": {"status": "fail"},
                "risk": {"status": "fail"},
                "dry_run": {"status": "warn"},
            },
        }

        merged = StrategyManager.merge_report_with_assessment(
            report,
            assessment,
            readiness_gate,
        )

        self.assertEqual(merged["assessment_summary"], "Assessment summary")
        self.assertEqual(merged["assessment_recommendation"], "reject")
        self.assertEqual(merged["assessment_risk_level"], "high")
        self.assertEqual(merged["readiness_status"], "blocked")
        self.assertEqual(
            merged["readiness_decision"],
            "improve_risk_before_promotion",
        )
        self.assertEqual(merged["readiness_gate"]["gates"]["risk"]["status"], "fail")
