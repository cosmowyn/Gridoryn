from __future__ import annotations

from PySide6.QtCore import QSettings

from workspace_profiles import WorkspaceProfileManager


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
