from __future__ import annotations

from db import Database


def test_saved_filter_views_roundtrip(tmp_path):
    db = Database(str(tmp_path / "views.sqlite3"))
    state = {
        "search_text": "tag:work due<today",
        "filter_panel": {"hide_done": True, "blocked_only": True},
        "perspective": "all",
        "sort_mode": "manual",
    }

    db.save_filter_view("My view", state, overwrite=True)
    assert db.load_filter_view("My view") == state

    views = db.list_saved_filter_views()
    assert any(view["name"] == "My view" for view in views)

    db.delete_filter_view("My view")
    assert db.load_filter_view("My view") is None
