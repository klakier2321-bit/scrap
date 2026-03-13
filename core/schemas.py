"""Pydantic schemas for the control API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Allowed request risk levels."""

    low = "low"
    medium = "medium"
    high = "high"


class BotSummary(BaseModel):
    """Short bot summary."""

    bot_id: str
    state: str
    strategy: str | None = None
    dry_run: bool = True
    description: str | None = None


class BotStatus(BotSummary):
    """Detailed bot status."""

    container_name: str | None = None
    logs_tail_default: int = 200


class ActionResult(BaseModel):
    """Generic action response."""

    bot_id: str
    accepted: bool
    message: str


class HealthResponse(BaseModel):
    """Health response for control API."""

    status: str
    agent_mode: str
    mock_llm: bool
    litellm_url: str
    kill_switch: bool
    docker_available: bool


class AgentRunRequest(BaseModel):
    """Request for launching an agent run."""

    agent_name: str
    goal: str
    business_reason: str = ""
    requested_paths: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.low
    cross_layer: bool = False
    does_touch_contract: bool = False
    does_touch_runtime: bool = False
    force_strong_model: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunRecord(BaseModel):
    """Stored agent run state."""

    run_id: str
    task_id: str
    agent_name: str
    goal: str
    business_reason: str = ""
    status: str
    risk_level: str
    model: str | None = None
    model_tier: str | None = None
    review_required: bool = False
    human_decision_required: bool = False
    approval_required: bool = False
    approval_granted: bool = False
    stop_requested: bool = False
    cross_layer: bool = False
    does_touch_contract: bool = False
    does_touch_runtime: bool = False
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    successful_requests: int = 0
    retry_like_requests: int = 0
    warnings_json: list[str] | None = None
    blocked_reason: str | None = None
    max_iterations: int = 0
    max_retry_limit: int = 0
    created_at: datetime | str
    started_at: datetime | str | None = None
    finished_at: datetime | str | None = None
    duration_seconds: float = 0.0
    payload_json: dict[str, Any]
    result_json: dict[str, Any] | None = None
    review_json: dict[str, Any] | None = None
    error: str | None = None


class AgentInfo(BaseModel):
    """Agent metadata shown in the operator panel."""

    name: str
    role: str
    model_tier: str
    default_daily_budget_usd: float
    default_per_run_budget_usd: float
    owned_scope: list[str]
    read_only_scope: list[str]
    forbidden_scope: list[str]


class StrategyReportResponse(BaseModel):
    """Normalized strategy report generated from the latest backtest."""

    strategy_name: str
    timeframe: str
    backtest_start: str
    backtest_end: str
    profit_pct: float
    absolute_profit: float
    drawdown_pct: float
    drawdown_abs: float
    total_trades: int
    win_rate: float
    stability_score: float | None = None
    stage_candidate: bool = False
    evaluation_status: str
    rejection_reasons: list[str] = Field(default_factory=list)
    periodic_breakdown_basis: str | None = None
    source_run_id: str | None = None
    source_archive: str | None = None
    assessment_summary: str | None = None
    assessment_recommendation: str | None = None
    assessment_risk_level: str | None = None
    assessment_generated_at: datetime | str | None = None
    generated_at: datetime | str
