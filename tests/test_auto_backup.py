from __future__ import annotations

from pathlib import Path

import pytest

import auto_backup
from db import Database, now_iso


def test_create_and_list_restore_points(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_backup, "app_data_dir", lambda: str(tmp_path))

    db = Database(str(tmp_path / "tasks.sqlite3"))
    db.insert_task({"description": "Snapshot me", "sort_order": 1, "last_update": now_iso()})

    backup_path = auto_backup.create_versioned_backup(db, reason="auto")
    points = auto_backup.list_restore_points(limit=5, db_path=db.path)

    assert backup_path.exists()
    assert points
    assert points[0]["path"] == str(backup_path)
    assert points[0]["reason"] == "auto"
    assert points[0]["task_count"] == 1
    assert points[0]["archived_count"] == 0
    assert auto_backup.last_restore_point(db_path=db.path)["path"] == str(backup_path)


def test_delete_restore_point_removes_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_backup, "app_data_dir", lambda: str(tmp_path))

    db = Database(str(tmp_path / "tasks.sqlite3"))
    db.insert_task({"description": "Snapshot me", "sort_order": 1, "last_update": now_iso()})
    backup_path = auto_backup.create_versioned_backup(db, reason="manual")

    deleted = auto_backup.delete_restore_point(backup_path, db_path=db.path)

    assert deleted["path"] == str(backup_path)
    assert not backup_path.exists()
    assert auto_backup.list_restore_points(db_path=db.path) == []


def test_delete_restore_point_rejects_outside_backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_backup, "app_data_dir", lambda: str(tmp_path))

    outside = Path(tmp_path / "not_a_snapshot.json")
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError):
        auto_backup.delete_restore_point(outside, db_path=str(tmp_path / "tasks.sqlite3"))
