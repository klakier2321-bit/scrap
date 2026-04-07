from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.operator_home import build_operator_home


class OperatorHomeBuilderTests(unittest.TestCase):
    def test_build_operator_home_surfaces_structured_cluster_stopped_blocker(self) -> None:
        home = build_operator_home(
            health={
                "agents_status": "agents_guarded",
                "agents_reason": "manual_mode",
                "docker_available": True,
                "resource_guard": {
                    "allow_new_runs": True,
                    "allow_coding_dispatch": True,
                    "primary_reason": None,
                    "operator_message": "Host resource guard is healthy.",
                    "notes": [],
                },
            },
            futures_bots=[
                {
                    "bot_id": "ft_trend_pullback_continuation_v1",
                    "state": "exited",
                    "strategy": "TrendPullbackContinuationV1RuntimeStrategy",
                    "dry_run": True,
                    "description": "trend",
                }
            ],
            futures_health={
                "ready": False,
                "snapshot_age_seconds": 99999,
                "last_smoke_status": "degraded",
                "last_smoke_at": "2026-03-29T12:00:00+00:00",
                "warnings": [
                    "2026-03-29 old runtime warning line that should not become a top blocker",
                ],
            },
            futures_snapshot=None,
            risk_decision={},
            strategy_layer_report={},
            autopilot_status={"running": False},
            coding_status={"running": True, "review_tasks": 0},
            agents=[],
            observability_summary={
                "top_blockers": [],
                "recent_errors": [],
                "recent_handoffs": [],
                "operator_attention": [],
                "freshness": {},
            },
            runtime_flags={
                "kill_switch": {
                    "flag_name": "kill_switch",
                    "env_enabled": False,
                    "operator_enabled": False,
                    "effective_enabled": False,
                },
                "runtime_freeze": {
                    "flag_name": "runtime_freeze",
                    "env_enabled": False,
                    "operator_enabled": False,
                    "effective_enabled": False,
                },
            },
            recent_runs=[],
            settings=SimpleNamespace(
                agent_global_daily_budget_usd=1.5,
                agent_global_per_run_budget_usd=0.12,
            ),
        )

        self.assertEqual(home["futures"]["cluster_state"], "stopped")
        self.assertFalse(home["futures"]["ready"])
        self.assertEqual(home["futures"]["top_blockers"], ["futures_cluster_stopped"])
        self.assertEqual(home["attention_items"][0]["title"], "futures_cluster_stopped")

    def test_build_operator_home_blocks_ai_actions_when_runtime_freeze_is_enabled(self) -> None:
        home = build_operator_home(
            health={
                "agents_status": "agents_guarded",
                "agents_reason": "manual_or_mock_mode",
                "docker_available": True,
                "resource_guard": {
                    "allow_new_runs": True,
                    "allow_coding_dispatch": True,
                    "primary_reason": None,
                    "operator_message": "Host resource guard is healthy.",
                    "notes": [],
                },
            },
            futures_bots=[
                {
                    "bot_id": "ft_trend_pullback_continuation_v1",
                    "state": "running",
                    "strategy": "TrendPullbackContinuationV1RuntimeStrategy",
                    "dry_run": True,
                    "description": "trend",
                },
                {
                    "bot_id": "ft_breakout_from_compression_v1",
                    "state": "exited",
                    "strategy": "BreakoutFromCompressionV1RuntimeStrategy",
                    "dry_run": True,
                    "description": "breakout",
                },
            ],
            futures_health={
                "ready": False,
                "snapshot_age_seconds": 180,
                "last_smoke_status": "fail",
                "last_smoke_at": "2026-03-29T12:00:00+00:00",
                "warnings": ["cluster_member_not_ready"],
            },
            futures_snapshot={"open_trades_count": 2},
            risk_decision={
                "trading_mode": "reduced_risk",
                "allow_trading": False,
                "force_reduce_only": True,
                "cooldown_active": True,
                "risk_reason_codes": ["cooldown_active"],
            },
            strategy_layer_report={
                "preferred_risk_admitted_strategy_id": "trend_pullback_continuation_v1",
            },
            autopilot_status={"running": False},
            coding_status={"running": False},
            agents=[
                {
                    "name": "system_lead_agent",
                    "activation_mode": "always_on_guarded",
                    "operational_state": "active_core",
                },
                {
                    "name": "architecture_agent",
                    "activation_mode": "manual_only",
                    "operational_state": "manual_only",
                },
                {
                    "name": "trend_pullback_steward",
                    "activation_mode": "disabled_by_default",
                    "operational_state": "disabled",
                },
            ],
            observability_summary={
                "top_blockers": [
                    {
                        "title": "Runtime freeze",
                        "severity": "high",
                        "why_blocking": "AI runtime is paused.",
                        "area": "ai_runtime",
                    }
                ],
                "recent_errors": [
                    {
                        "title": "Control API timeout",
                        "summary": "One request timed out.",
                        "severity": "medium",
                        "source": "api",
                    }
                ],
                "recent_handoffs": [
                    {
                        "title": "Handoff to strategy_agent",
                        "summary": "Review the next canonical increment.",
                        "from_agent": "system_lead_agent",
                        "status": "handoff",
                    }
                ],
                "operator_attention": ["Watch runtime freeze before restarting autopilot."],
                "freshness": {"latest_age_seconds": 42, "status": "fresh"},
            },
            runtime_flags={
                "kill_switch": {
                    "flag_name": "kill_switch",
                    "env_enabled": False,
                    "operator_enabled": False,
                    "effective_enabled": False,
                },
                "runtime_freeze": {
                    "flag_name": "runtime_freeze",
                    "env_enabled": False,
                    "operator_enabled": True,
                    "effective_enabled": True,
                },
            },
            recent_runs=[
                {"blocked_reason": "budget_parallel_limit", "status": "blocked", "agent_name": "strategy_agent"},
                {"blocked_reason": "host_resource_guard:low_available_memory", "status": "blocked", "agent_name": "system_lead_agent"},
            ],
            settings=SimpleNamespace(
                agent_global_daily_budget_usd=1.5,
                agent_global_per_run_budget_usd=0.12,
            ),
        )

        self.assertEqual(home["futures"]["cluster_state"], "degraded")
        self.assertTrue(home["futures"]["actions"]["start_cluster"]["enabled"])
        self.assertFalse(home["ai"]["actions"]["start_autopilot"]["enabled"])
        self.assertEqual(
            home["ai"]["actions"]["start_autopilot"]["blocked_reason"],
            "runtime_freeze_enabled",
        )
        self.assertEqual(home["ai"]["blocked_by_budget_total"], 1)
        self.assertEqual(home["ai"]["blocked_by_resource_guard_total"], 1)
        self.assertEqual(home["summary_labels"]["runtime_freeze"], "tak")
        self.assertEqual(home["futures"]["preferred_risk_admitted_strategy_id"], "trend_pullback_continuation_v1")

    def test_build_operator_home_deduplicates_structured_futures_attention(self) -> None:
        home = build_operator_home(
            health={
                "agents_status": "agents_guarded",
                "agents_reason": "manual_mode",
                "docker_available": True,
                "resource_guard": {
                    "allow_new_runs": True,
                    "allow_coding_dispatch": True,
                    "primary_reason": None,
                    "operator_message": "Host resource guard is healthy.",
                    "notes": [],
                },
            },
            futures_bots=[
                {
                    "bot_id": "ft_trend_pullback_continuation_v1",
                    "state": "running",
                    "strategy": "TrendPullbackContinuationV1RuntimeStrategy",
                    "dry_run": True,
                    "description": "trend",
                }
            ],
            futures_health={
                "ready": False,
                "snapshot_age_seconds": 99999,
                "last_smoke_status": "degraded",
                "last_smoke_at": "2026-03-29T12:00:00+00:00",
            },
            futures_snapshot=None,
            risk_decision={},
            strategy_layer_report={},
            autopilot_status={"running": False},
            coding_status={"running": False, "review_tasks": 0},
            agents=[],
            observability_summary={
                "top_blockers": [
                    {
                        "source": "Futures runtime",
                        "title": "Futures runtime jest nieświeży",
                        "severity": "Wysoki",
                        "why_blocking": "Snapshot jest stary.",
                        "area": "futures_canonical",
                    }
                ],
                "recent_errors": [],
                "recent_handoffs": [],
                "operator_attention": ["Futures runtime jest nieświeży"],
                "freshness": {},
            },
            runtime_flags={
                "kill_switch": {
                    "flag_name": "kill_switch",
                    "env_enabled": False,
                    "operator_enabled": False,
                    "effective_enabled": False,
                },
                "runtime_freeze": {
                    "flag_name": "runtime_freeze",
                    "env_enabled": False,
                    "operator_enabled": False,
                    "effective_enabled": False,
                },
            },
            recent_runs=[],
            settings=SimpleNamespace(
                agent_global_daily_budget_usd=1.5,
                agent_global_per_run_budget_usd=0.12,
            ),
        )

        self.assertEqual(len(home["attention_items"]), 1)
        self.assertEqual(home["attention_items"][0]["title"], "futures_runtime_stale")
