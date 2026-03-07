from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app_paths import app_data_dir
from backup_io import export_payload, write_backup_file
from db import Database


def backups_dir(db_path: str | None = None) -> Path:
    if db_path and str(db_path) != ":memory:":
        base = Path(str(db_path)).expanduser().resolve().parent
    else:
        base = Path(app_data_dir())
    p = base / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_versioned_backup(db, reason: str = "auto") -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"task_snapshot_{ts}_{reason}.json"
    path = backups_dir(getattr(db, "path", None)) / filename
    payload = export_payload(db)
    write_backup_file(path, payload)
    return path


def create_versioned_backup_from_db_path(db_path: str, reason: str = "auto") -> Path:
    db = Database(str(db_path))
    try:
        return create_versioned_backup(db, reason=reason)
    finally:
        try:
            db.conn.close()
        except Exception:
            pass


def snapshot_file_metadata(path: Path) -> dict:
    metadata = {
        "task_count": None,
        "archived_count": None,
        "custom_column_count": None,
        "template_count": None,
        "saved_view_count": None,
        "exported_at": "",
    }
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        tasks = payload.get("tasks") or []
        metadata["task_count"] = len(tasks)
        metadata["archived_count"] = sum(1 for task in tasks if str(task.get("archived_at") or "").strip())
        metadata["custom_column_count"] = len(payload.get("custom_columns") or [])
        metadata["template_count"] = len(payload.get("templates") or [])
        metadata["saved_view_count"] = len(payload.get("saved_filter_views") or [])
        metadata["exported_at"] = str(payload.get("exported_at") or "")
    except Exception:
        pass
    return metadata


def list_restore_points(limit: int | None = None, db_path: str | None = None) -> list[dict]:
    points = []
    files = sorted(backups_dir(db_path).glob("task_snapshot_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None:
        files = files[: max(0, int(limit))]
    for path in files:
        stem = path.stem
        reason = "unknown"
        created_at = datetime.fromtimestamp(path.stat().st_mtime)
        parts = stem.split("_")
        if len(parts) >= 4:
            reason = parts[-1]
            ts = "_".join(parts[2:4])
            try:
                created_at = datetime.strptime(ts, "%Y%m%d_%H%M%S")
            except Exception:
                pass
        points.append(
            {
                "path": str(path),
                "filename": path.name,
                "reason": reason,
                "created_at": created_at.isoformat(sep=" ", timespec="seconds"),
                "size_bytes": int(path.stat().st_size),
            }
        )
        points[-1].update(snapshot_file_metadata(path))
    return points


def last_restore_point(db_path: str | None = None) -> dict | None:
    points = list_restore_points(limit=1, db_path=db_path)
    return points[0] if points else None


def rotate_backups(max_keep: int = 20, db_path: str | None = None):
    keep = max(1, int(max_keep))
    files = sorted(backups_dir(db_path).glob("task_snapshot_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink(missing_ok=True)
        except Exception:
            continue
