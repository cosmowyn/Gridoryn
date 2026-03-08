from __future__ import annotations

import json
from pathlib import Path

import buildfile
from app_metadata import APP_NAME, APP_VERSION


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
