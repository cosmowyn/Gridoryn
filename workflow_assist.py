from __future__ import annotations

import json


def _normalize_review_key(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        numeric = int(text)
    except Exception:
        return text
    if numeric <= 0:
        return None
    return str(numeric)


def review_ack_state_from_setting(raw) -> dict[str, set[str]]:
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

    out: dict[str, set[str]] = {}
    for category, values in data.items():
        key = str(category or "").strip()
        if not key:
            continue
        ids: set[str] = set()
        if isinstance(values, (list, tuple, set)):
            for value in values:
                review_key = _normalize_review_key(value)
                if review_key is not None:
                    ids.add(review_key)
        if ids:
            out[key] = ids
    return out


def review_ack_state_to_setting(state: dict[str, set[str]] | None) -> str:
    payload = {}
    for category, ids in (state or {}).items():
        key = str(category or "").strip()
        if not key:
            continue
        values = sorted(
            {
                review_key
                for review_key in (_normalize_review_key(item) for item in (ids or set()))
                if review_key is not None
            }
        )
        if values:
            payload[key] = values
    return json.dumps(payload, sort_keys=True)


def acknowledge_review_items(
    state: dict[str, set[str]] | None,
    category: str,
    review_keys,
) -> dict[str, set[str]]:
    out = {str(k): set(v) for k, v in (state or {}).items()}
    key = str(category or "").strip()
    if not key:
        return out
    ids = out.setdefault(key, set())
    for value in review_keys or []:
        review_key = _normalize_review_key(value)
        if review_key is not None:
            ids.add(review_key)
    if not ids:
        out.pop(key, None)
    return out


def clear_review_acknowledgements(
    state: dict[str, set[str]] | None,
    category: str | None = None,
) -> dict[str, set[str]]:
    out = {str(k): set(v) for k, v in (state or {}).items()}
    if category is None:
        return {}
    out.pop(str(category or "").strip(), None)
    return out


def filter_acknowledged_review_data(
    data: dict[str, list[dict]] | None,
    ack_state: dict[str, set[str]] | None,
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
            review_key = _normalize_review_key(row.get("review_key"))
            if review_key is None:
                review_key = _normalize_review_key(row.get("id"))
            if review_key is not None and review_key in hidden_ids:
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
