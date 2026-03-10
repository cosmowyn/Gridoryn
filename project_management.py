from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from typing import Iterable

DEFAULT_PHASE_NAMES = [
    "Intake",
    "Planning",
    "Execution",
    "Testing",
    "Approval",
    "Closure",
]

PROJECT_HEALTH_STATES = [
    "on_track",
    "at_risk",
    "delayed",
    "blocked",
    "awaiting_external_input",
    "scope_drifting",
]

PROJECT_HEALTH_LABELS = {
    "on_track": "On track",
    "at_risk": "At risk",
    "delayed": "Delayed",
    "blocked": "Blocked",
    "awaiting_external_input": "Awaiting external input",
    "scope_drifting": "Scope drifting",
}

MILESTONE_STATUSES = ["planned", "in_progress", "blocked", "completed"]
DELIVERABLE_STATUSES = ["planned", "in_progress", "review", "blocked", "completed"]
REGISTER_ENTRY_TYPES = ["risk", "issue", "assumption", "decision"]
REGISTER_STATUSES = ["open", "monitoring", "resolved", "accepted"]
DEPENDENCY_KINDS = {"task", "milestone"}
DEPENDENCY_TYPE_FINISH_TO_START = "finish_to_start"


def today_local() -> date:
    return date.today()


def parse_iso_date(value: str | None) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        return None


def parse_iso_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def normalize_health(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in PROJECT_HEALTH_STATES:
        return raw
    aliases = {
        "on track": "on_track",
        "atrisk": "at_risk",
        "at risk": "at_risk",
        "awaiting external input": "awaiting_external_input",
        "scope drifting": "scope_drifting",
    }
    return aliases.get(raw)


def health_label(value: str | None) -> str:
    key = normalize_health(value)
    if not key:
        return "Unknown"
    return PROJECT_HEALTH_LABELS.get(key, key.replace("_", " ").title())


def default_phases_payload(project_task_id: int, stamp: str) -> list[dict]:
    rows = []
    for index, name in enumerate(DEFAULT_PHASE_NAMES, start=1):
        rows.append(
            {
                "project_task_id": int(project_task_id),
                "name": str(name),
                "sort_order": index,
                "created_at": stamp,
                "updated_at": stamp,
            }
        )
    return rows


def normalize_record_status(status: str | None, allowed: Iterable[str], fallback: str) -> str:
    raw = str(status or "").strip().lower()
    allowed_set = {str(item).strip().lower() for item in allowed}
    if raw in allowed_set:
        return raw
    return str(fallback).strip().lower()


def normalize_register_type(value: str | None) -> str:
    return normalize_record_status(value, REGISTER_ENTRY_TYPES, "risk")


def normalize_dependency_refs(refs: Iterable[dict] | None) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        kind = str(ref.get("kind") or "").strip().lower()
        if kind not in DEPENDENCY_KINDS:
            continue
        try:
            item_id = int(ref.get("id"))
        except Exception:
            continue
        if item_id <= 0:
            continue
        key = (kind, item_id)
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "id": item_id})
    return out


def validate_dependency_graph(
    existing_edges: Iterable[dict],
    predecessor_kind: str,
    predecessor_id: int,
    successor_kind: str,
    successor_id: int,
    *,
    exclude_edge_id: int | None = None,
) -> tuple[bool, str]:
    pre_kind = str(predecessor_kind or "").strip().lower()
    succ_kind = str(successor_kind or "").strip().lower()
    try:
        pre_id = int(predecessor_id)
        succ_id = int(successor_id)
    except Exception:
        return False, "Dependency IDs must be integers."

    if pre_kind not in DEPENDENCY_KINDS or succ_kind not in DEPENDENCY_KINDS:
        return False, "Unsupported dependency item type."
    if pre_id <= 0 or succ_id <= 0:
        return False, "Dependency IDs must be positive."
    if pre_kind == succ_kind and pre_id == succ_id:
        return False, "An item cannot depend on itself."

    graph: dict[tuple[str, int], set[tuple[str, int]]] = defaultdict(set)
    for edge in existing_edges or []:
        if not isinstance(edge, dict):
            continue
        try:
            edge_id = int(edge.get("id")) if edge.get("id") is not None else None
        except Exception:
            edge_id = None
        if exclude_edge_id is not None and edge_id == int(exclude_edge_id):
            continue
        edge_pre = (str(edge.get("predecessor_kind") or "").strip().lower(), int(edge.get("predecessor_id") or 0))
        edge_succ = (str(edge.get("successor_kind") or "").strip().lower(), int(edge.get("successor_id") or 0))
        if edge_pre[0] in DEPENDENCY_KINDS and edge_succ[0] in DEPENDENCY_KINDS and edge_pre[1] > 0 and edge_succ[1] > 0:
            graph[edge_pre].add(edge_succ)

    graph[(pre_kind, pre_id)].add((succ_kind, succ_id))
    target = (pre_kind, pre_id)
    start = (succ_kind, succ_id)
    queue: deque[tuple[str, int]] = deque([start])
    seen: set[tuple[str, int]] = set()
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        if node == target:
            return False, "This dependency would create a circular dependency."
        for child in graph.get(node, set()):
            if child not in seen:
                queue.append(child)
    return True, ""


def is_item_complete(kind: str, row: dict) -> bool:
    item_kind = str(kind or "").strip().lower()
    if item_kind == "task":
        return str(row.get("status") or "") == "Done" or bool(str(row.get("archived_at") or "").strip())
    if item_kind == "milestone":
        return str(row.get("status") or "").strip().lower() == "completed"
    if item_kind == "deliverable":
        return str(row.get("status") or "").strip().lower() == "completed"
    return False


def is_dependency_blocked(
    *,
    dependencies: Iterable[dict],
    tasks_by_id: dict[int, dict],
    milestones_by_id: dict[int, dict],
) -> bool:
    for dep in dependencies or []:
        kind = str(dep.get("kind") or "").strip().lower()
        try:
            dep_id = int(dep.get("id"))
        except Exception:
            continue
        if kind == "task":
            row = tasks_by_id.get(dep_id)
            if row and not is_item_complete("task", row):
                return True
        elif kind == "milestone":
            row = milestones_by_id.get(dep_id)
            if row and not is_item_complete("milestone", row):
                return True
    return False


def compute_personal_capacity(tasks: Iterable[dict], *, today: date | None = None) -> dict:
    current = today or today_local()
    daily: dict[str, dict] = defaultdict(lambda: {"task_count": 0, "effort_minutes": 0, "high_priority": 0})
    weekly: dict[str, dict] = defaultdict(lambda: {"task_count": 0, "effort_minutes": 0, "high_priority": 0})

    for task in tasks or []:
        if str(task.get("status") or "") == "Done":
            continue
        if str(task.get("archived_at") or "").strip():
            continue
        due = parse_iso_date(task.get("due_date"))
        if due is None:
            continue
        effort = int(task.get("effort_minutes") or 0)
        prio = int(task.get("priority") or 99)
        day_key = due.isoformat()
        week_start = (due - timedelta(days=due.weekday())).isoformat()
        daily[day_key]["task_count"] += 1
        daily[day_key]["effort_minutes"] += max(0, effort)
        if prio <= 2:
            daily[day_key]["high_priority"] += 1
        weekly[week_start]["task_count"] += 1
        weekly[week_start]["effort_minutes"] += max(0, effort)
        if prio <= 2:
            weekly[week_start]["high_priority"] += 1

    day_rows = [
        {
            "date": key,
            "task_count": value["task_count"],
            "effort_minutes": value["effort_minutes"],
            "high_priority_count": value["high_priority"],
            "overcommitted": value["task_count"] >= 6 or value["effort_minutes"] > 8 * 60,
        }
        for key, value in daily.items()
    ]
    day_rows.sort(key=lambda row: row["date"])

    week_rows = [
        {
            "week_start": key,
            "task_count": value["task_count"],
            "effort_minutes": value["effort_minutes"],
            "high_priority_count": value["high_priority"],
            "overcommitted": value["task_count"] >= 20 or value["effort_minutes"] > 40 * 60,
        }
        for key, value in weekly.items()
    ]
    week_rows.sort(key=lambda row: row["week_start"])

    warnings: list[dict] = []
    for row in day_rows:
        if row["overcommitted"]:
            warnings.append(
                {
                    "kind": "day_overcommitment",
                    "message": (
                        f"{row['date']}: {row['task_count']} task(s), "
                        f"{row['effort_minutes']} planned minutes."
                    ),
                }
            )
        elif row["high_priority_count"] >= 3:
            warnings.append(
                {
                    "kind": "priority_cluster",
                    "message": f"{row['date']}: {row['high_priority_count']} high-priority items are clustered.",
                }
            )
    for row in week_rows:
        if row["overcommitted"]:
            warnings.append(
                {
                    "kind": "week_overcommitment",
                    "message": (
                        f"Week starting {row['week_start']}: {row['task_count']} task(s), "
                        f"{row['effort_minutes']} planned minutes."
                    ),
                }
            )
    return {"days": day_rows, "weeks": week_rows, "warnings": warnings}


def compute_baseline_variance(current_value: str | None, baseline_value: str | None) -> dict:
    current_date = parse_iso_date(current_value)
    baseline_date = parse_iso_date(baseline_value)
    if current_date is None or baseline_date is None:
        return {"days": None, "direction": "none", "label": "No baseline"}
    delta = (current_date - baseline_date).days
    if delta == 0:
        return {"days": 0, "direction": "on_baseline", "label": "On baseline"}
    if delta > 0:
        return {"days": delta, "direction": "late", "label": f"{delta} day(s) late"}
    return {"days": abs(delta), "direction": "early", "label": f"{abs(delta)} day(s) early"}


def build_project_summary(
    project_task: dict,
    profile: dict | None,
    phases: list[dict],
    tasks: list[dict],
    milestones: list[dict],
    deliverables: list[dict],
    register_entries: list[dict],
    baseline: dict | None,
    dependency_map: dict[tuple[str, int], list[dict]],
    *,
    today: date | None = None,
) -> dict:
    current = today or today_local()
    phase_names = {int(row["id"]): str(row.get("name") or "") for row in phases if row.get("id") is not None}
    tasks_by_id = {int(row["id"]): row for row in tasks if row.get("id") is not None}
    milestones_by_id = {int(row["id"]): row for row in milestones if row.get("id") is not None}

    active_tasks = [row for row in tasks if str(row.get("status") or "") != "Done" and not str(row.get("archived_at") or "").strip()]
    open_milestones = [row for row in milestones if str(row.get("status") or "") != "completed"]
    open_deliverables = [row for row in deliverables if str(row.get("status") or "") != "completed"]

    overdue_tasks = [row for row in active_tasks if (parse_iso_date(row.get("due_date")) or date.max) < current]
    overdue_milestones = [row for row in open_milestones if (parse_iso_date(row.get("target_date")) or date.max) < current]
    due_soon_deliverables = [
        row for row in open_deliverables
        if (parse_iso_date(row.get("due_date")) or date.max) <= current + timedelta(days=7)
    ]

    blocked_task_count = sum(1 for row in active_tasks if int(row.get("blocked_by_count") or 0) > 0)
    waiting_task_count = sum(1 for row in active_tasks if str(row.get("waiting_for") or "").strip())
    blocked_milestone_count = 0
    next_milestone = None
    next_milestone_date = None
    for row in open_milestones:
        deps = dependency_map.get(("milestone", int(row["id"])), [])
        if is_dependency_blocked(dependencies=deps, tasks_by_id=tasks_by_id, milestones_by_id=milestones_by_id):
            blocked_milestone_count += 1
        milestone_date = parse_iso_date(row.get("target_date"))
        if milestone_date is None:
            continue
        if next_milestone_date is None or milestone_date < next_milestone_date:
            next_milestone_date = milestone_date
            next_milestone = dict(row)

    total_estimate = sum(max(0, int(row.get("effort_minutes") or 0)) for row in tasks)
    total_actual = sum(max(0, int(row.get("actual_minutes") or 0)) for row in tasks)
    remaining_effort = max(0, total_estimate - total_actual)

    phase_breakdown: list[dict] = []
    for phase in phases:
        phase_id = int(phase["id"])
        phase_tasks = [row for row in tasks if int(row.get("phase_id") or 0) == phase_id]
        phase_milestones = [row for row in milestones if int(row.get("phase_id") or 0) == phase_id]
        phase_deliverables = [row for row in deliverables if int(row.get("phase_id") or 0) == phase_id]
        if not phase_tasks and not phase_milestones and not phase_deliverables:
            continue
        phase_breakdown.append(
            {
                "phase_id": phase_id,
                "phase_name": str(phase.get("name") or ""),
                "task_count": len(phase_tasks),
                "milestone_count": len(phase_milestones),
                "deliverable_count": len(phase_deliverables),
                "open_task_count": sum(1 for row in phase_tasks if str(row.get("status") or "") != "Done"),
            }
        )

    recent_activity = None
    for row in tasks:
        last_update = parse_iso_datetime(row.get("last_update"))
        if last_update is None:
            continue
        if recent_activity is None or last_update > recent_activity:
            recent_activity = last_update
    inactivity_days = (current - recent_activity.date()).days if recent_activity is not None else None

    open_risks_high = sum(
        1 for row in register_entries
        if str(row.get("entry_type") or "") == "risk"
        and str(row.get("status") or "") not in {"resolved", "accepted"}
        and int(row.get("severity") or 0) >= 4
    )
    scope_mentions = sum(
        1 for row in register_entries
        if str(row.get("status") or "") not in {"resolved", "accepted"}
        and "scope" in f"{row.get('title') or ''} {row.get('details') or ''}".lower()
    )

    target_date = str((profile or {}).get("target_date") or project_task.get("due_date") or "") or None
    baseline_target_date = str((baseline or {}).get("target_date") or "") or None
    variance = compute_baseline_variance(target_date, baseline_target_date)

    inferred_health = "on_track"
    inferred_reason = "Healthy project trajectory."
    if scope_mentions > 0:
        inferred_health = "scope_drifting"
        inferred_reason = "Open register items mention scope changes or drift."
    elif overdue_milestones or overdue_tasks or (target_date and parse_iso_date(target_date) and parse_iso_date(target_date) < current):
        inferred_health = "delayed"
        inferred_reason = "Overdue work or missed milestone/target dates detected."
    elif waiting_task_count > 0 and blocked_task_count + blocked_milestone_count > 0:
        inferred_health = "awaiting_external_input"
        inferred_reason = "Critical work is waiting on external input or unresolved blockers."
    elif blocked_task_count > 0 or blocked_milestone_count > 0:
        inferred_health = "blocked"
        inferred_reason = "Dependencies are blocking current progress."
    elif open_risks_high > 0:
        inferred_health = "at_risk"
        inferred_reason = "High-severity open risks need active attention."
    elif next_milestone_date is not None and (next_milestone_date - current).days <= 7 and remaining_effort > (8 * 60 * 3):
        inferred_health = "at_risk"
        inferred_reason = "The next milestone is close and remaining effort is still high."
    elif inactivity_days is not None and inactivity_days >= 21:
        inferred_health = "at_risk"
        inferred_reason = f"No project activity logged for {inactivity_days} day(s)."

    manual_health = normalize_health((profile or {}).get("project_status_health"))
    effective_health = manual_health or inferred_health

    return {
        "project_task_id": int(project_task["id"]),
        "project_name": str(project_task.get("description") or ""),
        "owner": str((profile or {}).get("owner") or "Self"),
        "category": str((profile or {}).get("category") or ""),
        "target_date": target_date,
        "baseline_target_date": baseline_target_date,
        "target_variance": variance,
        "manual_health": manual_health,
        "inferred_health": inferred_health,
        "effective_health": effective_health,
        "effective_health_label": health_label(effective_health),
        "inferred_health_reason": inferred_reason,
        "objective": str((profile or {}).get("objective") or ""),
        "summary": str((profile or {}).get("summary") or ""),
        "active_task_count": len(active_tasks),
        "overdue_task_count": len(overdue_tasks),
        "milestone_open_count": len(open_milestones),
        "milestone_overdue_count": len(overdue_milestones),
        "deliverable_open_count": len(open_deliverables),
        "deliverables_due_soon": len(due_soon_deliverables),
        "blocked_task_count": blocked_task_count,
        "waiting_task_count": waiting_task_count,
        "blocked_milestone_count": blocked_milestone_count,
        "next_milestone": next_milestone,
        "next_milestone_days": (next_milestone_date - current).days if next_milestone_date is not None else None,
        "phase_breakdown": phase_breakdown,
        "phase_names": phase_names,
        "effort_estimate_minutes": total_estimate,
        "effort_actual_minutes": total_actual,
        "effort_remaining_minutes": remaining_effort,
        "baseline_effort_minutes": int((baseline or {}).get("effort_minutes") or 0),
        "baseline_effort_variance_minutes": total_estimate - int((baseline or {}).get("effort_minutes") or 0),
        "recent_activity_at": recent_activity.isoformat(sep=" ") if recent_activity is not None else None,
        "inactivity_days": inactivity_days,
        "open_risks_high": open_risks_high,
        "scope_mentions": scope_mentions,
    }


def _timeline_uid(kind: str, item_id: int | str) -> str:
    return f"{str(kind or '').strip().lower()}:{item_id}"


def _row_has_dates(row: dict) -> bool:
    return bool(parse_iso_date(row.get("start_date")) or parse_iso_date(row.get("end_date")))


def _row_sort_key(row: dict) -> tuple:
    return (
        parse_iso_date(row.get("start_date")) or parse_iso_date(row.get("end_date")) or date.max,
        str(row.get("label") or "").lower(),
        int(row.get("item_id") or 0),
    )


def build_timeline_rows(
    project_task: dict,
    phases: list[dict],
    tasks: list[dict],
    milestones: list[dict],
    deliverables: list[dict],
    summary: dict,
    dependency_rows: list[dict] | None = None,
) -> list[dict]:
    project_id = int(project_task["id"])
    phase_map = {
        int(row["id"]): {
            "id": int(row["id"]),
            "name": str(row.get("name") or ""),
            "sort_order": int(row.get("sort_order") or 0),
        }
        for row in phases
        if row.get("id") is not None
    }
    tasks_by_id = {
        int(row["id"]): row
        for row in tasks
        if row.get("id") is not None and int(row["id"]) != project_id
    }
    task_children: dict[int | None, list[dict]] = defaultdict(list)
    for row in tasks_by_id.values():
        task_children[row.get("parent_id")].append(row)
    for child_rows in task_children.values():
        child_rows.sort(
            key=lambda row: (
                int(row.get("sort_order") or 0),
                str(row.get("description") or "").lower(),
                int(row.get("id") or 0),
            )
        )

    milestones_by_phase: dict[int | None, list[dict]] = defaultdict(list)
    for row in milestones or []:
        if not parse_iso_date(row.get("start_date")) and not parse_iso_date(row.get("target_date")):
            continue
        milestones_by_phase[row.get("phase_id")].append(row)
    for rows in milestones_by_phase.values():
        rows.sort(
            key=lambda row: (
                parse_iso_date(row.get("target_date")) or date.max,
                str(row.get("title") or "").lower(),
                int(row.get("id") or 0),
            )
        )

    deliverables_by_phase: dict[int | None, list[dict]] = defaultdict(list)
    for row in deliverables or []:
        if not parse_iso_date(row.get("due_date")):
            continue
        deliverables_by_phase[row.get("phase_id")].append(row)
    for rows in deliverables_by_phase.values():
        rows.sort(
            key=lambda row: (
                parse_iso_date(row.get("due_date")) or date.max,
                str(row.get("title") or "").lower(),
                int(row.get("id") or 0),
            )
        )

    rows: list[dict] = []
    children_map: dict[str | None, list[str]] = defaultdict(list)
    row_lookup: dict[str, dict] = {}

    def add_row(row: dict):
        uid = str(row["uid"])
        rows.append(row)
        row_lookup[uid] = row
        children_map[str(row.get("parent_uid")) if row.get("parent_uid") is not None else None].append(uid)

    project_uid = _timeline_uid("project", project_id)
    add_row(
        {
            "uid": project_uid,
            "kind": "project",
            "item_id": project_id,
            "label": str(project_task.get("description") or "Project"),
            "parent_uid": None,
            "phase_id": None,
            "phase_name": "",
            "start_date": None,
            "end_date": str(summary.get("target_date") or project_task.get("due_date") or "") or None,
            "baseline_date": str(summary.get("baseline_target_date") or "") or None,
            "status": str(summary.get("effective_health") or "on_track"),
            "blocked": bool(summary.get("effective_health") in {"blocked", "awaiting_external_input"}),
            "progress_percent": int(project_task.get("progress_percent") or 0),
            "gantt_color_hex": str(project_task.get("gantt_color_hex") or "").strip() or None,
            "summary_row": True,
            "render_style": "summary",
            "editable_move": False,
            "editable_start": False,
            "editable_end": False,
            "linked_task_id": project_id,
            "sort_index": 0,
        }
    )

    def top_level_phase_key(task_row: dict) -> int | None:
        current = dict(task_row)
        phase_id = current.get("phase_id")
        parent_id = current.get("parent_id")
        while parent_id in tasks_by_id:
            current = tasks_by_id[int(parent_id)]
            parent_id = current.get("parent_id")
            if current.get("parent_id") == project_id:
                phase_id = current.get("phase_id")
        return phase_id

    top_level_tasks_by_phase: dict[int | None, list[dict]] = defaultdict(list)
    for task in tasks_by_id.values():
        if int(task.get("parent_id") or 0) == project_id:
            top_level_tasks_by_phase[task.get("phase_id")].append(task)
    for items in top_level_tasks_by_phase.values():
        items.sort(
            key=lambda row: (
                int(row.get("sort_order") or 0),
                str(row.get("description") or "").lower(),
                int(row.get("id") or 0),
            )
        )

    content_phase_ids: list[int | None] = []
    for phase_id, phase in sorted(
        phase_map.items(),
        key=lambda item: (int(item[1].get("sort_order") or 0), str(item[1].get("name") or "").lower()),
    ):
        if (
            top_level_tasks_by_phase.get(phase_id)
            or milestones_by_phase.get(phase_id)
            or deliverables_by_phase.get(phase_id)
        ):
            content_phase_ids.append(phase_id)
    if (
        top_level_tasks_by_phase.get(None)
        or milestones_by_phase.get(None)
        or deliverables_by_phase.get(None)
    ):
        content_phase_ids.append(None)

    def phase_label(phase_id: int | None) -> str:
        if phase_id is None:
            return "Unassigned"
        return str(phase_map.get(int(phase_id), {}).get("name") or "Phase")

    def add_task_branch(task_row: dict, parent_uid: str):
        task_id = int(task_row["id"])
        child_rows = list(task_children.get(task_id, []))
        has_children = bool(child_rows)
        start_date = str(task_row.get("start_date") or "") or None
        end_date = str(task_row.get("due_date") or "") or start_date
        add_row(
            {
                "uid": _timeline_uid("task", task_id),
                "kind": "task",
                "item_id": task_id,
                "label": str(task_row.get("description") or "Task"),
                "parent_uid": parent_uid,
                "phase_id": task_row.get("phase_id"),
                "phase_name": phase_label(task_row.get("phase_id"))
                if task_row.get("phase_id") is not None
                else "",
                "start_date": start_date or end_date,
                "end_date": end_date,
                "baseline_date": None,
                "status": str(task_row.get("status") or "Todo"),
                "blocked": int(task_row.get("blocked_by_count") or 0) > 0
                or bool(str(task_row.get("waiting_for") or "").strip()),
                "progress_percent": (
                    100
                    if str(task_row.get("status") or "") == "Done"
                    else int(task_row.get("progress_percent") or 0)
                ),
                "gantt_color_hex": str(task_row.get("gantt_color_hex") or "").strip() or None,
                "summary_row": has_children,
                "render_style": "summary" if has_children else "task",
                "editable_move": not has_children,
                "editable_start": not has_children,
                "editable_end": not has_children,
                "linked_task_id": task_id,
                "reorderable": True,
                "sort_index": int(task_row.get("sort_order") or 0),
                "actual_parent_task_id": (
                    int(task_row.get("parent_id"))
                    if task_row.get("parent_id") is not None
                    else None
                ),
            }
        )
        task_uid = _timeline_uid("task", task_id)
        for child in child_rows:
            add_task_branch(child, task_uid)

    for phase_id in content_phase_ids:
        phase_uid = _timeline_uid("phase", phase_id if phase_id is not None else "unassigned")
        add_row(
            {
                "uid": phase_uid,
                "kind": "phase",
                "item_id": -1 if phase_id is None else int(phase_id),
                "label": phase_label(phase_id),
                "parent_uid": project_uid,
                "phase_id": phase_id,
                "phase_name": phase_label(phase_id),
                "start_date": None,
                "end_date": None,
                "baseline_date": None,
                "status": "",
                "blocked": False,
                "progress_percent": 0,
                "gantt_color_hex": None,
                "summary_row": True,
                "render_style": "summary",
                "editable_move": False,
                "editable_start": False,
                "editable_end": False,
                "linked_task_id": project_id,
                "sort_index": int(phase_map.get(int(phase_id), {}).get("sort_order") or 999)
                if phase_id is not None
                else 9999,
            }
        )
        for task_row in top_level_tasks_by_phase.get(phase_id, []):
            add_task_branch(task_row, phase_uid)
        for milestone in milestones_by_phase.get(phase_id, []):
            milestone_id = int(milestone["id"])
            target_date = str(milestone.get("target_date") or "") or None
            start_date = str(milestone.get("start_date") or "") or target_date
            add_row(
                {
                    "uid": _timeline_uid("milestone", milestone_id),
                    "kind": "milestone",
                    "item_id": milestone_id,
                    "label": str(milestone.get("title") or "Milestone"),
                    "parent_uid": phase_uid,
                    "phase_id": phase_id,
                    "phase_name": phase_label(phase_id) if phase_id is not None else "",
                    "start_date": start_date or target_date,
                    "end_date": target_date or start_date,
                    "baseline_date": str(milestone.get("baseline_target_date") or "") or None,
                    "status": str(milestone.get("status") or "planned"),
                    "blocked": bool(milestone.get("is_blocked")),
                    "progress_percent": int(milestone.get("progress_percent") or 0),
                    "gantt_color_hex": str(milestone.get("gantt_color_hex") or "").strip() or None,
                    "summary_row": False,
                    "render_style": "milestone",
                    "editable_move": True,
                    "editable_start": False,
                    "editable_end": False,
                    "linked_task_id": int(milestone.get("linked_task_id") or project_id),
                    "sort_index": milestone_id,
                }
            )
        for deliverable in deliverables_by_phase.get(phase_id, []):
            deliverable_id = int(deliverable["id"])
            due_date = str(deliverable.get("due_date") or "") or None
            add_row(
                {
                    "uid": _timeline_uid("deliverable", deliverable_id),
                    "kind": "deliverable",
                    "item_id": deliverable_id,
                    "label": str(deliverable.get("title") or "Deliverable"),
                    "parent_uid": phase_uid,
                    "phase_id": phase_id,
                    "phase_name": phase_label(phase_id) if phase_id is not None else "",
                    "start_date": due_date,
                    "end_date": due_date,
                    "baseline_date": str(deliverable.get("baseline_due_date") or "") or None,
                    "status": str(deliverable.get("status") or "planned"),
                    "blocked": bool(deliverable.get("is_blocked")),
                    "progress_percent": (
                        100 if str(deliverable.get("status") or "") == "completed" else 0
                    ),
                    "gantt_color_hex": str(deliverable.get("gantt_color_hex") or "").strip() or None,
                    "summary_row": False,
                    "render_style": "deliverable",
                    "editable_move": True,
                    "editable_start": False,
                    "editable_end": False,
                    "linked_task_id": int(
                        deliverable.get("linked_task_id")
                        or deliverable.get("project_task_id")
                        or project_id
                    ),
                    "sort_index": deliverable_id,
                }
            )

    def summarize(uid: str) -> tuple[date | None, date | None]:
        row = row_lookup[uid]
        start = parse_iso_date(row.get("start_date"))
        end = parse_iso_date(row.get("end_date")) or start
        for child_uid in children_map.get(uid, []):
            child_start, child_end = summarize(child_uid)
            if child_start is not None:
                start = child_start if start is None else min(start, child_start)
            if child_end is not None:
                end = child_end if end is None else max(end, child_end)
        if row.get("summary_row"):
            row["display_start_date"] = start.isoformat() if start is not None else None
            row["display_end_date"] = end.isoformat() if end is not None else None
        else:
            row["display_start_date"] = row.get("start_date")
            row["display_end_date"] = row.get("end_date")
        return start, end

    summarize(project_uid)

    connectors: list[dict] = []
    for dep in dependency_rows or []:
        predecessor_uid = _timeline_uid(dep.get("predecessor_kind"), int(dep.get("predecessor_id") or 0))
        successor_uid = _timeline_uid(dep.get("successor_kind"), int(dep.get("successor_id") or 0))
        predecessor = row_lookup.get(predecessor_uid)
        successor = row_lookup.get(successor_uid)
        if not predecessor or not successor:
            continue
        if predecessor.get("summary_row") or successor.get("summary_row"):
            continue
        connectors.append(
            {
                "id": int(dep.get("id") or 0),
                "predecessor_uid": predecessor_uid,
                "successor_uid": successor_uid,
                "predecessor_kind": str(dep.get("predecessor_kind") or ""),
                "predecessor_id": int(dep.get("predecessor_id") or 0),
                "successor_kind": str(dep.get("successor_kind") or ""),
                "successor_id": int(dep.get("successor_id") or 0),
                "dep_type": str(dep.get("dep_type") or DEPENDENCY_TYPE_FINISH_TO_START),
                "is_soft": bool(dep.get("is_soft")),
            }
        )

    for row in rows:
        row["dependencies"] = [
            dep for dep in connectors if dep["successor_uid"] == str(row["uid"])
        ]

    rows.sort(
        key=lambda row: (
            0 if str(row.get("kind") or "") == "project" else 1,
            str(row.get("parent_uid") or ""),
            int(row.get("sort_index") or 0),
            _row_sort_key(
                {
                    "start_date": row.get("display_start_date") or row.get("start_date"),
                    "end_date": row.get("display_end_date") or row.get("end_date"),
                    "label": row.get("label"),
                    "item_id": row.get("item_id"),
                }
            ),
        )
    )
    return rows
