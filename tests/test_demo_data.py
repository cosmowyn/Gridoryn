from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSettings

from db import Database
from demo_data import DEMO_WORKSPACE_NAME, build_demo_payload, create_demo_workspace, populate_demo_database
from workspace_profiles import WorkspaceProfileManager


def test_populate_demo_database_creates_rich_sample_data(tmp_path):
    db = Database(str(tmp_path / "demo.sqlite3"))
    summary = populate_demo_database(db, today=date(2026, 3, 7))

    assert summary["task_count"] >= 10
    assert summary["project_count"] >= 2
    assert summary["milestone_count"] >= 3
    assert summary["deliverable_count"] >= 1
    assert summary["register_count"] >= 4
    assert summary["archived_count"] >= 1
    assert summary["recurring_count"] >= 1
    assert summary["saved_view_count"] >= 3
    assert summary["template_count"] >= 1

    tasks = db.fetch_tasks()
    assert any(task.get("parent_id") is not None for task in tasks)
    assert any(str(task.get("waiting_for") or "").strip() for task in tasks)
    assert any(task.get("recurrence") for task in tasks)
    assert any(str(task.get("start_date") or "").strip() for task in tasks)
    assert any(task.get("phase_id") is not None for task in tasks)
    assert len(db.fetch_custom_columns()) >= 3
    assert len(db.list_project_profiles()) >= 2
    assert db.load_template("Demo: Meeting follow-up") is not None
    assert db.load_filter_view("Demo: Inbox triage") is not None


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
    assert len(payload["custom_columns"]) >= 3
    assert len(payload["tasks"]) >= 10
    assert payload["recurrence_rules"]
    assert payload["project_profiles"]
    assert payload["project_phases"]
    assert payload["milestones"]
    assert payload["deliverables"]
    assert payload["project_register_entries"]
    assert payload["project_baselines"]
    assert payload["pm_dependencies"]
    assert payload["saved_filter_views"]
    assert payload["templates"]
