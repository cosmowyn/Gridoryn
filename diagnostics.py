from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app_metadata import APP_NAME, APP_PROFILE, APP_VERSION
from app_paths import app_data_dir
from auto_backup import backups_dir, last_restore_point, list_restore_points
from crash_logging import logs_dir


@dataclass
class DiagnosticItem:
    status: str
    label: str
    message: str
    details: str = ""


def _status_for_count(count: int) -> str:
    return "ok" if int(count or 0) == 0 else "warning"


def build_diagnostics_report(db, theme_name: str, workspace_name: str = "", workspace_path: str = "") -> dict:
    integrity = db.collect_integrity_report(include_attachment_scan=True)
    schema = db.schema_validation_report()
    restore_points = list_restore_points(limit=25, db_path=getattr(db, "path", None))
    latest_snapshot = last_restore_point(getattr(db, "path", None))

    broken_parents = integrity.get("broken_parent_links") or []
    invalid_sort_groups = integrity.get("invalid_sibling_sort_orders") or []
    orphaned_custom = integrity.get("orphaned_custom_values") or {}
    malformed_recurrence = integrity.get("malformed_recurrence") or {}
    missing_attachments = integrity.get("missing_file_attachments") or []
    fk_violations = integrity.get("foreign_key_violations") or []

    orphan_total = len(orphaned_custom.get("missing_tasks") or []) + len(orphaned_custom.get("missing_columns") or [])
    recurrence_total = sum(len(v) for v in malformed_recurrence.values())

    items = [
        DiagnosticItem(
            "ok" if schema.get("ok") else "error",
            "Schema validation",
            "Schema layout matches the current app expectations." if schema.get("ok") else "Schema validation found problems.",
            "\n".join(schema.get("issues") or []),
        ),
        DiagnosticItem(
            "ok" if integrity.get("integrity_check", {}).get("ok") else "error",
            "SQLite integrity check",
            str(integrity.get("integrity_check", {}).get("result") or "unknown"),
            "\n".join(integrity.get("integrity_check", {}).get("details") or []),
        ),
        DiagnosticItem(
            _status_for_count(len(fk_violations)),
            "Foreign-key violations",
            f"{len(fk_violations)} issue(s) detected.",
            "\n".join(
                f"{row['table']} rowid={row['rowid']} parent={row['parent']} fk={row['fkid']}"
                for row in fk_violations[:20]
            ),
        ),
        DiagnosticItem(
            _status_for_count(len(broken_parents)),
            "Broken parent links",
            f"{len(broken_parents)} task(s) reference a missing parent.",
            "\n".join(
                f"Task {row['id']}: {row.get('description') or ''} -> parent {row.get('parent_id')}"
                for row in broken_parents[:20]
            ),
        ),
        DiagnosticItem(
            _status_for_count(len(invalid_sort_groups)),
            "Sibling sort order",
            f"{len(invalid_sort_groups)} parent group(s) have invalid sibling ordering.",
            "\n".join(
                f"Parent {row.get('parent_id')}: {row.get('task_count')} task(s)"
                for row in invalid_sort_groups[:20]
            ),
        ),
        DiagnosticItem(
            _status_for_count(orphan_total),
            "Custom-value integrity",
            f"{orphan_total} orphaned custom value row(s) detected.",
            "\n".join(
                [f"Missing task ref: task={row['task_id']} column={row['column_id']}" for row in (orphaned_custom.get('missing_tasks') or [])[:10]]
                + [f"Missing column ref: task={row['task_id']} column={row['column_id']}" for row in (orphaned_custom.get('missing_columns') or [])[:10]]
            ),
        ),
        DiagnosticItem(
            _status_for_count(recurrence_total),
            "Recurrence integrity",
            f"{recurrence_total} malformed recurrence reference(s) detected.",
            "\n".join(_recurrence_lines(malformed_recurrence)),
        ),
        DiagnosticItem(
            _status_for_count(len(missing_attachments)),
            "Missing attachments",
            f"{len(missing_attachments)} attachment path(s) are missing on disk.",
            "\n".join(
                f"Task {row.get('task_id')}: {row.get('path') or '(empty path)'}"
                for row in missing_attachments[:20]
            ),
        ),
        DiagnosticItem(
            "ok" if latest_snapshot else "warning",
            "Restore points",
            f"{len(restore_points)} snapshot file(s) available." if restore_points else "No local restore points found.",
            latest_snapshot["filename"] if latest_snapshot else "",
        ),
    ]

    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "profile": str(workspace_name or APP_PROFILE),
        "theme_name": str(theme_name or ""),
        "schema_version": int(integrity.get("schema_version") or 0),
        "schema_ok": bool(schema.get("ok")),
        "db_path": str(db.path),
        "workspace_path": str(workspace_path or app_data_dir()),
        "backups_dir": str(backups_dir(getattr(db, "path", None))),
        "logs_dir": str(logs_dir()),
        "latest_snapshot": latest_snapshot,
        "restore_points": restore_points,
        "integrity": integrity,
        "items": items,
    }


def _recurrence_lines(report: dict[str, list[dict]]) -> Iterable[str]:
    for key, label in (
        ("invalid_frequency_rules", "Invalid frequency"),
        ("rules_missing_task", "Rule missing task"),
        ("task_rule_missing", "Task missing rule"),
        ("task_rule_mismatch", "Task/rule mismatch"),
        ("generated_origin_missing", "Generated task missing origin"),
    ):
        rows = report.get(key) or []
        for row in rows[:10]:
            identifier = row.get("id", row.get("task_id", "?"))
            yield f"{label}: {identifier}"
