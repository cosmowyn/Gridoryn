import json
import sqlite3
from calendar import monthrange
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from app_paths import app_data_dir
from crash_logging import log_event
from project_intelligence import analyze_projects, analyze_workload
from project_management import (
    DEFAULT_PHASE_NAMES,
    DELIVERABLE_STATUSES,
    DEPENDENCY_TYPE_FINISH_TO_START,
    MILESTONE_STATUSES,
    PROJECT_HEALTH_STATES,
    REGISTER_ENTRY_TYPES,
    REGISTER_STATUSES,
    build_project_summary,
    build_timeline_rows,
    compute_baseline_variance,
    compute_personal_capacity,
    default_phases_payload,
    health_label,
    is_dependency_blocked,
    normalize_dependency_refs,
    normalize_health,
    normalize_record_status,
    normalize_register_type,
    parse_iso_date as pm_parse_iso_date,
    validate_dependency_graph,
)


RECURRENCE_FREQUENCIES = {"daily", "weekly", "monthly", "yearly"}
LATEST_SCHEMA_VERSION = 8
MAX_CATEGORY_FOLDER_DEPTH = 10


class DatabaseError(RuntimeError):
    pass


class DatabaseMigrationError(DatabaseError):
    pass


class IntegrityRepairError(DatabaseError):
    pass


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_iso_datetime(s: str | None) -> datetime | None:
    raw = str(s or "").strip()
    if not raw:
        return None
    norm = raw.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(norm, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(norm)
    except Exception:
        return None


def _add_months(d: date, months: int) -> date:
    idx = (d.month - 1) + int(months)
    y = d.year + (idx // 12)
    m = (idx % 12) + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def _advance_recurrence_due(d: date, frequency: str) -> date:
    freq = str(frequency or "").strip().lower()
    if freq == "daily":
        return d + timedelta(days=1)
    if freq == "weekly":
        return d + timedelta(days=7)
    if freq == "monthly":
        return _add_months(d, 1)
    if freq == "yearly":
        return _add_months(d, 12)
    return d


class Database:
    def __init__(self, path: str):
        self.path = path
        self._pre_migration_backup_path: str | None = None
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        try:
            self._configure()
            self._migrate_with_validation()
        except Exception:
            try:
                self.conn.close()
            except Exception:
                pass
            raise

    def close(self):
        conn = getattr(self, "conn", None)
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass
        self.conn = None

    def _configure(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA busy_timeout=4000;")
        self.conn.commit()

    def schema_user_version(self) -> int:
        cur = self.conn.cursor()
        cur.execute("PRAGMA user_version;")
        row = cur.fetchone()
        return int(row[0] if row is not None else 0)

    def pre_migration_backup_path(self) -> str | None:
        return self._pre_migration_backup_path

    def _migration_backups_dir(self) -> Path:
        path = Path(app_data_dir()) / "migration_backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _database_file_has_content(self) -> bool:
        if not self.path or self.path == ":memory:":
            return False
        try:
            p = Path(self.path)
            return p.exists() and p.stat().st_size > 0
        except Exception:
            return False

    def _create_pre_migration_backup(self, from_version: int, to_version: int) -> str:
        if not self._database_file_has_content():
            raise DatabaseMigrationError("Cannot create a pre-migration backup for a missing database file.")

        src_path = Path(self.path)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self._migration_backups_dir() / f"{src_path.stem}_v{from_version}_to_v{to_version}_{ts}.sqlite3"
        backup_conn = None
        try:
            backup_conn = sqlite3.connect(str(dest))
            self.conn.backup(backup_conn)
            backup_conn.commit()
        except Exception as e:
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass
            raise DatabaseMigrationError(f"Failed to create pre-migration backup: {e}") from e
        finally:
            if backup_conn is not None:
                try:
                    backup_conn.close()
                except Exception:
                    pass
        log_event(
            "Pre-migration backup created",
            context="db.migration.backup",
            db_path=self.path,
            details={"from_version": int(from_version), "to_version": int(to_version), "backup_path": str(dest)},
        )
        return str(dest)

    def _validate_schema(self, expected_version: int = LATEST_SCHEMA_VERSION) -> dict:
        issues: list[str] = []
        version = self.schema_user_version()
        if version != int(expected_version):
            issues.append(f"Expected schema user_version {expected_version}, found {version}.")

        required_tables = {
            "tasks",
            "category_folders",
            "custom_columns",
            "task_custom_values",
            "custom_column_list_values",
            "recurrence_rules",
            "tags",
            "task_tags",
            "saved_filter_views",
            "task_attachments",
            "task_dependencies",
            "task_templates",
            "project_profiles",
            "project_phases",
            "pm_dependencies",
            "milestones",
            "deliverables",
            "project_register_entries",
            "project_baselines",
        }
        cur = self.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {str(r["name"]) for r in cur.fetchall()}
        for name in sorted(required_tables - existing_tables):
            issues.append(f"Missing required table: {name}")

        required_task_columns = {
            "id",
            "description",
            "due_date",
            "last_update",
            "priority",
            "status",
            "parent_id",
            "sort_order",
            "is_collapsed",
            "notes",
            "archived_at",
            "planned_bucket",
            "effort_minutes",
            "actual_minutes",
            "timer_started_at",
            "waiting_for",
            "recurrence_rule_id",
            "recurrence_origin_task_id",
            "is_generated_occurrence",
            "reminder_at",
            "reminder_minutes_before",
            "reminder_fired_at",
            "start_date",
            "phase_id",
            "category_folder_id",
            "gantt_color_hex",
        }
        if "tasks" in existing_tables:
            cur.execute("PRAGMA table_info(tasks);")
            task_columns = {str(r["name"]) for r in cur.fetchall()}
            for name in sorted(required_task_columns - task_columns):
                issues.append(f"Missing required tasks column: {name}")

        required_milestone_columns = {
            "id",
            "project_task_id",
            "title",
            "description",
            "phase_id",
            "linked_task_id",
            "start_date",
            "target_date",
            "baseline_target_date",
            "status",
            "progress_percent",
            "completed_at",
            "created_at",
            "updated_at",
            "gantt_color_hex",
        }
        if "milestones" in existing_tables:
            cur.execute("PRAGMA table_info(milestones);")
            milestone_columns = {str(r["name"]) for r in cur.fetchall()}
            for name in sorted(required_milestone_columns - milestone_columns):
                issues.append(f"Missing required milestones column: {name}")

        required_deliverable_columns = {
            "id",
            "project_task_id",
            "title",
            "description",
            "phase_id",
            "linked_task_id",
            "linked_milestone_id",
            "due_date",
            "baseline_due_date",
            "acceptance_criteria",
            "version_ref",
            "status",
            "completed_at",
            "created_at",
            "updated_at",
            "gantt_color_hex",
        }
        if "deliverables" in existing_tables:
            cur.execute("PRAGMA table_info(deliverables);")
            deliverable_columns = {str(r["name"]) for r in cur.fetchall()}
            for name in sorted(required_deliverable_columns - deliverable_columns):
                issues.append(f"Missing required deliverables column: {name}")

        required_phase_columns = {
            "id",
            "project_task_id",
            "name",
            "sort_order",
            "gantt_color_hex",
            "created_at",
            "updated_at",
        }
        if "project_phases" in existing_tables:
            cur.execute("PRAGMA table_info(project_phases);")
            phase_columns = {str(r["name"]) for r in cur.fetchall()}
            for name in sorted(required_phase_columns - phase_columns):
                issues.append(f"Missing required project_phases column: {name}")

        return {"ok": not issues, "schema_version": version, "issues": issues}

    def schema_validation_report(self) -> dict:
        return self._validate_schema(expected_version=LATEST_SCHEMA_VERSION)

    def _migrate_with_validation(self):
        start_version = self.schema_user_version()
        if start_version < 0:
            raise DatabaseMigrationError(f"Invalid schema user_version: {start_version}")
        if start_version > LATEST_SCHEMA_VERSION:
            raise DatabaseMigrationError(
                f"Database schema version {start_version} is newer than this app supports ({LATEST_SCHEMA_VERSION})."
            )

        if start_version < LATEST_SCHEMA_VERSION and self._database_file_has_content():
            self._pre_migration_backup_path = self._create_pre_migration_backup(start_version, LATEST_SCHEMA_VERSION)

        try:
            if start_version < LATEST_SCHEMA_VERSION:
                log_event(
                    "Database migration started",
                    context="db.migration",
                    db_path=self.path,
                    details={"from_version": int(start_version), "to_version": int(LATEST_SCHEMA_VERSION)},
                )
            self._migrate()
            validation = self._validate_schema(expected_version=LATEST_SCHEMA_VERSION)
            if not validation["ok"]:
                message = "Migration completed but schema validation failed:\n- " + "\n- ".join(validation["issues"])
                if self._pre_migration_backup_path:
                    message += f"\nPre-migration backup: {self._pre_migration_backup_path}"
                raise DatabaseMigrationError(message)
            if start_version < LATEST_SCHEMA_VERSION:
                log_event(
                    "Database migration completed",
                    context="db.migration",
                    db_path=self.path,
                    details={
                        "from_version": int(start_version),
                        "to_version": int(LATEST_SCHEMA_VERSION),
                        "pre_migration_backup_path": self._pre_migration_backup_path or "",
                    },
                )
        except DatabaseMigrationError:
            raise
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            message = f"Database migration failed from schema version {start_version}: {e}"
            if self._pre_migration_backup_path:
                message += f"\nPre-migration backup: {self._pre_migration_backup_path}"
            raise DatabaseMigrationError(message) from e

    def _migrate(self):
        cur = self.conn.cursor()
        ver = self.schema_user_version()

        if ver < 1:
            self._create_v1()
            cur.execute("PRAGMA user_version=1;")
            self.conn.commit()
            ver = 1

        if ver < 2:
            self._migrate_to_v2_hierarchy()
            cur.execute("PRAGMA user_version=2;")
            self.conn.commit()
            ver = 2

        if ver < 3:
            self._migrate_to_v3_custom_list_values()
            cur.execute("PRAGMA user_version=3;")
            self.conn.commit()
            ver = 3

        if ver < 4:
            self._migrate_to_v4_productivity()
            cur.execute("PRAGMA user_version=4;")
            self.conn.commit()
            ver = 4

        if ver < 5:
            self._migrate_to_v5_project_management()
            cur.execute("PRAGMA user_version=5;")
            self.conn.commit()
            ver = 5

        if ver < 6:
            self._migrate_to_v6_category_folders()
            cur.execute("PRAGMA user_version=6;")
            self.conn.commit()
            ver = 6

        if ver < 7:
            self._migrate_to_v7_gantt_item_colors()
            cur.execute("PRAGMA user_version=7;")
            self.conn.commit()
            ver = 7

        if ver < 8:
            self._migrate_to_v8_phase_gantt_colors()
            cur.execute("PRAGMA user_version=8;")
            self.conn.commit()
            ver = 8

    def _create_v1(self):
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT    NOT NULL DEFAULT '',
                due_date    TEXT    NULL,              -- ISO date: YYYY-MM-DD
                last_update TEXT    NOT NULL,
                priority    INTEGER NOT NULL DEFAULT 3, -- 1..5
                status      TEXT    NOT NULL DEFAULT 'Todo',
                sort_order  INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_sort ON tasks(sort_order);

            CREATE TABLE IF NOT EXISTS custom_columns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL UNIQUE,
                col_type    TEXT    NOT NULL,           -- text|int|date|bool
                created_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_custom_values (
                task_id     INTEGER NOT NULL,
                column_id   INTEGER NOT NULL,
                value       TEXT    NULL,
                PRIMARY KEY (task_id, column_id),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (column_id) REFERENCES custom_columns(id) ON DELETE CASCADE
            );
            """
        )
        self.conn.commit()

    def _migrate_to_v2_hierarchy(self):
        """
        Adds:
          - parent_id (self-referential FK, cascade delete)
          - is_collapsed (persist UI collapse)
          - per-parent sort_order usage (index)
        """
        cur = self.conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
        if not cur.fetchone():
            # Fresh DB (shouldn't happen if v1 ran), just create v2
            self._create_tasks_v2_table()
            return

        # Create new table
        self._create_tasks_v2_table(temp_name="tasks_new")

        # Copy existing tasks (as top-level)
        cur.execute(
            """
            INSERT INTO tasks_new (id, description, due_date, last_update, priority, status, parent_id, sort_order, is_collapsed)
            SELECT id, description, due_date, last_update, priority, status, NULL, sort_order, 0
            FROM tasks;
            """
        )

        # Swap tables
        cur.execute("DROP TABLE tasks;")
        cur.execute("ALTER TABLE tasks_new RENAME TO tasks;")

        # Recreate indexes
        cur.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_parent_sort ON tasks(parent_id, sort_order);
            """
        )
        self.conn.commit()

    def _create_tasks_v2_table(self, temp_name: str = "tasks_new"):
        cur = self.conn.cursor()
        cur.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {temp_name} (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                description  TEXT    NOT NULL DEFAULT '',
                due_date     TEXT    NULL,               -- ISO date YYYY-MM-DD
                last_update  TEXT    NOT NULL,
                priority     INTEGER NOT NULL DEFAULT 3,  -- 1..5
                status       TEXT    NOT NULL DEFAULT 'Todo',
                parent_id    INTEGER NULL,
                sort_order   INTEGER NOT NULL,
                is_collapsed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (parent_id) REFERENCES {temp_name}(id) ON DELETE CASCADE
            );
            """
        )

    def _migrate_to_v3_custom_list_values(self):
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS custom_column_list_values (
                column_id   INTEGER NOT NULL,
                value       TEXT    NOT NULL,
                sort_order  INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (column_id, value),
                FOREIGN KEY (column_id) REFERENCES custom_columns(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_custom_column_list_values_col_sort
            ON custom_column_list_values(column_id, sort_order, value);
            """
        )

    def _column_exists(self, table: str, column: str) -> bool:
        cur = self.conn.cursor()
        cur.execute(f"PRAGMA table_info({table});")
        return any(str(r["name"]) == str(column) for r in cur.fetchall())

    def _add_column_if_missing(self, table: str, column: str, ddl: str):
        if self._column_exists(table, column):
            return
        cur = self.conn.cursor()
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl};")

    def _migrate_to_v4_productivity(self):
        cur = self.conn.cursor()

        # Additive task metadata (safe for existing databases)
        self._add_column_if_missing("tasks", "notes", "TEXT NOT NULL DEFAULT ''")
        self._add_column_if_missing("tasks", "archived_at", "TEXT NULL")
        self._add_column_if_missing("tasks", "planned_bucket", "TEXT NOT NULL DEFAULT 'inbox'")
        self._add_column_if_missing("tasks", "effort_minutes", "INTEGER NULL")
        self._add_column_if_missing("tasks", "actual_minutes", "INTEGER NOT NULL DEFAULT 0")
        self._add_column_if_missing("tasks", "timer_started_at", "TEXT NULL")
        self._add_column_if_missing("tasks", "waiting_for", "TEXT NULL")
        self._add_column_if_missing("tasks", "recurrence_rule_id", "INTEGER NULL")
        self._add_column_if_missing("tasks", "recurrence_origin_task_id", "INTEGER NULL")
        self._add_column_if_missing("tasks", "is_generated_occurrence", "INTEGER NOT NULL DEFAULT 0")
        self._add_column_if_missing("tasks", "reminder_at", "TEXT NULL")
        self._add_column_if_missing("tasks", "reminder_minutes_before", "INTEGER NULL")
        self._add_column_if_missing("tasks", "reminder_fired_at", "TEXT NULL")

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS recurrence_rules (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id              INTEGER NOT NULL UNIQUE,
                frequency            TEXT    NOT NULL, -- daily|weekly|monthly|yearly
                create_next_on_done  INTEGER NOT NULL DEFAULT 1,
                is_active            INTEGER NOT NULL DEFAULT 1,
                created_at           TEXT    NOT NULL,
                updated_at           TEXT    NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_recurrence_rules_task ON recurrence_rules(task_id);

            CREATE TABLE IF NOT EXISTS tags (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_tags (
                task_id INTEGER NOT NULL,
                tag_id  INTEGER NOT NULL,
                PRIMARY KEY(task_id, tag_id),
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_task_tags_tag_task ON task_tags(tag_id, task_id);

            CREATE TABLE IF NOT EXISTS saved_filter_views (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                state_json  TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_attachments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL,
                path        TEXT    NOT NULL,
                label       TEXT    NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_task_attachments_task ON task_attachments(task_id, id);

            CREATE TABLE IF NOT EXISTS task_dependencies (
                task_id              INTEGER NOT NULL,
                depends_on_task_id   INTEGER NOT NULL,
                PRIMARY KEY(task_id, depends_on_task_id),
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(depends_on_task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_task_dependencies_dep ON task_dependencies(depends_on_task_id, task_id);

            CREATE TABLE IF NOT EXISTS task_templates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_archived ON tasks(archived_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_bucket ON tasks(planned_bucket);
            CREATE INDEX IF NOT EXISTS idx_tasks_reminder_due ON tasks(reminder_at, reminder_fired_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_recurrence ON tasks(recurrence_rule_id, is_generated_occurrence);
            """
        )

        # Normalize default buckets for legacy rows
        cur.execute(
            """
            UPDATE tasks
            SET planned_bucket='inbox'
            WHERE planned_bucket IS NULL OR TRIM(planned_bucket)='';
            """
        )

    def _migrate_to_v5_project_management(self):
        cur = self.conn.cursor()

        self._add_column_if_missing("tasks", "start_date", "TEXT NULL")
        self._add_column_if_missing("tasks", "phase_id", "INTEGER NULL")

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_profiles (
                task_id                INTEGER PRIMARY KEY,
                objective              TEXT    NOT NULL DEFAULT '',
                scope                  TEXT    NOT NULL DEFAULT '',
                out_of_scope           TEXT    NOT NULL DEFAULT '',
                owner                  TEXT    NOT NULL DEFAULT 'Self',
                stakeholders           TEXT    NOT NULL DEFAULT '',
                target_date            TEXT    NULL,
                success_criteria       TEXT    NOT NULL DEFAULT '',
                project_status_health  TEXT    NULL,
                summary                TEXT    NOT NULL DEFAULT '',
                category               TEXT    NOT NULL DEFAULT '',
                created_at             TEXT    NOT NULL,
                updated_at             TEXT    NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_phases (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                project_task_id  INTEGER NOT NULL,
                name             TEXT    NOT NULL,
                sort_order       INTEGER NOT NULL DEFAULT 1,
                gantt_color_hex  TEXT    NULL,
                created_at       TEXT    NOT NULL,
                updated_at       TEXT    NOT NULL,
                UNIQUE(project_task_id, name),
                FOREIGN KEY(project_task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_project_phases_project_sort
            ON project_phases(project_task_id, sort_order, id);

            CREATE TABLE IF NOT EXISTS pm_dependencies (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                predecessor_kind  TEXT    NOT NULL,
                predecessor_id    INTEGER NOT NULL,
                successor_kind    TEXT    NOT NULL,
                successor_id      INTEGER NOT NULL,
                dep_type          TEXT    NOT NULL DEFAULT 'finish_to_start',
                is_soft           INTEGER NOT NULL DEFAULT 0,
                created_at        TEXT    NOT NULL,
                UNIQUE(predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type)
            );

            CREATE INDEX IF NOT EXISTS idx_pm_dependencies_successor
            ON pm_dependencies(successor_kind, successor_id, predecessor_kind, predecessor_id);

            CREATE INDEX IF NOT EXISTS idx_pm_dependencies_predecessor
            ON pm_dependencies(predecessor_kind, predecessor_id, successor_kind, successor_id);

            CREATE TABLE IF NOT EXISTS milestones (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                project_task_id       INTEGER NOT NULL,
                title                 TEXT    NOT NULL,
                description           TEXT    NOT NULL DEFAULT '',
                phase_id              INTEGER NULL,
                linked_task_id        INTEGER NULL,
                start_date            TEXT    NULL,
                target_date           TEXT    NULL,
                baseline_target_date  TEXT    NULL,
                status                TEXT    NOT NULL DEFAULT 'planned',
                progress_percent      INTEGER NOT NULL DEFAULT 0,
                completed_at          TEXT    NULL,
                created_at            TEXT    NOT NULL,
                updated_at            TEXT    NOT NULL,
                FOREIGN KEY(project_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(phase_id) REFERENCES project_phases(id) ON DELETE SET NULL,
                FOREIGN KEY(linked_task_id) REFERENCES tasks(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_milestones_project_target
            ON milestones(project_task_id, target_date, status, id);

            CREATE TABLE IF NOT EXISTS deliverables (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                project_task_id      INTEGER NOT NULL,
                title                TEXT    NOT NULL,
                description          TEXT    NOT NULL DEFAULT '',
                phase_id             INTEGER NULL,
                linked_task_id       INTEGER NULL,
                linked_milestone_id  INTEGER NULL,
                due_date             TEXT    NULL,
                baseline_due_date    TEXT    NULL,
                acceptance_criteria  TEXT    NOT NULL DEFAULT '',
                version_ref          TEXT    NOT NULL DEFAULT '',
                status               TEXT    NOT NULL DEFAULT 'planned',
                completed_at         TEXT    NULL,
                created_at           TEXT    NOT NULL,
                updated_at           TEXT    NOT NULL,
                FOREIGN KEY(project_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(phase_id) REFERENCES project_phases(id) ON DELETE SET NULL,
                FOREIGN KEY(linked_task_id) REFERENCES tasks(id) ON DELETE SET NULL,
                FOREIGN KEY(linked_milestone_id) REFERENCES milestones(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_deliverables_project_due
            ON deliverables(project_task_id, due_date, status, id);

            CREATE TABLE IF NOT EXISTS project_register_entries (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                project_task_id     INTEGER NOT NULL,
                entry_type          TEXT    NOT NULL,
                title               TEXT    NOT NULL,
                details             TEXT    NOT NULL DEFAULT '',
                status              TEXT    NOT NULL DEFAULT 'open',
                severity            INTEGER NULL,
                review_date         TEXT    NULL,
                linked_task_id      INTEGER NULL,
                linked_milestone_id INTEGER NULL,
                created_at          TEXT    NOT NULL,
                updated_at          TEXT    NOT NULL,
                FOREIGN KEY(project_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(linked_task_id) REFERENCES tasks(id) ON DELETE SET NULL,
                FOREIGN KEY(linked_milestone_id) REFERENCES milestones(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_project_register_entries_project
            ON project_register_entries(project_task_id, entry_type, status, id);

            CREATE TABLE IF NOT EXISTS project_baselines (
                project_task_id  INTEGER PRIMARY KEY,
                target_date      TEXT    NULL,
                effort_minutes   INTEGER NULL,
                created_at       TEXT    NOT NULL,
                updated_at       TEXT    NOT NULL,
                FOREIGN KEY(project_task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_phase_id ON tasks(phase_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_start_date ON tasks(start_date);
            """
        )

    def _migrate_to_v6_category_folders(self):
        cur = self.conn.cursor()

        self._add_column_if_missing("tasks", "category_folder_id", "INTEGER NULL")

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS category_folders (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT    NOT NULL,
                parent_folder_id  INTEGER NULL,
                sort_order        INTEGER NOT NULL DEFAULT 1,
                color_hex         TEXT    NULL,
                icon_name         TEXT    NOT NULL DEFAULT 'folder',
                identifier        TEXT    NULL,
                created_at        TEXT    NOT NULL,
                updated_at        TEXT    NOT NULL,
                FOREIGN KEY(parent_folder_id) REFERENCES category_folders(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_category_folders_parent_sort
            ON category_folders(parent_folder_id, sort_order, id);

            CREATE INDEX IF NOT EXISTS idx_tasks_category_folder_id
            ON tasks(category_folder_id);
            """
        )

    def _migrate_to_v7_gantt_item_colors(self):
        cur = self.conn.cursor()

        self._add_column_if_missing("tasks", "gantt_color_hex", "TEXT NULL")
        self._add_column_if_missing("milestones", "gantt_color_hex", "TEXT NULL")
        self._add_column_if_missing("deliverables", "gantt_color_hex", "TEXT NULL")

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
            SELECT
                'task',
                td.depends_on_task_id,
                'task',
                td.task_id,
                'finish_to_start',
                0,
                ?
            FROM task_dependencies td
            WHERE NOT EXISTS (
                SELECT 1
                FROM pm_dependencies pd
                WHERE pd.predecessor_kind='task'
                  AND pd.predecessor_id=td.depends_on_task_id
                  AND pd.successor_kind='task'
                  AND pd.successor_id=td.task_id
                  AND pd.dep_type='finish_to_start'
            );
            """,
            (now_iso(),),
        )

    def _migrate_to_v8_phase_gantt_colors(self):
        self._add_column_if_missing("project_phases", "gantt_color_hex", "TEXT NULL")

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---------- Category folders ----------
    def fetch_category_folders(self) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, name, parent_folder_id, sort_order, color_hex, icon_name, identifier, created_at, updated_at
            FROM category_folders
            ORDER BY sort_order ASC, LOWER(name), id ASC;
            """
        )
        rows = [dict(row) for row in cur.fetchall()]
        by_id = {int(row["id"]): row for row in rows if row.get("id") is not None}
        children_by_parent: dict[int | None, list[dict]] = {}
        for row in rows:
            parent_id = row.get("parent_folder_id")
            parent_key = int(parent_id) if parent_id is not None else None
            children_by_parent.setdefault(parent_key, []).append(row)

        ordered: list[dict] = []

        def walk(parent_id: int | None, parts: list[str], depth: int):
            for child in sorted(
                children_by_parent.get(parent_id, []),
                key=lambda item: (
                    int(item.get("sort_order") or 0),
                    str(item.get("name") or "").lower(),
                    int(item.get("id") or 0),
                ),
            ):
                current_parts = parts + [str(child.get("name") or "")]
                child["depth"] = depth
                child["path"] = " / ".join(p for p in current_parts if p)
                identifier = str(child.get("identifier") or "").strip()
                child["display_name"] = (
                    f"[{identifier}] {child['name']}" if identifier else str(child.get("name") or "")
                )
                ordered.append(child)
                walk(int(child["id"]), current_parts, depth + 1)

        walk(None, [], 0)
        for row in rows:
            row.setdefault("depth", 0)
            row.setdefault("path", str(row.get("name") or ""))
            row.setdefault("display_name", str(row.get("name") or ""))
            row["child_folder_count"] = len(children_by_parent.get(int(row["id"]), []))
            row["is_leaf"] = row["child_folder_count"] == 0
        return ordered

    def fetch_category_folder(self, folder_id: int | None) -> dict | None:
        if folder_id is None:
            return None
        target_id = int(folder_id)
        for row in self.fetch_category_folders():
            if int(row.get("id") or 0) == target_id:
                return row
        return None

    def fetch_category_folder_descendant_ids(self, folder_id: int) -> list[int]:
        cur = self.conn.cursor()
        cur.execute(
            """
            WITH RECURSIVE folder_tree(id) AS (
                SELECT id FROM category_folders WHERE id=?
                UNION ALL
                SELECT cf.id
                FROM category_folders cf
                JOIN folder_tree ft ON cf.parent_folder_id = ft.id
            )
            SELECT id FROM folder_tree ORDER BY id;
            """,
            (int(folder_id),),
        )
        return [int(row["id"]) for row in cur.fetchall()]

    def _folder_depth(self, folder_id: int | None) -> int:
        if folder_id is None:
            return 0
        rows = {int(row["id"]): row for row in self.fetch_category_folders() if row.get("id") is not None}
        depth = 0
        current = rows.get(int(folder_id))
        while current is not None and current.get("parent_folder_id") is not None:
            depth += 1
            current = rows.get(int(current["parent_folder_id"]))
        return depth

    def _normalize_folder_identifier(self, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    def _validate_folder_parent(self, parent_folder_id: int | None, *, moving_folder_id: int | None = None):
        if parent_folder_id is None:
            return
        parent = self.fetch_category_folder(int(parent_folder_id))
        if not parent:
            raise ValueError("Parent category not found.")
        if moving_folder_id is not None:
            target = int(parent_folder_id)
            moving = int(moving_folder_id)
            if target == moving:
                raise ValueError("A category cannot be its own parent.")
            descendant_ids = set(self.fetch_category_folder_descendant_ids(moving))
            if target in descendant_ids:
                raise ValueError("A category cannot be moved into one of its descendants.")
        next_depth = self._folder_depth(int(parent_folder_id)) + 1
        if next_depth >= MAX_CATEGORY_FOLDER_DEPTH:
            raise ValueError(
                f"Category nesting is limited to {MAX_CATEGORY_FOLDER_DEPTH} levels."
            )

    def create_category_folder(
        self,
        name: str,
        parent_folder_id: int | None = None,
        *,
        color_hex: str | None = None,
        icon_name: str | None = None,
        identifier: str | None = None,
    ) -> int:
        folder_name = str(name or "").strip()
        if not folder_name:
            raise ValueError("Category name is required.")
        parent_id = None if parent_folder_id is None else int(parent_folder_id)
        self._validate_folder_parent(parent_id)
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                FROM category_folders
                WHERE parent_folder_id IS ?;
                """,
                (parent_id,),
            )
            next_order = int(cur.fetchone()["next_order"])
            cur.execute(
                """
                INSERT INTO category_folders(
                    name,
                    parent_folder_id,
                    sort_order,
                    color_hex,
                    icon_name,
                    identifier,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    folder_name,
                    parent_id,
                    next_order,
                    str(color_hex or "").strip() or None,
                    str(icon_name or "folder").strip() or "folder",
                    self._normalize_folder_identifier(identifier),
                    now_iso(),
                    now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def update_category_folder(self, folder_id: int, payload: dict):
        existing = self.fetch_category_folder(int(folder_id))
        if not existing:
            raise ValueError("Category not found.")
        parent_id = payload.get("parent_folder_id", existing.get("parent_folder_id"))
        parent_id = None if parent_id in {"", None} else int(parent_id)
        self._validate_folder_parent(parent_id, moving_folder_id=int(folder_id))
        name = str(payload.get("name", existing.get("name")) or "").strip()
        if not name:
            raise ValueError("Category name is required.")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                UPDATE category_folders
                SET name=?,
                    parent_folder_id=?,
                    color_hex=?,
                    icon_name=?,
                    identifier=?,
                    updated_at=?
                WHERE id=?;
                """,
                (
                    name,
                    parent_id,
                    str(payload.get("color_hex", existing.get("color_hex")) or "").strip() or None,
                    str(payload.get("icon_name", existing.get("icon_name") or "folder")).strip() or "folder",
                    self._normalize_folder_identifier(
                        payload.get("identifier", existing.get("identifier"))
                    ),
                    now_iso(),
                    int(folder_id),
                ),
            )

    def delete_category_folder(self, folder_id: int):
        target_id = int(folder_id)
        cur = self.conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS child_count FROM category_folders WHERE parent_folder_id=?;",
            (target_id,),
        )
        child_count = int(cur.fetchone()["child_count"] or 0)
        cur.execute(
            """
            SELECT COUNT(*) AS task_count
            FROM tasks
            WHERE category_folder_id=?
              AND parent_id IS NULL
              AND archived_at IS NULL;
            """,
            (target_id,),
        )
        task_count = int(cur.fetchone()["task_count"] or 0)
        if child_count > 0:
            raise ValueError("Category must have no subcategories before it can be removed.")
        if task_count > 0:
            raise ValueError("Category must have no active top-level tasks before it can be removed.")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                UPDATE tasks
                SET category_folder_id=NULL,
                    last_update=?
                WHERE category_folder_id=?;
                """,
                (now_iso(), target_id),
            )
            cur.execute("DELETE FROM category_folders WHERE id=?;", (target_id,))

    def set_task_category_folder(self, task_id: int, folder_id: int | None):
        task = self.fetch_task_by_id(int(task_id))
        if not task:
            raise ValueError("Task not found.")
        if task.get("parent_id") is not None:
            raise ValueError("Only top-level tasks and projects can be assigned to a category.")
        folder_value = None if folder_id is None else int(folder_id)
        if folder_value is not None and not self.fetch_category_folder(folder_value):
            raise ValueError("Category not found.")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE tasks SET category_folder_id=?, last_update=? WHERE id=?;",
                (folder_value, now_iso(), int(task_id)),
            )

    # ---------- Diagnostics / integrity ----------
    def _broken_parent_links(self) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT t.id, t.description, t.parent_id
            FROM tasks t
            LEFT JOIN tasks p ON p.id = t.parent_id
            WHERE t.parent_id IS NOT NULL
              AND p.id IS NULL
            ORDER BY t.id;
            """
        )
        return [dict(r) for r in cur.fetchall()]

    def _invalid_sibling_sort_order_groups(self) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, parent_id, sort_order, description
            FROM tasks
            ORDER BY COALESCE(parent_id, 0), sort_order ASC, id ASC;
            """
        )
        by_parent: dict[int | None, list[dict]] = {}
        for row in cur.fetchall():
            item = dict(row)
            pid = item.get("parent_id")
            by_parent.setdefault(pid, []).append(item)

        groups: list[dict] = []
        for parent_id, rows in by_parent.items():
            expected_rows = []
            invalid = False
            for pos, row in enumerate(rows, start=1):
                current = int(row.get("sort_order") or 0)
                if current != pos:
                    invalid = True
                expected_rows.append(
                    {
                        "id": int(row["id"]),
                        "description": str(row.get("description") or ""),
                        "current_sort_order": current,
                        "expected_sort_order": pos,
                    }
                )
            if invalid:
                groups.append(
                    {
                        "parent_id": parent_id,
                        "task_count": len(rows),
                        "rows": expected_rows,
                    }
                )
        return groups

    def _orphaned_custom_values(self) -> dict[str, list[dict]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT tcv.task_id, tcv.column_id, tcv.value
            FROM task_custom_values tcv
            LEFT JOIN tasks t ON t.id = tcv.task_id
            WHERE t.id IS NULL
            ORDER BY tcv.task_id, tcv.column_id;
            """
        )
        missing_tasks = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT tcv.task_id, tcv.column_id, tcv.value
            FROM task_custom_values tcv
            LEFT JOIN custom_columns cc ON cc.id = tcv.column_id
            WHERE cc.id IS NULL
            ORDER BY tcv.task_id, tcv.column_id;
            """
        )
        missing_columns = [dict(r) for r in cur.fetchall()]
        return {"missing_tasks": missing_tasks, "missing_columns": missing_columns}

    def _malformed_recurrence_report(self) -> dict[str, list[dict]]:
        cur = self.conn.cursor()
        placeholders = ", ".join(["?"] * len(RECURRENCE_FREQUENCIES))

        cur.execute(
            f"""
            SELECT id, task_id, frequency, create_next_on_done, is_active
            FROM recurrence_rules
            WHERE LOWER(COALESCE(frequency, '')) NOT IN ({placeholders})
            ORDER BY id;
            """,
            tuple(sorted(RECURRENCE_FREQUENCIES)),
        )
        invalid_frequency_rules = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT rr.id, rr.task_id, rr.frequency
            FROM recurrence_rules rr
            LEFT JOIN tasks t ON t.id = rr.task_id
            WHERE t.id IS NULL
            ORDER BY rr.id;
            """
        )
        rules_missing_task = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT t.id, t.description, t.recurrence_rule_id
            FROM tasks t
            LEFT JOIN recurrence_rules rr ON rr.id = t.recurrence_rule_id
            WHERE t.recurrence_rule_id IS NOT NULL
              AND rr.id IS NULL
            ORDER BY t.id;
            """
        )
        task_rule_missing = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT t.id, t.description, t.recurrence_rule_id, rr.task_id AS rule_task_id
            FROM tasks t
            JOIN recurrence_rules rr ON rr.id = t.recurrence_rule_id
            WHERE rr.task_id <> t.id
            ORDER BY t.id;
            """
        )
        task_rule_mismatch = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT t.id, t.description, t.recurrence_origin_task_id
            FROM tasks t
            LEFT JOIN tasks origin ON origin.id = t.recurrence_origin_task_id
            WHERE t.is_generated_occurrence = 1
              AND t.recurrence_origin_task_id IS NOT NULL
              AND origin.id IS NULL
            ORDER BY t.id;
            """
        )
        generated_origin_missing = [dict(r) for r in cur.fetchall()]

        return {
            "invalid_frequency_rules": invalid_frequency_rules,
            "rules_missing_task": rules_missing_task,
            "task_rule_missing": task_rule_missing,
            "task_rule_mismatch": task_rule_mismatch,
            "generated_origin_missing": generated_origin_missing,
        }

    def _missing_file_attachments(self) -> list[dict]:
        rows = self.fetch_all_attachments()
        missing = []
        for row in rows:
            path = str(row.get("path") or "")
            if not path:
                missing.append(dict(row))
                continue
            try:
                if not Path(path).exists():
                    missing.append(dict(row))
            except Exception:
                missing.append(dict(row))
        return missing

    def _project_management_integrity_report(self) -> dict[str, list[dict]]:
        cur = self.conn.cursor()

        cur.execute(
            """
            SELECT t.id, t.description, t.phase_id
            FROM tasks t
            LEFT JOIN project_phases pp ON pp.id = t.phase_id
            WHERE t.phase_id IS NOT NULL
              AND pp.id IS NULL
            ORDER BY t.id;
            """
        )
        broken_task_phase_refs = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT pd.id, pd.predecessor_kind, pd.predecessor_id, pd.successor_kind, pd.successor_id
            FROM pm_dependencies pd
            LEFT JOIN tasks pt ON pd.predecessor_kind='task' AND pt.id = pd.predecessor_id
            LEFT JOIN milestones pm ON pd.predecessor_kind='milestone' AND pm.id = pd.predecessor_id
            LEFT JOIN tasks st ON pd.successor_kind='task' AND st.id = pd.successor_id
            LEFT JOIN milestones sm ON pd.successor_kind='milestone' AND sm.id = pd.successor_id
            WHERE (pd.predecessor_kind='task' AND pt.id IS NULL)
               OR (pd.predecessor_kind='milestone' AND pm.id IS NULL)
               OR (pd.successor_kind='task' AND st.id IS NULL)
               OR (pd.successor_kind='milestone' AND sm.id IS NULL)
               OR pd.predecessor_kind NOT IN ('task', 'milestone')
               OR pd.successor_kind NOT IN ('task', 'milestone')
            ORDER BY pd.id;
            """
        )
        broken_pm_dependencies = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT m.id, m.title, m.project_task_id, m.phase_id, m.linked_task_id
            FROM milestones m
            LEFT JOIN tasks p ON p.id = m.project_task_id
            LEFT JOIN project_phases pp ON pp.id = m.phase_id
            LEFT JOIN tasks t ON t.id = m.linked_task_id
            WHERE p.id IS NULL
               OR (m.phase_id IS NOT NULL AND pp.id IS NULL)
               OR (m.linked_task_id IS NOT NULL AND t.id IS NULL)
            ORDER BY m.id;
            """
        )
        malformed_milestones = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT d.id, d.title, d.project_task_id, d.phase_id, d.linked_task_id, d.linked_milestone_id
            FROM deliverables d
            LEFT JOIN tasks p ON p.id = d.project_task_id
            LEFT JOIN project_phases pp ON pp.id = d.phase_id
            LEFT JOIN tasks t ON t.id = d.linked_task_id
            LEFT JOIN milestones m ON m.id = d.linked_milestone_id
            WHERE p.id IS NULL
               OR (d.phase_id IS NOT NULL AND pp.id IS NULL)
               OR (d.linked_task_id IS NOT NULL AND t.id IS NULL)
               OR (d.linked_milestone_id IS NOT NULL AND m.id IS NULL)
            ORDER BY d.id;
            """
        )
        malformed_deliverables = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT r.id, r.project_task_id, r.entry_type, r.title, r.linked_task_id, r.linked_milestone_id
            FROM project_register_entries r
            LEFT JOIN tasks p ON p.id = r.project_task_id
            LEFT JOIN tasks t ON t.id = r.linked_task_id
            LEFT JOIN milestones m ON m.id = r.linked_milestone_id
            WHERE p.id IS NULL
               OR (r.linked_task_id IS NOT NULL AND t.id IS NULL)
               OR (r.linked_milestone_id IS NOT NULL AND m.id IS NULL)
               OR r.entry_type NOT IN ('risk', 'issue', 'assumption', 'decision')
            ORDER BY r.id;
            """
        )
        malformed_register_entries = [dict(row) for row in cur.fetchall()]

        return {
            "broken_task_phase_refs": broken_task_phase_refs,
            "broken_pm_dependencies": broken_pm_dependencies,
            "malformed_milestones": malformed_milestones,
            "malformed_deliverables": malformed_deliverables,
            "malformed_register_entries": malformed_register_entries,
        }

    def fetch_all_attachments(self) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, task_id, path, label, created_at
            FROM task_attachments
            ORDER BY task_id, id;
            """
        )
        return [dict(r) for r in cur.fetchall()]

    def collect_integrity_report(self, include_attachment_scan: bool = True) -> dict:
        cur = self.conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        integrity_rows = [str(r[0]) for r in cur.fetchall()]
        integrity_ok = len(integrity_rows) == 1 and integrity_rows[0].lower() == "ok"

        cur.execute("PRAGMA foreign_key_check;")
        foreign_key_violations = [
            {
                "table": str(r[0]),
                "rowid": int(r[1]),
                "parent": str(r[2]),
                "fkid": int(r[3]),
            }
            for r in cur.fetchall()
        ]

        broken_parents = self._broken_parent_links()
        invalid_sort_groups = self._invalid_sibling_sort_order_groups()
        orphaned_custom_values = self._orphaned_custom_values()
        malformed_recurrence = self._malformed_recurrence_report()
        project_management = self._project_management_integrity_report()
        missing_attachments = self._missing_file_attachments() if include_attachment_scan else []

        recurrence_issue_count = sum(len(v) for v in malformed_recurrence.values())
        orphan_issue_count = (
            len(orphaned_custom_values["missing_tasks"]) +
            len(orphaned_custom_values["missing_columns"])
        )
        pm_issue_count = sum(len(v) for v in project_management.values())
        preview = {
            "reset_broken_parent_links": len(broken_parents),
            "normalize_sort_order_groups": len(invalid_sort_groups),
            "delete_orphaned_custom_values": orphan_issue_count,
            "repair_recurrence_records": recurrence_issue_count,
            "repair_project_management_records": pm_issue_count,
        }

        return {
            "schema_version": self.schema_user_version(),
            "integrity_check": {
                "ok": integrity_ok,
                "result": integrity_rows[0] if integrity_rows else "unknown",
                "details": integrity_rows,
            },
            "foreign_key_violations": foreign_key_violations,
            "broken_parent_links": broken_parents,
            "invalid_sibling_sort_orders": invalid_sort_groups,
            "orphaned_custom_values": orphaned_custom_values,
            "malformed_recurrence": malformed_recurrence,
            "project_management": project_management,
            "missing_file_attachments": missing_attachments,
            "repair_preview": preview,
        }

    def repair_integrity_issues(self, report: dict | None = None) -> dict:
        source_report = report or self.collect_integrity_report(include_attachment_scan=False)
        broken_parents = list(source_report.get("broken_parent_links") or [])
        orphaned_custom_values = dict(source_report.get("orphaned_custom_values") or {})
        malformed_recurrence = dict(source_report.get("malformed_recurrence") or {})
        project_management = dict(source_report.get("project_management") or {})

        repaired = {
            "reset_broken_parent_links": 0,
            "normalized_sort_order_groups": 0,
            "normalized_sort_order_rows": 0,
            "deleted_orphaned_custom_values": 0,
            "deleted_invalid_recurrence_rules": 0,
            "cleared_invalid_task_recurrence_refs": 0,
            "cleared_invalid_generated_origins": 0,
            "cleared_invalid_task_phase_refs": 0,
            "deleted_invalid_pm_dependencies": 0,
            "repaired_invalid_milestones": 0,
            "repaired_invalid_deliverables": 0,
            "repaired_invalid_register_entries": 0,
        }

        try:
            with self.tx():
                cur = self.conn.cursor()
                stamp = now_iso()

                for row in broken_parents:
                    cur.execute(
                        "UPDATE tasks SET parent_id=NULL, last_update=? WHERE id=?;",
                        (stamp, int(row["id"])),
                    )
                    repaired["reset_broken_parent_links"] += int(cur.rowcount or 0)

                for row in orphaned_custom_values.get("missing_tasks") or []:
                    cur.execute(
                        "DELETE FROM task_custom_values WHERE task_id=? AND column_id=?;",
                        (int(row["task_id"]), int(row["column_id"])),
                    )
                    repaired["deleted_orphaned_custom_values"] += int(cur.rowcount or 0)

                for row in orphaned_custom_values.get("missing_columns") or []:
                    cur.execute(
                        "DELETE FROM task_custom_values WHERE task_id=? AND column_id=?;",
                        (int(row["task_id"]), int(row["column_id"])),
                    )
                    repaired["deleted_orphaned_custom_values"] += int(cur.rowcount or 0)

                invalid_rule_ids = {
                    int(r["id"]) for r in (malformed_recurrence.get("invalid_frequency_rules") or []) if r.get("id") is not None
                }
                invalid_rule_ids.update(
                    int(r["id"]) for r in (malformed_recurrence.get("rules_missing_task") or []) if r.get("id") is not None
                )
                for rule_id in sorted(invalid_rule_ids):
                    cur.execute("DELETE FROM recurrence_rules WHERE id=?;", (int(rule_id),))
                    repaired["deleted_invalid_recurrence_rules"] += int(cur.rowcount or 0)

                task_ids_to_clear = {
                    int(r["id"]) for r in (malformed_recurrence.get("task_rule_missing") or []) if r.get("id") is not None
                }
                task_ids_to_clear.update(
                    int(r["task_id"])
                    for r in (malformed_recurrence.get("invalid_frequency_rules") or [])
                    if r.get("task_id") is not None
                )
                task_ids_to_clear.update(
                    int(r["id"]) for r in (malformed_recurrence.get("task_rule_mismatch") or []) if r.get("id") is not None
                )
                for task_id in sorted(task_ids_to_clear):
                    cur.execute(
                        """
                        UPDATE tasks
                        SET recurrence_rule_id=NULL, last_update=?
                        WHERE id=?;
                        """,
                        (stamp, int(task_id)),
                    )
                    repaired["cleared_invalid_task_recurrence_refs"] += int(cur.rowcount or 0)

                for row in malformed_recurrence.get("generated_origin_missing") or []:
                    cur.execute(
                        """
                        UPDATE tasks
                        SET recurrence_origin_task_id=NULL,
                            is_generated_occurrence=0,
                            last_update=?
                        WHERE id=?;
                        """,
                        (stamp, int(row["id"])),
                    )
                    repaired["cleared_invalid_generated_origins"] += int(cur.rowcount or 0)

                for row in project_management.get("broken_task_phase_refs") or []:
                    cur.execute(
                        "UPDATE tasks SET phase_id=NULL, last_update=? WHERE id=?;",
                        (stamp, int(row["id"])),
                    )
                    repaired["cleared_invalid_task_phase_refs"] += int(cur.rowcount or 0)

                invalid_pm_ids = {
                    int(row["id"])
                    for row in (project_management.get("broken_pm_dependencies") or [])
                    if row.get("id") is not None
                }
                for dep_id in sorted(invalid_pm_ids):
                    cur.execute("DELETE FROM pm_dependencies WHERE id=?;", (int(dep_id),))
                    repaired["deleted_invalid_pm_dependencies"] += int(cur.rowcount or 0)

                for row in project_management.get("malformed_milestones") or []:
                    milestone_id = int(row["id"])
                    cur.execute(
                        """
                        SELECT id, project_task_id, phase_id, linked_task_id
                        FROM milestones
                        WHERE id=?;
                        """,
                        (milestone_id,),
                    )
                    current = cur.fetchone()
                    if not current:
                        continue
                    project_ok = self._project_exists(int(current["project_task_id"]))
                    if not project_ok:
                        cur.execute("DELETE FROM milestones WHERE id=?;", (milestone_id,))
                        repaired["repaired_invalid_milestones"] += int(cur.rowcount or 0)
                        continue
                    phase_id = current["phase_id"]
                    if phase_id is not None:
                        phase = self._phase_record(int(phase_id))
                        if not phase or int(phase["project_task_id"]) != int(current["project_task_id"]):
                            cur.execute("UPDATE milestones SET phase_id=NULL, updated_at=? WHERE id=?;", (stamp, milestone_id))
                            repaired["repaired_invalid_milestones"] += int(cur.rowcount or 0)
                    linked_task_id = current["linked_task_id"]
                    if linked_task_id is not None and not self._task_in_project(
                        int(linked_task_id),
                        int(current["project_task_id"]),
                    ):
                        cur.execute(
                            "UPDATE milestones SET linked_task_id=NULL, updated_at=? WHERE id=?;",
                            (stamp, milestone_id),
                        )
                        repaired["repaired_invalid_milestones"] += int(cur.rowcount or 0)

                for row in project_management.get("malformed_deliverables") or []:
                    deliverable_id = int(row["id"])
                    cur.execute(
                        """
                        SELECT id, project_task_id, phase_id, linked_task_id, linked_milestone_id
                        FROM deliverables
                        WHERE id=?;
                        """,
                        (deliverable_id,),
                    )
                    current = cur.fetchone()
                    if not current:
                        continue
                    project_ok = self._project_exists(int(current["project_task_id"]))
                    if not project_ok:
                        cur.execute("DELETE FROM deliverables WHERE id=?;", (deliverable_id,))
                        repaired["repaired_invalid_deliverables"] += int(cur.rowcount or 0)
                        continue
                    phase_id = current["phase_id"]
                    if phase_id is not None:
                        phase = self._phase_record(int(phase_id))
                        if not phase or int(phase["project_task_id"]) != int(current["project_task_id"]):
                            cur.execute(
                                "UPDATE deliverables SET phase_id=NULL, updated_at=? WHERE id=?;",
                                (stamp, deliverable_id),
                            )
                            repaired["repaired_invalid_deliverables"] += int(cur.rowcount or 0)
                    linked_task_id = current["linked_task_id"]
                    if linked_task_id is not None and not self._task_in_project(
                        int(linked_task_id),
                        int(current["project_task_id"]),
                    ):
                        cur.execute(
                            "UPDATE deliverables SET linked_task_id=NULL, updated_at=? WHERE id=?;",
                            (stamp, deliverable_id),
                        )
                        repaired["repaired_invalid_deliverables"] += int(cur.rowcount or 0)
                    linked_milestone_id = current["linked_milestone_id"]
                    if linked_milestone_id is not None and not self._milestone_in_project(
                        int(linked_milestone_id),
                        int(current["project_task_id"]),
                    ):
                        cur.execute(
                            "UPDATE deliverables SET linked_milestone_id=NULL, updated_at=? WHERE id=?;",
                            (stamp, deliverable_id),
                        )
                        repaired["repaired_invalid_deliverables"] += int(cur.rowcount or 0)

                for row in project_management.get("malformed_register_entries") or []:
                    entry_id = int(row["id"])
                    cur.execute(
                        """
                        SELECT id, project_task_id, entry_type, linked_task_id, linked_milestone_id
                        FROM project_register_entries
                        WHERE id=?;
                        """,
                        (entry_id,),
                    )
                    current = cur.fetchone()
                    if not current:
                        continue
                    project_ok = self._project_exists(int(current["project_task_id"]))
                    if not project_ok:
                        cur.execute("DELETE FROM project_register_entries WHERE id=?;", (entry_id,))
                        repaired["repaired_invalid_register_entries"] += int(cur.rowcount or 0)
                        continue
                    if str(current["entry_type"] or "") not in REGISTER_ENTRY_TYPES:
                        cur.execute(
                            "UPDATE project_register_entries SET entry_type='risk', updated_at=? WHERE id=?;",
                            (stamp, entry_id),
                        )
                        repaired["repaired_invalid_register_entries"] += int(cur.rowcount or 0)
                    linked_task_id = current["linked_task_id"]
                    if linked_task_id is not None and not self._task_in_project(
                        int(linked_task_id),
                        int(current["project_task_id"]),
                    ):
                        cur.execute(
                            "UPDATE project_register_entries SET linked_task_id=NULL, updated_at=? WHERE id=?;",
                            (stamp, entry_id),
                        )
                        repaired["repaired_invalid_register_entries"] += int(cur.rowcount or 0)
                    linked_milestone_id = current["linked_milestone_id"]
                    if linked_milestone_id is not None and not self._milestone_in_project(
                        int(linked_milestone_id),
                        int(current["project_task_id"]),
                    ):
                        cur.execute(
                            "UPDATE project_register_entries SET linked_milestone_id=NULL, updated_at=? WHERE id=?;",
                            (stamp, entry_id),
                        )
                        repaired["repaired_invalid_register_entries"] += int(cur.rowcount or 0)

                sort_groups = self._invalid_sibling_sort_order_groups()
                for group in sort_groups:
                    changed_in_group = 0
                    for row in group.get("rows") or []:
                        current = int(row.get("current_sort_order") or 0)
                        expected = int(row.get("expected_sort_order") or 0)
                        if current == expected:
                            continue
                        cur.execute(
                            "UPDATE tasks SET sort_order=?, last_update=? WHERE id=?;",
                            (expected, stamp, int(row["id"])),
                        )
                        changed_in_group += int(cur.rowcount or 0)
                    if changed_in_group > 0:
                        repaired["normalized_sort_order_groups"] += 1
                        repaired["normalized_sort_order_rows"] += changed_in_group
        except Exception as e:
            raise IntegrityRepairError(f"Integrity repair failed: {e}") from e

        post_report = self.collect_integrity_report(include_attachment_scan=False)
        repaired["remaining_issue_count"] = (
            len(post_report.get("broken_parent_links") or []) +
            len(post_report.get("invalid_sibling_sort_orders") or []) +
            len((post_report.get("orphaned_custom_values") or {}).get("missing_tasks") or []) +
            len((post_report.get("orphaned_custom_values") or {}).get("missing_columns") or []) +
            sum(len(v) for v in (post_report.get("malformed_recurrence") or {}).values()) +
            sum(len(v) for v in (post_report.get("project_management") or {}).values())
        )
        repaired["post_report"] = post_report
        return repaired

    # ---------- Custom columns ----------
    def fetch_custom_columns(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, name, col_type FROM custom_columns ORDER BY id;")
        cols = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT column_id, value
            FROM custom_column_list_values
            ORDER BY column_id, sort_order ASC, value ASC;
            """
        )
        list_rows = cur.fetchall()
        list_values_by_col = {}
        for r in list_rows:
            cid = int(r["column_id"])
            list_values_by_col.setdefault(cid, []).append(str(r["value"]))

        for c in cols:
            if str(c.get("col_type") or "") == "list":
                c["list_values"] = list_values_by_col.get(int(c["id"]), [])

        return cols

    def _normalize_list_values(self, list_values) -> list[str]:
        if not isinstance(list_values, list):
            return []
        out = []
        seen = set()
        for v in list_values:
            s = str(v).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    def _insert_list_values(self, cur, col_id: int, list_values: list[str]):
        for i, val in enumerate(list_values, start=1):
            cur.execute(
                """
                INSERT INTO custom_column_list_values(column_id, value, sort_order)
                VALUES(?, ?, ?)
                ON CONFLICT(column_id, value) DO NOTHING;
                """,
                (int(col_id), val, i),
            )

    def add_custom_column(self, name: str, col_type: str, list_values: list[str] | None = None) -> int:
        normalized = self._normalize_list_values(list_values)
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO custom_columns(name, col_type, created_at) VALUES(?, ?, ?);",
                (name.strip(), col_type, now_iso()),
            )
            col_id = int(cur.lastrowid)
            if col_type == "list" and normalized:
                self._insert_list_values(cur, col_id, normalized)
            return col_id

    def remove_custom_column(self, col_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("DELETE FROM custom_columns WHERE id=?;", (int(col_id),))

    def restore_custom_column(self, col: dict):
        list_values = self._normalize_list_values(col.get("list_values"))
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO custom_columns(id, name, col_type, created_at) VALUES(?, ?, ?, ?);",
                (int(col["id"]), col["name"], col["col_type"], col["created_at"]),
            )
            if str(col.get("col_type") or "") == "list" and list_values:
                self._insert_list_values(cur, int(col["id"]), list_values)

    def add_custom_column_list_value(self, col_id: int, value: str) -> bool:
        s = str(value).strip()
        if not s:
            return False
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "SELECT 1 FROM custom_column_list_values WHERE column_id=? AND value=?;",
                (int(col_id), s),
            )
            if cur.fetchone():
                return False

            cur.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM custom_column_list_values WHERE column_id=?;",
                (int(col_id),),
            )
            next_order = int(cur.fetchone()["next_order"])

            cur.execute(
                """
                INSERT INTO custom_column_list_values(column_id, value, sort_order)
                VALUES(?, ?, ?);
                """,
                (int(col_id), s, next_order),
            )
        return True

    # ---------- Tasks (hierarchy) ----------
    def fetch_tasks(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, description, due_date, last_update, priority, status,
                   parent_id, sort_order, is_collapsed,
                   notes, archived_at, planned_bucket,
                   effort_minutes, actual_minutes, timer_started_at,
                   waiting_for,
                   recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                   reminder_at, reminder_minutes_before, reminder_fired_at,
                   start_date, phase_id, category_folder_id, gantt_color_hex
            FROM tasks
            ORDER BY COALESCE(parent_id, 0), sort_order ASC, id ASC;
            """
        )
        tasks = [dict(r) for r in cur.fetchall()]

        folders_by_id = {
            int(row["id"]): row for row in self.fetch_category_folders()
            if row.get("id") is not None
        }

        # Load custom values in one pass
        cur.execute(
            """
            SELECT task_id, column_id, value
            FROM task_custom_values;
            """
        )
        cv = cur.fetchall()
        values_by_task = {}
        for r in cv:
            values_by_task.setdefault(r["task_id"], {})[r["column_id"]] = r["value"]

        cur.execute(
            """
            SELECT tt.task_id, tg.name
            FROM task_tags tt
            JOIN tags tg ON tg.id = tt.tag_id
            ORDER BY tt.task_id, LOWER(tg.name), tg.name;
            """
        )
        tags_by_task: dict[int, list[str]] = {}
        for r in cur.fetchall():
            tid = int(r["task_id"])
            tags_by_task.setdefault(tid, []).append(str(r["name"]))

        cur.execute(
            """
            SELECT task_id, COUNT(*) AS dep_count
            FROM task_dependencies
            GROUP BY task_id;
            """
        )
        deps_by_task = {int(r["task_id"]): int(r["dep_count"]) for r in cur.fetchall()}

        cur.execute(
            """
            SELECT task_id, depends_on_task_id
            FROM task_dependencies
            ORDER BY task_id, depends_on_task_id;
            """
        )
        dependency_ids_by_task: dict[int, list[int]] = {}
        for r in cur.fetchall():
            dependency_ids_by_task.setdefault(int(r["task_id"]), []).append(int(r["depends_on_task_id"]))

        cur.execute(
            """
            SELECT task_id, frequency, create_next_on_done, is_active
            FROM recurrence_rules;
            """
        )
        recurrence_by_task = {int(r["task_id"]): dict(r) for r in cur.fetchall()}

        cur.execute(
            """
            SELECT id, name, project_task_id
            FROM project_phases;
            """
        )
        phase_rows = {int(r["id"]): dict(r) for r in cur.fetchall()}

        for t in tasks:
            t["custom"] = values_by_task.get(t["id"], {})
            t["tags"] = tags_by_task.get(int(t["id"]), [])
            t["blocked_by_count"] = deps_by_task.get(int(t["id"]), 0)
            t["dependencies"] = dependency_ids_by_task.get(int(t["id"]), [])
            t["recurrence"] = recurrence_by_task.get(int(t["id"]))
            phase = phase_rows.get(int(t.get("phase_id") or 0))
            t["phase_name"] = str(phase.get("name") or "") if phase else ""
            t["phase_project_task_id"] = int(phase["project_task_id"]) if phase and phase.get("project_task_id") is not None else None
            folder = folders_by_id.get(int(t.get("category_folder_id") or 0))
            t["category_folder_name"] = str(folder.get("name") or "") if folder else ""
            t["category_folder_path"] = str(folder.get("path") or "") if folder else ""
            t["category_folder_display_name"] = str(folder.get("display_name") or "") if folder else ""
        return tasks

    def fetch_task_by_id(self, task_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, description, due_date, last_update, priority, status,
                   parent_id, sort_order, is_collapsed,
                   notes, archived_at, planned_bucket,
                   effort_minutes, actual_minutes, timer_started_at,
                   waiting_for,
                   recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                   reminder_at, reminder_minutes_before, reminder_fired_at,
                   start_date, phase_id, category_folder_id, gantt_color_hex
            FROM tasks
            WHERE id=?;
            """,
            (int(task_id),),
        )
        r = cur.fetchone()
        if not r:
            return None
        task = dict(r)

        cur.execute(
            "SELECT column_id, value FROM task_custom_values WHERE task_id=?;",
            (int(task_id),),
        )
        task["custom"] = {int(x["column_id"]): x["value"] for x in cur.fetchall()}
        task["tags"] = self.fetch_task_tags(int(task_id))

        cur.execute(
            """
            SELECT COUNT(*) AS dep_count
            FROM task_dependencies
            WHERE task_id=?;
            """,
            (int(task_id),),
        )
        dep_row = cur.fetchone()
        task["blocked_by_count"] = int(dep_row["dep_count"]) if dep_row else 0
        task["dependencies"] = [int(d["id"]) for d in self.fetch_dependencies(int(task_id))]

        if task.get("phase_id") is not None:
            cur.execute(
                """
                SELECT id, name, project_task_id
                FROM project_phases
                WHERE id=?;
                """,
                (int(task["phase_id"]),),
            )
            phase = cur.fetchone()
            task["phase_name"] = str(phase["name"]) if phase else ""
            task["phase_project_task_id"] = int(phase["project_task_id"]) if phase and phase["project_task_id"] is not None else None
        else:
            task["phase_name"] = ""
            task["phase_project_task_id"] = None

        folder = self.fetch_category_folder(int(task["category_folder_id"])) if task.get("category_folder_id") is not None else None
        task["category_folder_name"] = str(folder.get("name") or "") if folder else ""
        task["category_folder_path"] = str(folder.get("path") or "") if folder else ""
        task["category_folder_display_name"] = str(folder.get("display_name") or "") if folder else ""

        cur.execute(
            """
            SELECT rr.id, rr.frequency, rr.create_next_on_done, rr.is_active
            FROM recurrence_rules rr
            WHERE rr.task_id=?;
            """,
            (int(task_id),),
        )
        rr = cur.fetchone()
        task["recurrence"] = dict(rr) if rr else None
        return task

    def fetch_task_details(self, task_id: int) -> dict | None:
        task = self.fetch_task_by_id(int(task_id))
        if not task:
            return None
        task["attachments"] = self.fetch_attachments(int(task_id))
        task["dependencies"] = self.fetch_dependencies(int(task_id))
        task["child_progress"] = self.child_progress(int(task_id))
        task["project_summary"] = self.project_health_for_task(int(task_id), stalled_days=14)
        project_id = self.project_id_for_task(int(task_id))
        task["project_id"] = project_id
        task["project_profile"] = self.fetch_project_profile(int(project_id)) if project_id is not None else None
        task["project_phases"] = self.fetch_project_phases(int(project_id)) if project_id is not None else []
        return task

    def fetch_task_snapshot(self, task_id: int) -> dict | None:
        task = self.fetch_task_by_id(int(task_id))
        if not task:
            return None
        task["attachments"] = self.fetch_attachments(int(task_id))
        task["dependencies"] = [int(d["id"]) for d in self.fetch_dependencies(int(task_id))]
        task["recurrence"] = self.get_recurrence_for_task(int(task_id))
        return task

    def fetch_subtree_task_ids(self, root_id: int) -> list[int]:
        cur = self.conn.cursor()
        cur.execute(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM tasks WHERE id=?
                UNION ALL
                SELECT t.id
                FROM tasks t
                JOIN subtree s ON t.parent_id = s.id
            )
            SELECT id FROM subtree;
            """,
            (int(root_id),),
        )
        return [int(r["id"]) for r in cur.fetchall()]

    def restore_task_snapshot(self, snapshot: dict):
        if not snapshot or snapshot.get("id") is None:
            return

        tid = int(snapshot["id"])
        recurrence = snapshot.get("recurrence") if isinstance(snapshot.get("recurrence"), dict) else None
        recurrence_id = int(recurrence["id"]) if recurrence and recurrence.get("id") is not None else None
        row_recurrence_rule_id = snapshot.get("recurrence_rule_id")
        deps = []
        for raw in snapshot.get("dependencies") or []:
            try:
                deps.append(int(raw["id"]) if isinstance(raw, dict) else int(raw))
            except Exception:
                continue

        attachments = []
        for att in snapshot.get("attachments") or []:
            if not isinstance(att, dict):
                continue
            attachments.append(
                {
                    "path": str(att.get("path") or ""),
                    "label": str(att.get("label") or ""),
                    "created_at": str(att.get("created_at") or now_iso()),
                }
            )

        custom_values = {}
        for raw_key, value in (snapshot.get("custom") or {}).items():
            try:
                custom_values[int(raw_key)] = value
            except Exception:
                continue

        with self.tx():
            cur = self.conn.cursor()

            cur.execute(
                """
                UPDATE tasks
                SET description=?,
                    due_date=?,
                    last_update=?,
                    priority=?,
                    status=?,
                    parent_id=?,
                    sort_order=?,
                    is_collapsed=?,
                    notes=?,
                    archived_at=?,
                    planned_bucket=?,
                    effort_minutes=?,
                    actual_minutes=?,
                    timer_started_at=?,
                    waiting_for=?,
                    recurrence_rule_id=?,
                    recurrence_origin_task_id=?,
                    is_generated_occurrence=?,
                    reminder_at=?,
                    reminder_minutes_before=?,
                    reminder_fired_at=?,
                    start_date=?,
                    phase_id=?,
                    category_folder_id=?,
                    gantt_color_hex=?
                WHERE id=?;
                """,
                (
                    str(snapshot.get("description") or ""),
                    snapshot.get("due_date"),
                    str(snapshot.get("last_update") or now_iso()),
                    int(snapshot.get("priority") or 3),
                    str(snapshot.get("status") or "Todo"),
                    snapshot.get("parent_id"),
                    int(snapshot.get("sort_order") or 0),
                    int(snapshot.get("is_collapsed") or 0),
                    str(snapshot.get("notes") or ""),
                    snapshot.get("archived_at"),
                    str(snapshot.get("planned_bucket") or "inbox"),
                    snapshot.get("effort_minutes"),
                    int(snapshot.get("actual_minutes") or 0),
                    snapshot.get("timer_started_at"),
                    snapshot.get("waiting_for"),
                    row_recurrence_rule_id if recurrence_id is None else recurrence_id,
                    snapshot.get("recurrence_origin_task_id"),
                    int(snapshot.get("is_generated_occurrence") or 0),
                    snapshot.get("reminder_at"),
                    snapshot.get("reminder_minutes_before"),
                    snapshot.get("reminder_fired_at"),
                    snapshot.get("start_date"),
                    snapshot.get("phase_id"),
                    snapshot.get("category_folder_id"),
                    str(snapshot.get("gantt_color_hex") or "").strip() or None,
                    tid,
                ),
            )

            cur.execute("DELETE FROM task_custom_values WHERE task_id=?;", (tid,))
            for col_id, value in custom_values.items():
                cur.execute(
                    """
                    INSERT INTO task_custom_values(task_id, column_id, value)
                    VALUES(?, ?, ?);
                    """,
                    (tid, int(col_id), value),
                )

            self._set_task_tags_tx(cur, tid, snapshot.get("tags") or [])

            cur.execute("DELETE FROM task_dependencies WHERE task_id=?;", (tid,))
            cur.execute(
                """
                DELETE FROM pm_dependencies
                WHERE successor_kind='task'
                  AND successor_id=?
                  AND predecessor_kind='task';
                """,
                (tid,),
            )
            for dep_id in deps:
                cur.execute(
                    """
                    INSERT INTO task_dependencies(task_id, depends_on_task_id)
                    VALUES(?, ?)
                    ON CONFLICT(task_id, depends_on_task_id) DO NOTHING;
                    """,
                    (tid, int(dep_id)),
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
                    (int(dep_id), tid, now_iso()),
                )

            cur.execute("DELETE FROM task_attachments WHERE task_id=?;", (tid,))
            for att in attachments:
                cur.execute(
                    """
                    INSERT INTO task_attachments(task_id, path, label, created_at)
                    VALUES(?, ?, ?, ?);
                    """,
                    (tid, att["path"], att["label"], att["created_at"]),
                )

            cur.execute("DELETE FROM recurrence_rules WHERE task_id=?;", (tid,))
            if recurrence and recurrence.get("frequency"):
                if recurrence_id is not None:
                    cur.execute(
                        """
                        INSERT INTO recurrence_rules(
                            id, task_id, frequency, create_next_on_done, is_active, created_at, updated_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            recurrence_id,
                            tid,
                            str(recurrence.get("frequency") or ""),
                            1 if int(recurrence.get("create_next_on_done") or 0) == 1 else 0,
                            1 if int(recurrence.get("is_active") or 0) == 1 else 0,
                            str(recurrence.get("created_at") or now_iso()),
                            str(recurrence.get("updated_at") or now_iso()),
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO recurrence_rules(
                            task_id, frequency, create_next_on_done, is_active, created_at, updated_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?);
                        """,
                        (
                            tid,
                            str(recurrence.get("frequency") or ""),
                            1 if int(recurrence.get("create_next_on_done") or 0) == 1 else 0,
                            1 if int(recurrence.get("is_active") or 0) == 1 else 0,
                            str(recurrence.get("created_at") or now_iso()),
                            str(recurrence.get("updated_at") or now_iso()),
                        ),
                    )
                    cur.execute(
                        "UPDATE tasks SET recurrence_rule_id=? WHERE id=?;",
                        (int(cur.lastrowid), tid),
                    )

    def next_sort_order(self, parent_id: int | None) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM tasks WHERE parent_id IS ?;",
            (parent_id,),
        )
        return int(cur.fetchone()[0])

    def insert_task(self, task: dict, keep_id: bool = False) -> int:
        """
        task keys:
          id(optional), description, due_date, last_update, priority, status,
          parent_id, sort_order, is_collapsed, custom{col_id:value}, tags(optional)
        """
        task_data = dict(task)
        task_data.setdefault("description", "")
        task_data.setdefault("due_date", None)
        task_data.setdefault("last_update", now_iso())
        task_data.setdefault("priority", 3)
        task_data.setdefault("status", "Todo")
        task_data.setdefault("parent_id", None)
        task_data.setdefault("sort_order", 1)
        task_data.setdefault("is_collapsed", 0)
        task_data.setdefault("notes", "")
        task_data.setdefault("archived_at", None)
        task_data.setdefault("planned_bucket", "inbox")
        task_data.setdefault("effort_minutes", None)
        task_data.setdefault("actual_minutes", 0)
        task_data.setdefault("timer_started_at", None)
        task_data.setdefault("waiting_for", None)
        task_data.setdefault("recurrence_rule_id", None)
        task_data.setdefault("recurrence_origin_task_id", None)
        task_data.setdefault("is_generated_occurrence", 0)
        task_data.setdefault("reminder_at", None)
        task_data.setdefault("reminder_minutes_before", None)
        task_data.setdefault("reminder_fired_at", None)
        task_data.setdefault("start_date", None)
        task_data.setdefault("phase_id", None)
        task_data.setdefault("category_folder_id", None)
        task_data.setdefault("gantt_color_hex", None)

        with self.tx():
            cur = self.conn.cursor()

            if keep_id and task_data.get("id") is not None:
                cur.execute(
                    """
                    INSERT INTO tasks(id, description, due_date, last_update, priority, status,
                                      parent_id, sort_order, is_collapsed,
                                      notes, archived_at, planned_bucket,
                                      effort_minutes, actual_minutes, timer_started_at,
                                      waiting_for,
                                      recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                                      reminder_at, reminder_minutes_before, reminder_fired_at,
                                      start_date, phase_id, category_folder_id, gantt_color_hex)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        task_data["id"], task_data["description"], task_data["due_date"], task_data["last_update"],
                        task_data["priority"], task_data["status"],
                        task_data.get("parent_id"), task_data["sort_order"], int(task_data.get("is_collapsed", 0)),
                        task_data.get("notes") or "",
                        task_data.get("archived_at"),
                        str(task_data.get("planned_bucket") or "inbox"),
                        task_data.get("effort_minutes"),
                        int(task_data.get("actual_minutes") or 0),
                        task_data.get("timer_started_at"),
                        task_data.get("waiting_for"),
                        task_data.get("recurrence_rule_id"),
                        task_data.get("recurrence_origin_task_id"),
                        int(task_data.get("is_generated_occurrence") or 0),
                        task_data.get("reminder_at"),
                        task_data.get("reminder_minutes_before"),
                        task_data.get("reminder_fired_at"),
                        task_data.get("start_date"),
                        task_data.get("phase_id"),
                        task_data.get("category_folder_id"),
                        str(task_data.get("gantt_color_hex") or "").strip() or None,
                    ),
                )
                task_id = int(task_data["id"])
            else:
                cur.execute(
                    """
                    INSERT INTO tasks(description, due_date, last_update, priority, status,
                                      parent_id, sort_order, is_collapsed,
                                      notes, archived_at, planned_bucket,
                                      effort_minutes, actual_minutes, timer_started_at,
                                      waiting_for,
                                      recurrence_rule_id, recurrence_origin_task_id, is_generated_occurrence,
                                      reminder_at, reminder_minutes_before, reminder_fired_at,
                                      start_date, phase_id, category_folder_id, gantt_color_hex)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        task_data["description"], task_data["due_date"], task_data["last_update"],
                        task_data["priority"], task_data["status"],
                        task_data.get("parent_id"), task_data["sort_order"], int(task_data.get("is_collapsed", 0)),
                        task_data.get("notes") or "",
                        task_data.get("archived_at"),
                        str(task_data.get("planned_bucket") or "inbox"),
                        task_data.get("effort_minutes"),
                        int(task_data.get("actual_minutes") or 0),
                        task_data.get("timer_started_at"),
                        task_data.get("waiting_for"),
                        task_data.get("recurrence_rule_id"),
                        task_data.get("recurrence_origin_task_id"),
                        int(task_data.get("is_generated_occurrence") or 0),
                        task_data.get("reminder_at"),
                        task_data.get("reminder_minutes_before"),
                        task_data.get("reminder_fired_at"),
                        task_data.get("start_date"),
                        task_data.get("phase_id"),
                        task_data.get("category_folder_id"),
                        str(task_data.get("gantt_color_hex") or "").strip() or None,
                    ),
                )
                task_id = int(cur.lastrowid)

            custom = task_data.get("custom") or {}
            for col_id, val in custom.items():
                cur.execute(
                    """
                    INSERT INTO task_custom_values(task_id, column_id, value)
                    VALUES(?, ?, ?)
                    ON CONFLICT(task_id, column_id) DO UPDATE SET value=excluded.value;
                    """,
                    (task_id, int(col_id), val),
                )

            tags = task_data.get("tags")
            if isinstance(tags, list):
                self._set_task_tags_tx(cur, int(task_id), tags)

        return task_id

    def delete_task(self, task_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                DELETE FROM pm_dependencies
                WHERE (predecessor_kind='task' AND predecessor_id=?)
                   OR (successor_kind='task' AND successor_id=?);
                """,
                (int(task_id), int(task_id)),
            )
            cur.execute("DELETE FROM tasks WHERE id=?;", (int(task_id),))

    def update_task_field(self, task_id: int, field: str, value):
        allowed = {
            "description",
            "due_date",
            "priority",
            "status",
            "notes",
            "archived_at",
            "planned_bucket",
            "effort_minutes",
            "actual_minutes",
            "timer_started_at",
            "waiting_for",
            "reminder_at",
            "reminder_minutes_before",
            "reminder_fired_at",
            "recurrence_rule_id",
            "recurrence_origin_task_id",
            "is_generated_occurrence",
            "start_date",
            "phase_id",
            "gantt_color_hex",
        }
        if field not in allowed:
            raise ValueError("Invalid field")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                f"UPDATE tasks SET {field}=?, last_update=? WHERE id=?;",
                (value, now_iso(), int(task_id)),
            )

    def update_task_fields(self, task_id: int, fields: dict):
        if not fields:
            return
        allowed = {
            "description",
            "due_date",
            "priority",
            "status",
            "notes",
            "archived_at",
            "planned_bucket",
            "effort_minutes",
            "actual_minutes",
            "timer_started_at",
            "waiting_for",
            "reminder_at",
            "reminder_minutes_before",
            "reminder_fired_at",
            "recurrence_rule_id",
            "recurrence_origin_task_id",
            "is_generated_occurrence",
            "is_collapsed",
            "parent_id",
            "sort_order",
            "start_date",
            "phase_id",
            "gantt_color_hex",
        }
        pairs = []
        params = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            pairs.append(f"{k}=?")
            params.append(v)
        if not pairs:
            return
        pairs.append("last_update=?")
        params.append(now_iso())
        params.append(int(task_id))

        with self.tx():
            cur = self.conn.cursor()
            cur.execute(f"UPDATE tasks SET {', '.join(pairs)} WHERE id=?;", tuple(params))

    def update_custom_value(self, task_id: int, col_id: int, value):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO task_custom_values(task_id, column_id, value)
                VALUES(?, ?, ?)
                ON CONFLICT(task_id, column_id) DO UPDATE SET value=excluded.value;
                """,
                (int(task_id), int(col_id), value),
            )
            cur.execute("UPDATE tasks SET last_update=? WHERE id=?;", (now_iso(), int(task_id)))

    def set_task_collapsed(self, task_id: int, collapsed: bool):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE tasks SET is_collapsed=?, last_update=? WHERE id=?;",
                (1 if collapsed else 0, now_iso(), int(task_id)),
            )

    # ---------- Archive ----------
    def archive_task(self, task_id: int):
        self._set_archive_state(int(task_id), archived=True)

    def restore_task(self, task_id: int):
        self._set_archive_state(int(task_id), archived=False)

    def _set_archive_state(self, task_id: int, archived: bool):
        stamp = now_iso() if archived else None
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                WITH RECURSIVE subtree(id) AS (
                    SELECT id FROM tasks WHERE id=?
                    UNION ALL
                    SELECT t.id FROM tasks t
                    JOIN subtree s ON t.parent_id = s.id
                )
                UPDATE tasks
                SET archived_at=?, last_update=?
                WHERE id IN (SELECT id FROM subtree);
                """,
                (int(task_id), stamp, now_iso()),
            )

    def fetch_archive_roots(self) -> list[dict]:
        """
        Return archived tasks whose parent is not archived (or absent),
        so each row represents a restorable archived subtree root.
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                t.id,
                t.description,
                t.due_date,
                t.priority,
                t.status,
                t.archived_at,
                t.parent_id,
                p.description AS parent_description
            FROM tasks t
            LEFT JOIN tasks p ON p.id = t.parent_id
            WHERE t.archived_at IS NOT NULL
              AND (t.parent_id IS NULL OR p.archived_at IS NULL)
            ORDER BY t.archived_at DESC, t.priority ASC, t.sort_order ASC, t.id ASC;
            """
        )
        return [dict(r) for r in cur.fetchall()]

    def fetch_project_health(self, stalled_days: int = 14) -> list[dict]:
        return analyze_projects(self.fetch_tasks(), stalled_days=int(stalled_days or 14), today=date.today())

    def project_health_for_task(self, task_id: int, stalled_days: int = 14) -> dict | None:
        tid = int(task_id)
        for row in self.fetch_project_health(stalled_days=int(stalled_days or 14)):
            if int(row.get("id") or 0) == tid:
                return row
        return None

    def fetch_review_data(
        self,
        waiting_days: int = 7,
        stalled_days: int = 14,
        recent_days: int = 30,
    ) -> dict[str, list[dict]]:
        wait_days = max(1, int(waiting_days or 7))
        stale_days = max(1, int(stalled_days or 14))
        rec_days = max(1, int(recent_days or 30))

        def _run(sql: str, params: tuple = ()) -> list[dict]:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

        data: dict[str, list[dict]] = {}
        base_cols = "id, description, due_date, priority, status, last_update, archived_at, planned_bucket, waiting_for"

        data["overdue"] = _run(
            f"""
            SELECT {base_cols}
            FROM tasks
            WHERE archived_at IS NULL
              AND status <> 'Done'
              AND due_date IS NOT NULL
              AND TRIM(due_date) <> ''
              AND due_date < date('now', 'localtime')
            ORDER BY due_date ASC, priority ASC, sort_order ASC, id ASC;
            """
        )

        data["no_due"] = _run(
            f"""
            SELECT {base_cols}
            FROM tasks
            WHERE archived_at IS NULL
              AND status <> 'Done'
              AND (due_date IS NULL OR TRIM(due_date) = '')
            ORDER BY priority ASC, sort_order ASC, id ASC;
            """
        )

        data["inbox_unprocessed"] = _run(
            f"""
            SELECT {base_cols}
            FROM tasks
            WHERE archived_at IS NULL
              AND status = 'Todo'
              AND LOWER(COALESCE(planned_bucket, 'inbox')) = 'inbox'
            ORDER BY priority ASC, sort_order ASC, id ASC;
            """
        )

        waiting_rows = _run(
            f"""
            SELECT {base_cols}
            FROM tasks
            WHERE archived_at IS NULL
              AND status <> 'Done'
              AND waiting_for IS NOT NULL
              AND TRIM(waiting_for) <> ''
              AND (julianday('now', 'localtime') - julianday(last_update)) >= ?
            ORDER BY last_update ASC, priority ASC, id ASC;
            """,
            (wait_days,),
        )
        for row in waiting_rows:
            row["review_note"] = f"waiting_for: {str(row.get('waiting_for') or '').strip()}"
        data["waiting_old"] = waiting_rows

        data["recurring_attention"] = _run(
            f"""
            SELECT {base_cols}
            FROM tasks
            WHERE archived_at IS NULL
              AND status <> 'Done'
              AND recurrence_rule_id IS NOT NULL
              AND (
                    due_date IS NULL
                 OR TRIM(due_date) = ''
                 OR due_date <= date('now', 'localtime')
              )
            ORDER BY COALESCE(due_date, '9999-12-31') ASC, priority ASC, id ASC;
            """
        )

        milestone_rows = _run(
            """
            SELECT m.id,
                   m.title AS description,
                   m.target_date AS due_date,
                   COALESCE(t.priority, p.priority, 3) AS priority,
                   m.status AS status,
                   m.updated_at AS last_update,
                   NULL AS archived_at,
                   '' AS planned_bucket,
                   '' AS waiting_for,
                   p.id AS project_task_id,
                   p.description AS project_name,
                   t.id AS linked_task_id,
                   t.description AS linked_task_description,
                   pp.name AS phase_name
            FROM milestones m
            JOIN tasks p ON p.id = m.project_task_id
            LEFT JOIN tasks t ON t.id = m.linked_task_id
            LEFT JOIN project_phases pp ON pp.id = m.phase_id
            WHERE m.status <> 'completed'
              AND m.target_date IS NOT NULL
              AND TRIM(m.target_date) <> ''
              AND m.target_date < date('now', 'localtime')
            ORDER BY m.target_date ASC, priority ASC, m.id ASC;
            """
        )
        for row in milestone_rows:
            focus_id = int(row.get("linked_task_id") or row.get("project_task_id") or 0)
            row["review_focus_id"] = focus_id
            row["review_key"] = f"milestone:{int(row.get('id') or 0)}"
            project_name = str(row.get("project_name") or "").strip()
            phase_name = str(row.get("phase_name") or "").strip()
            linked = str(row.get("linked_task_description") or "").strip()
            parts = []
            if project_name:
                parts.append(f"project: {project_name}")
            if phase_name:
                parts.append(f"phase: {phase_name}")
            if linked:
                parts.append(f"linked task: {linked}")
            row["review_note"] = " | ".join(parts)
        data["overdue_milestones"] = milestone_rows

        deliverable_rows = _run(
            """
            SELECT d.id,
                   d.title AS description,
                   d.due_date AS due_date,
                   COALESCE(t.priority, p.priority, 3) AS priority,
                   d.status AS status,
                   d.updated_at AS last_update,
                   NULL AS archived_at,
                   '' AS planned_bucket,
                   '' AS waiting_for,
                   p.id AS project_task_id,
                   p.description AS project_name,
                   t.id AS linked_task_id,
                   t.description AS linked_task_description,
                   m.title AS linked_milestone_title,
                   pp.name AS phase_name
            FROM deliverables d
            JOIN tasks p ON p.id = d.project_task_id
            LEFT JOIN tasks t ON t.id = d.linked_task_id
            LEFT JOIN milestones m ON m.id = d.linked_milestone_id
            LEFT JOIN project_phases pp ON pp.id = d.phase_id
            WHERE d.status <> 'completed'
              AND d.due_date IS NOT NULL
              AND TRIM(d.due_date) <> ''
              AND d.due_date <= date('now', 'localtime', '+7 day')
            ORDER BY d.due_date ASC, priority ASC, d.id ASC;
            """
        )
        for row in deliverable_rows:
            focus_id = int(row.get("linked_task_id") or row.get("project_task_id") or 0)
            row["review_focus_id"] = focus_id
            row["review_key"] = f"deliverable:{int(row.get('id') or 0)}"
            project_name = str(row.get("project_name") or "").strip()
            phase_name = str(row.get("phase_name") or "").strip()
            linked = str(row.get("linked_task_description") or row.get("linked_milestone_title") or "").strip()
            parts = []
            if project_name:
                parts.append(f"project: {project_name}")
            if phase_name:
                parts.append(f"phase: {phase_name}")
            if linked:
                parts.append(f"linked: {linked}")
            row["review_note"] = " | ".join(parts)
        data["deliverables_due_soon"] = deliverable_rows

        register_rows = _run(
            """
            SELECT r.id,
                   r.title AS description,
                   r.review_date AS due_date,
                   COALESCE(r.severity, 0) AS priority,
                   r.status AS status,
                   r.updated_at AS last_update,
                   NULL AS archived_at,
                   '' AS planned_bucket,
                   '' AS waiting_for,
                   r.entry_type,
                   r.severity,
                   p.id AS project_task_id,
                   p.description AS project_name,
                   t.id AS linked_task_id,
                   t.description AS linked_task_description,
                   m.title AS linked_milestone_title
            FROM project_register_entries r
            JOIN tasks p ON p.id = r.project_task_id
            LEFT JOIN tasks t ON t.id = r.linked_task_id
            LEFT JOIN milestones m ON m.id = r.linked_milestone_id
            WHERE r.status NOT IN ('resolved', 'accepted')
              AND COALESCE(r.severity, 0) >= 4
            ORDER BY COALESCE(r.severity, 0) DESC, COALESCE(r.review_date, '9999-12-31') ASC, r.id ASC;
            """
        )
        for row in register_rows:
            focus_id = int(row.get("linked_task_id") or row.get("project_task_id") or 0)
            row["review_focus_id"] = focus_id
            row["review_key"] = f"register:{int(row.get('id') or 0)}"
            project_name = str(row.get("project_name") or "").strip()
            linked = str(row.get("linked_task_description") or row.get("linked_milestone_title") or "").strip()
            severity = int(row.get("severity") or 0)
            parts = [f"type: {str(row.get('entry_type') or '').strip()}"]
            if severity > 0:
                parts.append(f"severity: {severity}")
            if project_name:
                parts.append(f"project: {project_name}")
            if linked:
                parts.append(f"linked: {linked}")
            row["review_note"] = " | ".join(parts)
        data["high_risk_registers"] = register_rows

        data["recent_done_archived"] = _run(
            f"""
            SELECT {base_cols}
            FROM tasks
            WHERE (status = 'Done' OR archived_at IS NOT NULL)
              AND date(COALESCE(archived_at, last_update)) >= date('now', 'localtime', ?)
            ORDER BY COALESCE(archived_at, last_update) DESC, id DESC;
            """,
            (f"-{rec_days} day",),
        )

        data["archive_roots"] = self.fetch_archive_roots()

        project_rows = self.fetch_project_health(stalled_days=stale_days)
        data["stalled_projects"] = [r for r in project_rows if bool(r.get("stalled"))]
        data["projects_no_next"] = [r for r in project_rows if bool(r.get("no_next_action"))]
        data["blocked_projects"] = [r for r in project_rows if bool(r.get("blocked"))]

        return data

    def fetch_focus_data(self, include_waiting: bool = False, limit: int = 40) -> list[dict]:
        tasks = self.fetch_tasks()
        today = date.today()
        max_items = max(1, int(limit or 40))

        children_by_parent: dict[int, list[dict]] = {}
        by_id: dict[int, dict] = {}
        for task in tasks:
            tid = int(task["id"])
            by_id[tid] = task
            pid = task.get("parent_id")
            if pid is None:
                continue
            try:
                parent_id = int(pid)
            except Exception:
                continue
            children_by_parent.setdefault(parent_id, []).append(task)

        section_order = {
            "Overdue": 0,
            "Today": 1,
            "Next action": 2,
            "Ready next": 3,
            "Waiting/Blocked": 4,
        }
        out_by_id: dict[int, dict] = {}

        def _is_active(task: dict) -> bool:
            return not str(task.get("archived_at") or "").strip() and str(task.get("status") or "") != "Done"

        def _is_blocked_or_waiting(task: dict) -> bool:
            return int(task.get("blocked_by_count") or 0) > 0 or bool(str(task.get("waiting_for") or "").strip())

        def _has_active_children(task_id: int) -> bool:
            for child in children_by_parent.get(int(task_id), []):
                if _is_active(child):
                    return True
            return False

        def _add(task: dict, section: str, note: str):
            tid = int(task["id"])
            if tid in out_by_id:
                current = out_by_id[tid]
                cur_order = section_order.get(str(current.get("focus_section")), 99)
                next_order = section_order.get(section, 99)
                if next_order < cur_order:
                    current["focus_section"] = section
                    current["focus_note"] = note
                elif note:
                    existing_note = str(current.get("focus_note") or "")
                    if note not in existing_note:
                        current["focus_note"] = f"{existing_note} | {note}" if existing_note else note
                return
            row = dict(task)
            row["focus_section"] = section
            row["focus_note"] = note
            out_by_id[tid] = row

        project_rows = self.fetch_project_health(stalled_days=14)
        next_action_ids = {
            int(row["next_action_task_id"])
            for row in project_rows
            if row.get("next_action_task_id") is not None
        }

        for task in tasks:
            if not _is_active(task):
                continue
            tid = int(task["id"])
            due = _parse_iso_date(task.get("due_date"))
            bucket = str(task.get("planned_bucket") or "inbox").strip().lower() or "inbox"
            blocked_waiting = _is_blocked_or_waiting(task)
            has_children = _has_active_children(tid)

            is_due_now = bool(bucket == "today" or (due is not None and due <= today))
            if is_due_now:
                if blocked_waiting:
                    if include_waiting:
                        note = str(task.get("waiting_for") or "").strip() or "blocked by dependency"
                        section = "Waiting/Blocked"
                        _add(task, section, note)
                    continue
                if not has_children:
                    section = "Overdue" if due is not None and due < today else "Today"
                    note = f"bucket: {bucket}" if bucket == "today" and due is None else ""
                    _add(task, section, note)

            if tid in next_action_ids and not blocked_waiting:
                _add(task, "Next action", "project next action")

        for task in tasks:
            if len(out_by_id) >= max_items:
                break
            if not _is_active(task):
                continue
            tid = int(task["id"])
            if tid in out_by_id:
                continue
            if _has_active_children(tid):
                continue
            if _is_blocked_or_waiting(task):
                continue
            due = _parse_iso_date(task.get("due_date"))
            if due is not None and due <= today:
                continue
            _add(task, "Ready next", "unblocked next step")

        rows = list(out_by_id.values())
        rows.sort(
            key=lambda row: (
                section_order.get(str(row.get("focus_section") or ""), 99),
                _parse_iso_date(row.get("due_date")) or date.max,
                int(row.get("priority") or 99),
                str(row.get("description") or "").lower(),
                int(row.get("id") or 0),
            )
        )
        return rows[:max_items]

    def fetch_analytics_summary(self, trend_days: int = 14, tag_days: int = 30) -> dict:
        trend_window = max(3, int(trend_days or 14))
        tag_window = max(7, int(tag_days or 30))
        tasks = self.fetch_tasks()

        cur = self.conn.cursor()

        def _scalar(sql: str, params: tuple = ()) -> int:
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                return 0
            return int(row[0] or 0)

        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        completed_today = _scalar(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE status='Done' AND date(last_update)=?;
            """,
            (today.isoformat(),),
        )
        completed_week = _scalar(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE status='Done' AND date(last_update) >= ? AND date(last_update) <= ?;
            """,
            (week_start.isoformat(), today.isoformat()),
        )
        overdue_open = _scalar(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE archived_at IS NULL
              AND status <> 'Done'
              AND due_date IS NOT NULL
              AND TRIM(due_date) <> ''
              AND due_date < ?;
            """,
            (today.isoformat(),),
        )
        open_no_due = _scalar(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE archived_at IS NULL
              AND status <> 'Done'
              AND (due_date IS NULL OR TRIM(due_date)='');
            """
        )
        inbox_unprocessed = _scalar(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE archived_at IS NULL
              AND status='Todo'
              AND LOWER(COALESCE(planned_bucket, 'inbox'))='inbox';
            """
        )
        active_open = _scalar(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE archived_at IS NULL
              AND status <> 'Done';
            """
        )
        archived_count = _scalar(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE archived_at IS NOT NULL;
            """
        )

        # Completed trend series
        cur.execute(
            """
            SELECT date(last_update) AS d, COUNT(*) AS c
            FROM tasks
            WHERE status='Done'
              AND date(last_update) >= date('now', 'localtime', ?)
            GROUP BY date(last_update)
            ORDER BY d ASC;
            """,
            (f"-{trend_window - 1} day",),
        )
        trend_raw = {str(r["d"]): int(r["c"] or 0) for r in cur.fetchall()}
        trend: list[dict] = []
        for offset in range(trend_window - 1, -1, -1):
            d = today - timedelta(days=offset)
            iso = d.isoformat()
            trend.append({"date": iso, "count": int(trend_raw.get(iso, 0))})

        # Top tags in recent completions
        cur.execute(
            """
            SELECT tg.name, COUNT(*) AS c
            FROM tasks t
            JOIN task_tags tt ON tt.task_id = t.id
            JOIN tags tg ON tg.id = tt.tag_id
            WHERE t.status='Done'
              AND date(t.last_update) >= date('now', 'localtime', ?)
            GROUP BY tg.id, tg.name
            ORDER BY c DESC, LOWER(tg.name), tg.name
            LIMIT 8;
            """,
            (f"-{tag_window - 1} day",),
        )
        top_tags = [{"tag": str(r["name"]), "count": int(r["c"] or 0)} for r in cur.fetchall()]

        project_rows = analyze_projects(tasks, stalled_days=14, today=today)
        project_total = len(project_rows)
        project_stalled = sum(1 for r in project_rows if bool(r.get("stalled")))
        project_blocked = sum(1 for r in project_rows if bool(r.get("blocked")))
        project_no_next = sum(1 for r in project_rows if bool(r.get("no_next_action")))
        workload = analyze_workload(tasks, today=today)

        return {
            "completed_today": int(completed_today),
            "completed_this_week": int(completed_week),
            "overdue_open": int(overdue_open),
            "open_no_due": int(open_no_due),
            "inbox_unprocessed": int(inbox_unprocessed),
            "active_open": int(active_open),
            "archived_count": int(archived_count),
            "active_vs_archived_ratio": (
                float(active_open) / float(archived_count)
                if archived_count > 0
                else float(active_open)
            ),
            "project_total": int(project_total),
            "project_stalled": int(project_stalled),
            "project_blocked": int(project_blocked),
            "project_no_next": int(project_no_next),
            "workload_busiest_days": workload.get("busiest_days") or [],
            "workload_warnings": workload.get("warnings") or [],
            "scheduling_hints": workload.get("suggestions") or [],
            "trend": trend,
            "top_tags": top_tags,
        }

    # ---------- Tags ----------
    def _normalize_tags(self, tags) -> list[str]:
        if tags is None:
            return []
        out: list[str] = []
        seen = set()
        if isinstance(tags, str):
            raw_parts = [x.strip() for x in tags.split(",")]
        else:
            raw_parts = [str(x).strip() for x in tags]
        for v in raw_parts:
            if not v:
                continue
            k = v.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(v)
        return out

    def _ensure_tag_id_tx(self, cur, tag_name: str) -> int:
        cur.execute("SELECT id FROM tags WHERE name=? COLLATE NOCASE;", (str(tag_name).strip(),))
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur.execute("INSERT INTO tags(name, created_at) VALUES(?, ?);", (str(tag_name).strip(), now_iso()))
        return int(cur.lastrowid)

    def _set_task_tags_tx(self, cur, task_id: int, tags) -> list[str]:
        norm = self._normalize_tags(tags)
        cur.execute("DELETE FROM task_tags WHERE task_id=?;", (int(task_id),))
        for tag in norm:
            tid = self._ensure_tag_id_tx(cur, tag)
            cur.execute(
                """
                INSERT INTO task_tags(task_id, tag_id)
                VALUES(?, ?)
                ON CONFLICT(task_id, tag_id) DO NOTHING;
                """,
                (int(task_id), int(tid)),
            )
        return norm

    def set_task_tags(self, task_id: int, tags) -> list[str]:
        with self.tx():
            cur = self.conn.cursor()
            out = self._set_task_tags_tx(cur, int(task_id), tags)
            cur.execute("UPDATE tasks SET last_update=? WHERE id=?;", (now_iso(), int(task_id)))
            return out

    def fetch_task_tags(self, task_id: int) -> list[str]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT tg.name
            FROM task_tags tt
            JOIN tags tg ON tg.id=tt.tag_id
            WHERE tt.task_id=?
            ORDER BY LOWER(tg.name), tg.name;
            """,
            (int(task_id),),
        )
        return [str(r["name"]) for r in cur.fetchall()]

    def fetch_all_tags(self) -> list[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT name FROM tags ORDER BY LOWER(name), name;")
        return [str(r["name"]) for r in cur.fetchall()]

    # ---------- Dependencies / waiting ----------
    def fetch_dependencies(self, task_id: int) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT td.depends_on_task_id AS id, t.description
            FROM task_dependencies td
            JOIN tasks t ON t.id = td.depends_on_task_id
            WHERE td.task_id=?
            ORDER BY t.description COLLATE NOCASE, t.id;
            """,
            (int(task_id),),
        )
        return [dict(r) for r in cur.fetchall()]

    def fetch_dependents(self, task_id: int) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT td.task_id AS id, t.description, t.status, t.priority, t.due_date
            FROM task_dependencies td
            JOIN tasks t ON t.id = td.task_id
            WHERE td.depends_on_task_id = ?
            ORDER BY COALESCE(t.due_date, '9999-12-31') ASC, t.priority ASC, LOWER(t.description), t.id;
            """,
            (int(task_id),),
        )
        return [dict(r) for r in cur.fetchall()]

    def fetch_task_relationships(self, task_id: int, limit: int = 12) -> dict:
        tid = int(task_id)
        tasks = self.fetch_tasks()
        by_id: dict[int, dict] = {}
        children_by_parent: dict[int, list[dict]] = {}
        for task in tasks:
            task_id_value = int(task["id"])
            by_id[task_id_value] = task
            parent_id = task.get("parent_id")
            if parent_id is None:
                continue
            try:
                children_by_parent.setdefault(int(parent_id), []).append(task)
            except Exception:
                continue

        task = by_id.get(tid)
        if not task:
            return {}

        max_items = max(1, int(limit or 12))

        def _active(row: dict) -> bool:
            return not str(row.get("archived_at") or "").strip()

        def _open(row: dict) -> bool:
            return _active(row) and str(row.get("status") or "") != "Done"

        def _sort_key(row: dict):
            due = _parse_iso_date(row.get("due_date")) or date.max
            return (
                due,
                int(row.get("priority") or 99),
                str(row.get("description") or "").lower(),
                int(row.get("id") or 0),
            )

        def _copy_rows(rows: list[dict], *, add_shared_tags: set[str] | None = None) -> list[dict]:
            out: list[dict] = []
            for row in rows[:max_items]:
                item = dict(row)
                if add_shared_tags:
                    shared = sorted(add_shared_tags.intersection({str(t).strip() for t in (row.get("tags") or []) if str(t).strip()}))
                    item["shared_tags"] = shared
                if str(item.get("waiting_for") or "").strip():
                    updated = _parse_iso_datetime(item.get("last_update"))
                    if updated is not None:
                        item["waiting_age_days"] = max(0, (date.today() - updated.date()).days)
                out.append(item)
            return out

        parent = None
        parent_id = task.get("parent_id")
        if parent_id is not None:
            try:
                parent = by_id.get(int(parent_id))
            except Exception:
                parent = None

        ancestors: list[dict] = []
        probe = parent
        seen = set()
        while probe and int(probe["id"]) not in seen:
            ancestors.append(dict(probe))
            seen.add(int(probe["id"]))
            next_parent_id = probe.get("parent_id")
            if next_parent_id is None:
                break
            probe = by_id.get(int(next_parent_id))
        ancestors.reverse()

        children = sorted([row for row in children_by_parent.get(tid, []) if _active(row)], key=_sort_key)
        siblings = []
        sibling_ids: set[int] = set()
        if parent is not None:
            siblings = [row for row in children_by_parent.get(int(parent["id"]), []) if int(row["id"]) != tid and _active(row)]
            siblings.sort(key=_sort_key)
            sibling_ids = {int(row["id"]) for row in siblings}

        dependency_ids = [int(x) for x in (task.get("dependencies") or []) if int(x) in by_id]
        depends_on = [by_id[dep_id] for dep_id in dependency_ids if _active(by_id[dep_id])]
        depends_on.sort(key=_sort_key)

        dependents = [
            row
            for row in tasks
            if int(row.get("id") or 0) != tid and tid in [int(x) for x in (row.get("dependencies") or [])]
            and _active(row)
        ]
        dependents.sort(key=_sort_key)

        task_tags = {str(tag).strip() for tag in (task.get("tags") or []) if str(tag).strip()}
        same_tags = [
            row
            for row in tasks
            if int(row.get("id") or 0) != tid
            and _active(row)
            and task_tags.intersection({str(tag).strip() for tag in (row.get("tags") or []) if str(tag).strip()})
        ]
        same_tags.sort(key=lambda row: (-len(task_tags.intersection(set(row.get("tags") or []))),) + _sort_key(row))

        waiting_for = str(task.get("waiting_for") or "").strip().lower()
        same_waiting = []
        if waiting_for:
            same_waiting = [
                row
                for row in tasks
                if int(row.get("id") or 0) != tid
                and _active(row)
                and str(row.get("waiting_for") or "").strip().lower() == waiting_for
            ]
            same_waiting.sort(key=_sort_key)

        def _root_id(row: dict) -> int:
            seen_ids = set()
            current = row
            while current:
                current_id = int(current.get("id") or 0)
                if current_id in seen_ids:
                    break
                seen_ids.add(current_id)
                pid = current.get("parent_id")
                if pid is None:
                    return current_id
                current = by_id.get(int(pid))
            return int(row.get("id") or 0)

        root_id = _root_id(task)
        lineage_ids = {int(row["id"]) for row in ancestors}
        direct_child_ids = {int(row["id"]) for row in children}
        same_project = [
            row
            for row in tasks
            if int(row.get("id") or 0) != tid
            and _active(row)
            and _root_id(row) == root_id
            and int(row.get("id") or 0) not in lineage_ids
            and int(row.get("id") or 0) not in direct_child_ids
            and int(row.get("id") or 0) not in sibling_ids
        ]
        same_project.sort(key=_sort_key)

        due_day_load = None
        due = _parse_iso_date(task.get("due_date"))
        if due is not None:
            same_day = [row for row in tasks if _open(row) and _parse_iso_date(row.get("due_date")) == due]
            if same_day:
                high_priority = sum(1 for row in same_day if int(row.get("priority") or 99) <= 2)
                warning = ""
                if len(same_day) >= 5:
                    warning = f"{len(same_day)} active tasks are due that day."
                elif high_priority >= 3:
                    warning = f"{high_priority} high-priority tasks are clustered on that day."
                due_day_load = {
                    "date": due.isoformat(),
                    "task_count": len(same_day),
                    "high_priority_count": int(high_priority),
                    "warning": warning,
                }

        project_summary = self.project_health_for_task(tid, stalled_days=14)
        return {
            "task": dict(task),
            "parent": dict(parent) if parent else None,
            "ancestors": ancestors,
            "children": _copy_rows(children),
            "siblings": _copy_rows(siblings),
            "depends_on": _copy_rows(depends_on),
            "dependents": _copy_rows(dependents),
            "same_tags": _copy_rows(same_tags, add_shared_tags=task_tags),
            "same_waiting_for": _copy_rows(same_waiting),
            "same_project": _copy_rows(same_project),
            "project_summary": project_summary,
            "due_day_load": due_day_load,
        }

    def set_task_dependencies(self, task_id: int, depends_on_ids: list[int]):
        ids = []
        seen = set()
        existing_edges = self._fetch_all_pm_dependencies()
        for raw in depends_on_ids or []:
            try:
                tid = int(raw)
            except Exception:
                continue
            if tid <= 0 or tid == int(task_id) or tid in seen:
                continue
            ok, reason = validate_dependency_graph(existing_edges, "task", tid, "task", int(task_id))
            if not ok:
                raise ValueError(reason)
            seen.add(tid)
            ids.append(tid)

        with self.tx():
            cur = self.conn.cursor()
            cur.execute("DELETE FROM task_dependencies WHERE task_id=?;", (int(task_id),))
            for dep_id in ids:
                cur.execute(
                    """
                    INSERT INTO task_dependencies(task_id, depends_on_task_id)
                    VALUES(?, ?)
                    ON CONFLICT(task_id, depends_on_task_id) DO NOTHING;
                    """,
                    (int(task_id), int(dep_id)),
                )
            self._sync_task_dependency_edges_tx(cur, int(task_id), ids)
            cur.execute("UPDATE tasks SET last_update=? WHERE id=?;", (now_iso(), int(task_id)))

    # ---------- Project management ----------
    def project_id_for_task(self, task_id: int | None) -> int | None:
        if task_id is None:
            return None
        tasks = {int(row["id"]): row for row in self.fetch_tasks() if row.get("id") is not None}
        current = tasks.get(int(task_id))
        if not current:
            return None
        profiled_ids = {int(row["task_id"]) for row in self.list_project_profiles()}
        candidate = int(current["id"])
        while current:
            current_id = int(current["id"])
            if current_id in profiled_ids:
                return current_id
            parent_id = current.get("parent_id")
            if parent_id is None:
                return current_id
            current = tasks.get(int(parent_id))
            candidate = current_id
        return candidate

    def fetch_project_task_ids(self, project_task_id: int) -> list[int]:
        cur = self.conn.cursor()
        cur.execute(
            """
            WITH RECURSIVE project_tree(id) AS (
                SELECT id
                FROM tasks
                WHERE id=?
                UNION ALL
                SELECT t.id
                FROM tasks t
                JOIN project_tree pt ON t.parent_id = pt.id
            )
            SELECT id FROM project_tree ORDER BY id;
            """,
            (int(project_task_id),),
        )
        return [int(row["id"]) for row in cur.fetchall()]

    def _project_exists(self, project_task_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM tasks WHERE id=?;", (int(project_task_id),))
        return cur.fetchone() is not None

    def _phase_record(self, phase_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, project_task_id, name, sort_order, gantt_color_hex, created_at, updated_at
            FROM project_phases
            WHERE id=?;
            """,
            (int(phase_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def _task_in_project(self, task_id: int, project_task_id: int) -> bool:
        return int(task_id) in set(self.fetch_project_task_ids(int(project_task_id)))

    def _milestone_in_project(self, milestone_id: int, project_task_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM milestones
            WHERE id=? AND project_task_id=?;
            """,
            (int(milestone_id), int(project_task_id)),
        )
        return cur.fetchone() is not None

    def list_project_profiles(self) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT pp.*, t.description AS project_name
            FROM project_profiles pp
            JOIN tasks t ON t.id = pp.task_id
            WHERE t.archived_at IS NULL
            ORDER BY LOWER(t.description), t.id;
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def list_project_candidates(self, folder_id: int | None = None) -> list[dict]:
        cur = self.conn.cursor()
        params: list[object] = []
        folder_clause = ""
        if folder_id is not None:
            folder_ids = self.fetch_category_folder_descendant_ids(int(folder_id))
            if not folder_ids:
                return []
            placeholders = ", ".join("?" for _ in folder_ids)
            folder_clause = f" AND t.category_folder_id IN ({placeholders})"
            params.extend(folder_ids)

        cur.execute(
            f"""
            SELECT DISTINCT t.id, t.description, t.status, t.priority, t.due_date, t.parent_id,
                            t.category_folder_id,
                            CASE WHEN pp.task_id IS NOT NULL THEN 1 ELSE 0 END AS has_profile
            FROM tasks t
            LEFT JOIN project_profiles pp ON pp.task_id = t.id
            WHERE t.archived_at IS NULL
              AND (t.parent_id IS NULL OR pp.task_id IS NOT NULL)
            {folder_clause}
            ORDER BY LOWER(t.description), t.id;
            """,
            params,
        )
        rows = [dict(row) for row in cur.fetchall()]
        folders_by_id = {
            int(row["id"]): row for row in self.fetch_category_folders()
            if row.get("id") is not None
        }
        for row in rows:
            folder = folders_by_id.get(int(row.get("category_folder_id") or 0))
            row["folder_name"] = str(folder.get("name") or "") if folder else ""
            row["folder_path"] = str(folder.get("path") or "") if folder else ""
            row["folder_display_name"] = str(folder.get("display_name") or "") if folder else ""
            row["folder_icon_name"] = str(folder.get("icon_name") or "folder") if folder else "folder"
            row["folder_color_hex"] = str(folder.get("color_hex") or "") if folder else ""
        return rows

    def _ensure_project_phase_defaults_tx(self, cur, project_task_id: int):
        cur.execute(
            "SELECT COUNT(*) AS c FROM project_phases WHERE project_task_id=?;",
            (int(project_task_id),),
        )
        row = cur.fetchone()
        if int(row["c"] or 0) > 0:
            return
        stamp = now_iso()
        for phase in default_phases_payload(int(project_task_id), stamp):
            cur.execute(
                """
                INSERT INTO project_phases(project_task_id, name, sort_order, gantt_color_hex, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?);
                """,
                (
                    int(phase["project_task_id"]),
                    str(phase["name"]),
                    int(phase["sort_order"]),
                    str(phase.get("gantt_color_hex") or "").strip() or None,
                    str(phase["created_at"]),
                    str(phase["updated_at"]),
                ),
            )

    def fetch_project_profile(self, project_task_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT pp.*, t.description AS project_name, t.status AS task_status, t.due_date AS task_due_date
            FROM project_profiles pp
            JOIN tasks t ON t.id = pp.task_id
            WHERE pp.task_id=?;
            """,
            (int(project_task_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def ensure_project_profile(self, project_task_id: int) -> dict:
        existing = self.fetch_project_profile(int(project_task_id))
        if existing:
            with self.tx():
                cur = self.conn.cursor()
                self._ensure_project_phase_defaults_tx(cur, int(project_task_id))
            return self.fetch_project_profile(int(project_task_id)) or existing
        stamp = now_iso()
        with self.tx():
            cur = self.conn.cursor()
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
                VALUES(?, '', '', '', 'Self', '', NULL, '', NULL, '', '', ?, ?);
                """,
                (int(project_task_id), stamp, stamp),
            )
            self._ensure_project_phase_defaults_tx(cur, int(project_task_id))
        return self.fetch_project_profile(int(project_task_id)) or {"task_id": int(project_task_id)}

    def save_project_profile(self, project_task_id: int, payload: dict) -> dict:
        if not self._project_exists(int(project_task_id)):
            raise ValueError("Project task not found.")
        target_date = str(payload.get("target_date") or "").strip() or None
        health = normalize_health(payload.get("project_status_health"))
        with self.tx():
            cur = self.conn.cursor()
            self._ensure_project_phase_defaults_tx(cur, int(project_task_id))
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
                    int(project_task_id),
                    str(payload.get("objective") or ""),
                    str(payload.get("scope") or ""),
                    str(payload.get("out_of_scope") or ""),
                    str(payload.get("owner") or "Self") or "Self",
                    str(payload.get("stakeholders") or ""),
                    target_date,
                    str(payload.get("success_criteria") or ""),
                    health,
                    str(payload.get("summary") or ""),
                    str(payload.get("category") or ""),
                    now_iso(),
                    now_iso(),
                ),
            )
        return self.fetch_project_profile(int(project_task_id)) or {"task_id": int(project_task_id)}

    def fetch_project_phases(self, project_task_id: int) -> list[dict]:
        self.ensure_project_profile(int(project_task_id))
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, project_task_id, name, sort_order, gantt_color_hex, created_at, updated_at
            FROM project_phases
            WHERE project_task_id=?
            ORDER BY sort_order ASC, id ASC;
            """,
            (int(project_task_id),),
        )
        return [dict(row) for row in cur.fetchall()]

    def fetch_project_phase_by_id(self, phase_id: int) -> dict | None:
        return self._phase_record(int(phase_id))

    def add_project_phase(self, project_task_id: int, name: str) -> int:
        phase_name = str(name or "").strip()
        if not phase_name:
            raise ValueError("Phase name is required.")
        self.ensure_project_profile(int(project_task_id))
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM project_phases WHERE project_task_id=?;",
                (int(project_task_id),),
            )
            next_order = int(cur.fetchone()["next_order"])
            cur.execute(
                """
                INSERT INTO project_phases(project_task_id, name, sort_order, gantt_color_hex, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?);
                """,
                (int(project_task_id), phase_name, next_order, None, now_iso(), now_iso()),
            )
            return int(cur.lastrowid)

    def update_project_phase(self, phase_id: int, name: str):
        phase_name = str(name or "").strip()
        if not phase_name:
            raise ValueError("Phase name is required.")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE project_phases SET name=?, updated_at=? WHERE id=?;",
                (phase_name, now_iso(), int(phase_id)),
            )

    def set_project_phase_gantt_color(self, phase_id: int, color_hex: str | None):
        if not self._phase_record(int(phase_id)):
            raise ValueError("Phase not found.")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE project_phases SET gantt_color_hex=?, updated_at=? WHERE id=?;",
                (str(color_hex or "").strip() or None, now_iso(), int(phase_id)),
            )

    def delete_project_phase(self, phase_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("UPDATE tasks SET phase_id=NULL WHERE phase_id=?;", (int(phase_id),))
            cur.execute("UPDATE milestones SET phase_id=NULL WHERE phase_id=?;", (int(phase_id),))
            cur.execute("UPDATE deliverables SET phase_id=NULL WHERE phase_id=?;", (int(phase_id),))
            cur.execute("DELETE FROM project_phases WHERE id=?;", (int(phase_id),))

    def restore_project_phase_snapshot(self, snapshot: dict):
        if not snapshot:
            raise ValueError("Project phase snapshot is required.")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO project_phases(
                    id,
                    project_task_id,
                    name,
                    sort_order,
                    gantt_color_hex,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_task_id=excluded.project_task_id,
                    name=excluded.name,
                    sort_order=excluded.sort_order,
                    gantt_color_hex=excluded.gantt_color_hex,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at;
                """,
                (
                    int(snapshot["id"]),
                    int(snapshot["project_task_id"]),
                    str(snapshot.get("name") or ""),
                    int(snapshot.get("sort_order") or 1),
                    str(snapshot.get("gantt_color_hex") or "").strip() or None,
                    str(snapshot.get("created_at") or now_iso()),
                    str(snapshot.get("updated_at") or now_iso()),
                ),
            )

    def set_task_phase(self, task_id: int, phase_id: int | None):
        phase_value = None if phase_id is None else int(phase_id)
        if phase_value is not None:
            project_task_id = self.project_id_for_task(int(task_id))
            if project_task_id is None:
                raise ValueError("Task not found.")
            phase = self._phase_record(int(phase_value))
            if not phase:
                raise ValueError("Phase not found.")
            if int(phase["project_task_id"]) != int(project_task_id):
                raise ValueError("Selected phase does not belong to this task's project.")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE tasks SET phase_id=?, last_update=? WHERE id=?;",
                (phase_value, now_iso(), int(task_id)),
            )

    def fetch_project_dependencies(self, project_task_id: int) -> list[dict]:
        task_ids = set(self.fetch_project_task_ids(int(project_task_id)))
        milestone_ids = {int(row["id"]) for row in self.fetch_project_milestones(int(project_task_id))}
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type, is_soft, created_at
            FROM pm_dependencies
            ORDER BY predecessor_kind, predecessor_id, successor_kind, successor_id, id;
            """
        )
        rows = []
        for row in cur.fetchall():
            item = dict(row)
            pre_kind = str(item.get("predecessor_kind") or "")
            succ_kind = str(item.get("successor_kind") or "")
            pre_id = int(item.get("predecessor_id") or 0)
            succ_id = int(item.get("successor_id") or 0)
            in_project = (
                (pre_kind == "task" and pre_id in task_ids) or
                (pre_kind == "milestone" and pre_id in milestone_ids) or
                (succ_kind == "task" and succ_id in task_ids) or
                (succ_kind == "milestone" and succ_id in milestone_ids)
            )
            if in_project:
                rows.append(item)
        return rows

    def fetch_dependencies_for_item(self, kind: str, item_id: int) -> list[dict]:
        item_kind = str(kind or "").strip().lower()
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT pd.id AS edge_id, pd.predecessor_kind AS kind, pd.predecessor_id AS id,
                   pd.dep_type, pd.is_soft
            FROM pm_dependencies pd
            WHERE pd.successor_kind=? AND pd.successor_id=?
            ORDER BY pd.predecessor_kind, pd.predecessor_id, pd.id;
            """,
            (item_kind, int(item_id)),
        )
        return [dict(row) for row in cur.fetchall()]

    def _pm_item_exists(self, kind: str, item_id: int) -> bool:
        item_kind = str(kind or "").strip().lower()
        cur = self.conn.cursor()
        if item_kind == "task":
            cur.execute("SELECT 1 FROM tasks WHERE id=?;", (int(item_id),))
            return cur.fetchone() is not None
        if item_kind == "milestone":
            cur.execute("SELECT 1 FROM milestones WHERE id=?;", (int(item_id),))
            return cur.fetchone() is not None
        return False

    def _fetch_all_pm_dependencies(self) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type, is_soft, created_at
            FROM pm_dependencies;
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def _sync_task_dependency_edges_tx(self, cur, task_id: int, depends_on_ids: list[int]):
        cur.execute(
            """
            DELETE FROM pm_dependencies
            WHERE successor_kind='task'
              AND successor_id=?
              AND predecessor_kind='task';
            """,
            (int(task_id),),
        )
        for dep_id in depends_on_ids:
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
                VALUES('task', ?, 'task', ?, ?, 0, ?)
                ON CONFLICT(predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type) DO NOTHING;
                """,
                (int(dep_id), int(task_id), DEPENDENCY_TYPE_FINISH_TO_START, now_iso()),
            )

    def set_milestone_dependencies(self, milestone_id: int, dependency_refs: list[dict]):
        refs = normalize_dependency_refs(dependency_refs)
        if not self._pm_item_exists("milestone", int(milestone_id)):
            raise ValueError("Milestone not found.")
        existing_edges = self._fetch_all_pm_dependencies()
        for ref in refs:
            if not self._pm_item_exists(str(ref["kind"]), int(ref["id"])):
                raise ValueError("Dependency target does not exist.")
            ok, reason = validate_dependency_graph(
                existing_edges,
                str(ref["kind"]),
                int(ref["id"]),
                "milestone",
                int(milestone_id),
            )
            if not ok:
                raise ValueError(reason)
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "DELETE FROM pm_dependencies WHERE successor_kind='milestone' AND successor_id=?;",
                (int(milestone_id),),
            )
            for ref in refs:
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
                    VALUES(?, ?, 'milestone', ?, ?, 0, ?)
                    ON CONFLICT(predecessor_kind, predecessor_id, successor_kind, successor_id, dep_type) DO NOTHING;
                    """,
                    (
                        str(ref["kind"]),
                        int(ref["id"]),
                        int(milestone_id),
                        DEPENDENCY_TYPE_FINISH_TO_START,
                        now_iso(),
                    ),
                )

    def fetch_project_milestones(self, project_task_id: int) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT m.id, m.project_task_id, m.title, m.description, m.phase_id, m.linked_task_id,
                   m.start_date, m.target_date, m.baseline_target_date,
                   m.status, m.progress_percent, m.completed_at, m.created_at, m.updated_at,
                   m.gantt_color_hex,
                   pp.name AS phase_name,
                   t.description AS linked_task_description
            FROM milestones m
            LEFT JOIN project_phases pp ON pp.id = m.phase_id
            LEFT JOIN tasks t ON t.id = m.linked_task_id
            WHERE m.project_task_id=?
            ORDER BY COALESCE(m.target_date, '9999-12-31') ASC, m.id ASC;
            """,
            (int(project_task_id),),
        )
        rows = [dict(row) for row in cur.fetchall()]
        task_rows = {int(row["id"]): row for row in self.fetch_tasks() if row.get("id") is not None}
        milestone_rows = {int(row["id"]): row for row in rows if row.get("id") is not None}
        for row in rows:
            deps = self.fetch_dependencies_for_item("milestone", int(row["id"]))
            row["dependencies"] = deps
            row["is_blocked"] = is_dependency_blocked(
                dependencies=deps,
                tasks_by_id=task_rows,
                milestones_by_id=milestone_rows,
            )
        return rows

    def fetch_milestone_by_id(self, milestone_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT *
            FROM milestones
            WHERE id=?;
            """,
            (int(milestone_id),),
        )
        row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        item["dependencies"] = self.fetch_dependencies_for_item("milestone", int(milestone_id))
        return item

    def upsert_milestone(self, payload: dict) -> int:
        status = normalize_record_status(payload.get("status"), MILESTONE_STATUSES, "planned")
        progress = max(0, min(100, int(payload.get("progress_percent") or 0)))
        if status == "completed":
            progress = 100
        milestone_id = payload.get("id")
        current = self.fetch_milestone_by_id(int(milestone_id)) if milestone_id else None
        project_task_id = payload.get("project_task_id")
        if project_task_id is None and current is not None:
            project_task_id = current.get("project_task_id")
        if project_task_id is None or not self._project_exists(int(project_task_id)):
            raise ValueError("Milestone must belong to a valid project.")

        phase_id = payload.get("phase_id")
        if phase_id is not None:
            phase = self._phase_record(int(phase_id))
            if not phase or int(phase["project_task_id"]) != int(project_task_id):
                raise ValueError("Milestone phase must belong to the same project.")

        linked_task_id = payload.get("linked_task_id")
        if linked_task_id is not None and not self._task_in_project(int(linked_task_id), int(project_task_id)):
            raise ValueError("Linked task must belong to the same project.")

        with self.tx():
            cur = self.conn.cursor()
            if milestone_id:
                cur.execute(
                    """
                    UPDATE milestones
                    SET title=?, description=?, phase_id=?, linked_task_id=?, start_date=?, target_date=?,
                        baseline_target_date=?, status=?, progress_percent=?, completed_at=?, gantt_color_hex=?, updated_at=?
                    WHERE id=?;
                    """,
                    (
                        str(payload.get("title") or ""),
                        str(payload.get("description") or ""),
                        payload.get("phase_id"),
                        payload.get("linked_task_id"),
                        payload.get("start_date"),
                        payload.get("target_date"),
                        payload.get("baseline_target_date"),
                        status,
                        progress,
                        payload.get("completed_at"),
                        str(payload.get("gantt_color_hex") or "").strip() or None,
                        now_iso(),
                        int(milestone_id),
                    ),
                )
                target_id = int(milestone_id)
            else:
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
                        gantt_color_hex,
                        created_at,
                        updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        int(project_task_id),
                        str(payload.get("title") or ""),
                        str(payload.get("description") or ""),
                        payload.get("phase_id"),
                        payload.get("linked_task_id"),
                        payload.get("start_date"),
                        payload.get("target_date"),
                        payload.get("baseline_target_date"),
                        status,
                        progress,
                        payload.get("completed_at"),
                        str(payload.get("gantt_color_hex") or "").strip() or None,
                        now_iso(),
                        now_iso(),
                    ),
                )
                target_id = int(cur.lastrowid)
        self.set_milestone_dependencies(int(target_id), payload.get("dependencies") or [])
        return int(target_id)

    def delete_milestone(self, milestone_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                DELETE FROM pm_dependencies
                WHERE (predecessor_kind='milestone' AND predecessor_id=?)
                   OR (successor_kind='milestone' AND successor_id=?);
                """,
                (int(milestone_id), int(milestone_id)),
            )
            cur.execute("DELETE FROM milestones WHERE id=?;", (int(milestone_id),))

    def restore_milestone_snapshot(self, snapshot: dict):
        if not snapshot or snapshot.get("id") is None:
            return
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO milestones(
                    id,
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
                    gantt_color_hex,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_task_id=excluded.project_task_id,
                    title=excluded.title,
                    description=excluded.description,
                    phase_id=excluded.phase_id,
                    linked_task_id=excluded.linked_task_id,
                    start_date=excluded.start_date,
                    target_date=excluded.target_date,
                    baseline_target_date=excluded.baseline_target_date,
                    status=excluded.status,
                    progress_percent=excluded.progress_percent,
                    completed_at=excluded.completed_at,
                    gantt_color_hex=excluded.gantt_color_hex,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at;
                """,
                (
                    int(snapshot["id"]),
                    int(snapshot["project_task_id"]),
                    str(snapshot.get("title") or ""),
                    str(snapshot.get("description") or ""),
                    snapshot.get("phase_id"),
                    snapshot.get("linked_task_id"),
                    snapshot.get("start_date"),
                    snapshot.get("target_date"),
                    snapshot.get("baseline_target_date"),
                    str(snapshot.get("status") or "planned"),
                    int(snapshot.get("progress_percent") or 0),
                    snapshot.get("completed_at"),
                    str(snapshot.get("gantt_color_hex") or "").strip() or None,
                    snapshot.get("created_at") or now_iso(),
                    snapshot.get("updated_at") or now_iso(),
                ),
            )
        self.set_milestone_dependencies(
            int(snapshot["id"]),
            list(snapshot.get("dependencies") or []),
        )

    def set_milestone_gantt_color(self, milestone_id: int, color_hex: str | None):
        normalized = str(color_hex or "").strip() or None
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE milestones SET gantt_color_hex=?, updated_at=? WHERE id=?;",
                (normalized, now_iso(), int(milestone_id)),
            )

    def fetch_project_deliverables(self, project_task_id: int) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT d.id, d.project_task_id, d.title, d.description, d.phase_id, d.linked_task_id,
                   d.linked_milestone_id, d.due_date, d.baseline_due_date, d.acceptance_criteria,
                   d.version_ref, d.status, d.completed_at, d.created_at, d.updated_at,
                   d.gantt_color_hex,
                   pp.name AS phase_name,
                   t.description AS linked_task_description,
                   m.title AS linked_milestone_title
            FROM deliverables d
            LEFT JOIN project_phases pp ON pp.id = d.phase_id
            LEFT JOIN tasks t ON t.id = d.linked_task_id
            LEFT JOIN milestones m ON m.id = d.linked_milestone_id
            WHERE d.project_task_id=?
            ORDER BY COALESCE(d.due_date, '9999-12-31') ASC, d.id ASC;
            """,
            (int(project_task_id),),
        )
        return [dict(row) for row in cur.fetchall()]

    def fetch_deliverable_by_id(self, deliverable_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM deliverables WHERE id=?;", (int(deliverable_id),))
        row = cur.fetchone()
        return dict(row) if row else None

    def upsert_deliverable(self, payload: dict) -> int:
        status = normalize_record_status(payload.get("status"), DELIVERABLE_STATUSES, "planned")
        deliverable_id = payload.get("id")
        current = self.fetch_deliverable_by_id(int(deliverable_id)) if deliverable_id else None
        project_task_id = payload.get("project_task_id")
        if project_task_id is None and current is not None:
            project_task_id = current.get("project_task_id")
        if project_task_id is None or not self._project_exists(int(project_task_id)):
            raise ValueError("Deliverable must belong to a valid project.")

        phase_id = payload.get("phase_id")
        if phase_id is not None:
            phase = self._phase_record(int(phase_id))
            if not phase or int(phase["project_task_id"]) != int(project_task_id):
                raise ValueError("Deliverable phase must belong to the same project.")

        linked_task_id = payload.get("linked_task_id")
        if linked_task_id is not None and not self._task_in_project(int(linked_task_id), int(project_task_id)):
            raise ValueError("Linked task must belong to the same project.")

        linked_milestone_id = payload.get("linked_milestone_id")
        if linked_milestone_id is not None and not self._milestone_in_project(
            int(linked_milestone_id),
            int(project_task_id),
        ):
            raise ValueError("Linked milestone must belong to the same project.")

        with self.tx():
            cur = self.conn.cursor()
            if deliverable_id:
                cur.execute(
                    """
                    UPDATE deliverables
                    SET title=?, description=?, phase_id=?, linked_task_id=?, linked_milestone_id=?,
                        due_date=?, baseline_due_date=?, acceptance_criteria=?, version_ref=?,
                        status=?, completed_at=?, gantt_color_hex=?, updated_at=?
                    WHERE id=?;
                    """,
                    (
                        str(payload.get("title") or ""),
                        str(payload.get("description") or ""),
                        payload.get("phase_id"),
                        payload.get("linked_task_id"),
                        payload.get("linked_milestone_id"),
                        payload.get("due_date"),
                        payload.get("baseline_due_date"),
                        str(payload.get("acceptance_criteria") or ""),
                        str(payload.get("version_ref") or ""),
                        status,
                        payload.get("completed_at"),
                        str(payload.get("gantt_color_hex") or "").strip() or None,
                        now_iso(),
                        int(deliverable_id),
                    ),
                )
                return int(deliverable_id)

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
                    gantt_color_hex,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    int(project_task_id),
                    str(payload.get("title") or ""),
                    str(payload.get("description") or ""),
                    payload.get("phase_id"),
                    payload.get("linked_task_id"),
                    payload.get("linked_milestone_id"),
                    payload.get("due_date"),
                    payload.get("baseline_due_date"),
                    str(payload.get("acceptance_criteria") or ""),
                    str(payload.get("version_ref") or ""),
                    status,
                    payload.get("completed_at"),
                    str(payload.get("gantt_color_hex") or "").strip() or None,
                    now_iso(),
                    now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def delete_deliverable(self, deliverable_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("DELETE FROM deliverables WHERE id=?;", (int(deliverable_id),))

    def restore_deliverable_snapshot(self, snapshot: dict):
        if not snapshot or snapshot.get("id") is None:
            return
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO deliverables(
                    id,
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
                    gantt_color_hex,
                    created_at,
                    updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_task_id=excluded.project_task_id,
                    title=excluded.title,
                    description=excluded.description,
                    phase_id=excluded.phase_id,
                    linked_task_id=excluded.linked_task_id,
                    linked_milestone_id=excluded.linked_milestone_id,
                    due_date=excluded.due_date,
                    baseline_due_date=excluded.baseline_due_date,
                    acceptance_criteria=excluded.acceptance_criteria,
                    version_ref=excluded.version_ref,
                    status=excluded.status,
                    completed_at=excluded.completed_at,
                    gantt_color_hex=excluded.gantt_color_hex,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at;
                """,
                (
                    int(snapshot["id"]),
                    int(snapshot["project_task_id"]),
                    str(snapshot.get("title") or ""),
                    str(snapshot.get("description") or ""),
                    snapshot.get("phase_id"),
                    snapshot.get("linked_task_id"),
                    snapshot.get("linked_milestone_id"),
                    snapshot.get("due_date"),
                    snapshot.get("baseline_due_date"),
                    str(snapshot.get("acceptance_criteria") or ""),
                    str(snapshot.get("version_ref") or ""),
                    str(snapshot.get("status") or "planned"),
                    snapshot.get("completed_at"),
                    str(snapshot.get("gantt_color_hex") or "").strip() or None,
                    snapshot.get("created_at") or now_iso(),
                    snapshot.get("updated_at") or now_iso(),
                ),
            )

    def set_deliverable_gantt_color(self, deliverable_id: int, color_hex: str | None):
        normalized = str(color_hex or "").strip() or None
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE deliverables SET gantt_color_hex=?, updated_at=? WHERE id=?;",
                (normalized, now_iso(), int(deliverable_id)),
            )

    def fetch_project_register_entries(self, project_task_id: int, entry_type: str | None = None) -> list[dict]:
        cur = self.conn.cursor()
        if entry_type:
            cur.execute(
                """
                SELECT pre.*, t.description AS linked_task_description, m.title AS linked_milestone_title
                FROM project_register_entries pre
                LEFT JOIN tasks t ON t.id = pre.linked_task_id
                LEFT JOIN milestones m ON m.id = pre.linked_milestone_id
                WHERE pre.project_task_id=? AND pre.entry_type=?
                ORDER BY pre.created_at DESC, pre.id DESC;
                """,
                (int(project_task_id), normalize_register_type(entry_type)),
            )
        else:
            cur.execute(
                """
                SELECT pre.*, t.description AS linked_task_description, m.title AS linked_milestone_title
                FROM project_register_entries pre
                LEFT JOIN tasks t ON t.id = pre.linked_task_id
                LEFT JOIN milestones m ON m.id = pre.linked_milestone_id
                WHERE pre.project_task_id=?
                ORDER BY pre.created_at DESC, pre.id DESC;
                """,
                (int(project_task_id),),
            )
        return [dict(row) for row in cur.fetchall()]

    def fetch_register_entry_by_id(self, entry_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM project_register_entries WHERE id=?;", (int(entry_id),))
        row = cur.fetchone()
        return dict(row) if row else None

    def upsert_project_register_entry(self, payload: dict) -> int:
        entry_type = normalize_register_type(payload.get("entry_type"))
        status = normalize_record_status(payload.get("status"), REGISTER_STATUSES, "open")
        entry_id = payload.get("id")
        current = self.fetch_register_entry_by_id(int(entry_id)) if entry_id else None
        project_task_id = payload.get("project_task_id")
        if project_task_id is None and current is not None:
            project_task_id = current.get("project_task_id")
        if project_task_id is None or not self._project_exists(int(project_task_id)):
            raise ValueError("Register entry must belong to a valid project.")

        linked_task_id = payload.get("linked_task_id")
        if linked_task_id is not None and not self._task_in_project(int(linked_task_id), int(project_task_id)):
            raise ValueError("Linked task must belong to the same project.")

        linked_milestone_id = payload.get("linked_milestone_id")
        if linked_milestone_id is not None and not self._milestone_in_project(
            int(linked_milestone_id),
            int(project_task_id),
        ):
            raise ValueError("Linked milestone must belong to the same project.")

        with self.tx():
            cur = self.conn.cursor()
            if entry_id:
                cur.execute(
                    """
                    UPDATE project_register_entries
                    SET entry_type=?, title=?, details=?, status=?, severity=?, review_date=?,
                        linked_task_id=?, linked_milestone_id=?, updated_at=?
                    WHERE id=?;
                    """,
                    (
                        entry_type,
                        str(payload.get("title") or ""),
                        str(payload.get("details") or ""),
                        status,
                        payload.get("severity"),
                        payload.get("review_date"),
                        payload.get("linked_task_id"),
                        payload.get("linked_milestone_id"),
                        now_iso(),
                        int(entry_id),
                    ),
                )
                return int(entry_id)

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
                    int(project_task_id),
                    entry_type,
                    str(payload.get("title") or ""),
                    str(payload.get("details") or ""),
                    status,
                    payload.get("severity"),
                    payload.get("review_date"),
                    payload.get("linked_task_id"),
                    payload.get("linked_milestone_id"),
                    now_iso(),
                    now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def delete_project_register_entry(self, entry_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("DELETE FROM project_register_entries WHERE id=?;", (int(entry_id),))

    def fetch_project_baseline(self, project_task_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM project_baselines WHERE project_task_id=?;", (int(project_task_id),))
        row = cur.fetchone()
        return dict(row) if row else None

    def save_project_baseline(self, project_task_id: int, target_date: str | None, effort_minutes: int | None):
        if not self._project_exists(int(project_task_id)):
            raise ValueError("Project task not found.")
        with self.tx():
            cur = self.conn.cursor()
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
                    int(project_task_id),
                    str(target_date or "").strip() or None,
                    None if effort_minutes is None else int(effort_minutes),
                    now_iso(),
                    now_iso(),
                ),
            )

    def fetch_project_dashboard(
        self,
        project_task_id: int,
        *,
        ensure_profile: bool = True,
    ) -> dict | None:
        project_task = self.fetch_task_by_id(int(project_task_id))
        if not project_task or str(project_task.get("archived_at") or "").strip():
            return None
        if ensure_profile:
            profile = self.ensure_project_profile(int(project_task_id))
            phases = self.fetch_project_phases(int(project_task_id))
        else:
            profile = self.fetch_project_profile(int(project_task_id))
            phases = self.fetch_project_phases(int(project_task_id)) if profile else []
        task_ids = set(self.fetch_project_task_ids(int(project_task_id)))
        tasks = [
            row
            for row in self.fetch_tasks()
            if int(row["id"]) in task_ids
            and not str(row.get("archived_at") or "").strip()
        ]
        milestones = self.fetch_project_milestones(int(project_task_id))
        deliverables = self.fetch_project_deliverables(int(project_task_id))
        register_entries = self.fetch_project_register_entries(int(project_task_id))
        baseline = self.fetch_project_baseline(int(project_task_id))
        dependency_rows = self.fetch_project_dependencies(int(project_task_id))
        dependency_map: dict[tuple[str, int], list[dict]] = {}
        for row in dependency_rows:
            key = (str(row.get("successor_kind") or ""), int(row.get("successor_id") or 0))
            dependency_map.setdefault(key, []).append(
                {
                    "id": int(row.get("predecessor_id") or 0),
                    "kind": str(row.get("predecessor_kind") or ""),
                    "dep_type": str(row.get("dep_type") or DEPENDENCY_TYPE_FINISH_TO_START),
                    "is_soft": int(row.get("is_soft") or 0),
                }
            )
        summary = build_project_summary(
            project_task,
            profile,
            phases,
            tasks,
            milestones,
            deliverables,
            register_entries,
            baseline,
            dependency_map,
            today=date.today(),
        )
        timeline_rows = build_timeline_rows(
            project_task,
            phases,
            tasks,
            milestones,
            deliverables,
            summary,
            dependency_rows,
        )
        capacity = compute_personal_capacity(tasks, today=date.today())
        return {
            "project": project_task,
            "profile": profile,
            "phases": phases,
            "tasks": tasks,
            "milestones": milestones,
            "deliverables": deliverables,
            "register_entries": register_entries,
            "baseline": baseline,
            "dependencies": dependency_rows,
            "summary": summary,
            "timeline_rows": timeline_rows,
            "capacity": capacity,
        }

    def fetch_project_health_overview(self) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for row in self.list_project_candidates():
            try:
                project_task_id = int(row["id"])
            except Exception:
                continue
            dashboard = self.fetch_project_dashboard(project_task_id, ensure_profile=False)
            if not dashboard:
                continue
            summary = dashboard.get("summary") or {}
            out[project_task_id] = {
                "effective_health": str(summary.get("effective_health") or ""),
                "effective_health_label": str(summary.get("effective_health_label") or ""),
                "manual_health": summary.get("manual_health"),
                "inferred_health": summary.get("inferred_health"),
                "blocked_task_count": int(summary.get("blocked_task_count") or 0),
                "blocked_milestone_count": int(summary.get("blocked_milestone_count") or 0),
                "milestone_overdue_count": int(summary.get("milestone_overdue_count") or 0),
                "deliverables_due_soon": int(summary.get("deliverables_due_soon") or 0),
            }
        return out

    # ---------- Saved filter views ----------
    def list_saved_filter_views(self) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, name, state_json, created_at, updated_at
            FROM saved_filter_views
            ORDER BY LOWER(name), name;
            """
        )
        out = []
        for r in cur.fetchall():
            row = dict(r)
            try:
                row["state"] = json.loads(str(row.get("state_json") or "{}"))
            except Exception:
                row["state"] = {}
            out.append(row)
        return out

    def save_filter_view(self, name: str, state: dict, overwrite: bool = True):
        n = str(name or "").strip()
        if not n:
            raise ValueError("View name is required")
        payload = json.dumps(state or {}, ensure_ascii=False)
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("SELECT id FROM saved_filter_views WHERE name=?;", (n,))
            row = cur.fetchone()
            if row:
                if not overwrite:
                    raise ValueError("A saved view with this name already exists")
                cur.execute(
                    """
                    UPDATE saved_filter_views
                    SET state_json=?, updated_at=?
                    WHERE name=?;
                    """,
                    (payload, now_iso(), n),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO saved_filter_views(name, state_json, created_at, updated_at)
                    VALUES(?, ?, ?, ?);
                    """,
                    (n, payload, now_iso(), now_iso()),
                )

    def delete_filter_view(self, name: str):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("DELETE FROM saved_filter_views WHERE name=?;", (str(name or "").strip(),))

    def load_filter_view(self, name: str) -> dict | None:
        cur = self.conn.cursor()
        cur.execute("SELECT state_json FROM saved_filter_views WHERE name=?;", (str(name or "").strip(),))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(str(row["state_json"] or "{}"))
        except Exception:
            return {}

    # ---------- Recurrence ----------
    def get_recurrence_for_task(self, task_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, task_id, frequency, create_next_on_done, is_active, created_at, updated_at
            FROM recurrence_rules
            WHERE task_id=?;
            """,
            (int(task_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def set_recurrence_for_task(self, task_id: int, frequency: str | None, create_next_on_done: bool = True):
        freq = str(frequency or "").strip().lower()
        with self.tx():
            cur = self.conn.cursor()
            if not freq:
                cur.execute("SELECT id FROM recurrence_rules WHERE task_id=?;", (int(task_id),))
                rr = cur.fetchone()
                if rr:
                    rule_id = int(rr["id"])
                    cur.execute("DELETE FROM recurrence_rules WHERE id=?;", (int(rule_id),))
                    cur.execute(
                        "UPDATE tasks SET recurrence_rule_id=NULL, last_update=? WHERE recurrence_rule_id=?;",
                        (now_iso(), int(rule_id)),
                    )
                cur.execute(
                    """
                    UPDATE tasks
                    SET recurrence_rule_id=NULL, recurrence_origin_task_id=NULL, is_generated_occurrence=0, last_update=?
                    WHERE id=?;
                    """,
                    (now_iso(), int(task_id)),
                )
                return

            if freq not in RECURRENCE_FREQUENCIES:
                raise ValueError("Invalid recurrence frequency")

            cur.execute("SELECT id FROM recurrence_rules WHERE task_id=?;", (int(task_id),))
            row = cur.fetchone()
            if row:
                rule_id = int(row["id"])
                cur.execute(
                    """
                    UPDATE recurrence_rules
                    SET frequency=?, create_next_on_done=?, is_active=1, updated_at=?
                    WHERE id=?;
                    """,
                    (freq, 1 if create_next_on_done else 0, now_iso(), int(rule_id)),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO recurrence_rules(task_id, frequency, create_next_on_done, is_active, created_at, updated_at)
                    VALUES(?, ?, ?, 1, ?, ?);
                    """,
                    (int(task_id), freq, 1 if create_next_on_done else 0, now_iso(), now_iso()),
                )
                rule_id = int(cur.lastrowid)

            cur.execute(
                """
                UPDATE tasks
                SET recurrence_rule_id=?, is_generated_occurrence=0, last_update=?
                WHERE id=?;
                """,
                (int(rule_id), now_iso(), int(task_id)),
            )

    def maybe_create_next_recurrence(self, done_task_id: int) -> int | None:
        """
        If the task has an active rule with create_next_on_done=1 and no child occurrence
        already generated from this done instance, create the next occurrence.
        Returns new task id or None.
        """
        task = self.fetch_task_by_id(int(done_task_id))
        if not task:
            return None

        cur = self.conn.cursor()
        rid = task.get("recurrence_rule_id")
        if rid is None:
            return None

        cur.execute(
            """
            SELECT id, frequency, create_next_on_done, is_active
            FROM recurrence_rules
            WHERE id=?;
            """,
            (int(rid),),
        )
        rule = cur.fetchone()
        if not rule:
            return None
        if int(rule["is_active"] or 0) != 1 or int(rule["create_next_on_done"] or 0) != 1:
            return None

        cur.execute("SELECT 1 FROM tasks WHERE recurrence_origin_task_id=? LIMIT 1;", (int(done_task_id),))
        if cur.fetchone():
            return None

        due = _parse_iso_date(task.get("due_date"))
        if due is None:
            due = date.today()
        next_due = _advance_recurrence_due(due, str(rule["frequency"]))

        new_task = dict(task)
        new_task.pop("id", None)
        new_task["description"] = str(task.get("description") or "")
        new_task["due_date"] = next_due.isoformat()
        new_task["last_update"] = now_iso()
        new_task["priority"] = int(task.get("priority") or 3)
        new_task["status"] = "Todo"
        new_task["parent_id"] = task.get("parent_id")
        new_task["sort_order"] = self.next_sort_order(task.get("parent_id"))
        new_task["is_collapsed"] = 0
        new_task["archived_at"] = None
        new_task["reminder_at"] = None
        new_task["reminder_minutes_before"] = None
        new_task["reminder_fired_at"] = None
        new_task["recurrence_rule_id"] = int(rid)
        new_task["recurrence_origin_task_id"] = int(done_task_id)
        new_task["is_generated_occurrence"] = 1

        new_id = self.insert_task(new_task, keep_id=False)
        self.set_task_tags(int(new_id), task.get("tags", []))

        with self.tx():
            c2 = self.conn.cursor()
            c2.execute(
                "UPDATE recurrence_rules SET updated_at=? WHERE id=?;",
                (now_iso(), int(rid)),
            )

        return int(new_id)

    # ---------- Attachments ----------
    def fetch_attachments(self, task_id: int) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, task_id, path, label, created_at
            FROM task_attachments
            WHERE task_id=?
            ORDER BY id;
            """,
            (int(task_id),),
        )
        return [dict(r) for r in cur.fetchall()]

    def add_attachment(self, task_id: int, path: str, label: str = "") -> int:
        p = str(path or "").strip()
        if not p:
            raise ValueError("Attachment path is required")
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO task_attachments(task_id, path, label, created_at)
                VALUES(?, ?, ?, ?);
                """,
                (int(task_id), p, str(label or "").strip(), now_iso()),
            )
            cur.execute("UPDATE tasks SET last_update=? WHERE id=?;", (now_iso(), int(task_id)))

    def set_task_gantt_color(self, task_id: int, color_hex: str | None):
        normalized = str(color_hex or "").strip() or None
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE tasks SET gantt_color_hex=?, last_update=? WHERE id=?;",
                (normalized, now_iso(), int(task_id)),
            )
            return int(cur.lastrowid)

    def fetch_attachment_by_id(self, attachment_id: int) -> dict | None:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, task_id, path, label, created_at
            FROM task_attachments
            WHERE id=?;
            """,
            (int(attachment_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def remove_attachment(self, attachment_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "SELECT task_id FROM task_attachments WHERE id=?;",
                (int(attachment_id),),
            )
            row = cur.fetchone()
            cur.execute("DELETE FROM task_attachments WHERE id=?;", (int(attachment_id),))
            if row:
                cur.execute("UPDATE tasks SET last_update=? WHERE id=?;", (now_iso(), int(row["task_id"])))

    # ---------- Time tracking ----------
    def start_timer(self, task_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("SELECT timer_started_at FROM tasks WHERE id=?;", (int(task_id),))
            row = cur.fetchone()
            if not row:
                return
            if row["timer_started_at"]:
                return
            cur.execute(
                "UPDATE tasks SET timer_started_at=?, last_update=? WHERE id=?;",
                (now_iso(), now_iso(), int(task_id)),
            )

    def stop_timer(self, task_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("SELECT timer_started_at, actual_minutes FROM tasks WHERE id=?;", (int(task_id),))
            row = cur.fetchone()
            if not row:
                return
            started = row["timer_started_at"]
            if not started:
                return
            try:
                start_dt = datetime.fromisoformat(str(started).replace("T", " "))
                delta_min = max(0, int((datetime.now() - start_dt).total_seconds() // 60))
            except Exception:
                delta_min = 0
            cur.execute(
                """
                UPDATE tasks
                SET actual_minutes=COALESCE(actual_minutes, 0) + ?,
                    timer_started_at=NULL,
                    last_update=?
                WHERE id=?;
                """,
                (int(delta_min), now_iso(), int(task_id)),
            )

    # ---------- Reminders ----------
    def set_task_reminder(self, task_id: int, reminder_at: str | None, minutes_before: int | None = None):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                """
                UPDATE tasks
                SET reminder_at=?, reminder_minutes_before=?, reminder_fired_at=NULL, last_update=?
                WHERE id=?;
                """,
                (reminder_at, minutes_before, now_iso(), int(task_id)),
            )

    def clear_task_reminder(self, task_id: int):
        self.set_task_reminder(int(task_id), None, None)

    def fetch_pending_reminders(self, limit: int = 20) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, description, due_date, reminder_at, reminder_minutes_before, status, priority
            FROM tasks
            WHERE archived_at IS NULL
              AND status <> 'Done'
              AND reminder_at IS NOT NULL
              AND reminder_fired_at IS NULL
              AND reminder_at <= ?
            ORDER BY reminder_at ASC, id ASC
            LIMIT ?;
            """,
            (now_iso(), int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]

    def mark_reminder_fired(self, task_id: int):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE tasks SET reminder_fired_at=?, last_update=? WHERE id=?;",
                (now_iso(), now_iso(), int(task_id)),
            )

    # ---------- Child progress ----------
    def child_progress(self, task_id: int) -> dict:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='Done' THEN 1 ELSE 0 END) AS done_count
            FROM tasks
            WHERE parent_id=? AND archived_at IS NULL;
            """,
            (int(task_id),),
        )
        row = cur.fetchone()
        total = int(row["total"] or 0)
        done_count = int(row["done_count"] or 0)
        pct = (100.0 * done_count / total) if total > 0 else 0.0
        return {"done": done_count, "total": total, "percent": pct}

    def build_project_template_payload(self, project_task_id: int, task_ids: set[int] | None = None) -> dict | None:
        project_id = int(project_task_id)
        profile = self.fetch_project_profile(project_id)
        if not profile:
            return None

        included_task_ids = {
            int(row_id)
            for row_id in (task_ids or set(self.fetch_project_task_ids(project_id)))
            if int(row_id) > 0
        }
        if project_id not in included_task_ids:
            return None

        phases = self.fetch_project_phases(project_id)
        included_phases = {int(row["id"]) for row in phases if row.get("id") is not None}
        included_tasks_sql = ", ".join("?" for _ in sorted(included_task_ids))
        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT id, phase_id
            FROM tasks
            WHERE id IN ({included_tasks_sql}) AND phase_id IS NOT NULL;
            """,
            tuple(sorted(included_task_ids)),
        )
        task_phase_refs = [
            {
                "task_id": int(row_data["id"]),
                "phase_id": int(row_data["phase_id"]),
            }
            for row_data in (dict(row) for row in cur.fetchall())
            if row_data.get("phase_id") is not None
        ]

        milestones = [
            {
                "id": int(row["id"]),
                "title": str(row.get("title") or ""),
                "description": str(row.get("description") or ""),
                "phase_id": row.get("phase_id"),
                "linked_task_id": row.get("linked_task_id"),
                "start_date": row.get("start_date"),
                "target_date": row.get("target_date"),
                "baseline_target_date": row.get("baseline_target_date"),
                "status": str(row.get("status") or "planned"),
                "progress_percent": int(row.get("progress_percent") or 0),
                "completed_at": row.get("completed_at"),
                "gantt_color_hex": str(row.get("gantt_color_hex") or "").strip() or None,
                "dependencies": list(row.get("dependencies") or []),
            }
            for row in self.fetch_project_milestones(project_id)
            if row.get("linked_task_id") is None or int(row["linked_task_id"]) in included_task_ids
        ]
        included_milestone_ids = {int(row["id"]) for row in milestones}

        deliverables = [
            {
                "id": int(row["id"]),
                "title": str(row.get("title") or ""),
                "description": str(row.get("description") or ""),
                "phase_id": row.get("phase_id"),
                "linked_task_id": row.get("linked_task_id"),
                "linked_milestone_id": row.get("linked_milestone_id"),
                "due_date": row.get("due_date"),
                "baseline_due_date": row.get("baseline_due_date"),
                "acceptance_criteria": str(row.get("acceptance_criteria") or ""),
                "version_ref": str(row.get("version_ref") or ""),
                "status": str(row.get("status") or "planned"),
                "completed_at": row.get("completed_at"),
                "gantt_color_hex": str(row.get("gantt_color_hex") or "").strip() or None,
            }
            for row in self.fetch_project_deliverables(project_id)
            if (
                (row.get("linked_task_id") is None or int(row["linked_task_id"]) in included_task_ids)
                and (
                    row.get("linked_milestone_id") is None
                    or int(row["linked_milestone_id"]) in included_milestone_ids
                )
            )
        ]

        register_entries = [
            {
                "id": int(row["id"]),
                "entry_type": str(row.get("entry_type") or "risk"),
                "title": str(row.get("title") or ""),
                "details": str(row.get("details") or ""),
                "status": str(row.get("status") or "open"),
                "severity": row.get("severity"),
                "review_date": row.get("review_date"),
                "linked_task_id": row.get("linked_task_id"),
                "linked_milestone_id": row.get("linked_milestone_id"),
            }
            for row in self.fetch_project_register_entries(project_id)
            if (
                (row.get("linked_task_id") is None or int(row["linked_task_id"]) in included_task_ids)
                and (
                    row.get("linked_milestone_id") is None
                    or int(row["linked_milestone_id"]) in included_milestone_ids
                )
            )
        ]

        baseline = self.fetch_project_baseline(project_id)
        baseline_payload = None
        if baseline:
            baseline_payload = {
                "target_date": baseline.get("target_date"),
                "effort_minutes": baseline.get("effort_minutes"),
            }

        return {
            "root_task_id": project_id,
            "profile": {
                "objective": str(profile.get("objective") or ""),
                "scope": str(profile.get("scope") or ""),
                "out_of_scope": str(profile.get("out_of_scope") or ""),
                "owner": str(profile.get("owner") or "Self") or "Self",
                "stakeholders": str(profile.get("stakeholders") or ""),
                "target_date": profile.get("target_date"),
                "success_criteria": str(profile.get("success_criteria") or ""),
                "project_status_health": profile.get("project_status_health"),
                "summary": str(profile.get("summary") or ""),
                "category": str(profile.get("category") or ""),
            },
            "phases": [
                {
                    "id": int(row["id"]),
                    "name": str(row.get("name") or ""),
                    "sort_order": int(row.get("sort_order") or 0),
                    "gantt_color_hex": str(row.get("gantt_color_hex") or "").strip() or None,
                }
                for row in phases
                if row.get("id") is not None and int(row["id"]) in included_phases
            ],
            "task_phase_refs": task_phase_refs,
            "baseline": baseline_payload,
            "milestones": milestones,
            "deliverables": deliverables,
            "register_entries": register_entries,
        }

    def restore_project_template_payload(self, payload: dict, task_id_map: dict[int, int]):
        project_template = payload.get("project_template") if isinstance(payload, dict) else None
        if not isinstance(project_template, dict):
            return

        old_root_id = project_template.get("root_task_id")
        if old_root_id is None:
            return
        new_root_id = task_id_map.get(int(old_root_id))
        if new_root_id is None:
            return

        profile = dict(project_template.get("profile") or {})
        phases = list(project_template.get("phases") or [])
        task_phase_refs = list(project_template.get("task_phase_refs") or [])
        milestones = list(project_template.get("milestones") or [])
        deliverables = list(project_template.get("deliverables") or [])
        register_entries = list(project_template.get("register_entries") or [])
        baseline = project_template.get("baseline")

        phase_id_map: dict[int, int] = {}
        milestone_id_map: dict[int, int] = {}
        milestone_dependency_refs: list[tuple[int, list[dict]]] = []
        stamp = now_iso()

        with self.tx():
            cur = self.conn.cursor()
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
                    int(new_root_id),
                    str(profile.get("objective") or ""),
                    str(profile.get("scope") or ""),
                    str(profile.get("out_of_scope") or ""),
                    str(profile.get("owner") or "Self") or "Self",
                    str(profile.get("stakeholders") or ""),
                    profile.get("target_date"),
                    str(profile.get("success_criteria") or ""),
                    normalize_health(profile.get("project_status_health")),
                    str(profile.get("summary") or ""),
                    str(profile.get("category") or ""),
                    stamp,
                    stamp,
                ),
            )

            for phase in phases:
                cur.execute(
                    """
                    INSERT INTO project_phases(project_task_id, name, sort_order, gantt_color_hex, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?);
                    """,
                    (
                        int(new_root_id),
                        str(phase.get("name") or ""),
                        int(phase.get("sort_order") or 0),
                        str(phase.get("gantt_color_hex") or "").strip() or None,
                        stamp,
                        stamp,
                    ),
                )
                if phase.get("id") is not None:
                    phase_id_map[int(phase["id"])] = int(cur.lastrowid)

            for ref in task_phase_refs:
                old_task_id = ref.get("task_id")
                old_phase_id = ref.get("phase_id")
                if old_task_id is None or old_phase_id is None:
                    continue
                new_task_id = task_id_map.get(int(old_task_id))
                new_phase_id = phase_id_map.get(int(old_phase_id))
                if new_task_id is None or new_phase_id is None:
                    continue
                cur.execute(
                    "UPDATE tasks SET phase_id=?, last_update=? WHERE id=?;",
                    (int(new_phase_id), stamp, int(new_task_id)),
                )

            for milestone in milestones:
                old_phase_id = milestone.get("phase_id")
                old_linked_task_id = milestone.get("linked_task_id")
                new_phase_id = None if old_phase_id is None else phase_id_map.get(int(old_phase_id))
                new_linked_task_id = (
                    None if old_linked_task_id is None else task_id_map.get(int(old_linked_task_id))
                )
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
                        gantt_color_hex,
                        created_at,
                        updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        int(new_root_id),
                        str(milestone.get("title") or ""),
                        str(milestone.get("description") or ""),
                        new_phase_id,
                        new_linked_task_id,
                        milestone.get("start_date"),
                        milestone.get("target_date"),
                        milestone.get("baseline_target_date"),
                        normalize_record_status(milestone.get("status"), MILESTONE_STATUSES, "planned"),
                        int(milestone.get("progress_percent") or 0),
                        milestone.get("completed_at"),
                        str(milestone.get("gantt_color_hex") or "").strip() or None,
                        stamp,
                        stamp,
                    ),
                )
                new_milestone_id = int(cur.lastrowid)
                if milestone.get("id") is not None:
                    milestone_id_map[int(milestone["id"])] = new_milestone_id
                milestone_dependency_refs.append((new_milestone_id, list(milestone.get("dependencies") or [])))

            for deliverable in deliverables:
                old_phase_id = deliverable.get("phase_id")
                old_linked_task_id = deliverable.get("linked_task_id")
                old_linked_milestone_id = deliverable.get("linked_milestone_id")
                new_phase_id = None if old_phase_id is None else phase_id_map.get(int(old_phase_id))
                new_linked_task_id = (
                    None if old_linked_task_id is None else task_id_map.get(int(old_linked_task_id))
                )
                new_linked_milestone_id = (
                    None
                    if old_linked_milestone_id is None
                    else milestone_id_map.get(int(old_linked_milestone_id))
                )
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
                        gantt_color_hex,
                        created_at,
                        updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        int(new_root_id),
                        str(deliverable.get("title") or ""),
                        str(deliverable.get("description") or ""),
                        new_phase_id,
                        new_linked_task_id,
                        new_linked_milestone_id,
                        deliverable.get("due_date"),
                        deliverable.get("baseline_due_date"),
                        str(deliverable.get("acceptance_criteria") or ""),
                        str(deliverable.get("version_ref") or ""),
                        normalize_record_status(deliverable.get("status"), DELIVERABLE_STATUSES, "planned"),
                        deliverable.get("completed_at"),
                        str(deliverable.get("gantt_color_hex") or "").strip() or None,
                        stamp,
                        stamp,
                    ),
                )

            for entry in register_entries:
                old_linked_task_id = entry.get("linked_task_id")
                old_linked_milestone_id = entry.get("linked_milestone_id")
                new_linked_task_id = (
                    None if old_linked_task_id is None else task_id_map.get(int(old_linked_task_id))
                )
                new_linked_milestone_id = (
                    None
                    if old_linked_milestone_id is None
                    else milestone_id_map.get(int(old_linked_milestone_id))
                )
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
                        int(new_root_id),
                        normalize_register_type(entry.get("entry_type")),
                        str(entry.get("title") or ""),
                        str(entry.get("details") or ""),
                        normalize_record_status(entry.get("status"), REGISTER_STATUSES, "open"),
                        entry.get("severity"),
                        entry.get("review_date"),
                        new_linked_task_id,
                        new_linked_milestone_id,
                        stamp,
                        stamp,
                    ),
                )

            if isinstance(baseline, dict):
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
                        int(new_root_id),
                        baseline.get("target_date"),
                        baseline.get("effort_minutes"),
                        stamp,
                        stamp,
                    ),
                )

        for new_milestone_id, refs in milestone_dependency_refs:
            mapped_refs = []
            for ref in refs:
                kind = str(ref.get("kind") or "").strip().lower()
                mapped_id = None
                if kind == "task" and ref.get("id") is not None:
                    mapped_id = task_id_map.get(int(ref["id"]))
                elif kind == "milestone" and ref.get("id") is not None:
                    mapped_id = milestone_id_map.get(int(ref["id"]))
                if mapped_id is None:
                    continue
                mapped_refs.append(
                    {
                        "kind": kind,
                        "id": int(mapped_id),
                        "dep_type": str(ref.get("dep_type") or DEPENDENCY_TYPE_FINISH_TO_START),
                        "is_soft": int(ref.get("is_soft") or 0),
                    }
                )
            self.set_milestone_dependencies(int(new_milestone_id), mapped_refs)

    # ---------- Templates ----------
    def save_template(self, name: str, payload: dict, overwrite: bool = True):
        n = str(name or "").strip()
        if not n:
            raise ValueError("Template name is required")
        body = json.dumps(payload or {}, ensure_ascii=False)
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("SELECT id FROM task_templates WHERE name=?;", (n,))
            row = cur.fetchone()
            if row:
                if not overwrite:
                    raise ValueError("Template already exists")
                cur.execute(
                    """
                    UPDATE task_templates
                    SET payload_json=?, updated_at=?
                    WHERE name=?;
                    """,
                    (body, now_iso(), n),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO task_templates(name, payload_json, created_at, updated_at)
                    VALUES(?, ?, ?, ?);
                    """,
                    (n, body, now_iso(), now_iso()),
                )

    def list_templates(self) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM task_templates
            ORDER BY LOWER(name), name;
            """
        )
        return [dict(r) for r in cur.fetchall()]

    def load_template(self, name: str) -> dict | None:
        cur = self.conn.cursor()
        cur.execute("SELECT payload_json FROM task_templates WHERE name=?;", (str(name or "").strip(),))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(str(row["payload_json"] or "{}"))
        except Exception:
            return {}

    def delete_template(self, name: str):
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("DELETE FROM task_templates WHERE name=?;", (str(name or "").strip(),))

    # ---------- Task lists ----------
    def fetch_tasks_due_on(self, due_date_iso: str, include_archived: bool = False) -> list[dict]:
        q = """
            SELECT id, description, due_date, status, priority, parent_id
            FROM tasks
            WHERE due_date=?
        """
        args = [str(due_date_iso)]
        if not include_archived:
            q += " AND archived_at IS NULL"
        q += " ORDER BY priority ASC, sort_order ASC, id ASC;"
        cur = self.conn.cursor()
        cur.execute(q, tuple(args))
        return [dict(r) for r in cur.fetchall()]

    def fetch_task_ids_by_due_date(self, due_date_iso: str, include_archived: bool = False) -> list[int]:
        return [int(r["id"]) for r in self.fetch_tasks_due_on(due_date_iso, include_archived=include_archived)]

    def fetch_due_date_completion_summary(
        self,
        start_due_iso: str | None = None,
        end_due_iso: str | None = None,
        include_archived: bool = False,
    ) -> list[dict]:
        q = """
            SELECT
                due_date,
                COUNT(*) AS total_count,
                SUM(CASE WHEN status='Done' THEN 1 ELSE 0 END) AS done_count
            FROM tasks
            WHERE due_date IS NOT NULL
              AND TRIM(due_date) <> ''
        """
        args: list[str] = []
        if not include_archived:
            q += " AND archived_at IS NULL"
        if start_due_iso:
            q += " AND due_date >= ?"
            args.append(str(start_due_iso))
        if end_due_iso:
            q += " AND due_date <= ?"
            args.append(str(end_due_iso))
        q += " GROUP BY due_date ORDER BY due_date ASC;"

        cur = self.conn.cursor()
        cur.execute(q, tuple(args))
        rows = []
        for r in cur.fetchall():
            total = int(r["total_count"] or 0)
            done = int(r["done_count"] or 0)
            rows.append(
                {
                    "due_date": str(r["due_date"]),
                    "total": total,
                    "done": done,
                    "percent": (100.0 * done / total) if total > 0 else 0.0,
                }
            )
        return rows

    def move_task(
        self,
        task_id: int,
        new_parent_id: int | None,
        old_parent_id: int | None,
        old_parent_order: list[int],
        new_parent_order: list[int],
    ):
        """
        Updates:
          - parent_id of moved node
          - sort_order of old parent siblings
          - sort_order of new parent siblings
        All in one transaction.
        """
        with self.tx():
            cur = self.conn.cursor()
            cur.execute("UPDATE tasks SET parent_id=? WHERE id=?;", (new_parent_id, int(task_id)))

            for i, tid in enumerate(old_parent_order, start=1):
                cur.execute("UPDATE tasks SET sort_order=? WHERE id=?;", (i, int(tid)))

            for i, tid in enumerate(new_parent_order, start=1):
                cur.execute("UPDATE tasks SET sort_order=? WHERE id=?;", (i, int(tid)))

    def bulk_delete_tasks(self, task_ids: list[int]):
        ids = [int(x) for x in task_ids if int(x) > 0]
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        with self.tx():
            cur = self.conn.cursor()
            cur.execute(f"DELETE FROM tasks WHERE id IN ({marks});", tuple(ids))
