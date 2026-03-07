from __future__ import annotations

from auto_backup import create_versioned_backup
from db import Database
from demo_data import populate_demo_database
from diagnostics import build_diagnostics_report


def test_build_diagnostics_report_includes_workspace_and_snapshot(tmp_path):
    db = Database(str(tmp_path / "tasks.sqlite3"))
    populate_demo_database(db)
    snapshot = create_versioned_backup(db, reason="test")

    report = build_diagnostics_report(
        db,
        theme_name="Light",
        workspace_name="Demo",
        workspace_path=str(tmp_path),
    )

    assert report["schema_ok"] is True
    assert report["profile"] == "Demo"
    assert report["workspace_path"] == str(tmp_path)
    assert report["latest_snapshot"]["path"] == str(snapshot)
    assert report["items"]
