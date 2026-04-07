"""Operator-managed runtime flags for guarded AI runtime control."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DEFAULT_FLAGS = {
    "kill_switch": False,
    "runtime_freeze": False,
}


def _normalize_flags(payload: dict[str, Any] | None) -> dict[str, bool]:
    data = dict(_DEFAULT_FLAGS)
    raw = dict(payload or {})
    for key in _DEFAULT_FLAGS:
        data[key] = bool(raw.get(key, False))
    return data


def load_runtime_flags(path: Path) -> dict[str, bool]:
    if not path.exists():
        return dict(_DEFAULT_FLAGS)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULT_FLAGS)
    return _normalize_flags(payload)


def write_runtime_flags(path: Path, payload: dict[str, Any]) -> dict[str, bool]:
    normalized = _normalize_flags(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def merge_runtime_flags(
    path: Path,
    *,
    kill_switch: bool | None = None,
    runtime_freeze: bool | None = None,
) -> dict[str, bool]:
    current = load_runtime_flags(path)
    if kill_switch is not None:
        current["kill_switch"] = bool(kill_switch)
    if runtime_freeze is not None:
        current["runtime_freeze"] = bool(runtime_freeze)
    return write_runtime_flags(path, current)
