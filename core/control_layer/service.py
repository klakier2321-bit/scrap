"""Serwis wykonujący lokalne workflow control layer bez efektów ubocznych."""

from __future__ import annotations

from time import monotonic

from .models import (
    ControlDecision,
    ControlDecisionStatus,
    ControlRequest,
    ControlResult,
    ControlResultStatus,
    utc_now_iso,
)
from .registry import HandlerRegistry, build_default_registry


class ControlLayerService:
    """Uruchamia jawnie zarejestrowane, offline'owe taski control layer."""

    def __init__(self, registry: HandlerRegistry | None = None) -> None:
        self.registry = registry or build_default_registry()

    def execute(self, request: ControlRequest) -> ControlResult:
        started_at = utc_now_iso()
        started_clock = monotonic()

        try:
            handler = self.registry.resolve(request.task_type)
            decision, output = handler.handle(request)
            status = (
                ControlResultStatus.completed
                if decision.accepted
                else ControlResultStatus.rejected
            )
        except KeyError as exc:
            decision = ControlDecision(
                accepted=False,
                status=ControlDecisionStatus.rejected,
                reasons=[str(exc)],
                handler_name="registry",
            )
            output = {"available_task_types": self.registry.available_task_types()}
            status = ControlResultStatus.rejected
        except Exception as exc:  # pragma: no cover - safety net
            decision = ControlDecision(
                accepted=False,
                status=ControlDecisionStatus.error,
                reasons=[f"Niespodziewany błąd control layer: {exc}"],
                handler_name="service",
            )
            output = {}
            status = ControlResultStatus.failed

        finished_at = utc_now_iso()
        duration_ms = round((monotonic() - started_clock) * 1000, 3)
        return ControlResult(
            request_id=request.request_id,
            task_type=request.task_type,
            status=status,
            decision=decision,
            output=output,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            metadata={
                "source": request.source,
                "offline_only": True,
                "request_metadata": request.metadata,
            },
        )
