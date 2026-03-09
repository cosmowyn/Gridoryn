from __future__ import annotations

from datetime import date
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontMetrics, QNativeGestureEvent, QPointingDevice, QWheelEvent

from gantt_ui import (
    CHART_LEFT_MARGIN,
    MAX_PIXELS_PER_DAY,
    MIN_PIXELS_PER_DAY,
    ProjectGanttView,
    TimelineHeaderWidget,
    _text_layout,
)
from platform_utils import is_macos
from project_cockpit_ui import ProjectCockpitPanel
from project_management import build_timeline_rows


def _sample_dashboard() -> dict:
    project = {
        "id": 1,
        "description": "Project Alpha",
        "progress_percent": 20,
        "due_date": "2026-03-20",
    }
    phases = [
        {"id": 10, "project_task_id": 1, "name": "Planning", "sort_order": 1},
        {"id": 20, "project_task_id": 1, "name": "Execution", "sort_order": 2},
    ]
    tasks = [
        project,
        {
            "id": 2,
            "description": "Draft specification",
            "parent_id": 1,
            "phase_id": 10,
            "start_date": "2026-03-08",
            "due_date": "2026-03-10",
            "status": "In Progress",
            "progress_percent": 40,
            "blocked_by_count": 0,
            "waiting_for": "",
            "sort_order": 1,
        },
        {
            "id": 3,
            "description": "Review draft",
            "parent_id": 2,
            "phase_id": 10,
            "start_date": "2026-03-10",
            "due_date": "2026-03-11",
            "status": "Todo",
            "progress_percent": 0,
            "blocked_by_count": 0,
            "waiting_for": "",
            "sort_order": 1,
        },
        {
            "id": 4,
            "description": "Publish release",
            "parent_id": 1,
            "phase_id": 20,
            "start_date": "2026-03-12",
            "due_date": "2026-03-18",
            "status": "Todo",
            "progress_percent": 0,
            "blocked_by_count": 1,
            "waiting_for": "",
            "sort_order": 2,
        },
    ]
    milestones = [
        {
            "id": 5,
            "project_task_id": 1,
            "title": "Specification approved",
            "phase_id": 10,
            "linked_task_id": 2,
            "start_date": "2026-03-10",
            "target_date": "2026-03-10",
            "baseline_target_date": "2026-03-09",
            "status": "planned",
            "progress_percent": 0,
            "is_blocked": True,
        }
    ]
    deliverables = [
        {
            "id": 6,
            "project_task_id": 1,
            "title": "Release package",
            "phase_id": 20,
            "linked_task_id": 4,
            "linked_milestone_id": 5,
            "due_date": "2026-03-18",
            "baseline_due_date": "2026-03-17",
            "status": "planned",
            "is_blocked": False,
        }
    ]
    dependencies = [
        {
            "id": 1,
            "predecessor_kind": "task",
            "predecessor_id": 2,
            "successor_kind": "milestone",
            "successor_id": 5,
            "dep_type": "finish_to_start",
            "is_soft": 0,
        },
        {
            "id": 2,
            "predecessor_kind": "milestone",
            "predecessor_id": 5,
            "successor_kind": "task",
            "successor_id": 4,
            "dep_type": "finish_to_start",
            "is_soft": 0,
        },
    ]
    summary = {
        "target_date": "2026-03-20",
        "baseline_target_date": "2026-03-18",
        "effective_health": "at_risk",
        "effective_health_label": "At risk",
        "inferred_health_reason": "Blocked execution and upcoming milestone.",
    }
    return {
        "project": project,
        "phases": phases,
        "tasks": tasks,
        "milestones": milestones,
        "deliverables": deliverables,
        "dependencies": dependencies,
        "summary": summary,
        "timeline_rows": build_timeline_rows(
            project,
            phases,
            tasks,
            milestones,
            deliverables,
            summary,
            dependencies,
        ),
    }


def test_gantt_view_builds_hierarchy_and_dependencies(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    assert widget.tree.topLevelItemCount() == 1
    project_item = widget.tree.topLevelItem(0)
    assert project_item.text(0) == "Project Alpha"
    assert project_item.childCount() == 2
    assert "task:2" in widget.bar_items
    assert "milestone:5" in widget.bar_items
    assert "deliverable:6" in widget.bar_items
    assert len(widget.connector_items) >= 2
    assert widget.range_start is not None
    assert widget.range_end is not None
    assert widget.range_start <= date.today() <= widget.range_end


def test_gantt_view_milestone_bounds_include_label_and_toolbar_controls_fit_text(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    milestone_item = widget.bar_items["milestone:5"]
    assert milestone_item.boundingRect().width() > milestone_item.base_rect().width()
    task_item = widget.bar_items["task:2"]
    assert task_item.boundingRect().width() > task_item.base_rect().width()

    for button in (
        widget.today_btn,
        widget.jump_selected_btn,
        widget.fit_project_btn,
        widget.fit_selection_btn,
        widget.expand_btn,
        widget.collapse_btn,
    ):
        metrics = QFontMetrics(button.font())
        expected = metrics.horizontalAdvance(button.text().replace("&", "")) + 20
        assert button.minimumWidth() >= expected

    assert widget.summary_label.minimumWidth() >= 260


def test_timeline_header_uses_separate_bands_and_keeps_today_badge_out_of_minor_row(qapp):
    header = TimelineHeaderWidget()
    header.resize(900, header.height())
    header.set_range(date(2026, 3, 1), date(2026, 3, 31), 18.0)
    qapp.processEvents()

    major_band = header._major_band_rect()
    minor_band = header._minor_band_rect()
    badge = header._today_badge_rect()

    assert header.minimumHeight() >= 58
    assert major_band.height() >= 22
    assert minor_band.height() > 0
    assert badge.bottom() <= major_band.bottom()
    assert badge.bottom() < minor_band.top() + 1


def test_timeline_header_uses_month_year_and_day_number_labels(qapp):
    header = TimelineHeaderWidget()

    assert header._major_label_for(date(2026, 2, 1)) == "February 2026"
    assert header._minor_label_for(date(2026, 2, 1)) == "1"
    assert header._minor_label_for(date(2026, 2, 28)) == "28"


def test_timeline_header_and_chart_share_the_same_left_margin(qapp):
    header = TimelineHeaderWidget()
    header.set_range(date(2026, 2, 1), date(2026, 2, 28), 12.0)

    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())

    assert header._scene_x_for(date(2026, 2, 1)) == int(CHART_LEFT_MARGIN)
    assert widget.range_start is not None
    assert widget.date_to_scene_x(widget.range_start) == CHART_LEFT_MARGIN


def test_timeline_text_layout_uses_full_text_or_dot_placeholder(qapp):
    font = qapp.font()
    fitted_font, _metrics, full_text = _text_layout(
        font,
        "March 2026",
        240.0,
        24.0,
        padding_x=8.0,
    )
    narrow_font, _narrow_metrics, dot_text = _text_layout(
        font,
        "Wednesday 18 March 2026",
        22.0,
        16.0,
        padding_x=4.0,
    )

    assert full_text == "March 2026"
    assert dot_text == "."
    assert fitted_font.pointSizeF() == narrow_font.pointSizeF()


def test_gantt_view_shows_visible_zoom_state_and_custom_scale(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    assert widget.scale_combo.currentData() == "week"
    assert widget.zoom_state_label.text().startswith("Zoom: Week")
    assert widget.zoom_panel.parentWidget() is not None
    assert widget.zoom_panel.parentWidget() is not widget.header
    assert widget.header._reserved_right == 0

    widget._set_zoom_pixels_per_day(17.0, mode="custom")
    qapp.processEvents()

    assert widget.pixels_per_day == 17.0
    assert widget.scale_combo.currentData() is None
    assert widget.zoom_state_label.text().startswith("Zoom: Custom")
    assert widget.header._pixels_per_day == widget.pixels_per_day


def test_gantt_view_zoom_bounds_disable_buttons(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    widget._set_zoom_pixels_per_day(0.5, mode="custom")
    qapp.processEvents()
    assert widget.pixels_per_day == MIN_PIXELS_PER_DAY
    assert widget.zoom_out_btn.isEnabled() is False
    assert widget.zoom_in_btn.isEnabled() is True

    widget._set_zoom_pixels_per_day(500.0, mode="custom")
    qapp.processEvents()
    assert widget.pixels_per_day == MAX_PIXELS_PER_DAY
    assert widget.zoom_out_btn.isEnabled() is True
    assert widget.zoom_in_btn.isEnabled() is False


def test_gantt_view_fit_modes_update_visible_zoom_state(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    widget.fit_project()
    qapp.processEvents()
    assert widget.zoom_state_label.text().startswith("Zoom: Fit project")
    assert widget.header._pixels_per_day == widget.pixels_per_day

    widget.select_item("task", 2)
    widget.fit_selection()
    qapp.processEvents()
    assert widget.zoom_state_label.text().startswith("Zoom: Fit selection")
    assert widget.header._pixels_per_day == widget.pixels_per_day


def test_gantt_view_modifier_wheel_zoom_uses_shared_zoom_state(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    before = float(widget.pixels_per_day)
    modifiers = (
        Qt.KeyboardModifier.MetaModifier
        if is_macos()
        else Qt.KeyboardModifier.ControlModifier
    )
    event = QWheelEvent(
        QPointF(180.0, 40.0),
        QPointF(180.0, 40.0),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    widget.view.wheelEvent(event)
    qapp.processEvents()

    assert event.isAccepted()
    assert widget.pixels_per_day > before
    assert widget.header._pixels_per_day == widget.pixels_per_day
    assert "Zoom:" in widget.zoom_state_label.text()


def test_gantt_view_native_pinch_zoom_uses_shared_zoom_state(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    before = float(widget.pixels_per_day)
    event = QNativeGestureEvent(
        Qt.NativeGestureType.ZoomNativeGesture,
        QPointingDevice.primaryPointingDevice(),
        2,
        QPointF(220.0, 50.0),
        QPointF(220.0, 50.0),
        QPointF(220.0, 50.0),
        0.2,
        QPointF(0.0, 0.0),
    )

    handled = widget.view.viewportEvent(event)
    qapp.processEvents()

    assert handled is True
    assert widget.pixels_per_day > before
    assert widget.header._pixels_per_day == widget.pixels_per_day


def test_gantt_view_release_path_survives_immediate_dashboard_rebuild(qapp):
    class _FakeEvent:
        def __init__(self):
            self.accepted = False

        def accept(self):
            self.accepted = True

    widget = ProjectGanttView()
    widget.resize(1100, 480)
    dashboard = _sample_dashboard()
    widget.set_dashboard(dashboard)
    widget.show()
    qapp.processEvents()

    item = widget.bar_items["task:2"]
    item._drag_mode = "move"
    item.preview_start = date(2026, 3, 9)
    item.preview_end = date(2026, 3, 11)

    widget.scheduleEditRequested.connect(
        lambda *_: widget.set_dashboard(_sample_dashboard())
    )

    event = _FakeEvent()
    item.mouseReleaseEvent(event)
    qapp.processEvents()

    assert event.accepted is True
    assert "task:2" in widget.bar_items


def test_gantt_view_preview_dates_coalesces_dependency_rebuilds(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    with patch.object(widget, "_rebuild_dependency_paths") as rebuild_mock:
        widget.preview_row_dates("task:2", date(2026, 3, 9), date(2026, 3, 11))
        widget.preview_row_dates("task:2", date(2026, 3, 10), date(2026, 3, 12))
        widget.preview_row_dates("task:2", date(2026, 3, 11), date(2026, 3, 13))
        assert rebuild_mock.call_count == 0
        qapp.processEvents()
        assert rebuild_mock.call_count == 1


def test_gantt_view_selection_updates_do_not_request_full_scene_redraw(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    with patch.object(widget.scene, "update", wraps=widget.scene.update) as update_mock:
        widget.select_item("task", 2)
        widget.select_item("task", 4)

    assert update_mock.call_count > 0
    assert all(call.args for call in update_mock.call_args_list)


def test_gantt_view_uses_bounding_rect_viewport_updates_for_line_stability(qapp):
    widget = ProjectGanttView()

    assert (
        widget.view.viewportUpdateMode()
        == widget.view.ViewportUpdateMode.BoundingRectViewportUpdate
    )
    assert widget.view.cacheMode() == widget.view.CacheModeFlag.CacheNone


def test_gantt_view_zoom_rebuild_invalidates_all_scene_layers(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    with patch.object(widget.scene, "invalidate", wraps=widget.scene.invalidate) as invalidate_mock:
        widget._set_zoom_pixels_per_day(18.0, mode="custom")
        qapp.processEvents()

    assert invalidate_mock.call_count > 0
    assert any(
        len(call.args) >= 2
        and call.args[1] == widget.scene.SceneLayer.AllLayers
        for call in invalidate_mock.call_args_list
    )


def test_gantt_view_scroll_coalesces_visible_region_repaint(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    with patch.object(widget, "_invalidate_scene_layers") as invalidate_mock:
        widget.handle_view_scrolled(42, 0)
        widget.handle_view_scrolled(18, 0)
        assert invalidate_mock.call_count == 0
        qapp.processEvents()

    assert invalidate_mock.call_count == 1
    assert invalidate_mock.call_args.args[0] == widget.scene.SceneLayer.AllLayers
    dirty_rect = invalidate_mock.call_args.args[1]
    assert dirty_rect.width() > 0
    assert dirty_rect.height() > 0


def test_gantt_view_commit_move_emits_schedule_edit(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    emitted: list[tuple[str, int, str | None, str | None]] = []
    widget.scheduleEditRequested.connect(
        lambda kind, item_id, start, end: emitted.append(
            (str(kind), int(item_id), start, end)
        )
    )

    widget.commit_row_dates(
        "task:2",
        date(2026, 3, 10),
        date(2026, 3, 12),
    )

    assert emitted == [("task", 2, "2026-03-10", "2026-03-12")]


def test_gantt_view_commit_resize_start_emits_schedule_edit(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.select_item("task", 2)
    widget.show()
    qapp.processEvents()

    emitted: list[tuple[str, int, str | None, str | None]] = []
    widget.scheduleEditRequested.connect(
        lambda kind, item_id, start, end: emitted.append(
            (str(kind), int(item_id), start, end)
        )
    )

    widget.commit_row_dates(
        "task:2",
        date(2026, 3, 9),
        date(2026, 3, 10),
    )

    assert emitted == [("task", 2, "2026-03-09", "2026-03-10")]


def test_gantt_view_selects_active_task(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.set_active_task(4)
    qapp.processEvents()

    assert widget.selected_uid == "task:4"
    assert widget.tree.currentItem() is not None
    assert widget.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == "task:4"


def test_gantt_view_selects_milestone_and_deliverable_rows(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())

    widget.select_item("milestone", 5)
    assert widget.selected_uid == "milestone:5"

    widget.select_item("deliverable", 6)
    assert widget.selected_uid == "deliverable:6"


def test_gantt_view_task_creation_emits_contextual_payload(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())

    emitted: list[dict] = []
    widget.taskCreateRequested.connect(lambda payload: emitted.append(dict(payload)))

    widget.create_task_at("phase:10", date(2026, 3, 16))

    assert emitted == [
        {
            "project_task_id": 1,
            "parent_id": 1,
            "phase_id": 10,
            "start_date": "2026-03-16",
            "due_date": "2026-03-16",
            "description": "New task",
        }
    ]


def test_gantt_view_child_task_creation_emits_child_parent(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())

    emitted: list[dict] = []
    widget.taskCreateRequested.connect(lambda payload: emitted.append(dict(payload)))

    widget.create_task_at("task:2", date(2026, 3, 12), child_mode=True)

    assert emitted == [
        {
            "project_task_id": 1,
            "parent_id": 2,
            "phase_id": 10,
            "start_date": "2026-03-12",
            "due_date": "2026-03-12",
            "description": "New task",
        }
    ]


def test_gantt_view_milestone_and_deliverable_creation_emit_payloads(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())

    milestone_payloads: list[dict] = []
    deliverable_payloads: list[dict] = []
    widget.milestoneCreateRequested.connect(
        lambda payload: milestone_payloads.append(dict(payload))
    )
    widget.deliverableCreateRequested.connect(
        lambda payload: deliverable_payloads.append(dict(payload))
    )

    widget.create_milestone_at("phase:20", date(2026, 3, 17))
    widget.create_deliverable_at("phase:20", date(2026, 3, 18))

    assert milestone_payloads[0]["project_task_id"] == 1
    assert milestone_payloads[0]["phase_id"] == 20
    assert milestone_payloads[0]["target_date"] == "2026-03-17"
    assert deliverable_payloads[0]["project_task_id"] == 1
    assert deliverable_payloads[0]["phase_id"] == 20
    assert deliverable_payloads[0]["due_date"] == "2026-03-18"


def test_gantt_view_keyboard_nudge_emits_schedule_edit(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.select_item("task", 4)
    qapp.processEvents()

    emitted: list[tuple[str, int, str | None, str | None]] = []
    widget.scheduleEditRequested.connect(
        lambda kind, item_id, start, end: emitted.append(
            (str(kind), int(item_id), start, end)
        )
    )

    widget.nudge_selection("move", 1)

    assert emitted == [("task", 4, "2026-03-13", "2026-03-19")]


def test_gantt_view_resize_end_emits_schedule_edit(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.select_item("task", 4)

    emitted: list[tuple[str, int, str | None, str | None]] = []
    widget.scheduleEditRequested.connect(
        lambda kind, item_id, start, end: emitted.append(
            (str(kind), int(item_id), start, end)
        )
    )

    widget.nudge_selection("resize_end", 2)

    assert emitted == [("task", 4, "2026-03-12", "2026-03-20")]


def test_gantt_view_milestone_move_emits_schedule_edit(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.select_item("milestone", 5)

    emitted: list[tuple[str, int, str | None, str | None]] = []
    widget.scheduleEditRequested.connect(
        lambda kind, item_id, start, end: emitted.append(
            (str(kind), int(item_id), start, end)
        )
    )

    widget.nudge_selection("move", 1)

    assert emitted == [("milestone", 5, "2026-03-11", "2026-03-11")]


def test_project_cockpit_syncs_table_selection_into_timeline(qapp):
    panel = ProjectCockpitPanel()
    dashboard = _sample_dashboard()
    panel.set_dashboard(dashboard)
    panel.show()
    qapp.processEvents()

    panel.milestones_table.selectRow(0)
    qapp.processEvents()
    assert panel.timeline_widget.selected_uid == "milestone:5"

    panel.deliverables_table.selectRow(0)
    qapp.processEvents()
    assert panel.timeline_widget.selected_uid == "deliverable:6"


def test_project_cockpit_syncs_timeline_selection_back_into_tables(qapp):
    panel = ProjectCockpitPanel()
    dashboard = _sample_dashboard()
    panel.set_dashboard(dashboard)
    panel.show()
    qapp.processEvents()

    panel._on_timeline_row_selected("milestone", 5)
    qapp.processEvents()
    assert panel.milestones_table.currentRow() == 0

    panel._on_timeline_row_selected("deliverable", 6)
    qapp.processEvents()
    assert panel.deliverables_table.currentRow() == 0


def test_project_cockpit_re_emits_timeline_task_creation(qapp):
    panel = ProjectCockpitPanel()
    dashboard = _sample_dashboard()
    panel.set_dashboard(dashboard)

    emitted: list[dict] = []
    panel.addTaskRequested.connect(lambda payload: emitted.append(dict(payload)))

    panel.timeline_widget.create_task_at("phase:10", date(2026, 3, 16))

    assert emitted[0]["project_task_id"] == 1
    assert emitted[0]["parent_id"] == 1
    assert emitted[0]["phase_id"] == 10
    assert emitted[0]["description"] == "New task"


def test_project_cockpit_has_compact_default_size_hints(qapp):
    panel = ProjectCockpitPanel()
    hint = panel.sizeHint()
    min_hint = panel.minimumSizeHint()

    assert hint.height() <= 700
    assert min_hint.height() <= 540
    assert panel.milestones_table.maximumHeight() <= 300
    assert panel.deliverables_table.maximumHeight() <= 300
    assert panel.register_table.maximumHeight() <= 300


def test_project_cockpit_status_labels_wrap_inside_summary_form(qapp):
    panel = ProjectCockpitPanel()

    assert (
        panel.status_summary_layout.rowWrapPolicy()
        == panel.status_summary_layout.RowWrapPolicy.WrapLongRows
    )
    for label in (
        panel.lbl_health,
        panel.lbl_next_milestone,
        panel.lbl_blockers,
        panel.lbl_due_soon,
        panel.lbl_effort,
        panel.lbl_variance,
    ):
        assert label.wordWrap() is True
        assert label.minimumWidth() == 0
        assert (
            label.alignment()
            & (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        ) == (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
