from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import buildfile
from app_metadata import APP_NAME, APP_LOG_SLUG, APP_STORAGE_NAME
from demo_data import build_demo_payload


def test_release_metadata_uses_stable_product_name():
    assert APP_NAME == "CustomToDo"
    assert APP_STORAGE_NAME == "CustomTaskManager"
    assert APP_LOG_SLUG == "customtodo"
    assert buildfile.APP_NAME == APP_NAME
    assert buildfile._release_basename().startswith("CustomToDo-1.0.0-")


def test_demo_payload_uses_fictionalized_owner_data():
    payload = build_demo_payload(today=date(2026, 3, 7))
    text = json.dumps(payload, sort_keys=True)
    assert "Mervyn" not in text
    assert "van de Kleut" not in text
    assert "Jordan Vale" in text
    assert "/Users/" not in text


def test_release_docs_and_spec_match_product_name():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert readme.startswith("# CustomToDo")
    assert "<your-repo-url>" not in readme
    assert "https://github.com/cosmowyn/CustomToDo.git" in readme
    assert "CustomToDo.spec" in readme
    assert Path("CustomToDo.spec").exists()


def test_release_checklist_uses_repo_relative_links():
    checklist = Path("docs/release-checklist.md").read_text(encoding="utf-8")
    assert "/Users/" not in checklist
    assert "[app_metadata.py](../app_metadata.py)" in checklist
    assert "[CHANGELOG.md](../CHANGELOG.md)" in checklist
    assert "[README.md](../README.md)" in checklist
