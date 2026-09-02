"""Tests for structured logging."""

from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, configure_logging, get_logger, log_event


def test_json_formatter_includes_event_and_metadata():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    record.event_type = "ORDER_SENT"
    record.metadata = {"ticket": 123}
    payload = json.loads(formatter.format(record))
    assert payload["event_type"] == "ORDER_SENT"
    assert payload["metadata"] == {"ticket": 123}
    assert payload["level"] == "INFO"


def test_log_event_writes_file(tmp_path):
    configure_logging(level="INFO", log_dir=tmp_path, force=True)
    log = get_logger("test.events")
    log_event(log, "MT5_CONNECTED", "connected", server="Demo")
    for handler in logging.getLogger().handlers:
        handler.flush()
    log_file = tmp_path / "bot.log"
    assert log_file.exists()
    lines = [l for l in log_file.read_text().splitlines() if l.strip()]
    parsed = [json.loads(l) for l in lines]
    events = [p for p in parsed if p.get("event_type") == "MT5_CONNECTED"]
    assert events and events[-1]["metadata"]["server"] == "Demo"
    # Reset logging so the file handler doesn't leak into other tests.
    configure_logging(level="INFO", force=True)
