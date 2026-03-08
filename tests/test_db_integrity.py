from __future__ import annotations

from pathlib import Path

from db import Database, now_iso


def _set_foreign_keys(db: Database, enabled: bool):
    db.conn.commit()
    db.conn.execute(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'};")
    db.conn.commit()


def _insert_issue_rows(db: Database, tmp_path: Path) -> dict[str, int]:
    task_one = db.insert_task({"description": "Task one", "sort_order": 1, "last_update": now_iso()})
    task_two = db.insert_task({"description": "Task two", "sort_order": 3, "last_update": now_iso()})
    broken_child = db.insert_task({"description": "Broken child", "sort_order": 4, "last_update": now_iso()})
    generated = db.insert_task(
        {
            "description": "Generated orphan",
            "sort_order": 5,
            "last_update": now_iso(),
            "is_generated_occurrence": 1,
        }
    )
    column_id = db.add_custom_column("Health column", "text")
    db.ensure_project_profile(task_one)
    phase_id = int(db.fetch_project_phases(task_one)[0]["id"])

    missing_path = tmp_path / "missing.txt"
    db.add_attachment(task_one, str(missing_path), "missing file")

    _set_foreign_keys(db, False)
    try:
        db.conn.execute("UPDATE tasks SET parent_id=? WHERE id=?;", (999_001, broken_child))
        db.conn.execute(
            "INSERT INTO task_custom_values(task_id, column_id, value) VALUES(?, ?, ?);",
            (999_002, column_id, "orphan task"),
        )
        db.conn.execute(
            "INSERT INTO task_custom_values(task_id, column_id, value) VALUES(?, ?, ?);",
            (task_one, 999_003, "orphan column"),
        )
        db.conn.execute(
            """
            INSERT INTO recurrence_rules(task_id, frequency, create_next_on_done, is_active, created_at, updated_at)
            VALUES(?, ?, 1, 1, ?, ?);
            """,
            (task_two, "hourly", now_iso(), now_iso()),
        )
        rule_id = int(db.conn.execute("SELECT last_insert_rowid();").fetchone()[0])
        db.conn.execute("UPDATE tasks SET recurrence_rule_id=? WHERE id=?;", (rule_id, task_two))
        db.conn.execute("UPDATE tasks SET recurrence_rule_id=? WHERE id=?;", (999_004, task_one))
        db.conn.execute("UPDATE tasks SET recurrence_origin_task_id=? WHERE id=?;", (999_005, generated))
        db.conn.execute("UPDATE tasks SET phase_id=? WHERE id=?;", (999_006, task_two))
        db.conn.execute(
            """
            INSERT INTO pm_dependencies(
                predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type, is_soft, created_at
            )
            VALUES('task', ?, 'milestone', ?, 'finish_to_start', 0, ?);
            """,
            (999_007, 999_008, now_iso()),
        )
        db.conn.execute(
            """
            INSERT INTO milestones(
                project_task_id, title, description, phase_id, linked_task_id, start_date, target_date,
                baseline_target_date, status, progress_percent, completed_at, created_at, updated_at
            )
            VALUES(?, ?, '', ?, ?, NULL, NULL, NULL, 'planned', 0, NULL, ?, ?);
            """,
            (task_one, "Broken milestone", 999_009, 999_010, now_iso(), now_iso()),
        )
        db.conn.execute(
            """
            INSERT INTO deliverables(
                project_task_id, title, description, phase_id, linked_task_id, linked_milestone_id, due_date,
                baseline_due_date, acceptance_criteria, version_ref, status, completed_at, created_at, updated_at
            )
            VALUES(?, ?, '', ?, ?, ?, NULL, NULL, '', '', 'planned', NULL, ?, ?);
            """,
            (task_one, "Broken deliverable", phase_id, 999_011, 999_012, now_iso(), now_iso()),
        )
        db.conn.execute(
            """
            INSERT INTO project_register_entries(
                project_task_id, entry_type, title, details, status, severity, review_date,
                linked_task_id, linked_milestone_id, created_at, updated_at
            )
            VALUES(?, ?, ?, '', 'open', NULL, NULL, ?, ?, ?, ?);
            """,
            (task_one, "not_a_type", "Broken register", 999_013, 999_014, now_iso(), now_iso()),
        )
        db.conn.commit()
    finally:
        _set_foreign_keys(db, True)

    return {
        "task_one": task_one,
        "task_two": task_two,
        "broken_child": broken_child,
        "generated": generated,
    }


def test_collect_and_repair_integrity_report(tmp_path):
    db = Database(str(tmp_path / "tasks.sqlite3"))
    ids = _insert_issue_rows(db, tmp_path)

    report = db.collect_integrity_report(include_attachment_scan=True)

    assert report["schema_version"] == 5
    assert len(report["broken_parent_links"]) == 1
    assert len(report["invalid_sibling_sort_orders"]) == 2
    assert len(report["orphaned_custom_values"]["missing_tasks"]) == 1
    assert len(report["orphaned_custom_values"]["missing_columns"]) == 1
    assert len(report["malformed_recurrence"]["invalid_frequency_rules"]) == 1
    assert len(report["malformed_recurrence"]["task_rule_missing"]) == 1
    assert len(report["malformed_recurrence"]["generated_origin_missing"]) == 1
    assert len(report["project_management"]["broken_task_phase_refs"]) == 1
    assert len(report["project_management"]["broken_pm_dependencies"]) == 1
    assert len(report["project_management"]["malformed_milestones"]) == 1
    assert len(report["project_management"]["malformed_deliverables"]) == 1
    assert len(report["project_management"]["malformed_register_entries"]) == 1
    assert len(report["missing_file_attachments"]) == 1

    result = db.repair_integrity_issues(report=report)

    assert result["reset_broken_parent_links"] == 1
    assert result["normalized_sort_order_groups"] == 1
    assert result["deleted_orphaned_custom_values"] == 2
    assert result["deleted_invalid_recurrence_rules"] == 1
    assert result["cleared_invalid_task_recurrence_refs"] == 2
    assert result["cleared_invalid_generated_origins"] == 1
    assert result["cleared_invalid_task_phase_refs"] == 1
    assert result["deleted_invalid_pm_dependencies"] == 1
    assert result["repaired_invalid_milestones"] >= 1
    assert result["repaired_invalid_deliverables"] >= 1
    assert result["repaired_invalid_register_entries"] >= 1
    assert result["remaining_issue_count"] == 0

    post = db.collect_integrity_report(include_attachment_scan=False)
    assert post["broken_parent_links"] == []
    assert post["invalid_sibling_sort_orders"] == []
    assert post["orphaned_custom_values"]["missing_tasks"] == []
    assert post["orphaned_custom_values"]["missing_columns"] == []
    assert all(not rows for rows in post["malformed_recurrence"].values())
    assert all(not rows for rows in post["project_management"].values())

    broken_child = db.fetch_task_by_id(ids["broken_child"])
    assert broken_child is not None
    assert broken_child["parent_id"] is None

    top_level = [task for task in db.fetch_tasks() if task.get("parent_id") is None]
    assert [int(task["sort_order"]) for task in top_level] == [1, 2, 3, 4]
