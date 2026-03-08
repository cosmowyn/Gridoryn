from __future__ import annotations

import json
import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from crash_logging import log_event, log_exception
from db import Database, now_iso


FORMAT_VERSION = 3
SUPPORTED_FORMAT_VERSIONS = {1, 2, 3}
ALLOWED_COL_TYPES = {"text", "int", "date", "bool", "list"}


class BackupError(RuntimeError):
    pass


@dataclass
class ImportReport:
    created_columns: int = 0
    skipped_columns: int = 0
    imported_tasks: int = 0
    imported_values: int = 0
    skipped_values: int = 0
    mode: str = ""


def export_backup_ui(parent: QWidget, db: Database) -> None:
    try:
        suggested = f"task_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_path, _ = QFileDialog.getSaveFileName(
            parent,
            "Export backup",
            suggested,
            "JSON Backup (*.json);;All files (*.*)",
        )
        if not out_path:
            return

        log_event(
            "Backup export started",
            context="backup.export",
            db_path=getattr(db, "path", None),
            details={"target_path": out_path},
        )
        payload = export_payload(db)
        write_backup_file(Path(out_path), payload)
        log_event(
            "Backup export completed",
            context="backup.export",
            db_path=getattr(db, "path", None),
            details={"target_path": out_path, "task_count": len(payload.get("tasks") or [])},
        )

        QMessageBox.information(
            parent,
            "Backup exported",
            f"Backup exported successfully.\n\nFile:\n{out_path}",
        )
    except Exception as e:
        log_exception(e, context="backup.export", db_path=getattr(db, "path", None))
        QMessageBox.critical(
            parent,
            "Backup export failed",
            _format_exception_message("Export failed", e),
        )


def import_backup_ui(parent: QWidget) -> None:
    try:
        backup_path, _ = QFileDialog.getOpenFileName(
            parent,
            "Select backup file",
            "",
            "JSON Backup (*.json);;All files (*.*)",
        )
        if not backup_path:
            return

        target_db_path, _ = QFileDialog.getSaveFileName(
            parent,
            "Select target database file (new name/location)",
            "restored_tasks.sqlite3",
            "SQLite DB (*.sqlite3 *.db);;All files (*.*)",
        )
        if not target_db_path:
            return

        log_event(
            "Backup import started",
            context="backup.import",
            details={"source_path": backup_path, "target_db_path": target_db_path},
        )
        payload = read_backup_file(Path(backup_path), parent=parent)
        report = import_payload_into_dbfile(
            parent=parent,
            payload=payload,
            target_db_path=Path(target_db_path),
            make_file_backup=True,
        )
        log_event(
            "Backup import completed",
            context="backup.import",
            db_path=str(target_db_path),
            details={
                "source_path": backup_path,
                "target_db_path": target_db_path,
                "mode": str(report.mode or ""),
                "imported_tasks": int(report.imported_tasks or 0),
                "created_columns": int(report.created_columns or 0),
            },
        )

        QMessageBox.information(
            parent,
            "Import completed",
            _format_success_report(report, target_db_path),
        )

    except Exception as e:
        log_exception(e, context="backup.import")
        QMessageBox.critical(
            parent,
            "Backup import failed",
            _format_exception_message("Import failed", e),
        )


def export_payload(db: Database) -> dict:
    cur = db.conn.cursor()

    cur.execute("PRAGMA user_version;")
    user_version = int(cur.fetchone()[0])

    cur.execute("SELECT id, name, col_type, created_at FROM custom_columns ORDER BY id;")
    cols = [dict(r) for r in cur.fetchall()]
    for c in cols:
        if c.get("col_type") not in ALLOWED_COL_TYPES:
            c["col_type"] = "text"

    cur.execute(
        """
        SELECT column_id, value
        FROM custom_column_list_values
        ORDER BY column_id, sort_order ASC, value ASC;
        """
    )
    list_values_by_col: dict[int, list[str]] = {}
    for r in cur.fetchall():
        cid = int(r["column_id"])
        list_values_by_col.setdefault(cid, []).append(str(r["value"]))

    col_id_to_name = {int(c["id"]): str(c["name"]) for c in cols}

    cur.execute(
        """
        SELECT id, description, due_date, last_update, priority, status,
               parent_id, sort_order, is_collapsed,
               notes, archived_at, planned_bucket,
               effort_minutes, actual_minutes, timer_started_at,
               waiting_for,
               recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
               reminder_at, reminder_minutes_before, reminder_fired_at,
               start_date, phase_id
        FROM tasks
        ORDER BY COALESCE(parent_id, 0), sort_order ASC, id ASC;
        """
    )
    tasks = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT task_id, column_id, value FROM task_custom_values;")
    rows = cur.fetchall()

    values_by_task: dict[int, dict[str, Any]] = {}
    for r in rows:
        tid = int(r["task_id"])
        cid = int(r["column_id"])
        name = col_id_to_name.get(cid)
        if not name:
            continue
        values_by_task.setdefault(tid, {})[name] = r["value"]

    for t in tasks:
        t["custom"] = values_by_task.get(int(t["id"]), {})

    cur.execute(
        """
        SELECT tt.task_id, tg.name
        FROM task_tags tt
        JOIN tags tg ON tg.id=tt.tag_id
        ORDER BY tt.task_id, LOWER(tg.name), tg.name;
        """
    )
    tags_by_task: dict[int, list[str]] = {}
    for r in cur.fetchall():
        tags_by_task.setdefault(int(r["task_id"]), []).append(str(r["name"]))

    cur.execute(
        """
        SELECT id, task_id, path, label, created_at
        FROM task_attachments
        ORDER BY task_id, id;
        """
    )
    attachments_by_task: dict[int, list[dict]] = {}
    for r in cur.fetchall():
        attachments_by_task.setdefault(int(r["task_id"]), []).append(
            {
                "id": int(r["id"]),
                "path": str(r["path"]),
                "label": str(r["label"] or ""),
                "created_at": str(r["created_at"] or now_iso()),
            }
        )

    cur.execute(
        """
        SELECT task_id, depends_on_task_id
        FROM task_dependencies
        ORDER BY task_id, depends_on_task_id;
        """
    )
    deps_by_task: dict[int, list[int]] = {}
    for r in cur.fetchall():
        deps_by_task.setdefault(int(r["task_id"]), []).append(int(r["depends_on_task_id"]))

    for t in tasks:
        tid = int(t["id"])
        t["tags"] = tags_by_task.get(tid, [])
        t["attachments"] = attachments_by_task.get(tid, [])
        t["dependencies"] = deps_by_task.get(tid, [])

    cur.execute(
        """
        SELECT id, task_id, frequency, create_next_on_done, is_active, created_at, updated_at
        FROM recurrence_rules
        ORDER BY id;
        """
    )
    recurrence_rules = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT id, name, state_json, created_at, updated_at
        FROM saved_filter_views
        ORDER BY LOWER(name), name;
        """
    )
    saved_filter_views = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT id, name, payload_json, created_at, updated_at
        FROM task_templates
        ORDER BY LOWER(name), name;
        """
    )
    templates = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT task_id, objective, scope, out_of_scope, owner, stakeholders, target_date,
               success_criteria, project_status_health, summary, category, created_at, updated_at
        FROM project_profiles
        ORDER BY task_id;
        """
    )
    project_profiles = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT id, project_task_id, name, sort_order, created_at, updated_at
        FROM project_phases
        ORDER BY project_task_id, sort_order, id;
        """
    )
    project_phases = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT id, predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type, is_soft, created_at
        FROM pm_dependencies
        ORDER BY predecessor_kind, predecessor_id, successor_kind, successor_id, id;
        """
    )
    pm_dependencies = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT id, project_task_id, title, description, phase_id, linked_task_id, start_date, target_date,
               baseline_target_date, status, progress_percent, completed_at, created_at, updated_at
        FROM milestones
        ORDER BY project_task_id, COALESCE(target_date, '9999-12-31'), id;
        """
    )
    milestones = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT id, project_task_id, title, description, phase_id, linked_task_id, linked_milestone_id,
               due_date, baseline_due_date, acceptance_criteria, version_ref, status, completed_at,
               created_at, updated_at
        FROM deliverables
        ORDER BY project_task_id, COALESCE(due_date, '9999-12-31'), id;
        """
    )
    deliverables = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT id, project_task_id, entry_type, title, details, status, severity, review_date,
               linked_task_id, linked_milestone_id, created_at, updated_at
        FROM project_register_entries
        ORDER BY project_task_id, created_at, id;
        """
    )
    project_register_entries = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT project_task_id, target_date, effort_minutes, created_at, updated_at
        FROM project_baselines
        ORDER BY project_task_id;
        """
    )
    project_baselines = [dict(r) for r in cur.fetchall()]

    payload_wo_checksum = {
        "format_version": FORMAT_VERSION,
        "exported_at": now_iso(),
        "schema_user_version": user_version,
        "custom_columns": [
            {
                "name": c["name"],
                "col_type": c["col_type"],
                "created_at": c.get("created_at") or now_iso(),
                "list_values": list_values_by_col.get(int(c["id"]), []) if c.get("col_type") == "list" else [],
            }
            for c in cols
        ],
        "tasks": tasks,
        "recurrence_rules": recurrence_rules,
        "saved_filter_views": saved_filter_views,
        "templates": templates,
        "project_profiles": project_profiles,
        "project_phases": project_phases,
        "pm_dependencies": pm_dependencies,
        "milestones": milestones,
        "deliverables": deliverables,
        "project_register_entries": project_register_entries,
        "project_baselines": project_baselines,
    }

    checksum = _sha256_canonical_json(payload_wo_checksum)
    payload_wo_checksum["checksum_sha256"] = checksum
    return payload_wo_checksum


def write_backup_file(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2)

    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def read_backup_file(path: Path, parent: Optional[QWidget] = None) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)

    _validate_payload_shape(payload)

    claimed = str(payload.get("checksum_sha256") or "")
    payload_no = dict(payload)
    payload_no.pop("checksum_sha256", None)
    actual = _sha256_canonical_json(payload_no)

    if claimed and claimed != actual:
        if parent is not None:
            res = QMessageBox.warning(
                parent,
                "Backup integrity warning",
                "The backup checksum does not match.\n\n"
                "This file may be corrupted or edited.\n\n"
                "Do you want to continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                raise BackupError("Import cancelled due to checksum mismatch.")
        else:
            raise BackupError("Checksum mismatch in backup file.")

    return payload


def import_payload_into_dbfile(
    parent: QWidget,
    payload: dict,
    target_db_path: Path,
    make_file_backup: bool = True,
) -> ImportReport:
    target_db_path = Path(target_db_path)

    bak_path = None
    existed_before = target_db_path.exists()
    if make_file_backup and existed_before:
        bak_path = target_db_path.with_suffix(target_db_path.suffix + ".preimport.bak")
        try:
            shutil.copy2(target_db_path, bak_path)
        except Exception:
            bak_path = None

    target_db = Database(str(target_db_path))
    try:
        report = import_payload(parent, payload, target_db)
    except Exception:
        try:
            target_db.conn.close()
        except Exception:
            pass

        if not existed_before:
            try:
                target_db_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise
    finally:
        try:
            target_db.conn.close()
        except Exception:
            pass

    return report


def import_payload(parent: QWidget, payload: dict, target_db: Database) -> ImportReport:
    _validate_payload_shape(payload)

    src_cols = payload["custom_columns"]
    src_tasks = payload["tasks"]
    src_recurrence = payload.get("recurrence_rules") or []
    src_saved_views = payload.get("saved_filter_views") or []
    src_templates = payload.get("templates") or []
    src_project_profiles = payload.get("project_profiles") or []
    src_project_phases = payload.get("project_phases") or []
    src_pm_dependencies = payload.get("pm_dependencies") or []
    src_milestones = payload.get("milestones") or []
    src_deliverables = payload.get("deliverables") or []
    src_project_register_entries = payload.get("project_register_entries") or []
    src_project_baselines = payload.get("project_baselines") or []

    tgt_cols = _get_target_columns(target_db)
    tgt_col_names = set(tgt_cols.keys())

    missing = [c for c in src_cols if c["name"] not in tgt_col_names]
    allowed_missing = [c for c in missing if c.get("col_type") in ALLOWED_COL_TYPES]
    unknown_type_missing = [c for c in missing if c.get("col_type") not in ALLOWED_COL_TYPES]

    if unknown_type_missing:
        for c in unknown_type_missing:
            c["col_type"] = "text"
        allowed_missing.extend(unknown_type_missing)

    create_missing = True
    if allowed_missing:
        text = "The backup contains custom columns that do not exist in the target database:\n\n"
        text += "\n".join([f"• {c['name']}  ({c['col_type']})" for c in allowed_missing])
        text += "\n\nCreate these columns in the target database before importing?"

        res = QMessageBox.question(
            parent,
            "Missing custom columns",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if res == QMessageBox.StandardButton.Cancel:
            raise BackupError("Import cancelled by user.")
        create_missing = (res == QMessageBox.StandardButton.Yes)

    tgt_task_count = _count_target_tasks(target_db)
    mode = "replace"
    if tgt_task_count > 0:
        res = QMessageBox.question(
            parent,
            "Target database not empty",
            f"The target database already contains {tgt_task_count} task(s).\n\n"
            "Do you want to REPLACE them with the backup content?\n\n"
            "Yes = Replace (clears existing tasks)\n"
            "No = Merge (imports alongside existing tasks)\n"
            "Cancel = Abort",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if res == QMessageBox.StandardButton.Cancel:
            raise BackupError("Import cancelled by user.")
        mode = "replace" if res == QMessageBox.StandardButton.Yes else "merge"

    report = ImportReport(mode=mode)

    try:
        with target_db.tx():
            cur = target_db.conn.cursor()

            if mode == "replace":
                cur.execute("DELETE FROM task_custom_values;")
                cur.execute("DELETE FROM task_tags;")
                cur.execute("DELETE FROM task_attachments;")
                cur.execute("DELETE FROM task_dependencies;")
                cur.execute("DELETE FROM recurrence_rules;")
                cur.execute("DELETE FROM tags;")
                cur.execute("DELETE FROM tasks;")
                cur.execute("DELETE FROM saved_filter_views;")
                cur.execute("DELETE FROM task_templates;")
                cur.execute("DELETE FROM project_register_entries;")
                cur.execute("DELETE FROM deliverables;")
                cur.execute("DELETE FROM milestones;")
                cur.execute("DELETE FROM pm_dependencies;")
                cur.execute("DELETE FROM project_baselines;")
                cur.execute("DELETE FROM project_phases;")
                cur.execute("DELETE FROM project_profiles;")

            if allowed_missing and create_missing:
                for c in allowed_missing:
                    cur.execute("SELECT 1 FROM custom_columns WHERE name=?;", (c["name"],))
                    if cur.fetchone():
                        continue
                    cur.execute(
                        "INSERT INTO custom_columns(name, col_type, created_at) VALUES(?, ?, ?);",
                        (c["name"], c["col_type"], c.get("created_at") or now_iso()),
                    )
                    new_col_id = int(cur.lastrowid)
                    if c.get("col_type") == "list":
                        vals = _normalize_list_values(c.get("list_values"))
                        for i, v in enumerate(vals, start=1):
                            cur.execute(
                                """
                                INSERT INTO custom_column_list_values(column_id, value, sort_order)
                                VALUES(?, ?, ?)
                                ON CONFLICT(column_id, value) DO NOTHING;
                                """,
                                (new_col_id, v, i),
                            )
                    report.created_columns += 1
            elif allowed_missing and not create_missing:
                report.skipped_columns = len(allowed_missing)

            tgt_cols = _get_target_columns(target_db)
            for c in src_cols:
                name = str(c.get("name", ""))
                tgt = tgt_cols.get(name)
                if not tgt:
                    continue
                col_id, tgt_type = tgt
                if tgt_type != "list":
                    continue
                vals = _normalize_list_values(c.get("list_values"))
                for v in vals:
                    cur.execute(
                        "SELECT 1 FROM custom_column_list_values WHERE column_id=? AND value=?;",
                        (int(col_id), v),
                    )
                    if cur.fetchone():
                        continue
                    cur.execute(
                        """
                        SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                        FROM custom_column_list_values
                        WHERE column_id=?;
                        """,
                        (int(col_id),),
                    )
                    next_order = int(cur.fetchone()["next_order"])
                    cur.execute(
                        """
                        INSERT INTO custom_column_list_values(column_id, value, sort_order)
                        VALUES(?, ?, ?)
                        ON CONFLICT(column_id, value) DO NOTHING;
                        """,
                        (int(col_id), v, next_order),
                    )

            task_id_map: dict[int, int] = {}
            if mode == "replace":
                _import_tasks_keep_ids(cur, src_tasks, tgt_cols, report, task_id_map)
            else:
                _import_tasks_merge(cur, src_tasks, tgt_cols, report, task_id_map)

            _import_task_extras(cur, src_tasks, task_id_map)
            _import_recurrence(cur, src_recurrence, src_tasks, task_id_map)
            phase_id_map = _import_project_profiles_and_phases(
                cur,
                src_project_profiles,
                src_project_phases,
                task_id_map,
            )
            _apply_task_phase_assignments(cur, src_tasks, task_id_map, phase_id_map)
            milestone_id_map = _import_milestones(cur, src_milestones, task_id_map, phase_id_map)
            _import_deliverables(cur, src_deliverables, task_id_map, phase_id_map, milestone_id_map)
            _import_project_register_entries(cur, src_project_register_entries, task_id_map, milestone_id_map)
            _import_project_baselines(cur, src_project_baselines, task_id_map)
            _import_pm_dependencies(cur, src_pm_dependencies, task_id_map, milestone_id_map)
            _import_saved_filter_views(cur, src_saved_views)
            _import_templates(cur, src_templates)

    except Exception as e:
        raise BackupError(_format_exception_message("Import transaction failed", e))

    return report


def _task_insert_values(t: dict, parent_id, sort_order: int):
    return (
        t.get("description", ""),
        t.get("due_date"),
        t.get("last_update") or now_iso(),
        int(t.get("priority", 3)),
        t.get("status", "Todo"),
        parent_id,
        int(sort_order),
        int(t.get("is_collapsed", 0)),
        str(t.get("notes") or ""),
        t.get("archived_at"),
        str(t.get("planned_bucket") or "inbox"),
        t.get("effort_minutes"),
        int(t.get("actual_minutes", 0) or 0),
        t.get("timer_started_at"),
        t.get("waiting_for"),
        None,  # recurrence_rule_id remapped in a dedicated pass
        None,  # recurrence_origin_task_id remapped in a dedicated pass
        int(t.get("is_generated_occurrence", 0) or 0),
        t.get("reminder_at"),
        t.get("reminder_minutes_before"),
        t.get("reminder_fired_at"),
        t.get("start_date"),
        t.get("phase_id"),
    )


def _import_tasks_keep_ids(
    cur,
    src_tasks: list[dict],
    tgt_cols: dict,
    report: ImportReport,
    id_map: dict[int, int],
) -> None:
    pending = {int(t["id"]): t for t in src_tasks if "id" in t}
    inserted = set()

    max_passes = len(pending) + 5
    passes = 0

    while pending and passes < max_passes:
        passes += 1
        progress = 0

        for tid in list(pending.keys()):
            t = pending[tid]
            pid = t.get("parent_id")
            if pid is None or int(pid) in inserted or int(pid) not in pending:
                parent_id = int(pid) if (pid is not None and int(pid) in inserted) else None

                cur.execute(
                    """
                    INSERT INTO tasks(id, description, due_date, last_update, priority, status,
                                      parent_id, sort_order, is_collapsed,
                                      notes, archived_at, planned_bucket,
                                      effort_minutes, actual_minutes, timer_started_at,
                                      waiting_for,
                                      recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                                      reminder_at, reminder_minutes_before, reminder_fired_at,
                                      start_date, phase_id)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (tid, *_task_insert_values(t, parent_id, int(t.get("sort_order", 1)))),
                )

                report.imported_tasks += 1
                inserted.add(tid)
                id_map[tid] = tid
                _insert_custom_values(cur, tid, t.get("custom", {}), tgt_cols, report)

                pending.pop(tid, None)
                progress += 1

        if progress == 0:
            for tid, t in list(pending.items()):
                cur.execute(
                    """
                    INSERT INTO tasks(id, description, due_date, last_update, priority, status,
                                      parent_id, sort_order, is_collapsed,
                                      notes, archived_at, planned_bucket,
                                      effort_minutes, actual_minutes, timer_started_at,
                                      waiting_for,
                                      recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                                      reminder_at, reminder_minutes_before, reminder_fired_at,
                                      start_date, phase_id)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (tid, *_task_insert_values(t, None, int(t.get("sort_order", 1)))),
                )
                report.imported_tasks += 1
                inserted.add(tid)
                id_map[tid] = tid
                _insert_custom_values(cur, tid, t.get("custom", {}), tgt_cols, report)
                pending.pop(tid, None)

    if pending:
        raise BackupError("Import failed: could not resolve some parent/child relations (unexpected).")


def _import_tasks_merge(cur, src_tasks: list[dict], tgt_cols: dict, report: ImportReport, id_map: dict[int, int]) -> None:
    cur.execute("SELECT parent_id, COALESCE(MAX(sort_order), 0) AS mx FROM tasks GROUP BY parent_id;")
    max_by_parent = {r["parent_id"]: int(r["mx"]) for r in cur.fetchall()}

    pending = {int(t["id"]): t for t in src_tasks if "id" in t}
    max_passes = len(pending) + 5
    passes = 0

    while pending and passes < max_passes:
        passes += 1
        progress = 0

        for old_id in list(pending.keys()):
            t = pending[old_id]
            old_parent = t.get("parent_id")

            if old_parent is None:
                new_parent = None
                can_insert = True
            else:
                op = int(old_parent)
                if op in id_map:
                    new_parent = id_map[op]
                    can_insert = True
                elif op not in pending:
                    new_parent = None
                    can_insert = True
                else:
                    can_insert = False

            if not can_insert:
                continue

            base = max_by_parent.get(new_parent, 0)
            sort_order = base + int(t.get("sort_order", 1))
            max_by_parent[new_parent] = max(max_by_parent.get(new_parent, 0), sort_order)

            cur.execute(
                """
                INSERT INTO tasks(description, due_date, last_update, priority, status,
                                  parent_id, sort_order, is_collapsed,
                                  notes, archived_at, planned_bucket,
                                  effort_minutes, actual_minutes, timer_started_at,
                                  waiting_for,
                                  recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                                  reminder_at, reminder_minutes_before, reminder_fired_at,
                                  start_date, phase_id)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                _task_insert_values(t, new_parent, sort_order),
            )
            new_id = int(cur.lastrowid)
            id_map[old_id] = new_id

            report.imported_tasks += 1
            _insert_custom_values(cur, new_id, t.get("custom", {}), tgt_cols, report)

            pending.pop(old_id, None)
            progress += 1

        if progress == 0:
            for old_id, t in list(pending.items()):
                cur.execute(
                    """
                    INSERT INTO tasks(description, due_date, last_update, priority, status,
                                      parent_id, sort_order, is_collapsed,
                                      notes, archived_at, planned_bucket,
                                      effort_minutes, actual_minutes, timer_started_at,
                                      waiting_for,
                                      recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                                      reminder_at, reminder_minutes_before, reminder_fired_at,
                                      start_date, phase_id)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    _task_insert_values(t, None, int(t.get("sort_order", 1))),
                )
                new_id = int(cur.lastrowid)
                id_map[old_id] = new_id

                report.imported_tasks += 1
                _insert_custom_values(cur, new_id, t.get("custom", {}), tgt_cols, report)

                pending.pop(old_id, None)


def _ensure_tag_id(cur, tag_name: str) -> int:
    cur.execute("SELECT id FROM tags WHERE name=? COLLATE NOCASE;", (str(tag_name).strip(),))
    row = cur.fetchone()
    if row:
        return int(row["id"])
    cur.execute("INSERT INTO tags(name, created_at) VALUES(?, ?);", (str(tag_name).strip(), now_iso()))
    return int(cur.lastrowid)


def _import_task_extras(cur, src_tasks: list[dict], id_map: dict[int, int]) -> None:
    for t in src_tasks:
        try:
            old_tid = int(t["id"])
        except Exception:
            continue
        new_tid = id_map.get(old_tid)
        if not new_tid:
            continue

        # Tags
        tags = t.get("tags") or []
        if isinstance(tags, list):
            for tag in tags:
                name = str(tag).strip()
                if not name:
                    continue
                tag_id = _ensure_tag_id(cur, name)
                cur.execute(
                    """
                    INSERT INTO task_tags(task_id, tag_id)
                    VALUES(?, ?)
                    ON CONFLICT(task_id, tag_id) DO NOTHING;
                    """,
                    (int(new_tid), int(tag_id)),
                )

        # Attachments (portable links)
        atts = t.get("attachments") or []
        if isinstance(atts, list):
            for att in atts:
                if not isinstance(att, dict):
                    continue
                path = str(att.get("path") or "").strip()
                if not path:
                    continue
                cur.execute(
                    """
                    INSERT INTO task_attachments(task_id, path, label, created_at)
                    VALUES(?, ?, ?, ?);
                    """,
                    (
                        int(new_tid),
                        path,
                        str(att.get("label") or ""),
                        str(att.get("created_at") or now_iso()),
                    ),
                )

    # Dependencies are applied in a second pass so all task ids are known.
    for t in src_tasks:
        try:
            old_tid = int(t["id"])
        except Exception:
            continue
        new_tid = id_map.get(old_tid)
        if not new_tid:
            continue
        deps = t.get("dependencies") or []
        if not isinstance(deps, list):
            continue
        for dep_old in deps:
            try:
                dep_old_id = int(dep_old)
            except Exception:
                continue
            dep_new = id_map.get(dep_old_id)
            if not dep_new or dep_new == new_tid:
                continue
            cur.execute(
                """
                INSERT INTO task_dependencies(task_id, depends_on_task_id)
                VALUES(?, ?)
                ON CONFLICT(task_id, depends_on_task_id) DO NOTHING;
                """,
                (int(new_tid), int(dep_new)),
            )
            cur.execute(
                """
                INSERT INTO pm_dependencies(
                    predecessor_kind,
                    predecessor_id,
                    successor_kind,
                    successor_id,
                    dep_type,
                    is_soft,
                    created_at
                )
                VALUES('task', ?, 'task', ?, 'finish_to_start', 0, ?)
                ON CONFLICT(predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type) DO NOTHING;
                """,
                (int(dep_new), int(new_tid), now_iso()),
            )


def _import_recurrence(cur, src_recurrence: list[dict], src_tasks: list[dict], id_map: dict[int, int]) -> None:
    rr_id_map: dict[int, int] = {}

    for rr in src_recurrence:
        if not isinstance(rr, dict):
            continue
        try:
            old_rule_id = int(rr.get("id"))
            old_task_id = int(rr.get("task_id"))
        except Exception:
            continue
        new_task_id = id_map.get(old_task_id)
        if not new_task_id:
            continue
        freq = str(rr.get("frequency") or "").strip().lower()
        if freq not in {"daily", "weekly", "monthly", "yearly"}:
            continue
        cur.execute(
            """
            INSERT INTO recurrence_rules(task_id, frequency, create_next_on_done, is_active, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?);
            """,
            (
                int(new_task_id),
                freq,
                int(rr.get("create_next_on_done", 1)),
                int(rr.get("is_active", 1)),
                str(rr.get("created_at") or now_iso()),
                str(rr.get("updated_at") or now_iso()),
            ),
        )
        rr_id_map[old_rule_id] = int(cur.lastrowid)

    for t in src_tasks:
        if not isinstance(t, dict):
            continue
        try:
            old_tid = int(t["id"])
        except Exception:
            continue
        new_tid = id_map.get(old_tid)
        if not new_tid:
            continue

        old_rr = t.get("recurrence_rule_id")
        old_origin = t.get("recurrence_origin_task_id")
        new_rr = None
        new_origin = None
        try:
            if old_rr is not None:
                new_rr = rr_id_map.get(int(old_rr))
        except Exception:
            new_rr = None
        try:
            if old_origin is not None:
                new_origin = id_map.get(int(old_origin))
        except Exception:
            new_origin = None

        cur.execute(
            """
            UPDATE tasks
            SET recurrence_rule_id=?, recurrence_origin_task_id=?, is_generated_occurrence=?
            WHERE id=?;
            """,
            (
                new_rr,
                new_origin,
                int(t.get("is_generated_occurrence", 0) or 0),
                int(new_tid),
            ),
        )


def _import_project_profiles_and_phases(
    cur,
    project_profiles: list[dict],
    project_phases: list[dict],
    task_id_map: dict[int, int],
) -> dict[int, int]:
    phase_id_map: dict[int, int] = {}

    for row in project_profiles:
        if not isinstance(row, dict):
            continue
        try:
            old_task_id = int(row.get("task_id"))
        except Exception:
            continue
        new_task_id = task_id_map.get(old_task_id)
        if not new_task_id:
            continue
        cur.execute(
            """
            INSERT INTO project_profiles(
                task_id,
                objective,
                scope,
                out_of_scope,
                owner,
                stakeholders,
                target_date,
                success_criteria,
                project_status_health,
                summary,
                category,
                created_at,
                updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                objective=excluded.objective,
                scope=excluded.scope,
                out_of_scope=excluded.out_of_scope,
                owner=excluded.owner,
                stakeholders=excluded.stakeholders,
                target_date=excluded.target_date,
                success_criteria=excluded.success_criteria,
                project_status_health=excluded.project_status_health,
                summary=excluded.summary,
                category=excluded.category,
                updated_at=excluded.updated_at;
            """,
            (
                int(new_task_id),
                str(row.get("objective") or ""),
                str(row.get("scope") or ""),
                str(row.get("out_of_scope") or ""),
                str(row.get("owner") or "Self"),
                str(row.get("stakeholders") or ""),
                str(row.get("target_date") or "").strip() or None,
                str(row.get("success_criteria") or ""),
                str(row.get("project_status_health") or "").strip() or None,
                str(row.get("summary") or ""),
                str(row.get("category") or ""),
                str(row.get("created_at") or now_iso()),
                str(row.get("updated_at") or now_iso()),
            ),
        )

    for row in project_phases:
        if not isinstance(row, dict):
            continue
        try:
            old_phase_id = int(row.get("id"))
            old_project_id = int(row.get("project_task_id"))
        except Exception:
            continue
        new_project_id = task_id_map.get(old_project_id)
        if not new_project_id:
            continue
        cur.execute(
            """
            INSERT INTO project_phases(project_task_id, name, sort_order, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?);
            """,
            (
                int(new_project_id),
                str(row.get("name") or ""),
                int(row.get("sort_order") or 1),
                str(row.get("created_at") or now_iso()),
                str(row.get("updated_at") or now_iso()),
            ),
        )
        phase_id_map[int(old_phase_id)] = int(cur.lastrowid)
    return phase_id_map


def _apply_task_phase_assignments(cur, src_tasks: list[dict], task_id_map: dict[int, int], phase_id_map: dict[int, int]) -> None:
    for task in src_tasks:
        if not isinstance(task, dict):
            continue
        try:
            old_task_id = int(task.get("id"))
        except Exception:
            continue
        new_task_id = task_id_map.get(old_task_id)
        if not new_task_id:
            continue
        old_phase_id = task.get("phase_id")
        if old_phase_id is None:
            continue
        try:
            mapped_phase_id = phase_id_map.get(int(old_phase_id))
        except Exception:
            mapped_phase_id = None
        cur.execute(
            "UPDATE tasks SET phase_id=?, start_date=? WHERE id=?;",
            (mapped_phase_id, task.get("start_date"), int(new_task_id)),
        )


def _import_milestones(cur, milestones: list[dict], task_id_map: dict[int, int], phase_id_map: dict[int, int]) -> dict[int, int]:
    milestone_id_map: dict[int, int] = {}
    for row in milestones:
        if not isinstance(row, dict):
            continue
        try:
            old_id = int(row.get("id"))
            old_project_id = int(row.get("project_task_id"))
        except Exception:
            continue
        new_project_id = task_id_map.get(old_project_id)
        if not new_project_id:
            continue
        linked_task_id = None
        if row.get("linked_task_id") is not None:
            try:
                linked_task_id = task_id_map.get(int(row.get("linked_task_id")))
            except Exception:
                linked_task_id = None
        phase_id = None
        if row.get("phase_id") is not None:
            try:
                phase_id = phase_id_map.get(int(row.get("phase_id")))
            except Exception:
                phase_id = None
        cur.execute(
            """
            INSERT INTO milestones(
                project_task_id,
                title,
                description,
                phase_id,
                linked_task_id,
                start_date,
                target_date,
                baseline_target_date,
                status,
                progress_percent,
                completed_at,
                created_at,
                updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(new_project_id),
                str(row.get("title") or ""),
                str(row.get("description") or ""),
                phase_id,
                linked_task_id,
                row.get("start_date"),
                row.get("target_date"),
                row.get("baseline_target_date"),
                str(row.get("status") or "planned"),
                int(row.get("progress_percent") or 0),
                row.get("completed_at"),
                str(row.get("created_at") or now_iso()),
                str(row.get("updated_at") or now_iso()),
            ),
        )
        milestone_id_map[int(old_id)] = int(cur.lastrowid)
    return milestone_id_map


def _import_deliverables(
    cur,
    deliverables: list[dict],
    task_id_map: dict[int, int],
    phase_id_map: dict[int, int],
    milestone_id_map: dict[int, int],
) -> None:
    for row in deliverables:
        if not isinstance(row, dict):
            continue
        try:
            old_project_id = int(row.get("project_task_id"))
        except Exception:
            continue
        new_project_id = task_id_map.get(old_project_id)
        if not new_project_id:
            continue
        linked_task_id = None
        linked_milestone_id = None
        phase_id = None
        try:
            if row.get("linked_task_id") is not None:
                linked_task_id = task_id_map.get(int(row.get("linked_task_id")))
        except Exception:
            linked_task_id = None
        try:
            if row.get("linked_milestone_id") is not None:
                linked_milestone_id = milestone_id_map.get(int(row.get("linked_milestone_id")))
        except Exception:
            linked_milestone_id = None
        try:
            if row.get("phase_id") is not None:
                phase_id = phase_id_map.get(int(row.get("phase_id")))
        except Exception:
            phase_id = None
        cur.execute(
            """
            INSERT INTO deliverables(
                project_task_id,
                title,
                description,
                phase_id,
                linked_task_id,
                linked_milestone_id,
                due_date,
                baseline_due_date,
                acceptance_criteria,
                version_ref,
                status,
                completed_at,
                created_at,
                updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(new_project_id),
                str(row.get("title") or ""),
                str(row.get("description") or ""),
                phase_id,
                linked_task_id,
                linked_milestone_id,
                row.get("due_date"),
                row.get("baseline_due_date"),
                str(row.get("acceptance_criteria") or ""),
                str(row.get("version_ref") or ""),
                str(row.get("status") or "planned"),
                row.get("completed_at"),
                str(row.get("created_at") or now_iso()),
                str(row.get("updated_at") or now_iso()),
            ),
        )


def _import_project_register_entries(
    cur,
    entries: list[dict],
    task_id_map: dict[int, int],
    milestone_id_map: dict[int, int],
) -> None:
    for row in entries:
        if not isinstance(row, dict):
            continue
        try:
            old_project_id = int(row.get("project_task_id"))
        except Exception:
            continue
        new_project_id = task_id_map.get(old_project_id)
        if not new_project_id:
            continue
        linked_task_id = None
        linked_milestone_id = None
        try:
            if row.get("linked_task_id") is not None:
                linked_task_id = task_id_map.get(int(row.get("linked_task_id")))
        except Exception:
            linked_task_id = None
        try:
            if row.get("linked_milestone_id") is not None:
                linked_milestone_id = milestone_id_map.get(int(row.get("linked_milestone_id")))
        except Exception:
            linked_milestone_id = None
        cur.execute(
            """
            INSERT INTO project_register_entries(
                project_task_id,
                entry_type,
                title,
                details,
                status,
                severity,
                review_date,
                linked_task_id,
                linked_milestone_id,
                created_at,
                updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(new_project_id),
                str(row.get("entry_type") or "risk"),
                str(row.get("title") or ""),
                str(row.get("details") or ""),
                str(row.get("status") or "open"),
                row.get("severity"),
                row.get("review_date"),
                linked_task_id,
                linked_milestone_id,
                str(row.get("created_at") or now_iso()),
                str(row.get("updated_at") or now_iso()),
            ),
        )


def _import_project_baselines(cur, baselines: list[dict], task_id_map: dict[int, int]) -> None:
    for row in baselines:
        if not isinstance(row, dict):
            continue
        try:
            old_project_id = int(row.get("project_task_id"))
        except Exception:
            continue
        new_project_id = task_id_map.get(old_project_id)
        if not new_project_id:
            continue
        cur.execute(
            """
            INSERT INTO project_baselines(project_task_id, target_date, effort_minutes, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(project_task_id) DO UPDATE SET
                target_date=excluded.target_date,
                effort_minutes=excluded.effort_minutes,
                updated_at=excluded.updated_at;
            """,
            (
                int(new_project_id),
                row.get("target_date"),
                row.get("effort_minutes"),
                str(row.get("created_at") or now_iso()),
                str(row.get("updated_at") or now_iso()),
            ),
        )


def _import_pm_dependencies(
    cur,
    dependencies: list[dict],
    task_id_map: dict[int, int],
    milestone_id_map: dict[int, int],
) -> None:
    for row in dependencies:
        if not isinstance(row, dict):
            continue
        pre_kind = str(row.get("predecessor_kind") or "").strip().lower()
        succ_kind = str(row.get("successor_kind") or "").strip().lower()
        if pre_kind not in {"task", "milestone"} or succ_kind not in {"task", "milestone"}:
            continue
        try:
            pre_old = int(row.get("predecessor_id"))
            succ_old = int(row.get("successor_id"))
        except Exception:
            continue
        pre_new = task_id_map.get(pre_old) if pre_kind == "task" else milestone_id_map.get(pre_old)
        succ_new = task_id_map.get(succ_old) if succ_kind == "task" else milestone_id_map.get(succ_old)
        if not pre_new or not succ_new:
            continue
        cur.execute(
            """
            INSERT INTO pm_dependencies(
                predecessor_kind,
                predecessor_id,
                successor_kind,
                successor_id,
                dep_type,
                is_soft,
                created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type) DO NOTHING;
            """,
            (
                pre_kind,
                int(pre_new),
                succ_kind,
                int(succ_new),
                str(row.get("dep_type") or "finish_to_start"),
                int(row.get("is_soft") or 0),
                str(row.get("created_at") or now_iso()),
            ),
        )


def _import_saved_filter_views(cur, saved_views: list[dict]) -> None:
    for sv in saved_views:
        if not isinstance(sv, dict):
            continue
        name = str(sv.get("name") or "").strip()
        if not name:
            continue
        state_json = sv.get("state_json")
        if state_json is None and "state" in sv:
            try:
                state_json = json.dumps(sv.get("state") or {}, ensure_ascii=False)
            except Exception:
                state_json = "{}"
        if state_json is None:
            state_json = "{}"
        cur.execute(
            """
            INSERT INTO saved_filter_views(name, state_json, created_at, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                state_json=excluded.state_json,
                updated_at=excluded.updated_at;
            """,
            (
                name,
                str(state_json),
                str(sv.get("created_at") or now_iso()),
                str(sv.get("updated_at") or now_iso()),
            ),
        )


def _import_templates(cur, templates: list[dict]) -> None:
    for tp in templates:
        if not isinstance(tp, dict):
            continue
        name = str(tp.get("name") or "").strip()
        if not name:
            continue
        payload_json = tp.get("payload_json")
        if payload_json is None and "payload" in tp:
            try:
                payload_json = json.dumps(tp.get("payload") or {}, ensure_ascii=False)
            except Exception:
                payload_json = "{}"
        if payload_json is None:
            payload_json = "{}"
        cur.execute(
            """
            INSERT INTO task_templates(name, payload_json, created_at, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at;
            """,
            (
                name,
                str(payload_json),
                str(tp.get("created_at") or now_iso()),
                str(tp.get("updated_at") or now_iso()),
            ),
        )


def _insert_custom_values(cur, task_id: int, custom: dict, tgt_cols: dict, report: ImportReport) -> None:
    if not isinstance(custom, dict):
        return

    for name, value in custom.items():
        if name not in tgt_cols:
            report.skipped_values += 1
            continue
        col_id, _col_type = tgt_cols[name]
        cur.execute(
            """
            INSERT INTO task_custom_values(task_id, column_id, value)
            VALUES(?, ?, ?)
            ON CONFLICT(task_id, column_id) DO UPDATE SET value=excluded.value;
            """,
            (int(task_id), int(col_id), None if value is None else str(value)),
        )
        if _col_type == "list" and value is not None:
            sv = str(value).strip()
            if sv:
                cur.execute(
                    "SELECT 1 FROM custom_column_list_values WHERE column_id=? AND value=?;",
                    (int(col_id), sv),
                )
                if not cur.fetchone():
                    cur.execute(
                        """
                        SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                        FROM custom_column_list_values
                        WHERE column_id=?;
                        """,
                        (int(col_id),),
                    )
                    next_order = int(cur.fetchone()["next_order"])
                    cur.execute(
                        """
                        INSERT INTO custom_column_list_values(column_id, value, sort_order)
                        VALUES(?, ?, ?)
                        ON CONFLICT(column_id, value) DO NOTHING;
                        """,
                        (int(col_id), sv, next_order),
                    )
        report.imported_values += 1


def _get_target_columns(db: Database) -> dict[str, tuple[int, str]]:
    cur = db.conn.cursor()
    cur.execute("SELECT id, name, col_type FROM custom_columns;")
    out = {}
    for r in cur.fetchall():
        out[str(r["name"])] = (int(r["id"]), str(r["col_type"]) if r["col_type"] in ALLOWED_COL_TYPES else "text")
    return out


def _normalize_list_values(values) -> list[str]:
    if not isinstance(values, list):
        return []
    out = []
    seen = set()
    for v in values:
        s = str(v).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _count_target_tasks(db: Database) -> int:
    cur = db.conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM tasks;")
    return int(cur.fetchone()["c"])


def _validate_payload_shape(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise BackupError("Backup payload is not a JSON object.")

    fmt = int(payload.get("format_version", -1))
    if fmt not in SUPPORTED_FORMAT_VERSIONS:
        raise BackupError(f"Unsupported backup format_version: {payload.get('format_version')}")

    if "custom_columns" not in payload or not isinstance(payload["custom_columns"], list):
        raise BackupError("Backup is missing 'custom_columns' list.")

    if "tasks" not in payload or not isinstance(payload["tasks"], list):
        raise BackupError("Backup is missing 'tasks' list.")

    seen = set()
    for c in payload["custom_columns"]:
        if not isinstance(c, dict):
            raise BackupError("Invalid custom_columns entry (not an object).")
        name = str(c.get("name", "")).strip()
        if not name:
            raise BackupError("Custom column with empty name found in backup.")
        lv = c.get("list_values")
        if lv is not None and not isinstance(lv, list):
            raise BackupError("Custom column 'list_values' must be a list if present.")
        if name in seen:
            raise BackupError(f"Duplicate custom column name in backup: {name}")
        seen.add(name)

    for t in payload["tasks"]:
        if not isinstance(t, dict):
            raise BackupError("Invalid task entry (not an object).")
        if "id" not in t:
            raise BackupError("Task missing 'id' in backup.")
        if "custom" in t and t["custom"] is not None and not isinstance(t["custom"], dict):
            raise BackupError("Task 'custom' must be an object if present.")
        if "tags" in t and t["tags"] is not None and not isinstance(t["tags"], list):
            raise BackupError("Task 'tags' must be a list if present.")
        if "attachments" in t and t["attachments"] is not None and not isinstance(t["attachments"], list):
            raise BackupError("Task 'attachments' must be a list if present.")
        if "dependencies" in t and t["dependencies"] is not None and not isinstance(t["dependencies"], list):
            raise BackupError("Task 'dependencies' must be a list if present.")

    if "saved_filter_views" in payload and not isinstance(payload["saved_filter_views"], list):
        raise BackupError("Backup field 'saved_filter_views' must be a list if present.")

    if "templates" in payload and not isinstance(payload["templates"], list):
        raise BackupError("Backup field 'templates' must be a list if present.")

    if "recurrence_rules" in payload and not isinstance(payload["recurrence_rules"], list):
        raise BackupError("Backup field 'recurrence_rules' must be a list if present.")

    for key in (
        "project_profiles",
        "project_phases",
        "pm_dependencies",
        "milestones",
        "deliverables",
        "project_register_entries",
        "project_baselines",
    ):
        if key in payload and not isinstance(payload[key], list):
            raise BackupError(f"Backup field '{key}' must be a list if present.")


def _sha256_canonical_json(obj: dict) -> str:
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _format_exception_message(prefix: str, e: Exception) -> str:
    return (
        f"{prefix}.\n\n"
        f"Type: {type(e).__name__}\n"
        f"Details: {e}\n\n"
        "Tip: If you need deeper debugging, run the app from a terminal to see tracebacks."
    )


def _format_success_report(report: ImportReport, target_db_path: str) -> str:
    lines = [
        "Import finished without errors.",
        "",
        f"Target DB: {target_db_path}",
        f"Mode: {report.mode}",
        "",
        f"Tasks imported: {report.imported_tasks}",
        f"Custom values imported: {report.imported_values}",
    ]
    if report.created_columns:
        lines.append(f"Custom columns created: {report.created_columns}")
    if report.skipped_columns:
        lines.append(f"Custom columns skipped: {report.skipped_columns}")
    if report.skipped_values:
        lines.append(f"Custom values skipped (missing columns): {report.skipped_values}")
    lines.append("")
    lines.append("You can now open the new database file in your app.")
    return "\n".join(lines)
