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
    readiness_status: str | None = None
    readiness_decision: str | None = None
    readiness_summary: str | None = None
    readiness_gate: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime | str


class CandidateAssessmentResponse(BaseModel):
    """Candidate-native assessment used by the strategy factory."""

    candidate_id: str
    strategy_name: str | None = None
    market_type: str | None = None
    lifecycle_status: str
    active_side_policy: str
    allowed_sides: str | list[str] | None = None
    candidate_bot_id: str | None = None
    broad_backtest_status: str
    risk_gate_status: str
    dry_run_gate_status: str
    overall_decision: str
    next_step: str
    blocked_reasons: list[str] = Field(default_factory=list)
    selector_status: str | None = None
    selector_rank: int | None = None
    runtime_policy: dict[str, Any] = Field(default_factory=dict)
    manifest_path: str | None = None
    broad_backtest_summary_path: str | None = None
    risk_report_path: str | None = None
    promotion_decision_path: str | None = None


class CandidateDryRunResponse(BaseModel):
    """Dry-run context dedicated to one shipping candidate."""

    candidate_id: str
    bot_id: str
    health: dict[str, Any] = Field(default_factory=dict)
    latest_snapshot: dict[str, Any] | None = None
    latest_smoke: dict[str, Any] | None = None


class RegimeStatusResponse(BaseModel):
    """Current market regime classification for operator and executive views."""

    generated_at: datetime | str
    asof_timeframe: str
    universe: list[str] = Field(default_factory=list)
    primary_regime: str
    confidence: float
    risk_level: str
    trend_strength: float
    volatility_level: str
    volume_state: str
    derivatives_state: dict[str, Any] = Field(default_factory=dict)
    feature_snapshot: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    eligible_candidate_ids: list[str] = Field(default_factory=list)
    blocked_candidate_ids: list[str] = Field(default_factory=list)
    candidate_freeze_mode: str | None = None
    htf_bias: str | None = None
    market_state: str | None = None
    ltf_execution_state: str | None = None
    bias: str | None = None
    alignment_score: float | None = None
    market_phase: str | None = None
    volatility_phase: str | None = None
    active_event_flags: dict[str, bool] = Field(default_factory=dict)
    signals: dict[str, bool] = Field(default_factory=dict)
    regime_persistence: dict[str, Any] = Field(default_factory=dict)
    position_size_multiplier: float | None = None
    entry_aggressiveness: str | None = None
    strategy_priority_order: list[str] = Field(default_factory=list)
    execution_constraints: dict[str, bool] = Field(default_factory=dict)
    btc_state: dict[str, Any] | None = None
    eth_state: dict[str, Any] | None = None
    market_consensus: str | None = None
    consensus_strength: float | None = None
    risk_regime: str | None = None
    regime_quality: float | None = None
    lead_symbol: str | None = None
    lag_confirmation: str | None = None
    outcome_tracking_status: str | None = None


class DerivativesStatusResponse(BaseModel):
    """Canonical derivatives feed status for regime detection."""

    generated_at: datetime | str
    source: str
    feed_status: str
    vendor_available: bool = False
    universe: list[str] = Field(default_factory=list)
    symbols: list[dict[str, Any]] = Field(default_factory=list)


class RegimeReplayResponse(BaseModel):
    """Replay and calibration summary for regime detector."""

    generated_at: datetime | str
    asof_timeframe: str
    bar_count: int
    replay_status: str
    warmup_bars: int
    regime_switches_total: int
    avg_minutes_in_regime: float
    no_trade_zone_share: float
    compression_to_expansion_count: int
    bias_followthrough_15m_pct: float | None = None
    bias_followthrough_1h_pct: float | None = None
    market_consensus_breakdown: dict[str, Any] = Field(default_factory=dict)
    regime_coverage: dict[str, Any] = Field(default_factory=dict)
    event_counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class DryRunHealthResponse(BaseModel):
    """Read-only health view of the active dry-run runtime."""

    bot_id: str
    bot_state: str
    dry_run: bool = False
    runtime_mode: str
    bridge_status: str
    api_authenticated: bool = False
    ready: bool = False
    blocking_reason: str | None = None
    snapshot_available: bool = False
    snapshot_age_seconds: float | None = None
    last_snapshot_at: datetime | str | None = None
    last_smoke_status: str | None = None
    last_smoke_at: datetime | str | None = None
    warnings: list[str] = Field(default_factory=list)


class DryRunSnapshotResponse(BaseModel):
    """Normalized runtime snapshot generated from active dry-run state."""

    bot_id: str
    generated_at: datetime | str
    source: str
    bridge_status: str
    dry_run: bool = False
    runmode: str
    strategy: str | None = None
    config_summary: dict[str, Any] = Field(default_factory=dict)
    balance_summary: dict[str, Any] = Field(default_factory=dict)
    profit_summary: dict[str, Any] = Field(default_factory=dict)
    performance_summary: dict[str, Any] = Field(default_factory=dict)
    trade_count_summary: dict[str, Any] = Field(default_factory=dict)
    open_trades_count: int = 0
    open_trades: list[dict[str, Any]] = Field(default_factory=list)
    runtime_warnings: list[str] = Field(default_factory=list)
    ping_status: str = "unknown"
    snapshot_status: str = "unknown"
    snapshot_stale_after_seconds: int = 0


class DryRunSmokeResponse(BaseModel):
    """Result of the dry-run smoke test."""

    bot_id: str
    generated_at: datetime | str
    status: str
    dry_run: bool = False
    runtime_mode: str
    blocking_reason: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    snapshot_path: str | None = None


class ControlStatusSourceResponse(BaseModel):
    """Per-source view inside the sanitized control status report."""

    source_name: str
    file_count: int
    latest_file_name: str | None = None
    latest_generated_at: datetime | str | None = None
    latest_status: str | None = None
    issues: list[str] = Field(default_factory=list)
    latest_record: dict[str, Any] | None = None


class ControlStatusResponse(BaseModel):
    """Sanitized control status exposed to operators and executive reporting."""

    generated_at: datetime | str
    overall_status: str
    summary: str
    sources: list[ControlStatusSourceResponse] = Field(default_factory=list)


class AutopilotStatusResponse(BaseModel):
    """Status of the continuous planning autopilot."""

    running: bool
    objective: str
    poll_interval_seconds: int
    max_cycles: int
    cycle_count: int
    current_task_name: str | None = None
    current_run_id: str | None = None
    last_run_id: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_started_at: datetime | str | None = None
    task_names: list[str] = Field(default_factory=list)
    next_task_name: str | None = None
    config_path: str


class CodingTaskCreateRequest(BaseModel):
    """Manual creation of one coding task for a selected module."""

    module_id: str
    goal_override: str | None = None
    business_reason: str | None = None
    target_files_override: list[str] = Field(default_factory=list)


class CodingTaskRecord(BaseModel):
    """Stored coding task managed by the supervised write runtime."""

    task_id: str
    module_id: str
    owner_agent: str
    goal: str
    business_reason: str
    owned_scope: list[str] = Field(default_factory=list)
    read_only_context: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    risk_level: str
    acceptance_checks: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)
    definition_of_done: list[str] = Field(default_factory=list)
    created_by_run_id: str
    status: str
    attempt_count: int = 0
    review_attempt_count: int = 0
    worktree_path: str | None = None
    branch_name: str | None = None
    base_ref: str | None = None
    base_commit: str | None = None
    diff_summary: str | None = None
    check_results: dict[str, Any] = Field(default_factory=dict)
    review_json: dict[str, Any] = Field(default_factory=dict)
    commit_sha: str | None = None
    planning_cost_usd: float = 0.0
    coding_cost_usd: float = 0.0
    review_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    last_error: str | None = None
    created_at: datetime | str
    started_at: datetime | str | None = None
    finished_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class CodingWorkspaceRecord(BaseModel):
    """Isolated git worktree assigned to one coding task."""

    task_id: str
    agent_name: str
    worktree_path: str
    branch_name: str
    base_ref: str
    base_commit: str
    changed_files: list[str] = Field(default_factory=list)
    diff_text: str = ""
    check_results: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime | str
    updated_at: datetime | str


class CodingStatusResponse(BaseModel):
    """High-level status of the supervised coding runtime."""

    running: bool
    enabled: bool
    lead_refresh_interval_seconds: int
    dispatcher_poll_interval_seconds: int
    max_active_tasks: int
    last_queue_refresh_at: datetime | str | None = None
    last_dispatch_at: datetime | str | None = None
    last_error: str | None = None
    attention_needed: bool = False
    task_timeout_seconds: int | None = None
    active_task_id: str | None = None
    active_task_age_seconds: float | None = None
    active_worker_alive: bool = False
    ready_tasks: int = 0
    review_tasks: int = 0
    committed_tasks: int = 0
    modules: list[dict[str, Any]] = Field(default_factory=list)


class CodingReviewDecisionRequest(BaseModel):
    """Optional reason used when rejecting a reviewed coding task."""

    reason: str = "Manual review rejection."
