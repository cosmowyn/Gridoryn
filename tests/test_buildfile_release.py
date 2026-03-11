from __future__ import annotations

import json
from pathlib import Path

import buildfile
from app_metadata import APP_NAME, APP_VERSION
from PySide6.QtGui import QImage


def test_stage_release_artifact_writes_manifest(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    source_artifact = dist_dir / f"{APP_NAME}.bin"
    source_artifact.write_text("artifact", encoding="utf-8")

    staged_artifact = buildfile._stage_release_artifact(source_artifact, dist_dir)
    manifest_path = dist_dir / "release_manifest.json"

    assert staged_artifact.exists()
    assert staged_artifact.parent == dist_dir / "release"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["app_name"] == APP_NAME
    assert manifest["app_version"] == APP_VERSION
    assert manifest["source_artifact"] == str(source_artifact)
    assert manifest["release_artifact"] == str(staged_artifact)


def test_stage_release_artifact_replaces_existing_copy(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    source_artifact = dist_dir / f"{APP_NAME}.bin"
    source_artifact.write_text("first", encoding="utf-8")

    first_target = buildfile._stage_release_artifact(source_artifact, dist_dir)
    assert first_target.read_text(encoding="utf-8") == "first"

    source_artifact.write_text("second", encoding="utf-8")
    second_target = buildfile._stage_release_artifact(source_artifact, dist_dir)

    assert first_target == second_target
    assert second_target.read_text(encoding="utf-8") == "second"


def test_resolve_build_python_prefers_active_virtualenv(monkeypatch, tmp_path: Path):
    active_python = tmp_path / "active-venv" / "Scripts" / "python.exe"
    active_python.parent.mkdir(parents=True)
    active_python.write_text("", encoding="utf-8")

    project_root = tmp_path / "project"
    project_root.mkdir()

    monkeypatch.delenv(buildfile.PYTHON_ENV_VAR, raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", str(active_python.parent.parent))
    monkeypatch.setattr(buildfile.sys, "executable", str(active_python))
    monkeypatch.setattr(buildfile.sys, "prefix", str(active_python.parent.parent))
    monkeypatch.setattr(buildfile.sys, "base_prefix", str(tmp_path / "python-base"))

    resolved = buildfile._resolve_build_python(project_root)
    assert resolved == active_python.resolve()


def test_resolve_icon_accepts_repo_root_icon_ico_on_windows(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    root_icon = project_root / "icon.ico"
    root_icon.write_bytes(b"ico")

    monkeypatch.delenv(buildfile.ICON_ENV_VAR, raising=False)
    monkeypatch.setattr(buildfile, "_is_windows", lambda: True)
    monkeypatch.setattr(buildfile, "_is_macos", lambda: False)

    resolved = buildfile._resolve_icon(project_root)
    assert resolved == str(root_icon)


def test_resolve_icon_converts_repo_root_png_to_ico_on_windows(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    png_icon = project_root / "icon.png"
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(0xFF3366CC)
    assert image.save(str(png_icon), "PNG")

    monkeypatch.delenv(buildfile.ICON_ENV_VAR, raising=False)
    monkeypatch.setattr(buildfile, "_is_windows", lambda: True)
    monkeypatch.setattr(buildfile, "_is_macos", lambda: False)

    resolved = Path(buildfile._resolve_icon(project_root))
    assert resolved.suffix.lower() == ".ico"
    assert resolved.exists()
    assert resolved.parent == project_root / "build_assets" / "icons"
