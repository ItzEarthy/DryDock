from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from flask import current_app

APP_START_TIME = datetime.utcnow()


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "level": record.levelname,
            "event": getattr(record, "event_name", record.getMessage()),
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "event_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        return json.dumps(payload, default=str)


DRYDOCK_LOGGER = logging.getLogger("drydock")


def configure_structured_logging(level_name: str = "INFO") -> None:
    logs_dir = Path(current_app.root_path) / "instance" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "drydock.jsonl"

    level = getattr(logging, (level_name or "INFO").upper(), logging.INFO)
    DRYDOCK_LOGGER.setLevel(level)

    has_file_handler = False
    for handler in DRYDOCK_LOGGER.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_file:
            has_file_handler = True
            break

    if not has_file_handler:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JsonLogFormatter())
        DRYDOCK_LOGGER.addHandler(file_handler)

    DRYDOCK_LOGGER.propagate = False


def log_event(level, event_name, **event_fields) -> None:
    severity = getattr(logging, str(level).upper(), logging.INFO)
    DRYDOCK_LOGGER.log(
        severity,
        event_name,
        extra={"event_name": event_name, "event_fields": event_fields},
    )


def format_uptime(delta):
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"
