"""Structured runtime schemas for agent execution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlanOutput(BaseModel):
    """Structured plan produced by planning agents."""

    summary: str
    recommended_actions: list[str] = Field(default_factory=list)
    affected_paths: list[str] = Field(default_factory=list)
    review_required: bool = False
    human_decision_required: bool = False
    warnings: list[str] = Field(default_factory=list)


class ReviewOutput(BaseModel):
    """Structured review result produced by review_agent."""

    decision: Literal["approve", "revise", "human_review_required"]
    risk_level: Literal["low", "medium", "high"] = "low"
    main_findings: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)


class StrategyAssessmentOutput(BaseModel):
    """Structured assessment produced by strategy_agent from backtest evidence."""

    summary: str
    recommendation: Literal[
        "reject",
        "needs_manual_review",
        "promote_after_human_review",
    ]
    risk_level: Literal["low", "medium", "high"] = "medium"
    rationale: list[str] = Field(default_factory=list)
    stage_candidate: bool = False


class StepUsage(BaseModel):
    """Usage metrics for a single runtime step."""

    agent_name: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    successful_requests: int = 0
    estimated_cost_usd: float = 0.0


class CodingTaskPacketOutput(BaseModel):
    """Task packet tworzony przez lead agenta dla coding flow."""

    summary: str
    module_id: str
    owner_agent: str
    goal: str
    business_reason: str
    owned_scope: list[str] = Field(default_factory=list)
    read_only_context: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium"] = "low"
    acceptance_checks: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)
    definition_of_done: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    review_required: bool = True
    human_decision_required: bool = False


class FileEditOutput(BaseModel):
    """Jeden zapis pliku proponowany przez coding agenta."""

    path: str
    content: str
    is_new_file: bool = False
    rationale: str = ""


class CodingChangeOutput(BaseModel):
    """Strukturalny output kodującego agenta."""

    summary: str
    file_edits: list[FileEditOutput] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
