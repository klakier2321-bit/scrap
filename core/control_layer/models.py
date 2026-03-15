"""Wewnętrzne kontrakty danych dla pierwszego przyrostu control layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    """Zwróć aktualny czas UTC w formacie ISO."""

    return datetime.now(timezone.utc).isoformat()


class ControlDecisionStatus(StrEnum):
    """Status decyzji handlera control layer."""

    approved = "approved"
    rejected = "rejected"
    error = "error"


class ControlResultStatus(StrEnum):
    """Status końcowy wykonania requestu control layer."""

    completed = "completed"
    rejected = "rejected"
    failed = "failed"


@dataclass(slots=True)
class ControlRequest:
    """Lokalny request do offline'owego workflow control layer."""

    task_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: f"ctrl-{uuid4()}")
    created_at: str = field(default_factory=utc_now_iso)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ControlDecision:
    """Decyzja zwrócona przez handler control layer."""

    accepted: bool
    status: ControlDecisionStatus
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    handler_name: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ControlResult:
    """Ustrukturyzowany wynik wykonania requestu control layer."""

    request_id: str
    task_type: str
    status: ControlResultStatus
    decision: ControlDecision
    output: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = field(default_factory=utc_now_iso)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
