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


def render_metrics(
    bot_states: list[dict[str, Any]],
    strategy_report: dict[str, Any] | None = None,
    strategy_report_history: list[dict[str, Any]] | None = None,
) -> tuple[bytes, str]:
    update_bot_statuses(bot_states)
    update_strategy_metrics(strategy_report)
    update_strategy_history_metrics(strategy_report_history or [])
    return generate_latest(), CONTENT_TYPE_LATEST
