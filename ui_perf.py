from __future__ import annotations

import atexit
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter


def ui_perf_enabled() -> bool:
    raw = str(os.environ.get("GRIDORYN_PROFILE_UI", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass
class _UiPerfStat:
    count: int = 0
    total_ms: float = 0.0
    worst_ms: float = 0.0
    visible_count: int = 0
    hidden_count: int = 0

    def add(self, duration_ms: float, visible: bool | None):
        self.count += 1
        self.total_ms += float(duration_ms)
        self.worst_ms = max(self.worst_ms, float(duration_ms))
        if visible is True:
            self.visible_count += 1
        elif visible is False:
            self.hidden_count += 1

    @property
    def average_ms(self) -> float:
        if self.count <= 0:
            return 0.0
        return self.total_ms / float(self.count)


_LOCK = threading.Lock()
_STATS: dict[str, _UiPerfStat] = {}


@contextmanager
def measure_ui(name: str, *, visible: bool | None = None):
    if not ui_perf_enabled():
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (perf_counter() - started) * 1000.0
        key = str(name or "unnamed")
        with _LOCK:
            stat = _STATS.setdefault(key, _UiPerfStat())
            stat.add(elapsed_ms, visible)


def ui_perf_snapshot() -> dict[str, dict[str, float | int]]:
    with _LOCK:
        snapshot = {
            name: {
                "count": stat.count,
                "average_ms": round(stat.average_ms, 3),
                "worst_ms": round(stat.worst_ms, 3),
                "visible_count": stat.visible_count,
                "hidden_count": stat.hidden_count,
            }
            for name, stat in sorted(
                _STATS.items(),
                key=lambda item: (-item[1].total_ms, item[0]),
            )
        }
    return snapshot


def _dump_ui_perf():
    if not ui_perf_enabled():
        return
    snapshot = ui_perf_snapshot()
    if not snapshot:
        return
    print("=== Gridoryn UI profile summary ===")
    for name, stat in snapshot.items():
        print(
            f"{name}: count={stat['count']} avg_ms={stat['average_ms']} "
            f"worst_ms={stat['worst_ms']} visible={stat['visible_count']} "
            f"hidden={stat['hidden_count']}"
        )


atexit.register(_dump_ui_perf)
