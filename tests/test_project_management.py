from __future__ import annotations

from datetime import date, timedelta

import pytest
from PySide6.QtCore import Qt

from db import Database, now_iso
from model import TaskTreeModel
from project_management import compute_baseline_variance, compute_personal_capacity
from template_params import apply_template_values, collect_template_placeholders


def _seed_project(db: Database):
    today = date(2026, 3, 8)
    project_id = db.insert_task(
        {
            "description": "Project Alpha",
            "due_date": (today + timedelta(days=8)).isoformat(),
            "last_update": now_iso(),
            "priority": 2,
            "status": "In Progress",
            "sort_order": 1,
        }
    )
    task_one = db.insert_task(
        {
            "description": "Draft specification",
            "parent_id": project_id,
            "start_date": today.isoformat(),
            "due_date": (today + timedelta(days=2)).isoformat(),
            "last_update": now_iso(),
            "priority": 1,
            "status": "In Progress",
            "sort_order": 1,
            "effort_minutes": 180,
            "actual_minutes": 60,
        }
    )
    task_two = db.insert_task(
        {
            "description": "Publish release",
            "parent_id": project_id,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "due_date": (today + timedelta(days=6)).isoformat(),
            "last_update": now_iso(),
            "priority": 2,
            "status": "Todo",
            "sort_order": 2,
            "effort_minutes": 240,
            "actual_minutes": 0,
        }
    )
    return today, project_id, task_one, task_two


def test_project_management_crud_dashboard_and_lifecycle(tmp_path):
    db = Database(str(tmp_path / "pm.sqlite3"))
    today, project_id, task_one, task_two = _seed_project(db)

    profile = db.save_project_profile(
        project_id,
        {
            "objective": "Ship a release with controlled scope.",
            "scope": "Specification, release task, and final package.",
            "out_of_scope": "Post-launch marketing.",
            "owner": "Self",
            "stakeholders": "Operations, Marketing",
            "target_date": (today + timedelta(days=8)).isoformat(),
            "success_criteria": "Release package published successfully.",
            "project_status_health": "at_risk",
            "summary": "Demo project for PM feature coverage.",
            "category": "Product",
        },
    )
    assert profile["owner"] == "Self"

    phases = db.fetch_project_phases(project_id)
    planning_phase = next(row for row in phases if row["name"] == "Planning")
    execution_phase = next(row for row in phases if row["name"] == "Execution")
    db.set_task_phase(task_one, int(planning_phase["id"]))
    db.set_task_phase(task_two, int(execution_phase["id"]))

    milestone_id = db.upsert_milestone(
        {
            "project_task_id": project_id,
            "title": "Specification approved",
            "description": "Approval gate for the project specification.",
            "phase_id": int(planning_phase["id"]),
            "linked_task_id": task_one,
            "start_date": today.isoformat(),
            "target_date": (today + timedelta(days=3)).isoformat(),
            "baseline_target_date": (today + timedelta(days=2)).isoformat(),
            "status": "in_progress",
            "progress_percent": 50,
            "completed_at": None,
            "dependencies": [{"kind": "task", "id": task_one}],
        }
    )
    milestone = db.fetch_milestone_by_id(milestone_id)
    assert milestone is not None
    assert len(milestone["dependencies"]) == 1

    deliverable_id = db.upsert_deliverable(
        {
            "project_task_id": project_id,
            "title": "Release package",
            "description": "Final release artifact bundle.",
            "phase_id": int(execution_phase["id"]),
            "linked_task_id": task_two,
            "linked_milestone_id": milestone_id,
            "due_date": (today + timedelta(days=6)).isoformat(),
            "baseline_due_date": (today + timedelta(days=5)).isoformat(),
            "acceptance_criteria": "Artifacts verified and signed off.",
            "version_ref": "v1.0.0",
            "status": "planned",
            "completed_at": None,
        }
    )
    entry_id = db.upsert_project_register_entry(
        {
            "project_task_id": project_id,
            "entry_type": "risk",
            "title": "Approval may slip",
            "details": "Specification review could delay the release.",
            "status": "open",
            "severity": 4,
            "review_date": (today + timedelta(days=1)).isoformat(),
            "linked_task_id": task_two,
            "linked_milestone_id": milestone_id,
        }
    )
    db.save_project_baseline(project_id, (today + timedelta(days=7)).isoformat(), 360)

    dashboard = db.fetch_project_dashboard(project_id)
    assert dashboard is not None
    assert dashboard["summary"]["manual_health"] == "at_risk"
    assert dashboard["summary"]["effective_health"] == "at_risk"
    assert dashboard["summary"]["milestone_open_count"] == 1
    assert dashboard["summary"]["deliverable_open_count"] == 1
    assert dashboard["summary"]["target_variance"]["direction"] == "late"
    assert dashboard["summary"]["baseline_effort_minutes"] == 360
    assert {row["kind"] for row in dashboard["timeline_rows"]} >= {
        "project",
        "phase",
        "task",
        "milestone",
        "deliverable",
    }
    assert any(bool(row.get("summary_row")) for row in dashboard["timeline_rows"])
    milestone_row = next(
        row for row in dashboard["timeline_rows"] if row["kind"] == "milestone"
    )
    assert milestone_row["dependencies"]

    updated_milestone_id = db.upsert_milestone(
        {
            "id": milestone_id,
            "project_task_id": project_id,
            "title": "Specification approved",
            "description": "Approval gate for the project specification.",
            "phase_id": int(planning_phase["id"]),
            "linked_task_id": task_one,
            "start_date": today.isoformat(),
            "target_date": (today + timedelta(days=3)).isoformat(),
            "baseline_target_date": (today + timedelta(days=2)).isoformat(),
            "status": "completed",
            "progress_percent": 100,
            "completed_at": today.isoformat(),
            "dependencies": [{"kind": "task", "id": task_one}],
        }
    )
    assert updated_milestone_id == milestone_id
    assert db.fetch_milestone_by_id(milestone_id)["status"] == "completed"

    db.delete_project_register_entry(entry_id)
    db.delete_deliverable(deliverable_id)
    db.delete_milestone(milestone_id)
    assert db.fetch_register_entry_by_id(entry_id) is None
    assert db.fetch_deliverable_by_id(deliverable_id) is None
    assert db.fetch_milestone_by_id(milestone_id) is None


def test_project_management_validation_blocks_cross_project_links_and_cycles(tmp_path):
    db = Database(str(tmp_path / "pm_validation.sqlite3"))
    today = date(2026, 3, 8)

    project_a = db.insert_task(
        {"description": "Project A", "due_date": (today + timedelta(days=5)).isoformat(), "last_update": now_iso(), "sort_order": 1}
    )
    task_a = db.insert_task(
        {"description": "Task A", "parent_id": project_a, "last_update": now_iso(), "sort_order": 1}
    )
    project_b = db.insert_task(
        {"description": "Project B", "due_date": (today + timedelta(days=9)).isoformat(), "last_update": now_iso(), "sort_order": 2}
    )
    task_b = db.insert_task(
        {"description": "Task B", "parent_id": project_b, "last_update": now_iso(), "sort_order": 1}
    )

    phase_a = int(next(row for row in db.fetch_project_phases(project_a) if row["name"] == "Planning")["id"])
    phase_b = int(next(row for row in db.fetch_project_phases(project_b) if row["name"] == "Planning")["id"])

    with pytest.raises(ValueError):
        db.set_task_phase(task_a, phase_b)

    milestone_a1 = db.upsert_milestone(
        {
            "project_task_id": project_a,
            "title": "Milestone A1",
            "phase_id": phase_a,
            "linked_task_id": task_a,
            "target_date": (today + timedelta(days=2)).isoformat(),
            "status": "planned",
            "progress_percent": 0,
            "dependencies": [],
        }
    )
    milestone_a2 = db.upsert_milestone(
        {
            "project_task_id": project_a,
            "title": "Milestone A2",
            "phase_id": phase_a,
            "linked_task_id": task_a,
            "target_date": (today + timedelta(days=3)).isoformat(),
            "status": "planned",
            "progress_percent": 0,
            "dependencies": [{"kind": "milestone", "id": milestone_a1}],
        }
    )

    with pytest.raises(ValueError):
        db.set_milestone_dependencies(milestone_a1, [{"kind": "milestone", "id": milestone_a2}])

    db.set_task_dependencies(task_a, [])
    db.set_task_dependencies(task_b, [task_a])
    with pytest.raises(ValueError):
        db.set_task_dependencies(task_a, [task_b])

    with pytest.raises(ValueError):
        db.upsert_deliverable(
            {
                "project_task_id": project_a,
                "title": "Cross project deliverable",
                "phase_id": phase_a,
                "linked_task_id": task_b,
                "linked_milestone_id": None,
                "due_date": (today + timedelta(days=4)).isoformat(),
                "status": "planned",
            }
        )

    with pytest.raises(ValueError):
        db.upsert_project_register_entry(
            {
                "project_task_id": project_a,
                "entry_type": "issue",
                "title": "Cross project register entry",
                "status": "open",
                "linked_task_id": task_b,
                "linked_milestone_id": None,
            }
        )


def test_task_phase_assignment_is_undoable(tmp_path, qapp):
    db = Database(str(tmp_path / "pm_phase_undo.sqlite3"))
    _today, project_id, task_one, _task_two = _seed_project(db)
    model = TaskTreeModel(db)

    planning_phase = next(
        row for row in db.fetch_project_phases(project_id) if row["name"] == "Planning"
    )
    phase_id = int(planning_phase["id"])

    model.set_task_phase(task_one, phase_id)
    assert db.fetch_task_by_id(task_one)["phase_id"] == phase_id

    model.undo_stack.undo()
    assert db.fetch_task_by_id(task_one)["phase_id"] is None

    model.undo_stack.redo()
    assert db.fetch_task_by_id(task_one)["phase_id"] == phase_id


def test_project_management_capacity_and_variance_helpers():
    today = date(2026, 3, 8)
    tasks = [
        {
            "id": index,
            "status": "Todo",
            "archived_at": None,
            "due_date": today.isoformat(),
            "priority": 1 if index < 4 else 3,
            "effort_minutes": 90,
        }
        for index in range(1, 8)
    ]
    capacity = compute_personal_capacity(tasks, today=today)
    assert capacity["warnings"]
    assert any(row["overcommitted"] for row in capacity["days"])

    variance = compute_baseline_variance("2026-03-12", "2026-03-10")
    assert variance["direction"] == "late"
    assert variance["days"] == 2


def test_project_health_column_and_pm_review_categories(tmp_path, qapp):
    db = Database(str(tmp_path / "pm_review.sqlite3"))
    today, project_id, task_one, task_two = _seed_project(db)

    db.save_project_profile(
        project_id,
        {
            "objective": "Ship project alpha cleanly.",
            "project_status_health": "delayed",
            "target_date": (today + timedelta(days=8)).isoformat(),
        },
    )
    phases = db.fetch_project_phases(project_id)
    planning_phase = next(row for row in phases if row["name"] == "Planning")
    execution_phase = next(row for row in phases if row["name"] == "Execution")

    db.upsert_milestone(
        {
            "project_task_id": project_id,
            "title": "Approval gate",
            "phase_id": int(planning_phase["id"]),
            "linked_task_id": task_one,
            "target_date": (today - timedelta(days=1)).isoformat(),
            "status": "planned",
            "progress_percent": 0,
            "dependencies": [],
        }
    )
    db.upsert_deliverable(
        {
            "project_task_id": project_id,
            "title": "Release note bundle",
            "phase_id": int(execution_phase["id"]),
            "linked_task_id": task_two,
            "due_date": (today + timedelta(days=3)).isoformat(),
            "status": "planned",
        }
    )
    db.upsert_project_register_entry(
        {
            "project_task_id": project_id,
            "entry_type": "risk",
            "title": "External approval dependency",
            "status": "open",
            "severity": 5,
            "review_date": (today + timedelta(days=1)).isoformat(),
            "linked_task_id": task_one,
        }
    )

    model = TaskTreeModel(db)
    health_col = next(
        index
        for index in range(model.columnCount())
        if model.column_key(index) == "project_health"
    )
    health_index = model.index(0, health_col)
    assert model.data(health_index, Qt.ItemDataRole.DisplayRole) == "Delayed"
    assert model.data(health_index, Qt.ItemDataRole.BackgroundRole) is not None

    review_data = db.fetch_review_data()
    assert review_data["overdue_milestones"]
    assert review_data["deliverables_due_soon"]
    assert review_data["high_risk_registers"]
    assert review_data["overdue_milestones"][0]["review_key"].startswith("milestone:")
    assert review_data["deliverables_due_soon"][0]["review_focus_id"] == task_two
    assert review_data["high_risk_registers"][0]["review_key"].startswith("register:")


def test_timeline_reschedule_for_milestone_and_deliverable_is_undoable(tmp_path, qapp):
    db = Database(str(tmp_path / "pm_timeline_undo.sqlite3"))
    today, project_id, task_one, task_two = _seed_project(db)
    phases = db.fetch_project_phases(project_id)
    planning_phase = next(row for row in phases if row["name"] == "Planning")
    execution_phase = next(row for row in phases if row["name"] == "Execution")

    milestone_id = db.upsert_milestone(
        {
            "project_task_id": project_id,
            "title": "Specification approved",
            "phase_id": int(planning_phase["id"]),
            "linked_task_id": task_one,
            "start_date": today.isoformat(),
            "target_date": (today + timedelta(days=2)).isoformat(),
            "status": "planned",
            "progress_percent": 0,
            "dependencies": [],
        }
    )
    deliverable_id = db.upsert_deliverable(
        {
            "project_task_id": project_id,
            "title": "Release package",
            "phase_id": int(execution_phase["id"]),
            "linked_task_id": task_two,
            "due_date": (today + timedelta(days=5)).isoformat(),
            "status": "planned",
        }
    )

    model = TaskTreeModel(db)
    model.set_milestone_dates(
        milestone_id,
        (today + timedelta(days=1)).isoformat(),
        (today + timedelta(days=3)).isoformat(),
    )
    changed_milestone = db.fetch_milestone_by_id(milestone_id)
    assert changed_milestone["start_date"] == (today + timedelta(days=1)).isoformat()
    assert changed_milestone["target_date"] == (today + timedelta(days=3)).isoformat()

    model.undo_stack.undo()
    original_milestone = db.fetch_milestone_by_id(milestone_id)
    assert original_milestone["start_date"] == today.isoformat()
    assert original_milestone["target_date"] == (today + timedelta(days=2)).isoformat()

    model.undo_stack.redo()
    redone_milestone = db.fetch_milestone_by_id(milestone_id)
    assert redone_milestone["start_date"] == (today + timedelta(days=1)).isoformat()
    assert redone_milestone["target_date"] == (today + timedelta(days=3)).isoformat()

    model.set_deliverable_due_date(
        deliverable_id,
        (today + timedelta(days=7)).isoformat(),
    )
    changed_deliverable = db.fetch_deliverable_by_id(deliverable_id)
    assert changed_deliverable["due_date"] == (today + timedelta(days=7)).isoformat()

    model.undo_stack.undo()
    original_deliverable = db.fetch_deliverable_by_id(deliverable_id)
    assert original_deliverable["due_date"] == (today + timedelta(days=5)).isoformat()

    model.undo_stack.redo()
    redone_deliverable = db.fetch_deliverable_by_id(deliverable_id)
    assert redone_deliverable["due_date"] == (today + timedelta(days=7)).isoformat()


def test_project_root_template_roundtrip_preserves_project_state(tmp_path, qapp):
    db = Database(str(tmp_path / "pm_template.sqlite3"))
    today, project_id, task_one, task_two = _seed_project(db)

    db.save_project_profile(
        project_id,
        {
            "objective": "Launch {project_name}",
            "scope": "Specification and release package.",
            "out_of_scope": "Post-launch work.",
            "owner": "{owner}",
            "stakeholders": "Operations",
            "target_date": (today + timedelta(days=8)).isoformat(),
            "success_criteria": "Release ships successfully.",
            "project_status_health": "at_risk",
            "summary": "Template coverage",
            "category": "Product",
        },
    )
    phases = db.fetch_project_phases(project_id)
    planning_phase = next(row for row in phases if row["name"] == "Planning")
    execution_phase = next(row for row in phases if row["name"] == "Execution")
    db.set_task_phase(task_one, int(planning_phase["id"]))
    db.set_task_phase(task_two, int(execution_phase["id"]))
    db.set_task_dependencies(task_two, [task_one])
    db.set_project_phase_gantt_color(int(planning_phase["id"]), "#552277")
    db.set_task_gantt_color(project_id, "#223344")
    db.set_task_gantt_color(task_one, "#446688")

    milestone_id = db.upsert_milestone(
        {
            "project_task_id": project_id,
            "title": "Specification approved",
            "description": "Approval gate",
            "phase_id": int(planning_phase["id"]),
            "linked_task_id": task_one,
            "start_date": today.isoformat(),
            "target_date": (today + timedelta(days=2)).isoformat(),
            "baseline_target_date": (today + timedelta(days=1)).isoformat(),
            "status": "in_progress",
            "progress_percent": 50,
            "gantt_color_hex": "#AA5500",
            "dependencies": [{"kind": "task", "id": task_one}],
        }
    )
    db.upsert_deliverable(
        {
            "project_task_id": project_id,
            "title": "Release package",
            "description": "Final bundle",
            "phase_id": int(execution_phase["id"]),
            "linked_task_id": task_two,
            "linked_milestone_id": milestone_id,
            "due_date": (today + timedelta(days=6)).isoformat(),
            "baseline_due_date": (today + timedelta(days=5)).isoformat(),
            "acceptance_criteria": "Bundle verified",
            "version_ref": "v2.0.0",
            "status": "planned",
            "gantt_color_hex": "#116655",
        }
    )
    db.upsert_project_register_entry(
        {
            "project_task_id": project_id,
            "entry_type": "risk",
            "title": "Approval delay",
            "details": "Approval may slip.",
            "status": "open",
            "severity": 4,
            "review_date": (today + timedelta(days=1)).isoformat(),
            "linked_task_id": task_two,
            "linked_milestone_id": milestone_id,
        }
    )
    db.save_project_baseline(project_id, (today + timedelta(days=7)).isoformat(), 360)

    model = TaskTreeModel(db)
    model.save_template_from_task("Project Template", project_id)
    payload = model.load_template_payload("Project Template")
    assert payload is not None
    assert "project_template" in payload
    assert all(task.get("phase_id") is None for task in payload["tasks"])

    placeholders = collect_template_placeholders(payload)
    assert {"project_name", "owner"} <= set(placeholders)

    resolved_payload = apply_template_values(
        payload,
        {"project_name": "Gridoryn Release", "owner": "Alice"},
    )
    new_root_id = model.create_tasks_from_template_payload(resolved_payload)
    assert new_root_id is not None

    new_dashboard = db.fetch_project_dashboard(int(new_root_id))
    assert new_dashboard is not None
    assert new_dashboard["profile"]["objective"] == "Launch Gridoryn Release"
    assert new_dashboard["profile"]["owner"] == "Alice"
    assert new_dashboard["baseline"]["effort_minutes"] == 360
    assert str(new_dashboard["project"].get("gantt_color_hex") or "").lower() == "#223344"
    new_phases = {str(row["name"]): row for row in new_dashboard["phases"]}
    assert str(new_phases["Planning"].get("gantt_color_hex") or "").lower() == "#552277"

    new_tasks = {
        str(row["description"]): row
        for row in new_dashboard["tasks"]
    }
    assert {"Draft specification", "Publish release"} <= set(new_tasks)
    assert new_tasks["Draft specification"]["phase_id"] is not None
    assert new_tasks["Publish release"]["phase_id"] is not None
    assert str(new_tasks["Draft specification"].get("gantt_color_hex") or "").lower() == "#446688"
    publish_deps = db.fetch_dependencies(int(new_tasks["Publish release"]["id"]))
    assert [int(row["id"]) for row in publish_deps] == [int(new_tasks["Draft specification"]["id"])]

    new_milestones = db.fetch_project_milestones(int(new_root_id))
    assert len(new_milestones) == 1
    new_milestone = new_milestones[0]
    assert str(new_milestone.get("gantt_color_hex") or "").lower() == "#aa5500"
    assert int(new_milestone["linked_task_id"]) == int(new_tasks["Draft specification"]["id"])
    assert len(new_milestone["dependencies"]) == 1
    assert int(new_milestone["dependencies"][0]["id"]) == int(new_tasks["Draft specification"]["id"])

    new_deliverables = db.fetch_project_deliverables(int(new_root_id))
    assert len(new_deliverables) == 1
    assert str(new_deliverables[0].get("gantt_color_hex") or "").lower() == "#116655"
    assert int(new_deliverables[0]["linked_task_id"]) == int(new_tasks["Publish release"]["id"])
    assert int(new_deliverables[0]["linked_milestone_id"]) == int(new_milestone["id"])

    new_register_entries = db.fetch_project_register_entries(int(new_root_id))
    assert len(new_register_entries) == 1
    assert int(new_register_entries[0]["linked_task_id"]) == int(new_tasks["Publish release"]["id"])
    assert int(new_register_entries[0]["linked_milestone_id"]) == int(new_milestone["id"])

    model.undo_stack.undo()
    assert db.fetch_task_by_id(int(new_root_id)) is None
    assert db.fetch_project_profile(int(new_root_id)) is None

    model.undo_stack.redo()
    assert db.fetch_task_by_id(int(new_root_id)) is not None
    assert db.fetch_project_profile(int(new_root_id)) is not None


def test_subtree_template_inside_project_stays_plain_task_template(tmp_path, qapp):
    db = Database(str(tmp_path / "pm_subtree_template.sqlite3"))
    today, project_id, task_one, task_two = _seed_project(db)
    db.save_project_profile(
        project_id,
        {
            "objective": "Project root profile",
            "target_date": (today + timedelta(days=8)).isoformat(),
        },
    )
    planning_phase = next(row for row in db.fetch_project_phases(project_id) if row["name"] == "Planning")
    db.set_task_phase(task_one, int(planning_phase["id"]))
    db.set_task_dependencies(task_two, [task_one])
    db.set_task_gantt_color(task_one, "#778899")

    model = TaskTreeModel(db)
    model.save_template_from_task("Child Template", task_one)
    payload = model.load_template_payload("Child Template")
    assert payload is not None
    assert "project_template" not in payload
    assert all(task.get("phase_id") is None for task in payload["tasks"])

    new_root_id = model.create_tasks_from_template_payload(payload)
    assert new_root_id is not None
    new_task = db.fetch_task_by_id(int(new_root_id))
    assert new_task is not None
    assert new_task["phase_id"] is None
    assert str(new_task.get("gantt_color_hex") or "").lower() == "#778899"
    assert db.fetch_project_profile(int(new_root_id)) is None


def test_archived_project_root_disappears_from_project_candidates(tmp_path):
    db = Database(str(tmp_path / "pm_archive_root.sqlite3"))
    today, project_id, task_one, _task_two = _seed_project(db)
    db.save_project_profile(
        project_id,
        {
            "objective": "Archive coverage",
            "target_date": (today + timedelta(days=8)).isoformat(),
        },
    )
    db.archive_task(project_id)

    assert project_id not in {
        int(row.get("id") or 0) for row in db.list_project_candidates()
    }
    assert project_id not in {
        int(row.get("task_id") or 0) for row in db.list_project_profiles()
    }
    assert db.fetch_project_dashboard(project_id) is None
    archived_child = db.fetch_task_by_id(task_one)
    assert archived_child is not None
    assert str(archived_child.get("archived_at") or "").strip()
