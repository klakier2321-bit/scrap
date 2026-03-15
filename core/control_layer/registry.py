"""Lokalny registry handlerów dla pierwszego przyrostu control layer."""

from __future__ import annotations

from typing import Any, Protocol

from .models import ControlDecision, ControlRequest


class ControlHandler(Protocol):
    """Kontrakt handlera control layer."""

    task_type: str
    handler_name: str

    def handle(self, request: ControlRequest) -> tuple[ControlDecision, dict[str, Any]]:
        """Obsłuż request i zwróć decyzję oraz output."""


class HandlerRegistry:
    """In-memory registry jawnie zarejestrowanych handlerów."""

    def __init__(self) -> None:
        self._handlers: dict[str, ControlHandler] = {}

    def register(self, handler: ControlHandler) -> None:
        task_type = handler.task_type.strip()
        if not task_type:
            raise ValueError("Handler task_type nie może być pusty.")
        if task_type in self._handlers:
            raise ValueError(f"Handler dla task_type '{task_type}' jest już zarejestrowany.")
        self._handlers[task_type] = handler

    def resolve(self, task_type: str) -> ControlHandler:
        try:
            return self._handlers[task_type]
        except KeyError as exc:
            raise KeyError(
                f"Nieznany task_type '{task_type}'. Dostępne: {', '.join(self.available_task_types())}"
            ) from exc

    def available_task_types(self) -> list[str]:
        return sorted(self._handlers)


def build_default_registry() -> HandlerRegistry:
    """Zbuduj domyślny registry z bezpiecznym, lokalnym handlerem referencyjnym."""

    from .handlers import DryControlCheckHandler

    registry = HandlerRegistry()
    registry.register(DryControlCheckHandler())
    return registry
