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
