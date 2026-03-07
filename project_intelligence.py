from __future__ import annotations

from datetime import date, datetime, timedelta


def _parse_iso_date(value: str | None) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip().replace("T", " ")
    if not raw:
        return None
    for text, fmt in (
        (raw[:19], "%Y-%m-%d %H:%M:%S"),
        (raw[:16], "%Y-%m-%d %H:%M"),
        (raw[:10], "%Y-%m-%d"),
    ):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _is_archived(task: dict) -> bool:
    return bool(str(task.get("archived_at") or "").strip())


def _is_done(task: dict) -> bool:
    return str(task.get("status") or "") == "Done"


def _bucket(task: dict) -> str:
    return str(task.get("planned_bucket") or "inbox").strip().lower() or "inbox"


def _blocked_reasons(task: dict, today: date) -> tuple[list[str], int | None]:
    reasons: list[str] = []
    waiting_age_days: int | None = None

    dep_count = int(task.get("blocked_by_count") or 0)
    status = str(task.get("status") or "")
    waiting_for = str(task.get("waiting_for") or "").strip()

    if dep_count > 0:
        reasons.append(f"blocked by {dep_count} dependenc{'y' if dep_count == 1 else 'ies'}")
    if status == "Blocked":
        reasons.append("status is Blocked")
    if waiting_for:
        reasons.append(f"waiting for {waiting_for}")
        updated = _parse_iso_datetime(task.get("last_update"))
        if updated is not None:
            waiting_age_days = max(0, (today - updated.date()).days)
    return reasons, waiting_age_days


def _next_action_sort_key(task: dict, today: date):
    due = _parse_iso_date(task.get("due_date"))
    bucket = _bucket(task)
    if due is not None and due < today:
        due_rank = 0
    elif due is not None and due == today:
        due_rank = 1
    elif bucket == "today":
        due_rank = 2
    elif due is None:
        due_rank = 4
    else:
        due_rank = 3
    return (
        due_rank,
        due or date.max,
        int(task.get("priority") or 99),
        int(task.get("sort_order") or 0),
        int(task.get("id") or 0),
    )


def analyze_projects(tasks: list[dict], stalled_days: int = 14, today: date | None = None) -> list[dict]:
    today = today or date.today()
    stale_threshold = max(1, int(stalled_days or 14))

    children_by_parent: dict[int, list[dict]] = {}
    for task in tasks:
        pid = task.get("parent_id")
        if pid is None:
            continue
        try:
            parent_id = int(pid)
        except Exception:
            continue
        children_by_parent.setdefault(parent_id, []).append(task)

    results: list[dict] = []
    for project in tasks:
        if _is_archived(project):
            continue
        project_id = int(project["id"])
        active_children = [child for child in children_by_parent.get(project_id, []) if not _is_archived(child)]
        if not active_children:
            continue

        active_children.sort(key=lambda row: (int(row.get("sort_order") or 0), int(row.get("id") or 0)))
        open_children = [child for child in active_children if not _is_done(child)]

        blocked_children: list[dict] = []
        waiting_children: list[dict] = []
        deferred_children: list[dict] = []
        no_due_children: list[dict] = []
        actionable_children: list[dict] = []
        oldest_waiting_days = 0

        for child in open_children:
            reasons, waiting_age = _blocked_reasons(child, today)
            if waiting_age is not None:
                oldest_waiting_days = max(oldest_waiting_days, waiting_age)
            if _bucket(child) == "someday":
                deferred_children.append(child)
                continue
            if not str(child.get("due_date") or "").strip():
                no_due_children.append(child)
            if reasons:
                if any("waiting for " in reason for reason in reasons):
                    waiting_children.append(child)
                else:
                    blocked_children.append(child)
                continue
            actionable_children.append(child)

        actionable_children.sort(key=lambda row: _next_action_sort_key(row, today))
        next_action = actionable_children[0] if actionable_children else None

        latest = _parse_iso_datetime(project.get("last_update")) or datetime.now()
        for child in open_children:
            updated = _parse_iso_datetime(child.get("last_update"))
            if updated is not None and updated > latest:
                latest = updated
        stale_age_days = max(0, (today - latest.date()).days)

        stalled_reasons: list[str] = []
        if not open_children and not _is_done(project):
            stalled_reasons.append("no incomplete child tasks")
        if open_children and len(blocked_children) + len(waiting_children) >= len(open_children):
            stalled_reasons.append("only blocked or waiting children")
        if open_children and len(deferred_children) >= len(open_children):
            stalled_reasons.append("all open children are deferred to Someday")
        if open_children and not next_action:
            stalled_reasons.append("no actionable next child")
        if open_children and len(no_due_children) >= len(open_children):
            stalled_reasons.append("open children have no due dates")
        if open_children and stale_age_days >= stale_threshold:
            stalled_reasons.append(f"no progress for {stale_age_days} days")

        blocked = bool(open_children) and not next_action and (blocked_children or waiting_children)
        stalled = bool(stalled_reasons)
        next_action_badge = str(next_action.get("description") or "").strip() if next_action else ""

        review_parts = [f"open {len(open_children)}/{len(active_children)}"]
        if next_action is not None:
            review_parts.append(f"next: {next_action_badge}")
        if blocked:
            review_parts.append("blocked")
        if oldest_waiting_days > 0:
            review_parts.append(f"waiting {oldest_waiting_days}d")
        if stalled_reasons:
            review_parts.append("; ".join(stalled_reasons))

        state_label = "Ready"
        if stalled:
            state_label = "Stalled"
        elif blocked:
            state_label = "Blocked"
        elif next_action is None and open_children:
            state_label = "No next action"

        results.append(
            {
                "id": project_id,
                "description": str(project.get("description") or ""),
                "status": str(project.get("status") or ""),
                "due_date": project.get("due_date"),
                "priority": int(project.get("priority") or 3),
                "child_total": len(active_children),
                "child_open": len(open_children),
                "next_action_task_id": int(next_action["id"]) if next_action else None,
                "next_action_description": next_action_badge,
                "next_action_due_date": next_action.get("due_date") if next_action else None,
                "next_action_priority": int(next_action.get("priority") or 0) if next_action else None,
                "next_action_badge": f"Next: {next_action_badge}" if next_action_badge else "Next: none",
                "no_next_action": bool(open_children) and next_action is None,
                "blocked": bool(blocked),
                "blocked_child_count": len(blocked_children),
                "waiting_child_count": len(waiting_children),
                "oldest_waiting_days": int(oldest_waiting_days),
                "deferred_child_count": len(deferred_children),
                "no_due_child_count": len(no_due_children),
                "stalled": bool(stalled),
                "stalled_reasons": stalled_reasons,
                "stalled_reason_text": "; ".join(stalled_reasons),
                "stale_days": int(stale_age_days),
                "state_label": state_label,
                "review_note": " | ".join(review_parts),
            }
        )

    results.sort(
        key=lambda row: (
            0 if row.get("stalled") else 1,
            0 if row.get("blocked") else 1,
            0 if row.get("next_action_task_id") else 1,
            int(row.get("priority") or 99),
            str(row.get("description") or "").lower(),
            int(row.get("id") or 0),
        )
    )
    return results


def analyze_workload(
    tasks: list[dict],
    *,
    overload_task_threshold: int = 5,
    high_priority_threshold: int = 3,
    overdue_warning_threshold: int = 5,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    overload_threshold = max(2, int(overload_task_threshold or 5))
    urgent_threshold = max(2, int(high_priority_threshold or 3))
    overdue_threshold = max(1, int(overdue_warning_threshold or 5))

    due_map: dict[str, list[dict]] = {}
    overdue_rows: list[dict] = []

    for task in tasks:
        if _is_archived(task) or _is_done(task):
            continue
        due = _parse_iso_date(task.get("due_date"))
        if due is None:
            continue
        due_map.setdefault(due.isoformat(), []).append(task)
        if due < today:
            overdue_rows.append(task)

    warnings: list[dict] = []
    suggestions: list[dict] = []
    busiest_days: list[dict] = []

    for due_iso, rows in sorted(due_map.items()):
        total = len(rows)
        urgent = sum(1 for row in rows if int(row.get("priority") or 99) <= 2)
        if total <= 0:
            continue
        busiest_days.append({"due_date": due_iso, "task_count": total, "high_priority_count": urgent})
        if total >= overload_threshold:
            warnings.append(
                {
                    "kind": "day_overload",
                    "due_date": due_iso,
                    "message": f"{total} tasks are due on {due_iso}.",
                    "task_ids": [int(row["id"]) for row in rows],
                }
            )
            move_candidates = [int(row["id"]) for row in rows if int(row.get("priority") or 99) >= 3]
            if move_candidates:
                suggestions.append(
                    {
                        "kind": "spread_day",
                        "message": f"Consider moving lower-priority tasks off {due_iso} to spread the workload.",
                        "task_ids": move_candidates,
                    }
                )
        if urgent >= urgent_threshold:
            warnings.append(
                {
                    "kind": "high_priority_cluster",
                    "due_date": due_iso,
                    "message": f"{urgent} high-priority tasks are clustered on {due_iso}.",
                    "task_ids": [int(row["id"]) for row in rows if int(row.get("priority") or 99) <= 2],
                }
            )
            lower_priority_same_day = [int(row["id"]) for row in rows if int(row.get("priority") or 99) > 2]
            if lower_priority_same_day:
                suggestions.append(
                    {
                        "kind": "protect_priority_day",
                        "message": f"Protect {due_iso} for urgent work by rescheduling non-urgent tasks.",
                        "task_ids": lower_priority_same_day,
                    }
                )

    if len(overdue_rows) >= overdue_threshold:
        warnings.append(
            {
                "kind": "overdue_growth",
                "message": f"{len(overdue_rows)} tasks are overdue.",
                "task_ids": [int(row["id"]) for row in overdue_rows],
            }
        )
        moveable_overdue = [int(row["id"]) for row in overdue_rows if int(row.get("priority") or 99) >= 3]
        if moveable_overdue:
            suggestions.append(
                {
                    "kind": "reschedule_overdue",
                    "message": "Reschedule non-urgent overdue tasks and clear blockers before adding more due dates.",
                    "task_ids": moveable_overdue,
                }
            )

    busiest_days.sort(key=lambda row: (-int(row["task_count"]), row["due_date"]))
    return {
        "warnings": warnings,
        "suggestions": suggestions,
        "busiest_days": busiest_days[:7],
        "overdue_open": len(overdue_rows),
    }
