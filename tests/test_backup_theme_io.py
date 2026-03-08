from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

import theme_io
from backup_io import BackupError, export_payload, import_payload, import_payload_into_dbfile, read_backup_file, write_backup_file
from db import Database
from demo_data import populate_demo_database


def _ini_settings(path) -> QSettings:
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.clear()
    return settings


def test_backup_import_roundtrip_and_replace(tmp_path, monkeypatch):
    source = Database(str(tmp_path / "source.sqlite3"))
    populate_demo_database(source)
    payload = export_payload(source)
    source_projects = source.list_project_profiles()
    source_project_ids = [int(row["task_id"]) for row in source_projects]

    target = Database(str(tmp_path / "target.sqlite3"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    report = import_payload(None, payload, target)

    assert report.mode == "replace"
    assert len(target.fetch_tasks()) == len(source.fetch_tasks())
    assert len(target.fetch_custom_columns()) == len(source.fetch_custom_columns())
    assert len(target.list_saved_filter_views()) == len(source.list_saved_filter_views())
    assert len(target.list_templates()) == len(source.list_templates())
    assert len(target.list_project_profiles()) == len(source_projects)
    assert (
        sum(len(target.fetch_project_milestones(project_id)) for project_id in source_project_ids)
        == sum(len(source.fetch_project_milestones(project_id)) for project_id in source_project_ids)
    )
    assert (
        sum(len(target.fetch_project_deliverables(project_id)) for project_id in source_project_ids)
        == sum(len(source.fetch_project_deliverables(project_id)) for project_id in source_project_ids)
    )
    assert (
        sum(len(target.fetch_project_register_entries(project_id)) for project_id in source_project_ids)
        == sum(len(source.fetch_project_register_entries(project_id)) for project_id in source_project_ids)
    )


def test_backup_import_merge_and_missing_custom_columns(tmp_path, monkeypatch):
    source = Database(str(tmp_path / "source.sqlite3"))
    populate_demo_database(source)
    payload = export_payload(source)

    target = Database(str(tmp_path / "target.sqlite3"))
    target.insert_task({"description": "Existing task", "sort_order": 1})

    answers = iter(
        [
            QMessageBox.StandardButton.Yes,  # create missing custom columns
            QMessageBox.StandardButton.No,   # merge instead of replace
        ]
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: next(answers))
    report = import_payload(None, payload, target)

    descriptions = {row["description"] for row in target.fetch_tasks()}
    assert report.mode == "merge"
    assert "Existing task" in descriptions
    assert "Demo: Website relaunch" in descriptions

    blank_target = Database(str(tmp_path / "target_blank.sqlite3"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    skipped_report = import_payload(None, payload, blank_target)
    assert skipped_report.skipped_columns >= 1
    assert blank_target.fetch_custom_columns() == []


def test_backup_checksum_and_failed_import_cleanup(tmp_path):
    db = Database(str(tmp_path / "source.sqlite3"))
    populate_demo_database(db)
    payload = export_payload(db)
    backup_path = tmp_path / "demo_backup.json"
    write_backup_file(backup_path, payload)

    tampered = json.loads(backup_path.read_text(encoding="utf-8"))
    tampered["checksum_sha256"] = "not-the-real-checksum"
    backup_path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(BackupError):
        read_backup_file(backup_path, parent=None)

    broken_target = tmp_path / "broken.sqlite3"
    with pytest.raises(BackupError):
        import_payload_into_dbfile(
            parent=None,
            payload={"format_version": 2, "custom_columns": []},
            target_db_path=broken_target,
            make_file_backup=True,
        )
    assert not broken_target.exists()


def test_theme_export_import_keep_both_conflict(tmp_path, monkeypatch):
    source_settings = _ini_settings(tmp_path / "source.ini")
    source_settings.setValue("themes/list", ["Light"])
    source_settings.setValue("themes/current", "Light")
    source_settings.setValue("themes/data/Light", json.dumps({"name": "Light", "colors": {"bg": "#ffffff"}}))

    payload = theme_io.export_themes_payload(source_settings)

    target_settings = _ini_settings(tmp_path / "target.ini")
    target_settings.setValue("themes/list", ["Light"])
    target_settings.setValue("themes/current", "Light")
    target_settings.setValue("themes/data/Light", json.dumps({"name": "Light", "colors": {"bg": "#000000"}}))

    monkeypatch.setattr(theme_io, "_prompt_conflict_mode", lambda *args, **kwargs: "keep_both")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    report = theme_io.import_themes_payload(None, target_settings, payload)
    names = set(target_settings.value("themes/list"))

    assert report["renamed"] == 1
    assert "Light" in names
    assert any(name.startswith("Light (imported") for name in names)
