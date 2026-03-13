"""Global CrewAI hooks used by the agent runtime."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Callable

from crewai.hooks.decorators import after_llm_call, before_llm_call, before_tool_call


@dataclass
class HookRunContext:
    """Context available to runtime hooks for one run."""

    run_id: str
    task_id: str
    agent_name: str
    model: str
    max_iterations: int
    stop_requested: Callable[[], bool]
    on_blocked: Callable[[str], None]
    on_llm_call: Callable[[str, str], None]


CURRENT_RUN_CONTEXT: contextvars.ContextVar[HookRunContext | None] = contextvars.ContextVar(
    "current_run_context",
    default=None,
)


def set_current_run_context(context: HookRunContext):
    """Bind the current run context to the active execution."""
    return CURRENT_RUN_CONTEXT.set(context)


def reset_current_run_context(token: contextvars.Token[HookRunContext | None]) -> None:
    """Reset the current run context after execution."""
    CURRENT_RUN_CONTEXT.reset(token)


def register_runtime_hooks() -> None:
    """Register hooks only once for the process."""

    if getattr(register_runtime_hooks, "_registered", False):
        return

    @before_llm_call
    def _before_llm_call(context) -> bool | None:
        run_context = CURRENT_RUN_CONTEXT.get()
        if run_context is None:
            return None
        run_context.on_llm_call(run_context.agent_name, run_context.model)
        if run_context.stop_requested():
            run_context.on_blocked("stop_requested")
            return False
        if context.iterations >= run_context.max_iterations:
            run_context.on_blocked("max_iterations")
            return False
        return None

    @after_llm_call
    def _after_llm_call(context) -> str | None:
        run_context = CURRENT_RUN_CONTEXT.get()
        if run_context and run_context.stop_requested():
            run_context.on_blocked("stop_requested_after_llm")
        return None

    @before_tool_call
    def _before_tool_call(context) -> bool | None:
        run_context = CURRENT_RUN_CONTEXT.get()
        if run_context is None:
            return False
        run_context.on_blocked(f"tool_blocked:{context.tool_name}")
        return False

    register_runtime_hooks._registered = True
