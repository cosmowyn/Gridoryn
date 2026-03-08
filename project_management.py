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


def build_timeline_rows(
    project_task: dict,
    phases: list[dict],
    tasks: list[dict],
    milestones: list[dict],
    deliverables: list[dict],
    summary: dict,
) -> list[dict]:
    phase_names = {int(row["id"]): str(row.get("name") or "") for row in phases if row.get("id") is not None}
    rows: list[dict] = []

    project_target = str(summary.get("target_date") or project_task.get("due_date") or "") or None
    rows.append(
        {
            "kind": "project",
            "item_id": int(project_task["id"]),
            "label": str(project_task.get("description") or "Project"),
            "phase_name": "",
            "start_date": None,
            "end_date": project_target,
            "baseline_date": str(summary.get("baseline_target_date") or "") or None,
            "status": str(summary.get("effective_health") or "on_track"),
            "blocked": bool(summary.get("effective_health") in {"blocked", "awaiting_external_input"}),
            "progress_percent": int(project_task.get("progress_percent") or 0),
        }
    )

    for task in tasks:
        start_date = str(task.get("start_date") or "") or None
        end_date = str(task.get("due_date") or "") or start_date
        if not start_date and not end_date:
            continue
        rows.append(
            {
                "kind": "task",
                "item_id": int(task["id"]),
                "label": str(task.get("description") or "Task"),
                "phase_name": phase_names.get(int(task.get("phase_id") or 0), ""),
                "start_date": start_date or end_date,
                "end_date": end_date,
                "baseline_date": None,
                "status": str(task.get("status") or "Todo"),
                "blocked": int(task.get("blocked_by_count") or 0) > 0 or bool(str(task.get("waiting_for") or "").strip()),
                "progress_percent": 100 if str(task.get("status") or "") == "Done" else int(task.get("progress_percent") or 0),
            }
        )

    for milestone in milestones:
        target_date = str(milestone.get("target_date") or "") or None
        start_date = str(milestone.get("start_date") or "") or target_date
        if not start_date and not target_date:
            continue
        rows.append(
            {
                "kind": "milestone",
                "item_id": int(milestone["id"]),
                "label": str(milestone.get("title") or "Milestone"),
                "phase_name": phase_names.get(int(milestone.get("phase_id") or 0), ""),
                "start_date": start_date or target_date,
                "end_date": target_date or start_date,
                "baseline_date": str(milestone.get("baseline_target_date") or "") or None,
                "status": str(milestone.get("status") or "planned"),
                "blocked": bool(milestone.get("is_blocked")),
                "progress_percent": int(milestone.get("progress_percent") or 0),
            }
        )

    for deliverable in deliverables:
        due_date = str(deliverable.get("due_date") or "") or None
        if not due_date:
            continue
        rows.append(
            {
                "kind": "deliverable",
                "item_id": int(deliverable["id"]),
                "label": str(deliverable.get("title") or "Deliverable"),
                "phase_name": phase_names.get(int(deliverable.get("phase_id") or 0), ""),
                "start_date": due_date,
                "end_date": due_date,
                "baseline_date": str(deliverable.get("baseline_due_date") or "") or None,
                "status": str(deliverable.get("status") or "planned"),
                "blocked": bool(deliverable.get("is_blocked")),
                "progress_percent": 100 if str(deliverable.get("status") or "") == "completed" else 0,
            }
        )

    order = {"project": 0, "milestone": 1, "deliverable": 2, "task": 3}
    rows.sort(
        key=lambda row: (
            parse_iso_date(row.get("start_date")) or parse_iso_date(row.get("end_date")) or date.max,
            order.get(str(row.get("kind") or ""), 99),
            str(row.get("phase_name") or "").lower(),
            str(row.get("label") or "").lower(),
            int(row.get("item_id") or 0),
        )
    )
    return rows
