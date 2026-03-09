from __future__ import annotations

import os
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


def test_log_event_writes_labeled_operation_block(tmp_path, monkeypatch):
    log_path = tmp_path / "ops.log"
    monkeypatch.setattr(crash_logging, "current_log_path", lambda: log_path)

    written = crash_logging.log_event(
        "Backup export completed",
        context="backup.export",
        db_path="/tmp/tasks.sqlite3",
        details={"target_path": "/tmp/out.json", "task_count": 4},
    )

    assert written == log_path
    text = log_path.read_text(encoding="utf-8")
    assert "entry_type: event" in text
    assert "context: backup.export" in text
    assert "message: Backup export completed" in text
    assert '"task_count": 4' in text


def test_list_log_paths_returns_newest_first(tmp_path, monkeypatch):
    logs_root = tmp_path / "logs"
    logs_root.mkdir()
    older = logs_root / "gridoryn_2026-03-07.log"
    newer = logs_root / "gridoryn_2026-03-08.log"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))
    monkeypatch.setattr(crash_logging, "logs_dir", lambda: logs_root)

    paths = crash_logging.list_log_paths()

    assert paths[0] == newer
    assert older in paths
