from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Set

from PySide6.QtCore import Qt, QSortFilterProxyModel, QModelIndex

from query_parsing import parse_search_query, ParsedSearch


STATUS_ORDER = {
    "Todo": 0,
    "In Progress": 1,
    "Blocked": 2,
    "Done": 3,
}


def _parse_iso_date(s: str | None) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


class TaskFilterProxyModel(QSortFilterProxyModel):
    """
    Recursive tree filtering for TaskTreeModel.
    Keeps parents when children match (recursive filtering enabled).
    Optionally keeps children of matching parents (show_children_of_matches).
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setRecursiveFilteringEnabled(True)
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._search_text = ""
        self._parsed: ParsedSearch = ParsedSearch()
        self._status_allowed: Optional[Set[str]] = None  # None = all
        self._priority_min: Optional[int] = None
        self._priority_max: Optional[int] = None
        self._due_from: Optional[date] = None
        self._due_to: Optional[date] = None
        self._hide_done = False
        self._overdue_only = False
        self._show_children_of_matches = True
        self._tag_filter: set[str] = set()
        self._perspective = "all"  # all|today|upcoming|inbox|someday|completed
        self._sort_mode = "manual"  # manual|due_date|priority|status
        self._blocked_only = False
        self._waiting_only = False

    def _refresh_filter(self):
        """Refresh row filtering without using deprecated Qt APIs when available."""
        begin = getattr(self, "beginFilterChange", None)
        end = getattr(self, "endFilterChange", None)
        if callable(begin) and callable(end):
            begin()
            try:
                direction = getattr(QSortFilterProxyModel, "Direction", None)
                if direction is not None and hasattr(direction, "Rows"):
                    end(direction.Rows)
                else:
                    end()
            except TypeError:
                end()
            return
        self.invalidateFilter()

    # ---------- Public setters ----------
    def set_search_text(self, text: str):
        t = (text or "").strip()
        if t != self._search_text:
            self._search_text = t
            self._parsed = parse_search_query(t)
            self._refresh_filter()
            self.invalidate()

    def set_status_allowed(self, statuses: Optional[Set[str]]):
        # None = all
        if statuses is not None and len(statuses) == 0:
            statuses = None
        if statuses != self._status_allowed:
            self._status_allowed = statuses
            self._refresh_filter()

    def set_priority_range(self, pmin: Optional[int], pmax: Optional[int]):
        if pmin is not None:
            pmin = int(pmin)
        if pmax is not None:
            pmax = int(pmax)
        if (pmin, pmax) != (self._priority_min, self._priority_max):
            self._priority_min, self._priority_max = pmin, pmax
            self._refresh_filter()

    def set_due_range(self, dfrom: Optional[date], dto: Optional[date]):
        if (dfrom, dto) != (self._due_from, self._due_to):
            self._due_from, self._due_to = dfrom, dto
            self._refresh_filter()

    def set_hide_done(self, hide: bool):
        hide = bool(hide)
        if hide != self._hide_done:
            self._hide_done = hide
            self._refresh_filter()

    def set_overdue_only(self, overdue: bool):
        overdue = bool(overdue)
        if overdue != self._overdue_only:
            self._overdue_only = overdue
            self._refresh_filter()

    def set_show_children_of_matches(self, enabled: bool):
        enabled = bool(enabled)
        if enabled != self._show_children_of_matches:
            self._show_children_of_matches = enabled
            self._refresh_filter()

    def set_tag_filter(self, tags: set[str] | None):
        next_tags = {str(t).strip().lower() for t in (tags or set()) if str(t).strip()}
        if next_tags != self._tag_filter:
            self._tag_filter = next_tags
            self._refresh_filter()

    def set_blocked_only(self, enabled: bool):
        v = bool(enabled)
        if v != self._blocked_only:
            self._blocked_only = v
            self._refresh_filter()

    def set_waiting_only(self, enabled: bool):
        v = bool(enabled)
        if v != self._waiting_only:
            self._waiting_only = v
            self._refresh_filter()

    def set_perspective(self, perspective: str):
        p = str(perspective or "all").strip().lower()
        if not p:
            p = "all"
        if p != self._perspective:
            self._perspective = p
            self._refresh_filter()

    def perspective(self) -> str:
        return self._perspective

    def set_sort_mode(self, mode: str):
        m = str(mode or "manual").strip().lower()
        if m not in {"manual", "due_date", "priority", "status"}:
            m = "manual"
        if m == self._sort_mode:
            return
        self._sort_mode = m
        self.invalidate()
        self.sort(0, Qt.SortOrder.AscendingOrder)

    def sort_mode(self) -> str:
        return self._sort_mode

    def is_manual_sort_mode(self) -> bool:
        return self._sort_mode == "manual"

    # ---------- Status ----------
    def is_filter_active(self) -> bool:
        if self._search_text:
            return True
        if self._status_allowed is not None:
            return True
        if self._priority_min is not None or self._priority_max is not None:
            return True
        if self._due_from is not None or self._due_to is not None:
            return True
        if self._hide_done:
            return True
        if self._overdue_only:
            return True
        if self._tag_filter:
            return True
        if self._blocked_only:
            return True
        if self._waiting_only:
            return True
        if self._perspective != "all":
            return True
        # show_children_of_matches doesn't activate a filter by itself
        return False

    # ---------- Filtering ----------
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        sm = self.sourceModel()
        if sm is None:
            return True

        idx0 = sm.index(source_row, 0, source_parent)
        if not idx0.isValid():
            return True

        node = idx0.internalPointer()
        task = getattr(node, "task", None)
        if not isinstance(task, dict):
            return True

        # Hard filters (always apply even when showing children of matches)
        if not self._passes_hard_filters(task, node):
            return False

        # If no free-text terms, only hard/structured filters matter
        if not self._parsed.free_text:
            return True

        # Search match for this node?
        if self._matches_search(task):
            return True

        # Optionally show children of matching parents (search only)
        if self._show_children_of_matches and self._ancestor_matches_search(source_parent):
            return True

        return False

    def _passes_hard_filters(self, task: dict, node) -> bool:
        if not self._passes_perspective(task):
            return False

        status = str(task.get("status") or "")
        if self._hide_done and status == "Done":
            return False

        if self._status_allowed is not None and status not in self._status_allowed:
            return False

        try:
            prio = int(task.get("priority") or 0)
        except Exception:
            prio = 0

        if self._priority_min is not None and prio < self._priority_min:
            return False
        if self._priority_max is not None and prio > self._priority_max:
            return False

        due = _parse_iso_date(task.get("due_date"))
        today = date.today()

        if self._overdue_only:
            # overdue requires due date and not done
            if due is None:
                return False
            if due >= today:
                return False

        if self._due_from is not None:
            if due is None or due < self._due_from:
                return False

        if self._due_to is not None:
            if due is None or due > self._due_to:
                return False

        if self._tag_filter:
            task_tags = {str(t).strip().lower() for t in (task.get("tags") or []) if str(t).strip()}
            if not self._tag_filter.issubset(task_tags):
                return False

        # Structured search operators
        if self._parsed.statuses:
            mapped = {self._normalize_status_name(s) for s in self._parsed.statuses}
            if status not in mapped:
                return False

        if self._parsed.priority is not None:
            if prio != int(self._parsed.priority):
                return False

        bucket = str(task.get("planned_bucket") or "").strip().lower() or "inbox"
        if self._parsed.bucket:
            if bucket != str(self._parsed.bucket).strip().lower():
                return False

        if self._parsed.due_none and due is not None:
            return False

        if self._parsed.tags:
            task_tags = {str(t).strip().lower() for t in (task.get("tags") or []) if str(t).strip()}
            if not {t.lower() for t in self._parsed.tags}.issubset(task_tags):
                return False

        if self._parsed.has_children is not None:
            has_children = bool(getattr(node, "children", []))
            if has_children != bool(self._parsed.has_children):
                return False

        if self._parsed.blocked_only or self._blocked_only:
            if int(task.get("blocked_by_count") or 0) <= 0:
                return False

        if self._parsed.waiting_only or self._waiting_only:
            if not str(task.get("waiting_for") or "").strip():
                return False

        if self._parsed.recurring_only:
            rec = task.get("recurrence") or {}
            if not str(rec.get("frequency") or "").strip():
                return False

        if self._parsed.due_ops:
            if due is None:
                return False
            for op, rhs_iso in self._parsed.due_ops:
                rhs = _parse_iso_date(rhs_iso)
                if rhs is None:
                    continue
                if op == "<" and not (due < rhs):
                    return False
                if op == "<=" and not (due <= rhs):
                    return False
                if op == ">" and not (due > rhs):
                    return False
                if op == ">=" and not (due >= rhs):
                    return False
                if op == "=" and not (due == rhs):
                    return False

        return True

    def _passes_perspective(self, task: dict) -> bool:
        p = self._perspective
        status = str(task.get("status") or "")
        due = _parse_iso_date(task.get("due_date"))
        bucket = str(task.get("planned_bucket") or "").strip().lower() or "inbox"
        archived = bool(str(task.get("archived_at") or "").strip())
        today = date.today()

        if p == "all":
            return not archived
        if p == "completed":
            return archived or status == "Done"
        if p == "inbox":
            return (not archived) and status != "Done" and bucket == "inbox"
        if p == "today":
            explicit_today = bucket == "today"
            due_today = due is not None and due == today
            return (not archived) and (explicit_today or due_today)
        if p == "upcoming":
            due_future = due is not None and due > today
            explicit_upcoming = bucket == "upcoming"
            return (not archived) and status != "Done" and (due_future or explicit_upcoming)
        if p == "someday":
            return (not archived) and bucket == "someday"
        return not archived

    def _normalize_status_name(self, s: str) -> str:
        raw = str(s or "").strip().lower()
        if raw in {"todo", "to-do"}:
            return "Todo"
        if raw in {"inprogress", "in_progress", "progress", "in-progress"}:
            return "In Progress"
        if raw in {"done", "completed", "complete"}:
            return "Done"
        if raw in {"blocked"}:
            return "Blocked"
        return str(s).strip()

    def _matches_search(self, task: dict) -> bool:
        q = self._parsed.free_text
        if not q:
            return True

        parts = []

        # Core fields
        parts.append(str(task.get("description") or ""))
        parts.append(str(task.get("status") or ""))
        parts.append(str(task.get("due_date") or ""))
        parts.append(str(task.get("reminder_at") or ""))
        parts.append(str(task.get("priority") or ""))
        parts.append(str(task.get("last_update") or ""))
        parts.append(str(task.get("notes") or ""))
        parts.append(str(task.get("waiting_for") or ""))
        parts.append(str(task.get("planned_bucket") or ""))

        # Custom values
        custom = task.get("custom") or {}
        if isinstance(custom, dict):
            for v in custom.values():
                if v is not None:
                    parts.append(str(v))

        for tag in task.get("tags") or []:
            parts.append(str(tag))

        rec = task.get("recurrence") or {}
        if isinstance(rec, dict):
            parts.append(str(rec.get("frequency") or ""))

        hay = " ".join(parts).lower()
        return q in hay

    def _ancestor_matches_search(self, source_parent: QModelIndex) -> bool:
        # Walk upwards: if any ancestor matches search, keep this row
        sm = self.sourceModel()
        p = source_parent
        while p.isValid():
            node = p.internalPointer()
            task = getattr(node, "task", None)
            if isinstance(task, dict):
                if self._matches_search(task):
                    return True
            p = p.parent()
        return False

    # ---------- Sorting ----------
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        if self._sort_mode == "manual":
            return left.row() < right.row()

        lnode = left.internalPointer() if left.isValid() else None
        rnode = right.internalPointer() if right.isValid() else None
        ltask = getattr(lnode, "task", None)
        rtask = getattr(rnode, "task", None)

        if not isinstance(ltask, dict) or not isinstance(rtask, dict):
            return super().lessThan(left, right)

        if self._sort_mode == "due_date":
            ld = _parse_iso_date(ltask.get("due_date"))
            rd = _parse_iso_date(rtask.get("due_date"))
            if ld is None and rd is None:
                pass
            elif ld is None:
                return False
            elif rd is None:
                return True
            elif ld != rd:
                return ld < rd

        elif self._sort_mode == "priority":
            try:
                lp = int(ltask.get("priority") or 0)
            except Exception:
                lp = 0
            try:
                rp = int(rtask.get("priority") or 0)
            except Exception:
                rp = 0
            if lp != rp:
                return lp < rp

        elif self._sort_mode == "status":
            ls = STATUS_ORDER.get(str(ltask.get("status") or ""), 99)
            rs = STATUS_ORDER.get(str(rtask.get("status") or ""), 99)
            if ls != rs:
                return ls < rs

        ldesc = str(ltask.get("description") or "").lower()
        rdesc = str(rtask.get("description") or "").lower()
        if ldesc != rdesc:
            return ldesc < rdesc
        return left.row() < right.row()
