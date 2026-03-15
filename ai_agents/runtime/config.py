"""Configuration loading for the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "ai_agents" / "config"
PROMPTS_DIR = ROOT_DIR / "ai_agents" / "prompts"
RULES_DIR = ROOT_DIR / "ai_agents" / "rules"


@dataclass(frozen=True)
class AgentProfile:
    """Runtime configuration for one agent."""

    name: str
    role: str
    goal: str
    backstory: str
    prompt_file: Path
    model_tier: str
    max_iter: int
    max_retry_limit: int


@dataclass(frozen=True)
class ModelProfile:
    """Model routing and rough cost data."""

    tier: str
    model: str
    estimated_input_cost_per_1k_usd: float
    estimated_output_cost_per_1k_usd: float
    max_output_tokens: int


@dataclass(frozen=True)
class BudgetProfile:
    """Budget limits for one agent."""

    daily_usd: float
    per_run_usd: float
    max_iterations: int
    max_retry_limit: int
    require_approval_for_strong_model: bool


@dataclass(frozen=True)
class CodingModuleProfile:
    """Konfiguracja jednego modułu obsługiwanego przez coding agents."""

    module_id: str
    owner_agent: str
    enabled: bool
    priority: int
    title: str
    module_summary: str
    read_only_context: list[str]
    target_candidates: list[str]
    acceptance_checks: list[str]
    required_tests: list[str]
    definition_of_done: list[str]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        matches = re.findall(r"\$\{([A-Z0-9_]+)\}", value)
        for match in matches:
            value = value.replace(f"${{{match}}}", os.getenv(match, ""))
        return value
    if isinstance(value, dict):
        return {key: _expand_env(raw_value) for key, raw_value in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def load_agent_profiles() -> dict[str, AgentProfile]:
    raw = _load_yaml(CONFIG_DIR / "agents.yaml").get("agents", {})
    profiles: dict[str, AgentProfile] = {}
    for name, config in raw.items():
        profiles[name] = AgentProfile(
            name=name,
            role=config["role"],
            goal=config["goal"],
            backstory=config["backstory"],
            prompt_file=PROMPTS_DIR / config["prompt_file"],
            model_tier=config["model_tier"],
            max_iter=int(config["max_iter"]),
            max_retry_limit=int(config["max_retry_limit"]),
        )
    return profiles


def load_model_profiles() -> dict[str, ModelProfile]:
    raw = _expand_env(_load_yaml(CONFIG_DIR / "models.yaml")).get("models", {})
    models: dict[str, ModelProfile] = {}
    for tier, config in raw.items():
        models[tier] = ModelProfile(
            tier=tier,
            model=config["model"],
            estimated_input_cost_per_1k_usd=float(
                config["estimated_input_cost_per_1k_usd"]
            ),
            estimated_output_cost_per_1k_usd=float(
                config["estimated_output_cost_per_1k_usd"]
            ),
            max_output_tokens=int(config["max_output_tokens"]),
        )
    return models


def load_budget_profiles() -> tuple[dict[str, Any], dict[str, BudgetProfile]]:
    raw = _load_yaml(CONFIG_DIR / "budgets.yaml")
    global_budget = raw.get("global", {})
    profiles: dict[str, BudgetProfile] = {}
    for name, config in raw.get("agents", {}).items():
        profiles[name] = BudgetProfile(
            daily_usd=float(config["daily_usd"]),
            per_run_usd=float(config["per_run_usd"]),
            max_iterations=int(config["max_iterations"]),
            max_retry_limit=int(config["max_retry_limit"]),
            require_approval_for_strong_model=bool(
                config["require_approval_for_strong_model"]
            ),
        )
    return global_budget, profiles


def load_scope_manifest() -> dict[str, Any]:
    return _load_yaml(RULES_DIR / "AGENT_SCOPE_MANIFEST.yaml")


def load_coding_runtime_config(path: Path) -> tuple[dict[str, Any], list[CodingModuleProfile]]:
    raw = _load_yaml(path).get("coding_runtime", {})
    profiles: list[CodingModuleProfile] = []
    for item in raw.get("modules", []):
        profiles.append(
            CodingModuleProfile(
                module_id=item["module_id"],
                owner_agent=item["owner_agent"],
                enabled=bool(item.get("enabled", True)),
                priority=int(item.get("priority", 100)),
                title=item["title"],
                module_summary=item["module_summary"],
                read_only_context=list(item.get("read_only_context", [])),
                target_candidates=list(item.get("target_candidates", [])),
                acceptance_checks=list(item.get("acceptance_checks", [])),
                required_tests=list(item.get("required_tests", [])),
                definition_of_done=list(item.get("definition_of_done", [])),
            )
        )
    return raw, sorted(profiles, key=lambda profile: profile.priority, reverse=True)


def load_prompt(prompt_file: Path) -> str:
    return prompt_file.read_text(encoding="utf-8").strip()
