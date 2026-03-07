from __future__ import annotations

import json


def review_ack_state_from_setting(raw) -> dict[str, set[int]]:
    data = raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            data = json.loads(s)
        except Exception:
            return {}
    if not isinstance(data, dict):
        return {}

    out: dict[str, set[int]] = {}
    for category, values in data.items():
        key = str(category or "").strip()
        if not key:
            continue
        ids = set()
        if isinstance(values, (list, tuple, set)):
            for value in values:
                try:
                    task_id = int(value)
                except Exception:
                    continue
                if task_id > 0:
                    ids.add(task_id)
        if ids:
            out[key] = ids
    return out


def review_ack_state_to_setting(state: dict[str, set[int]] | None) -> str:
    payload = {}
    for category, ids in (state or {}).items():
        key = str(category or "").strip()
        if not key:
            continue
        values = sorted({int(task_id) for task_id in (ids or set()) if int(task_id) > 0})
        if values:
            payload[key] = values
    return json.dumps(payload, sort_keys=True)


def acknowledge_review_items(
    state: dict[str, set[int]] | None,
    category: str,
    task_ids: list[int] | tuple[int, ...] | set[int],
) -> dict[str, set[int]]:
    out = {str(k): set(v) for k, v in (state or {}).items()}
    key = str(category or "").strip()
    if not key:
        return out
    ids = out.setdefault(key, set())
    for value in task_ids or []:
        try:
            task_id = int(value)
        except Exception:
            continue
        if task_id > 0:
            ids.add(task_id)
    if not ids:
        out.pop(key, None)
    return out


def clear_review_acknowledgements(
    state: dict[str, set[int]] | None,
    category: str | None = None,
) -> dict[str, set[int]]:
    out = {str(k): set(v) for k, v in (state or {}).items()}
    if category is None:
        return {}
    out.pop(str(category or "").strip(), None)
    return out


def filter_acknowledged_review_data(
    data: dict[str, list[dict]] | None,
    ack_state: dict[str, set[int]] | None,
) -> tuple[dict[str, list[dict]], dict[str, int]]:
    filtered: dict[str, list[dict]] = {}
    hidden_counts: dict[str, int] = {}
    source = data or {}
    ack = ack_state or {}

    for category, rows in source.items():
        hidden = 0
        allowed: list[dict] = []
        hidden_ids = ack.get(str(category), set())
        for row in rows or []:
            try:
                task_id = int(row.get("id") or 0)
            except Exception:
                task_id = 0
            if task_id > 0 and task_id in hidden_ids:
                hidden += 1
                continue
            allowed.append(row)
        filtered[str(category)] = allowed
        hidden_counts[str(category)] = hidden
    return filtered, hidden_counts


def should_show_onboarding(onboarding_completed: bool, task_count: int) -> bool:
    if bool(onboarding_completed):
        return False
    return int(task_count or 0) <= 0
