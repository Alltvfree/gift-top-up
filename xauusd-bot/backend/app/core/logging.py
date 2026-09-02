"""Structured logging.

Emits human-readable lines to the console and JSON lines to a rotating file so
every MT5 operation, signal and risk decision is auditable. Event-style helpers
(``log_event``) attach structured ``metadata`` that later phases persist to the
``bot_events`` table.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path
from typing import Any, Optional

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """Render each record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event_type = getattr(record, "event_type", None)
        if event_type:
            payload["event_type"] = event_type
        metadata = getattr(record, "metadata", None)
        if metadata:
            payload["metadata"] = metadata
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Compact, readable console line: ``TIME LEVEL EVENT message``."""

    def format(self, record: logging.LogRecord) -> str:
        time_str = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        event_type = getattr(record, "event_type", None)
        head = f"{time_str} {record.levelname}"
        if event_type:
            head += f" {event_type}"
        line = f"{head} {record.getMessage()}"
        metadata = getattr(record, "metadata", None)
        if metadata:
            line += f" | {json.dumps(metadata, default=str)}"
        return line


def configure_logging(
    level: str = "INFO",
    log_dir: Optional[str | Path] = None,
    *,
    force: bool = False,
) -> None:
    """Configure the root logger. Idempotent unless ``force=True``."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    # Clear existing handlers so repeated configuration (e.g. in tests) is clean.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path / "bot.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger (configures with defaults if not yet configured)."""
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event_type: str,
    message: str = "",
    *,
    level: int = logging.INFO,
    **metadata: Any,
) -> None:
    """Log a structured event.

    Example::

        log_event(log, "MT5_CONNECTED", "connected to broker", server="Demo")
    """
    logger.log(
        level,
        message or event_type,
        extra={"event_type": event_type, "metadata": metadata or None},
    )


__all__ = ["configure_logging", "get_logger", "log_event", "JsonFormatter"]
