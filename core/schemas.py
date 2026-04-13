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


class OperatorActionResponse(BaseModel):
    """High-level operator action response."""

    accepted: bool
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Health response for control API."""

    status: str
    agent_mode: str
    mock_llm: bool
    litellm_url: str
    kill_switch: bool
    runtime_freeze: bool
    docker_available: bool
    agents_status: str
    agents_reason: str | None = None
    resource_guard: dict[str, Any] = Field(default_factory=dict)


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


class ChatThreadCreateRequest(BaseModel):
    """Create one manual chat thread for a specific agent."""

    agent_name: str
    title: str | None = None


class ChatMessageCreateRequest(BaseModel):
    """Append one user message to a chat thread."""

    content: str = Field(min_length=1, max_length=4000)


class ChatMessageResponse(BaseModel):
    """One stored chat message."""

    message_id: str
    thread_id: str
    role: str
    content: str
    run_id: str | None = None
    created_at: datetime | str
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ChatThreadSummaryResponse(BaseModel):
    """Compact chat thread summary for operator UI."""

    thread_id: str
    agent_name: str
    title: str
    created_at: datetime | str
    updated_at: datetime | str
    last_message_at: datetime | str | None = None
    last_run_id: str | None = None
    last_message_preview: str | None = None
    message_count: int = 0
    active_run_id: str | None = None
    active_run_status: str | None = None


class ChatThreadDetailResponse(ChatThreadSummaryResponse):
    """Full thread payload with message history."""

    messages: list[ChatMessageResponse] = Field(default_factory=list)


class AgentInfo(BaseModel):
    """Agent metadata shown in the operator panel."""

    name: str
    role: str
    parent_agent: str | None = None
    child_agents: list[str] = Field(default_factory=list)
    activation_mode: str = "manual_only"
    operational_state: str = "unknown"
    enabled_override: bool | None = None
    effective_enabled: bool = False
    domain: str = "platform"
    model_tier: str
    cost_tier: str = "cheap"
    default_daily_budget_usd: float
    default_per_run_budget_usd: float
    effective_daily_budget_usd: float | None = None
    effective_per_run_budget_usd: float | None = None
    max_parallel_runs: int = 1
    grafana_visibility: bool = True
    requires_review_for_activation: bool = False
    can_dispatch_subtasks: bool = False
    can_touch_runtime: bool = False
    handoff_targets: list[str] = Field(default_factory=list)
    writes_to: list[str] = Field(default_factory=list)
    reads_from: list[str] = Field(default_factory=list)
    strategy_scope: str | None = None
    owned_scope: list[str]
    read_only_scope: list[str]
    forbidden_scope: list[str]


class AgentRuntimeOverrideResponse(BaseModel):
    """Operator-managed runtime override for one agent."""

    enabled: bool | None = None
    daily_budget_usd: float | None = None
    per_run_budget_usd: float | None = None


class AgentRuntimeOverrideUpdateRequest(BaseModel):
    """Patch payload for one agent runtime override."""

    enabled: bool | None = None
    daily_budget_usd: float | None = Field(default=None, ge=0.0)
    per_run_budget_usd: float | None = Field(default=None, ge=0.0)


class ObservabilityGraphNode(BaseModel):
    """One node in the operator-facing control tower graph."""

    node_id: str
    label: str
    node_type: str
    lane: str
    operational_state: str
    owner: str | None = None
    summary: str | None = None
    target_url: str | None = None


class ObservabilityGraphEdge(BaseModel):
    """One edge in the operator-facing control tower graph."""

    edge_id: str
    source: str
    target: str
    edge_type: str
    status: str
    summary: str | None = None


class ObservabilityCurrentWorkItem(BaseModel):
    """Compact current-work item for Grafana and operator views."""

    item_id: str
    owner_name: str
    owner_type: str
    workstream: str
    status: str
    title: str
    next_step: str | None = None
    scope: str | None = None


class OperatorActionState(BaseModel):
    """Whether one high-level operator action is currently allowed."""

    enabled: bool
    blocked_reason: str | None = None


class OperatorAttentionItem(BaseModel):
    """Compact attention item for the simplified operator home."""

    kind: str
    severity: str
    title: str
    summary: str
    owner: str | None = None


class ObservabilitySummaryResponse(BaseModel):
    """Single operator snapshot behind the unified Grafana home dashboard."""

    generated_at: datetime | str
    state_hash: str
    graph_nodes: list[ObservabilityGraphNode] = Field(default_factory=list)
    graph_edges: list[ObservabilityGraphEdge] = Field(default_factory=list)
    current_work: list[ObservabilityCurrentWorkItem] = Field(default_factory=list)
    recent_handoffs: list[dict[str, Any]] = Field(default_factory=list)
    recent_errors: list[dict[str, Any]] = Field(default_factory=list)
    top_blockers: list[dict[str, Any]] = Field(default_factory=list)
    goals_and_direction: dict[str, Any] = Field(default_factory=dict)
    operator_attention: list[str] = Field(default_factory=list)
    futures_runtime: dict[str, Any] = Field(default_factory=dict)
    runtime_focus: list[dict[str, Any]] = Field(default_factory=list)
    cost_control: dict[str, Any] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)


class RuntimeFlagUpdateRequest(BaseModel):
    """Toggle one persistent operator runtime flag."""

    enabled: bool


class RuntimeFlagStateResponse(BaseModel):
    """Effective state of one runtime flag."""

    flag_name: str
    env_enabled: bool = False
    operator_enabled: bool = False
    effective_enabled: bool = False


class OperatorHomeFutures(BaseModel):
    """Home-card snapshot for the futures runtime cluster."""

    cluster_id: str
    cluster_state: str
    bots: list[BotSummary] = Field(default_factory=list)
    ready: bool = False
    runtime_operational: bool = False
    data_fresh: bool = False
    snapshot_age_seconds: float | None = None
    last_smoke_status: str | None = None
    last_smoke_at: datetime | str | None = None
    last_smoke_age_seconds: float | None = None
    risk_mode: str | None = None
    allow_trading: bool | None = None
    risk_reason_codes: list[str] = Field(default_factory=list)
    force_reduce_only: bool | None = None
    cooldown_active: bool | None = None
    preferred_risk_admitted_strategy_id: str | None = None
    top_blockers: list[str] = Field(default_factory=list)
    snapshot_open_trades: int | None = None
    actions: dict[str, OperatorActionState] = Field(default_factory=dict)


class OperatorHomeAi(BaseModel):
    """Home-card snapshot for the AI runtime."""

    agents_status: str
    agents_reason: str | None = None
    autopilot_running: bool = False
    coding_supervisor_running: bool = False
    resource_guard: dict[str, Any] = Field(default_factory=dict)
    global_daily_budget_usd: float = 0.0
    global_per_run_budget_usd: float = 0.0
    blocked_by_budget_total: int = 0
    blocked_by_resource_guard_total: int = 0
    agent_tree_summary: dict[str, Any] = Field(default_factory=dict)
    runtime_flags: dict[str, RuntimeFlagStateResponse] = Field(default_factory=dict)
    actions: dict[str, OperatorActionState] = Field(default_factory=dict)


class OperatorHomeResponse(BaseModel):
    """Single lightweight snapshot for the simplified operator home."""

    generated_at: datetime | str
    status: str
    freshness: dict[str, Any] = Field(default_factory=dict)
    futures: OperatorHomeFutures
    ai: OperatorHomeAi
    attention_items: list[OperatorAttentionItem] = Field(default_factory=list)
    recent_errors: list[dict[str, Any]] = Field(default_factory=list)
    recent_actions: list[dict[str, Any]] = Field(default_factory=list)
    goals_and_direction: dict[str, Any] = Field(default_factory=dict)
    operator_attention: list[str] = Field(default_factory=list)
    observability_owner: str | None = None
    summary_labels: dict[str, str] = Field(default_factory=dict)


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


class StrategyManifestResponse(BaseModel):
    """Canonical manifest entry for one regime-aware strategy."""

    strategy_id: str
    display_name: str
    version: str
    strategy_family: str
    risk_profile: str
    execution_style: str
    archetype: str
    status: str
    supported_regimes: list[str] = Field(default_factory=list)
    supported_market_states: list[str] = Field(default_factory=list)
    supported_market_phases: list[str] = Field(default_factory=list)
    supported_volatility_phases: list[str] = Field(default_factory=list)
    supported_biases: list[str] = Field(default_factory=list)
    supported_event_contexts: list[str] = Field(default_factory=list)
    minimum_data_trust: str = "low_trust"
    disallowed_conditions: list[str] = Field(default_factory=list)
    required_data_inputs: list[str] = Field(default_factory=list)
    optional_data_inputs: list[str] = Field(default_factory=list)
    signal_contract: dict[str, Any] = Field(default_factory=dict)
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    entry_semantics: dict[str, Any] = Field(default_factory=dict)
    exit_semantics: dict[str, Any] = Field(default_factory=dict)
    telemetry_requirements: list[str] = Field(default_factory=list)
    backtest_priority: str = "medium"
    steward_agent_role: str | None = None
    owner_team: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    implementation_status: str = "planned"
    manifest_path: str | None = None


class StrategyLayerResponse(BaseModel):
    """Canonical runtime view of the regime-aware strategy layer."""

    generated_at: datetime | str
    bot_id: str
    status: str
    primary_regime: str | None = None
    market_state: str | None = None
    market_phase: str | None = None
    volatility_phase: str | None = None
    trading_mode: str | None = None
    data_trust_level: str | None = None
    allowed_directions: list[str] = Field(default_factory=list)
    manifests_total: int = 0
    implemented_strategies_total: int = 0
    applicable_strategy_ids: list[str] = Field(default_factory=list)
    blocked_strategy_ids: list[str] = Field(default_factory=list)
    risk_admitted_strategy_ids: list[str] = Field(default_factory=list)
    blocked_by_risk_strategy_ids: list[str] = Field(default_factory=list)
    advisory_strategy_ids: list[str] = Field(default_factory=list)
    strategy_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    built_signals: list[dict[str, Any]] = Field(default_factory=list)
    preferred_strategy_id: str | None = None
    preferred_risk_admitted_strategy_id: str | None = None
    ranking: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None


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
    risk_decision: dict[str, Any] = Field(default_factory=dict)
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
    eligible_strategy_ids: list[str] = Field(default_factory=list)
    blocked_strategy_ids: list[str] = Field(default_factory=list)
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
    actionable_event_flags: dict[str, bool] = Field(default_factory=dict)
    active_event_flags_reliability: str | None = None
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
    fetched_at: datetime | str | None = None
    source_timestamp: datetime | str | None = None
    age_seconds: float | None = None
    is_stale: bool = False
    source: str
    feed_status: str
    vendor_available: bool = False
    vendor_name: str | None = None
    fetch_errors: list[str] = Field(default_factory=list)
    event_reliability: str | None = None
    liquidation_source_type: str | None = None
    liquidation_event_confidence: str | None = None
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
    derivatives_source_breakdown: dict[str, int] = Field(default_factory=dict)
    derivatives_event_reliability_breakdown: dict[str, int] = Field(default_factory=dict)
    derivatives_stale_share: float = 0.0
    notes: list[str] = Field(default_factory=list)


class RiskDecisionResponse(BaseModel):
    """Canonical runtime risk decision for one bot/runtime scope."""

    generated_at: datetime | str
    allow_trading: bool = False
    trading_mode: str
    risk_state: str
    risk_score: int
    data_validation_status: str
    data_trust_level: str
    allowed_directions: list[str] = Field(default_factory=list)
    blocked_directions: list[str] = Field(default_factory=list)
    max_position_size_pct: float = 0.0
    max_total_exposure_pct: float = 0.0
    max_positions_total: int = 0
    max_positions_per_symbol: int = 0
    max_correlated_positions: int = 0
    allowed_strategy_ids: list[str] = Field(default_factory=list)
    blocked_strategy_ids: list[str] = Field(default_factory=list)
    allowed_strategy_families: list[str] = Field(default_factory=list)
    blocked_strategy_families: list[str] = Field(default_factory=list)
    leverage_cap: float = 1.0
    force_reduce_only: bool = False
    new_entries_allowed: bool = False
    cooldown_active: bool = False
    execution_budget_multiplier: float = 1.0
    hard_enforcement_enabled: bool = True
    enforced_by: list[str] = Field(default_factory=list)
    last_enforcement_status: str | None = None
    last_blocked_order_reason_codes: list[str] = Field(default_factory=list)
    enforcement_counters: dict[str, int] = Field(default_factory=dict)
    protective_overrides: dict[str, bool] = Field(default_factory=dict)
    risk_reason_codes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    decision_trace: list[dict[str, Any]] = Field(default_factory=list)
    degradation_flags: dict[str, bool] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


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
    agents_status: str
    agents_reason: str | None = None
    runtime_freeze: bool = False


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
    superseded_reason: str | None = None
    superseded_by_commit: str | None = None
    created_at: datetime | str
    started_at: datetime | str | None = None
    finished_at: datetime | str | None = None
    resolved_at: datetime | str | None = None
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
    superseded_tasks: int = 0
    modules: list[dict[str, Any]] = Field(default_factory=list)
    resource_guard: dict[str, Any] = Field(default_factory=dict)


class CodingReviewDecisionRequest(BaseModel):
    """Optional reason used when rejecting a reviewed coding task."""

    reason: str = "Manual review rejection."


class CodingTaskSupersedeRequest(BaseModel):
    """Operator-driven closure for stale or superseded coding tasks."""

    reason: str = "Task was superseded by a later code change."
    superseded_by_commit: str | None = None
