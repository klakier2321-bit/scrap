"""Structured logging for the control layer."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path

from .config import AppSettings


class JsonFormatter(logging.Formatter):
    """Simple JSON formatter for operational logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "run_id",
            "task_id",
            "agent_name",
            "model",
            "status",
            "event",
            "bot_id",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def setup_logging(settings: AppSettings) -> None:
    """Configure root logging with stdout and file output."""

    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.control_api_log_level.upper(), logging.INFO))
    root_logger.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
