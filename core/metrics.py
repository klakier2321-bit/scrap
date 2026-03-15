"""Prometheus metrics for agent runs and bot control."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


AGENT_RUNS_TOTAL = Counter(
    "crypto_ai_agent_runs_total",
    "Total number of agent runs by final or queued status.",
    ["agent_name", "status"],
)
ACTIVE_RUNS = Gauge(
    "crypto_ai_active_runs",
    "Currently active agent runs.",
    ["agent_name"],
)
RUN_DURATION_SECONDS = Histogram(
    "crypto_ai_agent_run_duration_seconds",
    "Duration of completed agent runs.",
    ["agent_name"],
)
LLM_CALLS_TOTAL = Counter(
    "crypto_ai_llm_calls_total",
    "Number of LLM calls executed by agents.",
    ["agent_name", "model"],
)
PROMPT_TOKENS_TOTAL = Counter(
    "crypto_ai_prompt_tokens_total",
    "Prompt token usage by agent and model.",
    ["agent_name", "model"],
)
COMPLETION_TOKENS_TOTAL = Counter(
    "crypto_ai_completion_tokens_total",
    "Completion token usage by agent and model.",
    ["agent_name", "model"],
)
TOTAL_TOKENS_TOTAL = Counter(
    "crypto_ai_total_tokens_total",
    "Total token usage by agent and model.",
    ["agent_name", "model"],
)
RETRY_LIKE_REQUESTS_TOTAL = Counter(
    "crypto_ai_retry_like_requests_total",
    "Additional LLM requests above the first request per runtime step.",
    ["agent_name"],
)
CACHE_HITS_TOTAL = Counter(
    "crypto_ai_cache_hits_total",
    "Number of cached agent step responses reused by the runtime.",
    ["agent_name", "step_type"],
)
CACHE_MISSES_TOTAL = Counter(
    "crypto_ai_cache_misses_total",
    "Number of cache misses for agent step responses.",
    ["agent_name", "step_type"],
)
ESTIMATED_COST_USD_TOTAL = Counter(
    "crypto_ai_estimated_cost_usd_total",
    "Estimated USD cost accumulated by agent and model.",
    ["agent_name", "model"],
)
BLOCKED_CALLS_TOTAL = Counter(
    "crypto_ai_blocked_calls_total",
    "Blocked calls caused by cost, scope, or stop gates.",
    ["agent_name", "reason"],
)
REVIEW_REQUIRED_TOTAL = Counter(
    "crypto_ai_review_required_total",
    "Number of runs that required review.",
    ["agent_name"],
)
HUMAN_ESCALATIONS_TOTAL = Counter(
    "crypto_ai_human_escalations_total",
    "Number of runs escalated to human review.",
    ["agent_name"],
)
SCOPE_VIOLATIONS_TOTAL = Counter(
    "crypto_ai_scope_violations_total",
    "Number of detected scope violations.",
    ["agent_name"],
)
MODEL_ALLOWLIST_VIOLATIONS_TOTAL = Counter(
    "crypto_ai_model_allowlist_violations_total",
    "Number of blocked requests caused by a model outside the configured allowlist.",
    ["agent_name"],
)
BOT_RUNNING = Gauge(
    "crypto_ai_bot_running",
    "Whether a bot container is currently running.",
    ["bot_id"],
)
DRY_RUN_READY = Gauge(
    "crypto_dry_run_ready",
    "Whether the dry run runtime and snapshot pipeline are ready for agent consumption.",
    ["bot_id"],
)
DRY_RUN_SNAPSHOT_AGE_SECONDS = Gauge(
    "crypto_dry_run_snapshot_age_seconds",
    "Age of the latest dry run snapshot in seconds.",
    ["bot_id"],
)
DRY_RUN_OPEN_TRADES = Gauge(
    "crypto_dry_run_open_trades",
    "Open trade count from the latest dry run snapshot.",
    ["bot_id"],
)
DRY_RUN_SMOKE_FAILURES_TOTAL = Counter(
    "crypto_dry_run_smoke_failures_total",
    "Number of failed dry run smoke tests.",
    ["bot_id", "reason"],
)
DRY_RUN_BRIDGE_ERRORS_TOTAL = Counter(
    "crypto_dry_run_bridge_errors_total",
    "Number of dry run runtime bridge errors by reason.",
    ["reason"],
)
STRATEGY_LATEST_PROFIT_PCT = Gauge(
    "crypto_strategy_latest_profit_pct",
    "Latest normalized strategy profit ratio from the most recent backtest report.",
    ["strategy_name"],
)
STRATEGY_LATEST_DRAWDOWN_PCT = Gauge(
    "crypto_strategy_latest_drawdown_pct",
    "Latest normalized strategy drawdown ratio from the most recent backtest report.",
    ["strategy_name"],
)
STRATEGY_LATEST_TOTAL_TRADES = Gauge(
    "crypto_strategy_latest_total_trades",
    "Latest total trade count from the most recent strategy report.",
    ["strategy_name"],
)
STRATEGY_LATEST_WIN_RATE = Gauge(
    "crypto_strategy_latest_win_rate",
    "Latest win rate ratio from the most recent strategy report.",
    ["strategy_name"],
)
STRATEGY_STAGE_CANDIDATE = Gauge(
    "crypto_strategy_stage_candidate",
    "Whether the latest strategy report qualifies as a candidate for the next stage.",
    ["strategy_name"],
)
STRATEGY_REPORT_PROFIT_PCT = Gauge(
    "crypto_strategy_report_profit_pct",
    "Historical normalized strategy report profit ratio.",
    ["strategy_name", "source_run_id", "evaluation_status"],
)
STRATEGY_REPORT_DRAWDOWN_PCT = Gauge(
    "crypto_strategy_report_drawdown_pct",
    "Historical normalized strategy report drawdown ratio.",
    ["strategy_name", "source_run_id", "evaluation_status"],
)
STRATEGY_REPORT_TOTAL_TRADES = Gauge(
    "crypto_strategy_report_total_trades",
    "Historical total trade count for generated strategy reports.",
    ["strategy_name", "source_run_id"],
)
STRATEGY_REPORT_GENERATED_AT_SECONDS = Gauge(
    "crypto_strategy_report_generated_at_seconds",
    "Unix timestamp for the generated historical strategy report.",
    ["strategy_name", "source_run_id"],
)
EXEC_MODULES_TOTAL = Gauge(
    "crypto_exec_modules_total",
    "Number of roadmap modules by executive status.",
    ["status"],
)
EXEC_OPEN_TASKS_TOTAL = Gauge(
    "crypto_exec_open_tasks_total",
    "Number of open executive tasks.",
)
EXEC_COMPLETED_TASKS_TOTAL = Gauge(
    "crypto_exec_completed_tasks_total",
    "Number of executive tasks already closed.",
)
EXEC_TASKS_NEEDING_CEO_TOTAL = Gauge(
    "crypto_exec_tasks_needing_ceo_total",
    "Number of open tasks waiting for CEO-level attention or guidance.",
)
EXEC_DECISIONS_WAITING_TOTAL = Gauge(
    "crypto_exec_decisions_waiting_total",
    "Number of open executive decisions waiting for an answer.",
)
EXEC_HIGH_RISKS_TOTAL = Gauge(
    "crypto_exec_high_risks_total",
    "Number of open risks classified as high severity.",
)
EXEC_BLOCKERS_TOTAL = Gauge(
    "crypto_exec_blockers_total",
    "Number of executive blockers that currently slow the project.",
)
EXEC_ACTIVE_AGENT_RUNS_TOTAL = Gauge(
    "crypto_exec_active_agent_runs_total",
    "Number of currently active agent runs from the executive perspective.",
)
EXEC_AUTOPILOT_RUNNING = Gauge(
    "crypto_exec_autopilot_running",
    "Whether the continuous agent autopilot is currently running.",
)
EXEC_AUTOPILOT_CYCLE_COUNT = Gauge(
    "crypto_exec_autopilot_cycle_count",
    "Number of autopilot cycles completed since the last restart.",
)
EXEC_AUTOPILOT_ATTENTION_NEEDED = Gauge(
    "crypto_exec_autopilot_attention_needed",
    "Whether the autopilot appears stale or otherwise needs executive attention.",
)
EXEC_AUTOPILOT_LAST_STARTED_AT_SECONDS = Gauge(
    "crypto_exec_autopilot_last_started_at_seconds",
    "Unix timestamp of the last autopilot dispatch.",
)
EXEC_MODULE_PROGRESS_PCT = Gauge(
    "crypto_exec_module_progress_pct",
    "Progress percent for one executive roadmap module.",
    [
        "module_id",
        "module_name",
        "status",
        "owner_agent",
        "risk_level",
        "direction",
        "current_focus",
        "next_milestone",
        "executive_note",
    ],
)
EXEC_MODULE_ACTIVE_RUNS = Gauge(
    "crypto_exec_module_active_runs",
    "Current active run count mapped to one executive module.",
    ["module_id", "module_name"],
)
EXEC_MODULE_RECENT_RUNS_24H = Gauge(
    "crypto_exec_module_recent_runs_24h",
    "Recent run count from the last 24h mapped to one executive module.",
    ["module_id", "module_name"],
)
EXEC_OPEN_TASK = Gauge(
    "crypto_exec_open_task",
    "Open executive task used to populate the CEO roadmap dashboard.",
    [
        "task_id",
        "module_id",
        "module_name",
        "task_title",
        "status",
        "owner_agent",
        "priority",
        "needs_human",
        "next_step",
    ],
)
EXEC_DECISION_WAITING = Gauge(
    "crypto_exec_decision_waiting",
    "Executive decision item waiting for a response.",
    [
        "decision_id",
        "title",
        "area",
        "priority",
        "status",
        "expected_from_ceo",
        "impact",
    ],
)
EXEC_RISK_OPEN = Gauge(
    "crypto_exec_risk_open",
    "Open executive risk item shown on the CEO dashboard.",
    ["risk_id", "title", "area", "severity", "status", "mitigation"],
)
EXEC_ASSUMPTION = Gauge(
    "crypto_exec_assumption",
    "Core project assumptions shown on the executive dashboard.",
    ["assumption_id", "title", "status", "description", "why_it_matters"],
)
EXEC_RECENT_CHANGE = Gauge(
    "crypto_exec_recent_change",
    "Recent changes and effects from agent runs for executive reporting.",
    ["change_id", "module_name", "agent_name", "title", "status", "effect", "happened_at"],
)
EXEC_LEAD_NOTE = Gauge(
    "crypto_exec_lead_note",
    "Latest management-facing notes from the lead agent.",
    ["note_id", "title", "agent_name", "status", "message", "next_step", "updated_at"],
)
EXEC_COMPLETED_TASK = Gauge(
    "crypto_exec_completed_task",
    "Recently completed executive tasks shown on the CEO dashboard.",
    ["task_id", "module_id", "module_name", "task_title", "status", "owner_agent", "next_step"],
)
EXEC_BLOCKER = Gauge(
    "crypto_exec_blocker",
    "Executive blockers visible on the CEO dashboard.",
    ["blocker_id", "source", "area", "title", "severity", "status", "why_blocking", "expected_action"],
)
EXEC_AUTOPILOT_HEARTBEAT = Gauge(
    "crypto_exec_autopilot_heartbeat",
    "Current heartbeat information for the continuous autopilot and lead coordination.",
    [
        "last_started_at",
        "last_status",
        "next_task_name",
        "current_task_name",
        "cycle_count",
        "poll_interval_seconds",
    ],
)
EXEC_CODING_READY_TASKS_TOTAL = Gauge(
    "crypto_exec_coding_ready_tasks_total",
    "Number of coding tasks ready for dispatch.",
)
EXEC_CODING_REVIEW_TASKS_TOTAL = Gauge(
    "crypto_exec_coding_review_tasks_total",
    "Number of coding tasks waiting in review.",
)
EXEC_CODING_COMMITTED_TASKS_TOTAL = Gauge(
    "crypto_exec_coding_committed_tasks_total",
    "Number of coding tasks already committed on worktree branches.",
)
EXEC_CODING_TASKS_WAITING_CEO_TOTAL = Gauge(
    "crypto_exec_coding_tasks_waiting_ceo_total",
    "Number of coding tasks waiting for manual executive approval.",
)
EXEC_CODING_ACTIVE_TASK = Gauge(
    "crypto_exec_coding_active_task",
    "Active coding task visible on the CEO dashboard.",
    ["task_id", "module_id", "module_name", "owner_agent", "status", "goal", "branch_name"],
)
EXEC_CODING_TASK = Gauge(
    "crypto_exec_coding_task",
    "Coding tasks managed by the supervised write runtime.",
    [
        "task_id",
        "module_id",
        "module_name",
        "owner_agent",
        "status",
        "goal",
        "branch_name",
        "risk_level",
        "review_decision",
    ],
)
EXEC_CODING_WORKSPACE = Gauge(
    "crypto_exec_coding_workspace",
    "Coding workspaces and their latest state.",
    [
        "task_id",
        "module_id",
        "module_name",
        "agent_name",
        "branch_name",
        "status",
        "worktree_path",
        "changed_files_count",
    ],
)


def record_run_created(agent_name: str, status: str) -> None:
    AGENT_RUNS_TOTAL.labels(agent_name=agent_name, status=status).inc()


def record_run_started(agent_name: str) -> None:
    ACTIVE_RUNS.labels(agent_name=agent_name).inc()


def record_run_succeeded(
    agent_name: str,
    model: str,
    duration_seconds: float,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    successful_requests: int,
    retry_like_requests: int,
    estimated_cost_usd: float,
) -> None:
    ACTIVE_RUNS.labels(agent_name=agent_name).dec()
    AGENT_RUNS_TOTAL.labels(agent_name=agent_name, status="completed").inc()
    RUN_DURATION_SECONDS.labels(agent_name=agent_name).observe(duration_seconds)
    if successful_requests:
        LLM_CALLS_TOTAL.labels(agent_name=agent_name, model=model).inc(successful_requests)
    if prompt_tokens:
        PROMPT_TOKENS_TOTAL.labels(agent_name=agent_name, model=model).inc(prompt_tokens)
    if completion_tokens:
        COMPLETION_TOKENS_TOTAL.labels(agent_name=agent_name, model=model).inc(completion_tokens)
    if total_tokens:
        TOTAL_TOKENS_TOTAL.labels(agent_name=agent_name, model=model).inc(total_tokens)
    if estimated_cost_usd:
        ESTIMATED_COST_USD_TOTAL.labels(agent_name=agent_name, model=model).inc(
            estimated_cost_usd
        )
    if retry_like_requests:
        RETRY_LIKE_REQUESTS_TOTAL.labels(agent_name=agent_name).inc(retry_like_requests)


def record_cache_hit(agent_name: str, step_type: str) -> None:
    CACHE_HITS_TOTAL.labels(agent_name=agent_name, step_type=step_type).inc()


def record_cache_miss(agent_name: str, step_type: str) -> None:
    CACHE_MISSES_TOTAL.labels(agent_name=agent_name, step_type=step_type).inc()


def record_run_failed(agent_name: str, duration_seconds: float, reason: str) -> None:
    ACTIVE_RUNS.labels(agent_name=agent_name).dec()
    AGENT_RUNS_TOTAL.labels(agent_name=agent_name, status="failed").inc()
    RUN_DURATION_SECONDS.labels(agent_name=agent_name).observe(duration_seconds)
    BLOCKED_CALLS_TOTAL.labels(agent_name=agent_name, reason=reason).inc()


def record_blocked_call(agent_name: str, reason: str) -> None:
    AGENT_RUNS_TOTAL.labels(agent_name=agent_name, status="blocked").inc()
    BLOCKED_CALLS_TOTAL.labels(agent_name=agent_name, reason=reason).inc()


def record_review_required(agent_name: str) -> None:
    REVIEW_REQUIRED_TOTAL.labels(agent_name=agent_name).inc()


def record_human_escalation(agent_name: str) -> None:
    HUMAN_ESCALATIONS_TOTAL.labels(agent_name=agent_name).inc()


def record_scope_violation(agent_name: str) -> None:
    SCOPE_VIOLATIONS_TOTAL.labels(agent_name=agent_name).inc()


def record_model_allowlist_violation(agent_name: str) -> None:
    MODEL_ALLOWLIST_VIOLATIONS_TOTAL.labels(agent_name=agent_name).inc()


def update_bot_statuses(bots: list[dict[str, Any]]) -> None:
    for bot in bots:
        BOT_RUNNING.labels(bot_id=bot["bot_id"]).set(1 if bot["state"] == "running" else 0)


def record_dry_run_smoke_failure(bot_id: str, reason: str) -> None:
    DRY_RUN_SMOKE_FAILURES_TOTAL.labels(bot_id=bot_id, reason=reason).inc()


def record_dry_run_bridge_error(reason: str) -> None:
    DRY_RUN_BRIDGE_ERRORS_TOTAL.labels(reason=reason).inc()


def update_dry_run_metrics(
    dry_run_health: dict[str, Any] | None,
    dry_run_snapshot: dict[str, Any] | None,
) -> None:
    if not dry_run_health:
        return
    bot_id = dry_run_health.get("bot_id", "freqtrade")
    DRY_RUN_READY.labels(bot_id=bot_id).set(1 if dry_run_health.get("ready") else 0)
    snapshot_age = dry_run_health.get("snapshot_age_seconds")
    if snapshot_age is not None:
        DRY_RUN_SNAPSHOT_AGE_SECONDS.labels(bot_id=bot_id).set(float(snapshot_age))
    if dry_run_snapshot:
        DRY_RUN_OPEN_TRADES.labels(bot_id=bot_id).set(
            int(dry_run_snapshot.get("open_trades_count", 0))
        )
    else:
        DRY_RUN_OPEN_TRADES.labels(bot_id=bot_id).set(0)


def update_strategy_metrics(strategy_report: dict[str, Any] | None) -> None:
    if not strategy_report:
        return
    strategy_name = strategy_report["strategy_name"]
    STRATEGY_LATEST_PROFIT_PCT.labels(strategy_name=strategy_name).set(
        float(strategy_report.get("profit_pct", 0.0))
    )
    STRATEGY_LATEST_DRAWDOWN_PCT.labels(strategy_name=strategy_name).set(
        float(strategy_report.get("drawdown_pct", 0.0))
    )
    STRATEGY_LATEST_TOTAL_TRADES.labels(strategy_name=strategy_name).set(
        int(strategy_report.get("total_trades", 0))
    )
    STRATEGY_LATEST_WIN_RATE.labels(strategy_name=strategy_name).set(
        float(strategy_report.get("win_rate", 0.0))
    )
    STRATEGY_STAGE_CANDIDATE.labels(strategy_name=strategy_name).set(
        1 if strategy_report.get("stage_candidate") else 0
    )


def update_strategy_history_metrics(strategy_reports: list[dict[str, Any]]) -> None:
    for report in strategy_reports:
        strategy_name = report["strategy_name"]
        source_run_id = report.get("source_run_id") or "latest"
        evaluation_status = report.get("evaluation_status", "unknown")
        STRATEGY_REPORT_PROFIT_PCT.labels(
            strategy_name=strategy_name,
            source_run_id=source_run_id,
            evaluation_status=evaluation_status,
        ).set(float(report.get("profit_pct", 0.0)))
        STRATEGY_REPORT_DRAWDOWN_PCT.labels(
            strategy_name=strategy_name,
            source_run_id=source_run_id,
            evaluation_status=evaluation_status,
        ).set(float(report.get("drawdown_pct", 0.0)))
        STRATEGY_REPORT_TOTAL_TRADES.labels(
            strategy_name=strategy_name,
            source_run_id=source_run_id,
        ).set(int(report.get("total_trades", 0)))
        generated_at = report.get("generated_at")
        if generated_at:
            try:
                timestamp = float(
                    datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).timestamp()
                )
            except ValueError:
                timestamp = 0.0
        else:
            timestamp = 0.0
        STRATEGY_REPORT_GENERATED_AT_SECONDS.labels(
            strategy_name=strategy_name,
            source_run_id=source_run_id,
        ).set(timestamp)


def update_executive_metrics(executive_report: dict[str, Any] | None) -> None:
    if not executive_report:
        return

    EXEC_MODULES_TOTAL.clear()
    EXEC_MODULE_PROGRESS_PCT.clear()
    EXEC_MODULE_ACTIVE_RUNS.clear()
    EXEC_MODULE_RECENT_RUNS_24H.clear()
    EXEC_OPEN_TASK.clear()
    EXEC_DECISION_WAITING.clear()
    EXEC_RISK_OPEN.clear()
    EXEC_ASSUMPTION.clear()
    EXEC_RECENT_CHANGE.clear()
    EXEC_LEAD_NOTE.clear()
    EXEC_COMPLETED_TASK.clear()
    EXEC_BLOCKER.clear()
    EXEC_CODING_ACTIVE_TASK.clear()
    EXEC_CODING_TASK.clear()
    EXEC_CODING_WORKSPACE.clear()

    summary = executive_report.get("summary", {})
    for status, count in summary.get("modules_by_status", {}).items():
        EXEC_MODULES_TOTAL.labels(status=status).set(count)

    EXEC_OPEN_TASKS_TOTAL.set(int(summary.get("open_tasks_total", 0)))
    EXEC_COMPLETED_TASKS_TOTAL.set(int(summary.get("completed_tasks_total", 0)))
    EXEC_TASKS_NEEDING_CEO_TOTAL.set(int(summary.get("tasks_needing_ceo_total", 0)))
    EXEC_DECISIONS_WAITING_TOTAL.set(int(summary.get("decisions_waiting_total", 0)))
    EXEC_HIGH_RISKS_TOTAL.set(int(summary.get("high_risks_total", 0)))
    EXEC_BLOCKERS_TOTAL.set(int(summary.get("blockers_total", 0)))
    EXEC_ACTIVE_AGENT_RUNS_TOTAL.set(int(summary.get("active_agent_runs_total", 0)))
    EXEC_CODING_READY_TASKS_TOTAL.set(int(summary.get("coding_tasks_ready_total", 0)))
    EXEC_CODING_REVIEW_TASKS_TOTAL.set(int(summary.get("coding_tasks_review_total", 0)))
    EXEC_CODING_COMMITTED_TASKS_TOTAL.set(int(summary.get("coding_tasks_committed_total", 0)))
    EXEC_CODING_TASKS_WAITING_CEO_TOTAL.set(int(summary.get("coding_tasks_waiting_ceo_total", 0)))

    autopilot = executive_report.get("autopilot", {})
    EXEC_AUTOPILOT_RUNNING.set(1 if autopilot.get("running") else 0)
    EXEC_AUTOPILOT_CYCLE_COUNT.set(int(autopilot.get("cycle_count", 0)))
    EXEC_AUTOPILOT_ATTENTION_NEEDED.set(1 if autopilot.get("attention_needed") else 0)
    last_started_at = autopilot.get("last_started_at")
    if last_started_at:
        try:
            timestamp = float(
                datetime.fromisoformat(str(last_started_at).replace("Z", "+00:00")).timestamp()
            )
        except ValueError:
            timestamp = 0.0
    else:
        timestamp = 0.0
    EXEC_AUTOPILOT_LAST_STARTED_AT_SECONDS.set(timestamp)
    EXEC_AUTOPILOT_HEARTBEAT.clear()
    EXEC_AUTOPILOT_HEARTBEAT.labels(
        last_started_at=str(autopilot.get("last_started_at") or "brak"),
        last_status=str(autopilot.get("last_status") or "brak"),
        next_task_name=str(autopilot.get("next_task_name") or "brak"),
        current_task_name=str(autopilot.get("current_task_name") or "brak"),
        cycle_count=str(autopilot.get("cycle_count", 0)),
        poll_interval_seconds=str(autopilot.get("poll_interval_seconds", 0)),
    ).set(1)

    modules_by_id = {
        module["id"]: module.get("name", module["id"])
        for module in executive_report.get("modules", [])
    }

    for module in executive_report.get("modules", []):
        EXEC_MODULE_PROGRESS_PCT.labels(
            module_id=module["id"],
            module_name=module["name"],
            status=module["status"],
            owner_agent=module["owner_agent"],
            risk_level=module["risk_level"],
            direction=module["direction"],
            current_focus=module["current_focus"],
            next_milestone=module["next_milestone"],
            executive_note=module["executive_note"],
        ).set(float(module.get("progress_pct", 0.0)))
        EXEC_MODULE_ACTIVE_RUNS.labels(
            module_id=module["id"],
            module_name=module["name"],
        ).set(int(module.get("active_runs", 0)))
        EXEC_MODULE_RECENT_RUNS_24H.labels(
            module_id=module["id"],
            module_name=module["name"],
        ).set(int(module.get("recent_runs_24h", 0)))

    for task in executive_report.get("tasks", []):
        EXEC_OPEN_TASK.labels(
            task_id=task["id"],
            module_id=task["module_id"],
            module_name=modules_by_id.get(task["module_id"], task["module_id"]),
            task_title=task["title"],
            status=task["status"],
            owner_agent=task["owner_agent"],
            priority=task["priority"],
            needs_human=task["needs_human"],
            next_step=task["next_step"],
        ).set(1)

    for decision in executive_report.get("decisions", []):
        EXEC_DECISION_WAITING.labels(
            decision_id=decision["id"],
            title=decision["title"],
            area=decision["area"],
            priority=decision["priority"],
            status=decision["status"],
            expected_from_ceo=decision["expected_from_ceo"],
            impact=decision["impact"],
        ).set(1)

    for risk in executive_report.get("risks", []):
        EXEC_RISK_OPEN.labels(
            risk_id=risk["id"],
            title=risk["title"],
            area=risk["area"],
            severity=risk["severity"],
            status=risk["status"],
            mitigation=risk["mitigation"],
        ).set(1)

    for assumption in executive_report.get("assumptions", []):
        EXEC_ASSUMPTION.labels(
            assumption_id=assumption["id"],
            title=assumption["title"],
            status=assumption["status"],
            description=assumption["description"],
            why_it_matters=assumption["why_it_matters"],
        ).set(1)

    for change in executive_report.get("recent_changes", []):
        EXEC_RECENT_CHANGE.labels(
            change_id=change["change_id"],
            module_name=change["module_name"],
            agent_name=change["agent_name"],
            title=change["title"],
            status=change["status"],
            effect=change["effect"],
            happened_at=change["happened_at"],
        ).set(1)

    for note in executive_report.get("lead_notes", []):
        EXEC_LEAD_NOTE.labels(
            note_id=note["note_id"],
            title=note["title"],
            agent_name=note["agent_name"],
            status=note["status"],
            message=note["message"],
            next_step=note["next_step"],
            updated_at=note["updated_at"],
        ).set(1)

    for task in executive_report.get("completed_tasks", []):
        EXEC_COMPLETED_TASK.labels(
            task_id=task["id"],
            module_id=task["module_id"],
            module_name=modules_by_id.get(task["module_id"], task["module_id"]),
            task_title=task["title"],
            status=task["status"],
            owner_agent=task["owner_agent"],
            next_step=task["next_step"],
        ).set(1)

    for blocker in executive_report.get("blockers", []):
        EXEC_BLOCKER.labels(
            blocker_id=blocker["blocker_id"],
            source=blocker["source"],
            area=blocker["area"],
            title=blocker["title"],
            severity=blocker["severity"],
            status=blocker["status"],
            why_blocking=blocker["why_blocking"],
            expected_action=blocker["expected_action"],
        ).set(1)

    coding = executive_report.get("coding", {})
    modules_by_id = {
        module["id"]: module.get("name", module["id"])
        for module in executive_report.get("modules", [])
    }
    tasks_by_id = {
        task["task_id"]: task
        for task in coding.get("tasks", [])
    }
    active_task = (coding.get("summary") or {}).get("active_task")
    if active_task:
        EXEC_CODING_ACTIVE_TASK.labels(
            task_id=active_task["task_id"],
            module_id=active_task["module_id"],
            module_name=modules_by_id.get(active_task["module_id"], active_task["module_id"]),
            owner_agent=active_task["owner_agent"],
            status=active_task["status"],
            goal=active_task["goal"],
            branch_name=active_task.get("branch_name") or "brak",
        ).set(1)

    for task in coding.get("tasks", []):
        review_json = task.get("review_json") or {}
        EXEC_CODING_TASK.labels(
            task_id=task["task_id"],
            module_id=task["module_id"],
            module_name=modules_by_id.get(task["module_id"], task["module_id"]),
            owner_agent=task["owner_agent"],
            status=task["status"],
            goal=task["goal"],
            branch_name=task.get("branch_name") or "brak",
            risk_level=task.get("risk_level") or "low",
            review_decision=review_json.get("decision") or "brak",
        ).set(float(task.get("total_cost_usd", 0.0)))

    for workspace in coding.get("workspaces", []):
        related_task = tasks_by_id.get(workspace["task_id"], {})
        module_id = related_task.get("module_id", "nieznany_modul")
        EXEC_CODING_WORKSPACE.labels(
            task_id=workspace["task_id"],
            module_id=module_id,
            module_name=modules_by_id.get(module_id, module_id),
            agent_name=workspace["agent_name"],
            branch_name=workspace["branch_name"],
            status=workspace["status"],
            worktree_path=workspace["worktree_path"],
            changed_files_count=str(len(workspace.get("changed_files", []))),
        ).set(1)


def render_metrics(
    bot_states: list[dict[str, Any]],
    strategy_report: dict[str, Any] | None = None,
    strategy_report_history: list[dict[str, Any]] | None = None,
    dry_run_health: dict[str, Any] | None = None,
    dry_run_snapshot: dict[str, Any] | None = None,
    executive_report: dict[str, Any] | None = None,
) -> tuple[bytes, str]:
    update_bot_statuses(bot_states)
    update_strategy_metrics(strategy_report)
    update_strategy_history_metrics(strategy_report_history or [])
    update_dry_run_metrics(dry_run_health, dry_run_snapshot)
    update_executive_metrics(executive_report)
    return generate_latest(), CONTENT_TYPE_LATEST
