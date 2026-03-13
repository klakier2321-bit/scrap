"""Prometheus metrics for agent runs and bot control."""

from __future__ import annotations

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
BOT_RUNNING = Gauge(
    "crypto_ai_bot_running",
    "Whether a bot container is currently running.",
    ["bot_id"],
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


def update_bot_statuses(bots: list[dict[str, Any]]) -> None:
    for bot in bots:
        BOT_RUNNING.labels(bot_id=bot["bot_id"]).set(1 if bot["state"] == "running" else 0)


def render_metrics(bot_states: list[dict[str, Any]]) -> tuple[bytes, str]:
    update_bot_statuses(bot_states)
    return generate_latest(), CONTENT_TYPE_LATEST
