from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QCoreApplication, Qt

from db import Database, now_iso
from model import TaskTreeModel
from project_intelligence import analyze_projects, analyze_workload


def test_analyze_projects_selects_next_action_and_ignores_blocked_children():
    today = date(2026, 3, 7)
    tasks = [
        {"id": 1, "description": "Project", "status": "Todo", "priority": 3, "archived_at": None, "last_update": "2026-03-06 09:00:00"},
        {
            "id": 2,
            "parent_id": 1,
            "description": "Ready next",
            "status": "Todo",
            "priority": 2,
            "due_date": "2026-03-08",
            "sort_order": 2,
            "archived_at": None,
            "last_update": "2026-03-06 09:00:00",
            "blocked_by_count": 0,
            "waiting_for": "",
            "planned_bucket": "upcoming",
        },
        {
            "id": 3,
            "parent_id": 1,
            "description": "Blocked child",
            "status": "Blocked",
            "priority": 1,
            "due_date": "2026-03-07",
            "sort_order": 1,
            "archived_at": None,
            "last_update": "2026-03-05 09:00:00",
            "blocked_by_count": 1,
            "waiting_for": "",
            "planned_bucket": "today",
        },
        {
            "id": 4,
            "parent_id": 1,
            "description": "Done child",
            "status": "Done",
            "priority": 3,
            "due_date": "2026-03-06",
            "sort_order": 3,
            "archived_at": None,
            "last_update": "2026-03-06 12:00:00",
            "blocked_by_count": 0,
            "waiting_for": "",
            "planned_bucket": "today",
        },
    ]

    rows = analyze_projects(tasks, stalled_days=14, today=today)

    assert len(rows) == 1
    row = rows[0]
    assert row["next_action_task_id"] == 2
    assert row["next_action_description"] == "Ready next"
    assert row["blocked"] is False
    assert row["blocked_child_count"] == 1
    assert row["child_open"] == 2
    assert row["state_label"] == "Ready"


def test_analyze_projects_reports_stalled_waiting_and_no_next_action():
    today = date(2026, 3, 7)
    tasks = [
        {"id": 10, "description": "Project", "status": "Todo", "priority": 3, "archived_at": None, "last_update": "2026-02-01 09:00:00"},
        {
            "id": 11,
            "parent_id": 10,
            "description": "Waiting child",
            "status": "Todo",
            "priority": 2,
            "due_date": "2026-03-10",
            "sort_order": 1,
            "archived_at": None,
            "last_update": "2026-02-10 09:00:00",
            "blocked_by_count": 0,
            "waiting_for": "Alex",
            "planned_bucket": "upcoming",
        },
        {
            "id": 12,
            "parent_id": 10,
            "description": "Someday child",
            "status": "Todo",
            "priority": 3,
            "due_date": None,
            "sort_order": 2,
            "archived_at": None,
            "last_update": "2026-02-12 09:00:00",
            "blocked_by_count": 0,
            "waiting_for": "",
            "planned_bucket": "someday",
        },
    ]

    row = analyze_projects(tasks, stalled_days=14, today=today)[0]

    assert row["next_action_task_id"] is None
    assert row["blocked"] is True
    assert row["waiting_child_count"] == 1
    assert row["oldest_waiting_days"] >= 25
    assert row["stalled"] is True
    assert "no actionable next child" in row["stalled_reasons"]
    assert "no progress for 23 days" in row["stalled_reasons"]
    assert row["state_label"] == "Stalled"


def test_analyze_workload_emits_warnings_and_scheduling_hints():
    today = date(2026, 3, 7)
    crowded_day = "2026-03-09"
    tasks = []
    for idx in range(1, 7):
        tasks.append(
            {
                "id": idx,
                "description": f"Task {idx}",
                "status": "Todo",
                "priority": 1 if idx <= 3 else 3,
                "due_date": crowded_day,
                "archived_at": None,
            }
        )
    tasks.extend(
        [
            {"id": 20, "description": "Overdue 1", "status": "Todo", "priority": 3, "due_date": "2026-03-01", "archived_at": None},
            {"id": 21, "description": "Overdue 2", "status": "Todo", "priority": 4, "due_date": "2026-03-02", "archived_at": None},
            {"id": 22, "description": "Overdue 3", "status": "Todo", "priority": 4, "due_date": "2026-03-03", "archived_at": None},
            {"id": 23, "description": "Overdue 4", "status": "Todo", "priority": 4, "due_date": "2026-03-04", "archived_at": None},
            {"id": 24, "description": "Overdue 5", "status": "Todo", "priority": 4, "due_date": "2026-03-05", "archived_at": None},
        ]
    )

    report = analyze_workload(tasks, today=today)
    warning_kinds = {row["kind"] for row in report["warnings"]}
    suggestion_kinds = {row["kind"] for row in report["suggestions"]}

    assert {"day_overload", "high_priority_cluster", "overdue_growth"} <= warning_kinds
    assert {"spread_day", "protect_priority_day", "reschedule_overdue"} <= suggestion_kinds
    assert report["busiest_days"][0]["due_date"] == crowded_day
    assert report["overdue_open"] == 5


def test_model_project_columns_refresh_after_child_waiting_change(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None

    db = Database(str(tmp_path / "project-intelligence.sqlite3"))
    project_id = db.insert_task({"description": "Project", "sort_order": 1, "last_update": now_iso()})
    child_id = db.insert_task(
        {
            "description": "Ready child",
            "parent_id": project_id,
            "sort_order": 1,
            "last_update": now_iso(),
            "due_date": (date.today() + timedelta(days=1)).isoformat(),
        }
    )
    model = TaskTreeModel(db)

    next_action_col = next(i for i in range(model.columnCount()) if model.column_key(i) == "next_action")
    state_col = next(i for i in range(model.columnCount()) if model.column_key(i) == "project_state")

    project_next_index = model.index(0, next_action_col)
    project_state_index = model.index(0, state_col)

    assert model.data(project_next_index, Qt.ItemDataRole.DisplayRole) == "Next: Ready child"
    assert model.data(project_state_index, Qt.ItemDataRole.DisplayRole) == "Ready"

    db.update_task_field(int(child_id), "waiting_for", "Alex")
    model._refresh_after_task_mutation([int(child_id)], reload=False)

    assert model.data(project_next_index, Qt.ItemDataRole.DisplayRole) == "Next: none"
    assert model.data(project_state_index, Qt.ItemDataRole.DisplayRole) == "Stalled"
