from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSettings

from db import Database
from demo_data import (
    DEMO_WORKSPACE_NAME,
    LAUNCH_PROJECT_NAME,
    PORTAL_PROJECT_NAME,
    build_demo_payload,
    create_demo_workspace,
    populate_demo_database,
)
from workspace_profiles import WorkspaceProfileManager


def test_populate_demo_database_creates_rich_sample_data(tmp_path):
    db = Database(str(tmp_path / "demo.sqlite3"))
    summary = populate_demo_database(db, today=date(2026, 3, 7))

    assert summary["task_count"] >= 80
    assert summary["project_count"] >= 4
    assert summary["milestone_count"] >= 15
    assert summary["deliverable_count"] >= 12
    assert summary["register_count"] >= 14
    assert summary["archived_count"] >= 1
    assert summary["recurring_count"] >= 4
    assert summary["saved_view_count"] >= 8
    assert summary["template_count"] >= 5
    assert summary["phase_count"] >= 24
    assert summary["pm_dependency_count"] >= 20
    assert summary["attachment_count"] >= 10
    assert summary["custom_column_count"] >= 5

    tasks = db.fetch_tasks()
    assert any(task.get("parent_id") is not None for task in tasks)
    assert any(str(task.get("waiting_for") or "").strip() for task in tasks)
    assert any(task.get("recurrence") for task in tasks)
    assert any(str(task.get("start_date") or "").strip() for task in tasks)
    assert any(task.get("phase_id") is not None for task in tasks)
    assert len(db.fetch_custom_columns()) >= 5
    assert len(db.list_project_profiles()) >= 4
    assert db.load_template("Demo: Meeting follow-up") is not None
    assert db.load_filter_view("Demo: Inbox triage") is not None

    task_map = {
        str(task.get("description") or ""): int(task["id"])
        for task in tasks
        if task.get("id") is not None
    }
    launch_dashboard = db.fetch_project_dashboard(task_map[LAUNCH_PROJECT_NAME])
    portal_dashboard = db.fetch_project_dashboard(task_map[PORTAL_PROJECT_NAME])

    assert len(launch_dashboard["timeline_rows"]) >= 40
    assert len(launch_dashboard["milestones"]) >= 6
    assert len(launch_dashboard["deliverables"]) >= 5
    assert len(launch_dashboard["register_entries"]) >= 6
    assert len(portal_dashboard["timeline_rows"]) >= 20
    assert len(portal_dashboard["milestones"]) >= 4
    assert len(portal_dashboard["deliverables"]) >= 4
    assert len(portal_dashboard["register_entries"]) >= 4


def test_create_demo_workspace_is_safe_and_recreatable(tmp_path):
    settings = QSettings(str(tmp_path / "demo_workspace.ini"), QSettings.Format.IniFormat)
    settings.clear()
    manager = WorkspaceProfileManager(settings=settings, base_dir=str(tmp_path))

    first = create_demo_workspace(manager, today=date(2026, 3, 7))
    second = create_demo_workspace(manager, today=date(2026, 3, 7))

    first_ws = first["workspace"]
    second_ws = second["workspace"]

    assert first_ws["name"] == DEMO_WORKSPACE_NAME
    assert second_ws["name"] == DEMO_WORKSPACE_NAME
    assert first_ws["id"] != second_ws["id"]
    assert first_ws["db_path"] != second_ws["db_path"]

    first_db = Database(str(first_ws["db_path"]))
    second_db = Database(str(second_ws["db_path"]))
    assert len(first_db.fetch_tasks()) == first["summary"]["task_count"]
    assert len(second_db.fetch_tasks()) == second["summary"]["task_count"]


def test_build_demo_payload_contains_expected_capabilities():
    payload = build_demo_payload(today=date(2026, 3, 7))

    assert payload["format_version"] == 3
    assert payload["schema_user_version"] == 5
    assert len(payload["custom_columns"]) >= 5
    assert len(payload["tasks"]) >= 80
    assert len(payload["recurrence_rules"]) >= 4
    assert len(payload["project_profiles"]) >= 4
    assert len(payload["project_phases"]) >= 24
    assert len(payload["milestones"]) >= 15
    assert len(payload["deliverables"]) >= 12
    assert len(payload["project_register_entries"]) >= 14
    assert len(payload["project_baselines"]) >= 4
    assert len(payload["pm_dependencies"]) >= 20
    assert len(payload["saved_filter_views"]) >= 8
    assert len(payload["templates"]) >= 5
