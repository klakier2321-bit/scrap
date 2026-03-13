"""SQLite-backed persistence for agent runs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    goal TEXT NOT NULL,
    business_reason TEXT,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    model TEXT,
    model_tier TEXT,
    review_required INTEGER DEFAULT 0,
    human_decision_required INTEGER DEFAULT 0,
    approval_required INTEGER DEFAULT 0,
    approval_granted INTEGER DEFAULT 0,
    stop_requested INTEGER DEFAULT 0,
    cross_layer INTEGER DEFAULT 0,
    does_touch_contract INTEGER DEFAULT 0,
    does_touch_runtime INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0,
    actual_cost_usd REAL DEFAULT 0,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    successful_requests INTEGER DEFAULT 0,
    warnings_json TEXT,
    blocked_reason TEXT,
    max_iterations INTEGER DEFAULT 0,
    max_retry_limit INTEGER DEFAULT 0,
    duration_seconds REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT,
    result_json TEXT,
    review_json TEXT,
    error TEXT
);
"""


class RunStore:
    """Persists agent run state in a local SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.commit()

    def create_run(self, record: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        values = {
            "run_id": record["run_id"],
            "task_id": record["task_id"],
            "agent_name": record["agent_name"],
            "goal": record["goal"],
            "business_reason": record.get("business_reason", ""),
            "payload_json": json.dumps(record.get("payload_json", {})),
            "status": record["status"],
            "risk_level": record["risk_level"],
            "model": record.get("model"),
            "model_tier": record.get("model_tier"),
            "review_required": int(bool(record.get("review_required"))),
            "human_decision_required": int(bool(record.get("human_decision_required"))),
            "approval_required": int(bool(record.get("approval_required"))),
            "approval_granted": int(bool(record.get("approval_granted"))),
            "stop_requested": int(bool(record.get("stop_requested"))),
            "cross_layer": int(bool(record.get("cross_layer"))),
            "does_touch_contract": int(bool(record.get("does_touch_contract"))),
            "does_touch_runtime": int(bool(record.get("does_touch_runtime"))),
            "estimated_cost_usd": float(record.get("estimated_cost_usd", 0)),
            "actual_cost_usd": float(record.get("actual_cost_usd", 0)),
            "prompt_tokens": int(record.get("prompt_tokens", 0)),
            "completion_tokens": int(record.get("completion_tokens", 0)),
            "total_tokens": int(record.get("total_tokens", 0)),
            "successful_requests": int(record.get("successful_requests", 0)),
            "warnings_json": json.dumps(record.get("warnings_json", [])),
            "blocked_reason": record.get("blocked_reason"),
            "max_iterations": int(record.get("max_iterations", 0)),
            "max_retry_limit": int(record.get("max_retry_limit", 0)),
            "duration_seconds": float(record.get("duration_seconds", 0)),
            "created_at": record.get("created_at", now),
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
            "updated_at": now,
            "result_json": json.dumps(record.get("result_json", None)),
            "review_json": json.dumps(record.get("review_json", None)),
            "error": record.get("error"),
        }
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs (
                    run_id, task_id, agent_name, goal, business_reason, payload_json,
                    status, risk_level, model, model_tier, review_required,
                    human_decision_required, approval_required, approval_granted,
                    stop_requested, cross_layer, does_touch_contract, does_touch_runtime,
                    estimated_cost_usd, actual_cost_usd, prompt_tokens, completion_tokens,
                    total_tokens, successful_requests, warnings_json, blocked_reason,
                    max_iterations, max_retry_limit, duration_seconds, created_at,
                    started_at, finished_at, updated_at, result_json, review_json, error
                ) VALUES (
                    :run_id, :task_id, :agent_name, :goal, :business_reason, :payload_json,
                    :status, :risk_level, :model, :model_tier, :review_required,
                    :human_decision_required, :approval_required, :approval_granted,
                    :stop_requested, :cross_layer, :does_touch_contract, :does_touch_runtime,
                    :estimated_cost_usd, :actual_cost_usd, :prompt_tokens, :completion_tokens,
                    :total_tokens, :successful_requests, :warnings_json, :blocked_reason,
                    :max_iterations, :max_retry_limit, :duration_seconds, :created_at,
                    :started_at, :finished_at, :updated_at, :result_json, :review_json, :error
                )
                """,
                values,
            )
            connection.commit()

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status",
            "model",
            "model_tier",
            "review_required",
            "human_decision_required",
            "approval_required",
            "approval_granted",
            "stop_requested",
            "estimated_cost_usd",
            "actual_cost_usd",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "successful_requests",
            "warnings_json",
            "blocked_reason",
            "max_iterations",
            "max_retry_limit",
            "duration_seconds",
            "started_at",
            "finished_at",
            "result_json",
            "review_json",
            "error",
        }
        payload: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key.endswith("_json"):
                payload[key] = json.dumps(value)
            elif isinstance(value, bool):
                payload[key] = int(value)
            else:
                payload[key] = value
        if not payload:
            return
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload["run_id"] = run_id
        assignments = ", ".join(f"{key} = :{key}" for key in payload if key != "run_id")

        with self._lock, self._connection() as connection:
            connection.execute(
                f"UPDATE agent_runs SET {assignments} WHERE run_id = :run_id",
                payload,
            )
            connection.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("payload_json", "warnings_json", "result_json", "review_json"):
            value = data.get(key)
            data[key] = json.loads(value) if value else None
        for key in (
            "review_required",
            "human_decision_required",
            "approval_required",
            "approval_granted",
            "stop_requested",
            "cross_layer",
            "does_touch_contract",
            "does_touch_runtime",
        ):
            data[key] = bool(data.get(key))
        return data

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def reconcile_stale_runs(self) -> dict[str, int]:
        """Mark orphaned queued or running runs after a service restart."""

        now = datetime.now(timezone.utc).isoformat()
        summary = {"queued": 0, "running": 0}
        with self._lock, self._connection() as connection:
            queued = connection.execute(
                """
                UPDATE agent_runs
                SET status = 'stopped',
                    finished_at = COALESCE(finished_at, ?),
                    updated_at = ?,
                    error = CASE
                        WHEN error IS NULL OR error = ''
                        THEN 'Run was left queued after ai_control restart.'
                        ELSE error
                    END
                WHERE status = 'queued'
                """,
                (now, now),
            )
            running = connection.execute(
                """
                UPDATE agent_runs
                SET status = 'failed',
                    finished_at = COALESCE(finished_at, ?),
                    updated_at = ?,
                    error = CASE
                        WHEN error IS NULL OR error = ''
                        THEN 'Run was interrupted by ai_control restart.'
                        ELSE error
                    END
                WHERE status = 'running'
                """,
                (now, now),
            )
            connection.commit()
            summary["queued"] = queued.rowcount
            summary["running"] = running.rowcount
        return summary

    def get_today_spend(self, agent_name: str) -> float:
        today_prefix = datetime.now(timezone.utc).date().isoformat()
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(
                    SUM(
                        CASE
                            WHEN actual_cost_usd > 0 THEN actual_cost_usd
                            ELSE estimated_cost_usd
                        END
                    ),
                    0
                ) AS spend
                FROM agent_runs
                WHERE agent_name = ?
                  AND created_at LIKE ?
                  AND status NOT IN ('failed', 'stopped', 'blocked')
                """,
                (agent_name, f"{today_prefix}%"),
            ).fetchone()
        return float(row["spend"]) if row else 0.0

    def get_today_total_spend(self) -> float:
        today_prefix = datetime.now(timezone.utc).date().isoformat()
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(
                    SUM(
                        CASE
                            WHEN actual_cost_usd > 0 THEN actual_cost_usd
                            ELSE estimated_cost_usd
                        END
                    ),
                    0
                ) AS spend
                FROM agent_runs
                WHERE created_at LIKE ?
                  AND status NOT IN ('failed', 'stopped', 'blocked')
                """,
                (f"{today_prefix}%",),
            ).fetchone()
        return float(row["spend"]) if row else 0.0
