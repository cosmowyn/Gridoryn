from __future__ import annotations

import sqlite3

import pytest

from db import Database, DatabaseMigrationError


def test_database_rejects_newer_schema_version(tmp_path):
    db_path = tmp_path / "future.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA user_version=999;")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(DatabaseMigrationError):
        Database(str(db_path))


def test_database_migrates_v4_to_v7_project_management_categories_and_gantt_colors(tmp_path):
    db_path = tmp_path / "legacy_v4.sqlite3"

    legacy = object.__new__(Database)
    legacy.path = str(db_path)
    legacy._pre_migration_backup_path = None
    legacy.conn = sqlite3.connect(db_path)
    legacy.conn.row_factory = sqlite3.Row
    try:
        legacy._configure()
        legacy._create_v1()
        legacy.conn.execute("PRAGMA user_version=1;")
        legacy.conn.commit()
        legacy._migrate_to_v2_hierarchy()
        legacy.conn.execute("PRAGMA user_version=2;")
        legacy.conn.commit()
        legacy._migrate_to_v3_custom_list_values()
        legacy.conn.execute("PRAGMA user_version=3;")
        legacy.conn.commit()
        legacy._migrate_to_v4_productivity()
        legacy.conn.execute("PRAGMA user_version=4;")
        legacy.conn.commit()
        legacy.conn.execute(
            """
            INSERT INTO tasks(description, due_date, last_update, priority, status, parent_id, sort_order, is_collapsed,
                              notes, archived_at, planned_bucket, effort_minutes, actual_minutes, timer_started_at,
                              waiting_for, recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                              reminder_at, reminder_minutes_before, reminder_fired_at)
            VALUES('Legacy project', NULL, '2026-03-08 09:00:00', 2, 'Todo', NULL, 1, 0,
                   '', NULL, 'inbox', NULL, 0, NULL, NULL, NULL, NULL, 0, NULL, NULL, NULL);
            """
        )
        legacy.conn.commit()
    finally:
        legacy.conn.close()

    migrated = Database(str(db_path))
    try:
        assert migrated.schema_user_version() == 7
        assert migrated.pre_migration_backup_path() is not None
        assert migrated.fetch_project_profile(1) is None
        phases = migrated.fetch_project_phases(1)
        assert len(phases) >= 6
        task = migrated.fetch_task_by_id(1)
        assert task is not None
        assert "start_date" in task
        assert "phase_id" in task
        assert "category_folder_id" in task
        assert "gantt_color_hex" in task
        assert migrated.fetch_category_folders() == []
    finally:
        migrated.close()
