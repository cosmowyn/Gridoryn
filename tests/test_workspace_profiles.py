from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from workspace_profiles import WorkspaceProfileError, WorkspaceProfileManager


def test_workspace_profiles_restore_isolated_state(tmp_path):
    settings = QSettings(str(tmp_path / "workspace_settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    settings.setValue("ui/perspective", "today")
    settings.setValue("ui/reminder_mode", "normal")
    settings.setValue("themes/current", "Light")
    settings.setValue("themes/list", ["Light", "Dark"])
    settings.setValue("themes/data/Light", "{}")

    manager = WorkspaceProfileManager(settings=settings, base_dir=str(tmp_path))
    manager.save_state_for("default")

    work = manager.create_workspace("Work")
    work_id = str(work["id"])

    settings.setValue("ui/perspective", "someday")
    settings.setValue("ui/reminder_mode", "mute_all")
    manager.save_state_for(work_id)

    manager.restore_state_for("default")
    assert settings.value("ui/perspective") == "today"
    assert settings.value("ui/reminder_mode") == "normal"
    assert settings.value("themes/current") == "Light"

    manager.restore_state_for(work_id)
    assert settings.value("ui/perspective") == "someday"
    assert settings.value("ui/reminder_mode") == "mute_all"
    assert settings.value("themes/data/Light") == "{}"


def test_workspace_profiles_can_register_existing_database(tmp_path):
    settings = QSettings(str(tmp_path / "workspace_settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    manager = WorkspaceProfileManager(settings=settings, base_dir=str(tmp_path))

    db_path = tmp_path / "client.sqlite3"
    row = manager.create_workspace("Client Project", db_path=str(db_path))

    assert row["name"] == "Client Project"
    assert row["db_path"] == str(db_path.resolve())
    assert any(item["id"] == row["id"] for item in manager.list_workspaces())


def test_workspace_profiles_can_remove_profile_and_database_file(tmp_path):
    settings = QSettings(str(tmp_path / "workspace_settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    manager = WorkspaceProfileManager(settings=settings, base_dir=str(tmp_path))

    db_path = tmp_path / "work.sqlite3"
    db_path.write_text("demo", encoding="utf-8")
    row = manager.create_workspace("Work", db_path=str(db_path))

    plan = manager.workspace_removal_plan(str(row["id"]))
    assert plan["can_remove"] is True
    assert plan["can_delete_db_file"] is True

    report = manager.remove_workspace(str(row["id"]), delete_db_file=True)

    assert report["deleted_db_file"] is True
    assert not db_path.exists()
    assert manager.workspace_by_id(str(row["id"])) is None


def test_workspace_profiles_do_not_delete_shared_database_files(tmp_path):
    settings = QSettings(str(tmp_path / "workspace_settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    manager = WorkspaceProfileManager(settings=settings, base_dir=str(tmp_path))

    db_path = tmp_path / "shared.sqlite3"
    db_path.write_text("demo", encoding="utf-8")
    row_a = manager.create_workspace("Shared A", db_path=str(db_path))
    row_b = manager.create_workspace("Shared B", db_path=str(db_path))

    plan = manager.workspace_removal_plan(str(row_a["id"]))
    assert plan["can_remove"] is True
    assert plan["can_delete_db_file"] is False

    with pytest.raises(WorkspaceProfileError):
        manager.remove_workspace(str(row_a["id"]), delete_db_file=True)

    manager.remove_workspace(str(row_b["id"]), delete_db_file=False)
    assert db_path.exists()
