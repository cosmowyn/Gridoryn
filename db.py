import json
import sqlite3
from calendar import monthrange
from contextlib import contextmanager
from datetime import date, datetime, timedelta


RECURRENCE_FREQUENCIES = {"daily", "weekly", "monthly", "yearly"}


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
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    def _configure(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA busy_timeout=4000;")
        self.conn.commit()

    def _migrate(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA user_version;")
        ver = int(cur.fetchone()[0])

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

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

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
                   reminder_at, reminder_minutes_before, reminder_fired_at
            FROM tasks
            ORDER BY COALESCE(parent_id, 0), sort_order ASC, id ASC;
            """
        )
        tasks = [dict(r) for r in cur.fetchall()]

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
            SELECT task_id, frequency, create_next_on_done, is_active
            FROM recurrence_rules;
            """
        )
        recurrence_by_task = {int(r["task_id"]): dict(r) for r in cur.fetchall()}

        for t in tasks:
            t["custom"] = values_by_task.get(t["id"], {})
            t["tags"] = tags_by_task.get(int(t["id"]), [])
            t["blocked_by_count"] = deps_by_task.get(int(t["id"]), 0)
            t["recurrence"] = recurrence_by_task.get(int(t["id"]))
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
                   reminder_at, reminder_minutes_before, reminder_fired_at
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
                    reminder_fired_at=?
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
            for dep_id in deps:
                cur.execute(
                    """
                    INSERT INTO task_dependencies(task_id, depends_on_task_id)
                    VALUES(?, ?)
                    ON CONFLICT(task_id, depends_on_task_id) DO NOTHING;
                    """,
                    (tid, int(dep_id)),
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
                                      reminder_at, reminder_minutes_before, reminder_fired_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                                      reminder_at, reminder_minutes_before, reminder_fired_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
        tasks = self.fetch_tasks()
        children_by_parent: dict[int, list[dict]] = {}
        for t in tasks:
            pid = t.get("parent_id")
            if pid is None:
                continue
            try:
                parent_id = int(pid)
            except Exception:
                continue
            children_by_parent.setdefault(parent_id, []).append(t)

        today = date.today()
        out: list[dict] = []
        stale_threshold = max(1, int(stalled_days or 14))

        for t in tasks:
            if str(t.get("archived_at") or "").strip():
                continue
            tid = int(t["id"])
            children = [c for c in children_by_parent.get(tid, []) if not str(c.get("archived_at") or "").strip()]
            if not children:
                continue

            children.sort(key=lambda c: (int(c.get("sort_order") or 0), int(c.get("id") or 0)))
            open_children = [c for c in children if str(c.get("status") or "") != "Done"]
            blocked_open = [
                c
                for c in open_children
                if int(c.get("blocked_by_count") or 0) > 0 or str(c.get("waiting_for") or "").strip()
            ]

            next_action = None
            for c in open_children:
                if int(c.get("blocked_by_count") or 0) > 0:
                    continue
                if str(c.get("waiting_for") or "").strip():
                    continue
                next_action = c
                break

            no_next_action = bool(open_children) and next_action is None
            blocked = bool(open_children) and next_action is None and bool(blocked_open)

            latest = _parse_iso_datetime(str(t.get("last_update") or "")) or datetime.now()
            for c in open_children:
                dt = _parse_iso_datetime(str(c.get("last_update") or ""))
                if dt and dt > latest:
                    latest = dt
            stale_age_days = max(0, (today - latest.date()).days)
            stalled = bool(open_children) and (no_next_action or stale_age_days >= stale_threshold)

            note_parts = [f"open {len(open_children)}/{len(children)}"]
            if next_action is not None:
                note_parts.append(f"next: {str(next_action.get('description') or '').strip()}")
            elif no_next_action:
                note_parts.append("next: none")
            if blocked:
                note_parts.append("blocked")
            if stale_age_days >= stale_threshold:
                note_parts.append(f"stale {stale_age_days}d")

            out.append(
                {
                    "id": tid,
                    "description": str(t.get("description") or ""),
                    "status": str(t.get("status") or ""),
                    "due_date": t.get("due_date"),
                    "priority": int(t.get("priority") or 3),
                    "child_total": len(children),
                    "child_open": len(open_children),
                    "next_action_task_id": int(next_action["id"]) if next_action else None,
                    "next_action_description": str(next_action.get("description") or "") if next_action else "",
                    "no_next_action": bool(no_next_action),
                    "blocked": bool(blocked),
                    "stalled": bool(stalled),
                    "stale_days": int(stale_age_days),
                    "review_note": " | ".join(note_parts),
                }
            )

        out.sort(
            key=lambda r: (
                0 if r.get("stalled") else 1,
                0 if r.get("blocked") else 1,
                int(r.get("priority") or 99),
                str(r.get("description") or "").lower(),
                int(r.get("id") or 0),
            )
        )
        return out

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

    def fetch_analytics_summary(self, trend_days: int = 14, tag_days: int = 30) -> dict:
        trend_window = max(3, int(trend_days or 14))
        tag_window = max(7, int(tag_days or 30))

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

        project_rows = self.fetch_project_health(stalled_days=14)
        project_total = len(project_rows)
        project_stalled = sum(1 for r in project_rows if bool(r.get("stalled")))
        project_blocked = sum(1 for r in project_rows if bool(r.get("blocked")))
        project_no_next = sum(1 for r in project_rows if bool(r.get("no_next_action")))

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

    def set_task_dependencies(self, task_id: int, depends_on_ids: list[int]):
        ids = []
        seen = set()
        for raw in depends_on_ids or []:
            try:
                tid = int(raw)
            except Exception:
                continue
            if tid <= 0 or tid == int(task_id) or tid in seen:
                continue
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
            cur.execute("UPDATE tasks SET last_update=? WHERE id=?;", (now_iso(), int(task_id)))

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
