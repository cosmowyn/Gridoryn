from __future__ import annotations

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
