from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from project_cockpit_ui import ProjectCockpitPanel, ProjectTimelineWidget


def test_timeline_drag_emits_reschedule_request(qapp):
    widget = ProjectTimelineWidget()
    widget.resize(920, 280)
    widget.set_rows(
        [
            {
                "kind": "task",
                "item_id": 42,
                "label": "Draft specification",
                "phase_name": "Planning",
                "start_date": "2026-03-08",
                "end_date": "2026-03-10",
                "baseline_date": None,
                "status": "Todo",
                "blocked": False,
                "progress_percent": 0,
            }
        ]
    )
    emitted: list[tuple[str, int, int]] = []
    widget.rescheduleRequested.connect(
        lambda kind, item_id, delta_days: emitted.append(
            (str(kind), int(item_id), int(delta_days))
        )
    )
    widget.show()
    widget.repaint()
    qapp.processEvents()

    assert widget._bar_bounds
    bar = widget._bar_bounds[0]["rect"]
    press = bar.center().toPoint()
    pixels_per_day = max(1, int(round(widget._timeline_width / widget._span_days)))
    release = QPoint(int(press.x() + (pixels_per_day * 2)), int(press.y()))

    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, press)
    QTest.mouseMove(widget, release)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, release)
    qapp.processEvents()

    assert emitted == [("task", 42, 2)]


def test_project_cockpit_has_compact_default_size_hints(qapp):
    panel = ProjectCockpitPanel()
    hint = panel.sizeHint()
    min_hint = panel.minimumSizeHint()

    assert hint.height() <= 700
    assert min_hint.height() <= 540
    assert panel.milestones_table.maximumHeight() <= 300
    assert panel.deliverables_table.maximumHeight() <= 300
    assert panel.register_table.maximumHeight() <= 300
