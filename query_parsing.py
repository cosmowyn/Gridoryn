from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


WEEKDAY_TO_INT = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

PRIORITY_ALIASES = {
    "high": 1,
    "medium": 3,
    "low": 5,
}


@dataclass
class QuickAddResult:
    description: str
    due_date: str | None = None  # YYYY-MM-DD
    priority: int | None = None
    tags: list[str] = field(default_factory=list)
    bucket: str | None = None
    create_as_child: bool = False
    parent_hint: str | None = None
    parse_warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedSearch:
    free_text: str = ""
    statuses: set[str] = field(default_factory=set)
    priority: int | None = None
    due_ops: list[tuple[str, str]] = field(default_factory=list)  # (op, YYYY-MM-DD)
    due_none: bool = False
    tags: set[str] = field(default_factory=set)
    bucket: str | None = None
    phase: str | None = None
    has_children: bool | None = None
    blocked_only: bool = False
    waiting_only: bool = False
    recurring_only: bool = False
    parse_warnings: list[str] = field(default_factory=list)


def _today() -> date:
    return date.today()


def _parse_iso_date(text: str) -> date | None:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_dd_mmm_yyyy(text: str) -> date | None:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d-%b-%Y").date()
    except Exception:
        return None


def _parse_natural_day_token(token: str) -> date | None:
    t = str(token or "").strip().lower()
    if t == "today":
        return _today()
    if t == "tomorrow":
        return _today() + timedelta(days=1)
    return None


def _parse_next_weekday(token1: str, token2: str) -> date | None:
    if str(token1 or "").strip().lower() != "next":
        return None
    wd = WEEKDAY_TO_INT.get(str(token2 or "").strip().lower())
    if wd is None:
        return None
    today = _today()
    delta = (wd - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _add_months(d: date, months: int) -> date:
    idx = (d.month - 1) + int(months)
    y = d.year + (idx // 12)
    m = (idx % 12) + 1
    day = int(d.day)
    while day > 28:
        try:
            return date(y, m, day)
        except ValueError:
            day -= 1
    return date(y, m, max(1, day))


def _parse_quick_due_phrase(tokens: list[str], i: int) -> tuple[date | None, int]:
    if i < 0 or i >= len(tokens):
        return None, 0
    today = _today()
    t0 = str(tokens[i] or "").strip().lower()

    if t0 in {"today", "tonight"}:
        return today, 1
    if t0 == "tomorrow":
        return today + timedelta(days=1), 1

    if t0 == "day" and (i + 2) < len(tokens):
        t1 = str(tokens[i + 1] or "").strip().lower()
        t2 = str(tokens[i + 2] or "").strip().lower()
        if t1 == "after" and t2 == "tomorrow":
            return today + timedelta(days=2), 3

    if t0 == "next" and (i + 1) < len(tokens):
        t1 = str(tokens[i + 1] or "").strip().lower()
        wd = WEEKDAY_TO_INT.get(t1)
        if wd is not None:
            delta = (wd - today.weekday()) % 7
            if delta == 0:
                delta = 7
            return today + timedelta(days=delta), 2
        if t1 in {"week", "weeks", "wk"}:
            return today + timedelta(days=7), 2
        if t1 in {"month", "months"}:
            return _add_months(today, 1), 2
        if t1 in {"year", "years"}:
            return _add_months(today, 12), 2

    if t0 == "in" and (i + 2) < len(tokens):
        amount_txt = str(tokens[i + 1] or "").strip()
        unit = str(tokens[i + 2] or "").strip().lower()
        if amount_txt.isdigit():
            amount = int(amount_txt)
            if unit in {"day", "days"}:
                return today + timedelta(days=amount), 3
            if unit in {"week", "weeks"}:
                return today + timedelta(days=(7 * amount)), 3
            if unit in {"month", "months"}:
                return _add_months(today, amount), 3
            if unit in {"year", "years"}:
                return _add_months(today, amount * 12), 3

    if t0 in WEEKDAY_TO_INT:
        wd = WEEKDAY_TO_INT[t0]
        delta = (wd - today.weekday()) % 7
        return today + timedelta(days=delta), 1

    if t0 == "this" and (i + 1) < len(tokens):
        wd = WEEKDAY_TO_INT.get(str(tokens[i + 1] or "").strip().lower())
        if wd is not None:
            delta = (wd - today.weekday()) % 7
            return today + timedelta(days=delta), 2

    return None, 0


def parse_quick_add(text: str) -> QuickAddResult:
    raw = str(text or "").strip()
    if not raw:
        return QuickAddResult(description="")

    try:
        tokens = shlex.split(raw)
    except Exception:
        tokens = raw.split()
    consumed = [False] * len(tokens)
    due_date: date | None = None
    priority: int | None = None
    tags: list[str] = []
    tag_seen: set[str] = set()
    bucket: str | None = None
    create_as_child = False
    parent_hint: str | None = None
    warnings: list[str] = []

    for i, tok in enumerate(tokens):
        s = str(tok or "").strip()
        sl = s.lower()
        if not s:
            continue
        if sl == "+child":
            create_as_child = True
            consumed[i] = True
            continue
        if s.startswith(">"):
            hint = s[1:].strip()
            if hint:
                parent_hint = hint
            else:
                warnings.append("Ignored empty parent hint.")
            consumed[i] = True
            continue
        if s.startswith("@") or s.startswith("#"):
            tag = s[1:].strip()
            if tag:
                tag_key = tag.lower()
                if tag_key not in tag_seen:
                    tag_seen.add(tag_key)
                    tags.append(tag)
            else:
                warnings.append(f"Ignored invalid tag token: {s}")
            consumed[i] = True
            continue
        if s.startswith("/"):
            bucket_key = s[1:].strip().lower()
            if bucket_key in {"inbox", "today", "upcoming", "someday"}:
                bucket = bucket_key
                consumed[i] = True
                continue
        if s.startswith("!"):
            body = s[1:].strip().lower()
            m = re.fullmatch(r"p([1-5])", body)
            if m:
                priority = int(m.group(1))
                consumed[i] = True
                continue
            p = PRIORITY_ALIASES.get(body)
            if p is not None:
                priority = p
                consumed[i] = True
                continue

    # Priority: p1..p5
    for i, tok in enumerate(tokens):
        if consumed[i]:
            continue
        m = re.fullmatch(r"p([1-5])", tok.strip().lower())
        if m:
            priority = int(m.group(1))
            consumed[i] = True
            break

    # Priority aliases
    if priority is None:
        for i, tok in enumerate(tokens):
            if consumed[i]:
                continue
            p = PRIORITY_ALIASES.get(tok.strip().lower())
            if p is not None:
                priority = p
                consumed[i] = True
                break

    # Natural phrases and relative date words.
    if due_date is None:
        i = 0
        while i < len(tokens):
            if consumed[i]:
                i += 1
                continue
            d, used = _parse_quick_due_phrase(tokens, i)
            if d is not None:
                due_date = d
                for j in range(i, min(i + max(1, used), len(tokens))):
                    consumed[j] = True
                break
            i += 1

    # Legacy two-token next weekday parser (kept as fallback).
    if due_date is None:
        for i in range(len(tokens) - 1):
            if consumed[i] or consumed[i + 1]:
                continue
            d = _parse_next_weekday(tokens[i], tokens[i + 1])
            if d is not None:
                due_date = d
                consumed[i] = True
                consumed[i + 1] = True
                break

    # Basic date words (today / tomorrow)
    if due_date is None:
        for i, tok in enumerate(tokens):
            if consumed[i]:
                continue
            d = _parse_natural_day_token(tok)
            if d is not None:
                due_date = d
                consumed[i] = True
                break

    # ISO date
    if due_date is None:
        for i, tok in enumerate(tokens):
            if consumed[i]:
                continue
            d = _parse_iso_date(tok)
            if d is not None:
                due_date = d
                consumed[i] = True
                break

    # dd-mmm-yyyy
    if due_date is None:
        for i, tok in enumerate(tokens):
            if consumed[i]:
                continue
            d = _parse_dd_mmm_yyyy(tok)
            if d is not None:
                due_date = d
                consumed[i] = True
                break

    description_tokens = [tokens[i] for i in range(len(tokens)) if not consumed[i]]
    description = " ".join(description_tokens).strip()
    if not description:
        # Preserve original input if every token was recognized metadata
        description = raw

    return QuickAddResult(
        description=description,
        due_date=due_date.isoformat() if due_date else None,
        priority=priority,
        tags=tags,
        bucket=bucket,
        create_as_child=create_as_child,
        parent_hint=parent_hint,
        parse_warnings=warnings,
    )


def _resolve_search_date(text: str) -> date | None:
    s = str(text or "").strip().lower()
    if not s:
        return None
    if s == "today":
        return _today()
    if s == "tomorrow":
        return _today() + timedelta(days=1)
    d = _parse_iso_date(s)
    if d is not None:
        return d
    d = _parse_dd_mmm_yyyy(s)
    if d is not None:
        return d
    return None


def parse_search_query(text: str) -> ParsedSearch:
    raw = str(text or "").strip()
    if not raw:
        return ParsedSearch()

    try:
        tokens = shlex.split(raw)
    except Exception:
        tokens = raw.split()

    out = ParsedSearch()
    free_tokens: list[str] = []

    due_pattern = re.compile(r"^due(<=|>=|<|>|=)(.+)$", re.IGNORECASE)
    prio_pattern = re.compile(r"^priority:(\d+)$", re.IGNORECASE)

    for tok in tokens:
        s = str(tok).strip()
        sl = s.lower()
        if not s:
            continue

        if sl.startswith("status:"):
            value = sl.split(":", 1)[1].strip()
            if value:
                out.statuses.add(value.title() if value != "todo" else "Todo")
            else:
                out.parse_warnings.append(f"Ignored invalid status token: {s}")
            continue

        m = prio_pattern.match(sl)
        if m:
            try:
                out.priority = int(m.group(1))
            except Exception:
                out.parse_warnings.append(f"Ignored invalid priority token: {s}")
            continue

        m = due_pattern.match(sl)
        if m:
            op = m.group(1)
            rhs = m.group(2).strip()
            if rhs == "none":
                out.due_none = True
                continue
            d = _resolve_search_date(rhs)
            if d is None:
                out.parse_warnings.append(f"Ignored invalid due token: {s}")
            else:
                out.due_ops.append((op, d.isoformat()))
            continue

        if sl == "due:none":
            out.due_none = True
            continue

        if sl.startswith("tag:"):
            tag = s.split(":", 1)[1].strip()
            if tag:
                out.tags.add(tag)
            else:
                out.parse_warnings.append(f"Ignored invalid tag token: {s}")
            continue

        if sl.startswith("bucket:"):
            bucket = s.split(":", 1)[1].strip().lower()
            if bucket:
                out.bucket = bucket
            else:
                out.parse_warnings.append(f"Ignored invalid bucket token: {s}")
            continue

        if sl.startswith("phase:"):
            phase = s.split(":", 1)[1].strip()
            if phase:
                out.phase = phase.lower()
            else:
                out.parse_warnings.append(f"Ignored invalid phase token: {s}")
            continue

        if sl == "has:children":
            out.has_children = True
            continue
        if sl == "has:nochildren":
            out.has_children = False
            continue
        if sl in {"blocked:true", "blocked:yes", "is:blocked"}:
            out.blocked_only = True
            continue
        if sl in {"waiting:true", "waiting:yes", "is:waiting"}:
            out.waiting_only = True
            continue
        if sl in {"recurring:true", "recurring:yes", "is:recurring"}:
            out.recurring_only = True
            continue

        free_tokens.append(s)

    out.free_text = " ".join(free_tokens).strip().lower()
    return out
