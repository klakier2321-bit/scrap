from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_agents.runtime.config import (
    load_agent_profiles,
    load_budget_profiles,
    load_model_profiles,
    load_scope_manifest,
)
from ai_agents.runtime.policy import evaluate_request
from ai_agents.runtime.service import AgentRuntimeService


class AgentRuntimePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent_profiles = load_agent_profiles()
        _global_budget, self.budget_profiles = load_budget_profiles()
        self.model_profiles = load_model_profiles()
        self.scope_manifest = load_scope_manifest()

    def test_catalog_contains_ops_observability_and_strategy_stewards(self) -> None:
        self.assertIn("ops_observability_agent", self.agent_profiles)
        self.assertIn("trend_pullback_steward", self.agent_profiles)
        self.assertEqual(
            self.agent_profiles["trend_pullback_steward"].activation_mode,
            "disabled_by_default",
        )
        self.assertEqual(
            self.agent_profiles["ops_observability_agent"].activation_mode,
            "always_on_guarded",
        )

    def test_disabled_steward_is_blocked_without_explicit_enable(self) -> None:
        decision = evaluate_request(
            request_payload={
                "agent_name": "trend_pullback_steward",
                "goal": "Analyze steward telemetry.",
                "business_reason": "Check replay.",
                "requested_paths": [
                    "research/strategies/manifests/trend_pullback_continuation_v1.yaml"
                ],
                "risk_level": "low",
                "cross_layer": False,
                "does_touch_contract": False,
                "does_touch_runtime": False,
                "force_strong_model": False,
                "metadata": {},
            },
            agent_profile=self.agent_profiles["trend_pullback_steward"],
            budget_profile=self.budget_profiles["trend_pullback_steward"],
            models=self.model_profiles,
            scope_manifest=self.scope_manifest,
            current_agent_spend=0.0,
            current_total_spend=0.0,
            global_daily_budget_usd=10.0,
            global_per_run_budget_usd=1.0,
            risk_overrides={"warnings": [], "review_required": False, "human_decision_required": False},
            sensitive_path_violations=[],
            current_agent_active_runs=0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocked_reason, "agent_disabled_by_default")

    def test_manual_only_agent_is_blocked_from_autopilot(self) -> None:
        decision = evaluate_request(
            request_payload={
                "agent_name": "architecture_agent",
                "goal": "Review a cross-layer contract change.",
                "business_reason": "Safety gate.",
                "requested_paths": ["docs/ARCHITECTURE.md"],
                "risk_level": "medium",
                "cross_layer": True,
                "does_touch_contract": True,
                "does_touch_runtime": False,
                "force_strong_model": False,
                "metadata": {"autopilot": True},
            },
            agent_profile=self.agent_profiles["architecture_agent"],
            budget_profile=self.budget_profiles["architecture_agent"],
            models=self.model_profiles,
            scope_manifest=self.scope_manifest,
            current_agent_spend=0.0,
            current_total_spend=0.0,
            global_daily_budget_usd=10.0,
            global_per_run_budget_usd=1.0,
            risk_overrides={"warnings": [], "review_required": True, "human_decision_required": False},
            sensitive_path_violations=[],
            current_agent_active_runs=0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocked_reason, "autopilot_agent_not_allowed")

    def test_runtime_touch_is_blocked_for_non_runtime_agent(self) -> None:
        decision = evaluate_request(
            request_payload={
                "agent_name": "strategy_agent",
                "goal": "Touch runtime settings.",
                "business_reason": "Should be blocked.",
                "requested_paths": ["research/strategies/"],
                "risk_level": "low",
                "cross_layer": False,
                "does_touch_contract": False,
                "does_touch_runtime": True,
                "force_strong_model": False,
                "metadata": {},
            },
            agent_profile=self.agent_profiles["strategy_agent"],
            budget_profile=self.budget_profiles["strategy_agent"],
            models=self.model_profiles,
            scope_manifest=self.scope_manifest,
            current_agent_spend=0.0,
            current_total_spend=0.0,
            global_daily_budget_usd=10.0,
            global_per_run_budget_usd=1.0,
            risk_overrides={"warnings": [], "review_required": False, "human_decision_required": False},
            sensitive_path_violations=[],
            current_agent_active_runs=0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocked_reason, "runtime_touch_not_allowed")

    def test_parallel_limit_blocks_extra_agent_run(self) -> None:
        decision = evaluate_request(
            request_payload={
                "agent_name": "system_lead_agent",
                "goal": "Prepare next safe plan.",
                "business_reason": "Coordination.",
                "requested_paths": ["docs/"],
                "risk_level": "low",
                "cross_layer": False,
                "does_touch_contract": False,
                "does_touch_runtime": False,
                "force_strong_model": False,
                "metadata": {},
            },
            agent_profile=self.agent_profiles["system_lead_agent"],
            budget_profile=self.budget_profiles["system_lead_agent"],
            models=self.model_profiles,
            scope_manifest=self.scope_manifest,
            current_agent_spend=0.0,
            current_total_spend=0.0,
            global_daily_budget_usd=10.0,
            global_per_run_budget_usd=1.0,
            risk_overrides={"warnings": [], "review_required": False, "human_decision_required": False},
            sensitive_path_violations=[],
            current_agent_active_runs=1,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.blocked_reason, "agent_parallel_limit")

    def test_list_agents_exposes_tree_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SimpleNamespace(
                agent_context_packets_dir=Path(tmpdir),
                agent_use_mock_llm=True,
                agent_allow_mock_fallback=True,
                agent_litellm_base_url="http://localhost:4000/v1",
                agent_litellm_api_key="disabled",
            )
            service = AgentRuntimeService(settings=settings)
            agents = {item["name"]: item for item in service.list_agents()}
        self.assertIn("ops_observability_agent", agents)
        self.assertIn("trend_pullback_steward", agents)
        self.assertIn("ops_observability_agent", agents["system_lead_agent"]["child_agents"])
        self.assertEqual(
            agents["trend_pullback_steward"]["parent_agent"],
            "strategy_agent",
        )

    def test_operator_override_can_enable_disabled_steward(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SimpleNamespace(
                agent_context_packets_dir=Path(tmpdir) / "packets",
                agent_runtime_overrides_path=Path(tmpdir) / "agent_runtime_overrides.json",
                agent_use_mock_llm=True,
                agent_allow_mock_fallback=True,
                agent_litellm_base_url="http://localhost:4000/v1",
                agent_litellm_api_key="disabled",
                agent_global_daily_budget_usd=10.0,
                agent_global_per_run_budget_usd=1.0,
            )
            service = AgentRuntimeService(settings=settings)
            service.update_agent_override(
                agent_name="trend_pullback_steward",
                enabled=True,
                daily_budget_usd=0.03,
                per_run_budget_usd=0.01,
            )
            agents = {item["name"]: item for item in service.list_agents()}
            self.assertTrue(agents["trend_pullback_steward"]["effective_enabled"])
            self.assertEqual(agents["trend_pullback_steward"]["operational_state"], "manual_enabled")
            self.assertEqual(agents["trend_pullback_steward"]["effective_daily_budget_usd"], 0.03)
            decision = service.prepare_run(
                request_payload={
                    "agent_name": "trend_pullback_steward",
                    "goal": "Analyze strategy telemetry.",
                    "business_reason": "Steward replay review.",
                    "requested_paths": [
                        "research/strategies/manifests/trend_pullback_continuation_v1.yaml"
                    ],
                    "risk_level": "low",
                    "cross_layer": False,
                    "does_touch_contract": False,
                    "does_touch_runtime": False,
                    "force_strong_model": False,
                    "metadata": {},
                },
                current_agent_spend=0.0,
                current_total_spend=0.0,
                risk_overrides={"warnings": [], "review_required": False, "human_decision_required": False},
                sensitive_path_violations=[],
                current_agent_active_runs=0,
            )
            self.assertTrue(decision["allowed"])

    def test_operator_override_can_disable_active_core_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SimpleNamespace(
                agent_context_packets_dir=Path(tmpdir) / "packets",
                agent_runtime_overrides_path=Path(tmpdir) / "agent_runtime_overrides.json",
                agent_use_mock_llm=True,
                agent_allow_mock_fallback=True,
                agent_litellm_base_url="http://localhost:4000/v1",
                agent_litellm_api_key="disabled",
                agent_global_daily_budget_usd=10.0,
                agent_global_per_run_budget_usd=1.0,
            )
            service = AgentRuntimeService(settings=settings)
            service.update_agent_override(agent_name="strategy_agent", enabled=False)
            decision = service.prepare_run(
                request_payload={
                    "agent_name": "strategy_agent",
                    "goal": "Coordinate strategy review.",
                    "business_reason": "Test operator shutdown.",
                    "requested_paths": ["research/strategies/"],
                    "risk_level": "low",
                    "cross_layer": False,
                    "does_touch_contract": False,
                    "does_touch_runtime": False,
                    "force_strong_model": False,
                    "metadata": {},
                },
                current_agent_spend=0.0,
                current_total_spend=0.0,
                risk_overrides={"warnings": [], "review_required": False, "human_decision_required": False},
                sensitive_path_violations=[],
                current_agent_active_runs=0,
            )
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["blocked_reason"], "agent_disabled_by_operator")

    def test_resource_guard_blocks_new_runs_before_policy_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SimpleNamespace(
                agent_context_packets_dir=Path(tmpdir) / "packets",
                agent_runtime_overrides_path=Path(tmpdir) / "agent_runtime_overrides.json",
                agent_use_mock_llm=True,
                agent_allow_mock_fallback=True,
                agent_litellm_base_url="http://localhost:4000/v1",
                agent_litellm_api_key="disabled",
                agent_global_daily_budget_usd=10.0,
                agent_global_per_run_budget_usd=1.0,
            )
            service = AgentRuntimeService(
                settings=settings,
                resource_guard_provider=lambda: {
                    "enabled": True,
                    "allow_new_runs": False,
                    "allow_coding_dispatch": False,
                    "primary_reason": "low_available_memory",
                    "blocked_reasons": ["low_available_memory"],
                    "operator_message": "Available memory is low and new agent runs are paused for safety.",
                    "notes": ["Available memory dropped below the configured threshold."],
                    "resources": {},
                },
            )
            decision = service.prepare_run(
                request_payload={
                    "agent_name": "system_lead_agent",
                    "goal": "Coordinate next safe implementation step.",
                    "business_reason": "Protect host capacity.",
                    "requested_paths": ["docs/"],
                    "risk_level": "low",
                    "cross_layer": False,
                    "does_touch_contract": False,
                    "does_touch_runtime": False,
                    "force_strong_model": False,
                    "metadata": {},
                },
                current_agent_spend=0.0,
                current_total_spend=0.0,
                risk_overrides={"warnings": [], "review_required": False, "human_decision_required": False},
                sensitive_path_violations=[],
                current_agent_active_runs=0,
            )
            self.assertFalse(decision["allowed"])
            self.assertEqual(
                decision["blocked_reason"],
                "host_resource_guard:low_available_memory",
            )
            self.assertIn("paused for safety", " ".join(decision["warnings"]).lower())


if __name__ == "__main__":
    unittest.main()
