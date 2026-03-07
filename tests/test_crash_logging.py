from __future__ import annotations

from pathlib import Path

import crash_logging


def test_write_exception_log_writes_expected_fields(tmp_path, monkeypatch):
    log_path = tmp_path / "crash.log"
    monkeypatch.setattr(crash_logging, "current_log_path", lambda: log_path)

    try:
        raise ValueError("boom")
    except ValueError as exc:
        written = crash_logging.log_exception(exc, context="unit-test", db_path="/tmp/tasks.sqlite3")

    assert written == log_path
    text = log_path.read_text(encoding="utf-8")
    assert "context: unit-test" in text
    assert "exception_type: ValueError" in text
    assert "message: boom" in text
    assert "app_version:" in text
    assert "python_version:" in text
    assert "db_path: /tmp/tasks.sqlite3" in text
    assert "Traceback" in text


def test_write_exception_log_failures_do_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(crash_logging, "current_log_path", lambda: Path(tmp_path))

    try:
        raise RuntimeError("cannot write")
    except RuntimeError as exc:
        written = crash_logging.log_exception(exc, context="write-failure")

    assert written is None
