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
