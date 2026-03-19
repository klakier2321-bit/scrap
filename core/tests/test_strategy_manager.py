from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core.strategy_manager import StrategyManager
import yaml


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

    def test_build_candidate_assessment_uses_manifest_and_candidate_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            user_data_dir = repo_root / "trading" / "freqtrade" / "user_data"
            reports_dir = repo_root / "data" / "ai_control" / "strategy_reports"
            snapshots_dir = repo_root / "data" / "ai_control" / "dry_run_snapshots"
            (repo_root / "research" / "candidates" / "candidate_v1").mkdir(parents=True)
            (repo_root / "research" / "risk").mkdir(parents=True)
            (repo_root / "research" / "promotion").mkdir(parents=True)
            (repo_root / "research" / "evaluation").mkdir(parents=True)
            user_data_dir.mkdir(parents=True)
            reports_dir.mkdir(parents=True)
            snapshots_dir.mkdir(parents=True)

            manifest = {
                "strategy_id": "candidate_v1",
                "strategy_name": "CandidateStrategy",
                "market_type": "futures",
                "status": "limited_dry_run_candidate",
                "active_side_policy": "long_biased_with_parked_short",
                "candidate_bot_id": "freqtrade_candidate",
                "risk_report_path": "research/risk/candidate_v1_risk_report.json",
                "promotion_decision_path": "research/promotion/candidate_v1_promotion_decision.md",
                "broad_backtest_summary_path": "research/evaluation/candidate_v1_broad_backtest_summary.json",
            }
            (repo_root / "research" / "candidates" / "candidate_v1" / "strategy_manifest.yaml").write_text(
                yaml.safe_dump(manifest, sort_keys=False),
                encoding="utf-8",
            )
            (repo_root / "research" / "risk" / "candidate_v1_risk_report.json").write_text(
                json.dumps({"status": "warn", "promotion_gate": "ready_for_limited_dry_run"}),
                encoding="utf-8",
            )
            (repo_root / "research" / "evaluation" / "candidate_v1_broad_backtest_summary.json").write_text(
                json.dumps({"result": "pass_for_limited_dry_run", "notes": []}),
                encoding="utf-8",
            )
            (repo_root / "research" / "promotion" / "candidate_v1_promotion_decision.md").write_text(
                "\n".join(
                    [
                        "# Candidate Promotion Decision",
                        "- promotion_decision: promote_to_limited_dry_run",
                        "- dry_run_gate: ready",
                        "- next_step: Continue limited candidate dry run.",
                    ]
                ),
                encoding="utf-8",
            )

            manager = StrategyManager(
                user_data_dir=user_data_dir,
                reports_dir=reports_dir,
                dry_run_snapshots_dir=snapshots_dir,
            )
            assessment = manager.build_candidate_assessment(
                "candidate_v1",
                dry_run_health={"ready": True},
                dry_run_snapshot={"strategy": "CandidateStrategy"},
            )

            self.assertEqual(assessment["candidate_id"], "candidate_v1")
            self.assertEqual(assessment["broad_backtest_status"], "pass")
            self.assertEqual(assessment["risk_gate_status"], "ready")
            self.assertEqual(assessment["dry_run_gate_status"], "ready")
            self.assertEqual(assessment["overall_decision"], "promote_to_limited_dry_run")
            self.assertEqual(assessment["blocked_reasons"], [])
