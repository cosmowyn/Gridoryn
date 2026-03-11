from __future__ import annotations

from datetime import date
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QNativeGestureEvent,
    QPainter,
    QPointingDevice,
    QWheelEvent,
)

from gantt_ui import (
    CHART_LEFT_MARGIN,
    MAX_PIXELS_PER_DAY,
    MIN_PIXELS_PER_DAY,
    ProjectGanttView,
    ROW_HEIGHT,
    TimelineHeaderWidget,
    _text_layout,
)
from platform_utils import is_macos
from project_cockpit_ui import ProjectCockpitPanel
from project_management import build_timeline_rows
from theme import ThemeManager


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


def _dashboard_with_reorderable_phase_siblings() -> dict:
    dashboard = _sample_dashboard()
    extra_task = {
        "id": 7,
        "description": "Validate rollout copy",
        "parent_id": 1,
        "phase_id": 10,
        "start_date": "2026-03-11",
        "due_date": "2026-03-14",
        "status": "Todo",
        "progress_percent": 0,
        "blocked_by_count": 0,
        "waiting_for": "",
        "sort_order": 3,
    }
    tasks = list(dashboard["tasks"]) + [extra_task]
    dashboard["tasks"] = tasks
    dashboard["timeline_rows"] = build_timeline_rows(
        dashboard["project"],
        dashboard["phases"],
        tasks,
        dashboard["milestones"],
        dashboard["deliverables"],
        dashboard["summary"],
        dashboard["dependencies"],
    )
    return dashboard


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


def test_gantt_view_distinguishes_summary_bars_from_normal_tasks(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    summary_row = widget.row_lookup["project:1"]
    task_row = widget.row_lookup["task:4"]
    summary_item = widget.bar_items["project:1"]
    task_item = widget.bar_items["task:4"]

    assert str(summary_row.get("render_style")) == "summary"
    assert str(task_row.get("render_style")) == "task"
    assert widget.bar_color_for_row(summary_row) != widget.bar_color_for_row(task_row)
    assert summary_item.base_rect().height() > task_item.base_rect().height()
    assert summary_item.boundingRect().width() <= summary_item.base_rect().width() + 20.0


def test_gantt_large_bars_do_not_expand_for_text_labels(qapp):
    widget = ProjectGanttView()
    widget.resize(820, 420)
    widget.set_dashboard(_sample_dashboard())
    widget._set_zoom_pixels_per_day(MIN_PIXELS_PER_DAY, mode="custom")
    widget.show()
    qapp.processEvents()

    summary_item = widget.bar_items["task:2"]
    task_item = widget.bar_items["task:4"]
    deliverable_item = widget.bar_items["deliverable:6"]

    assert summary_item.boundingRect().width() <= summary_item.base_rect().width() + 20.0
    assert task_item.boundingRect().width() <= task_item.base_rect().width() + 20.0
    assert (
        deliverable_item.boundingRect().width()
        <= deliverable_item.base_rect().width() + 20.0
    )


def test_gantt_view_uses_local_item_color_override_before_defaults(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    dashboard = _sample_dashboard()
    dashboard["timeline_rows"] = [dict(row) for row in dashboard["timeline_rows"]]
    widget.set_dashboard(dashboard)
    widget.show()
    qapp.processEvents()

    task_row = widget.row_lookup["task:3"]
    summary_row = widget.row_lookup["project:1"]
    phase_row = widget.row_lookup["phase:10"]
    default_task_color = widget.bar_color_for_row(task_row).name().lower()
    default_summary_color = widget.bar_color_for_row(summary_row).name().lower()
    default_phase_color = widget.bar_color_for_row(phase_row).name().lower()

    task_row["gantt_color_hex"] = "#334455"
    summary_row["gantt_color_hex"] = "#eeddee"
    phase_row["gantt_color_hex"] = "#552277"

    assert widget.bar_color_for_row(task_row).name().lower() == "#334455"
    assert widget.bar_color_for_row(summary_row).name().lower() == "#eeddee"
    assert widget.bar_color_for_row(phase_row).name().lower() == "#552277"
    assert default_task_color != "#334455"
    assert default_summary_color != "#eeddee"
    assert default_phase_color != "#552277"


def test_gantt_view_uses_persisted_theme_colors_for_task_and_summary_bars(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    original_task_color = widget.bar_color_for_row(widget.row_lookup["task:3"]).name().lower()
    original_summary_color = widget.bar_color_for_row(widget.row_lookup["task:2"]).name().lower()

    settings = QSettings()
    tm = ThemeManager(settings)
    theme_name = tm.current_theme_name()
    theme = tm.load_theme(theme_name)
    theme["colors"]["gantt_task_bg"] = "#1122CC"
    theme["colors"]["gantt_task_text"] = "#F8F9FA"
    theme["colors"]["gantt_summary_bg"] = "#101820"
    theme["colors"]["gantt_summary_text"] = "#F4EBD0"
    tm.save_theme(theme_name, theme)
    tm.apply_to_app(qapp)

    widget.reload_theme_colors()
    qapp.processEvents()

    summary_row = widget.row_lookup["task:2"]
    task_row = widget.row_lookup["task:3"]

    assert original_task_color != "#1122cc"
    assert original_summary_color != "#101820"
    assert widget.bar_color_for_row(task_row).name().lower() == "#1122cc"
    assert widget.bar_text_color_for_row(task_row).name().lower() == "#f8f9fa"
    assert widget.bar_color_for_row(summary_row).name().lower() == "#101820"
    assert widget.bar_text_color_for_row(summary_row).name().lower() == "#f4ebd0"


def test_gantt_view_milestone_bounds_include_label_and_toolbar_controls_fit_text(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    milestone_item = widget.bar_items["milestone:5"]
    assert milestone_item.boundingRect().width() > milestone_item.base_rect().width()

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


def test_gantt_view_milestone_label_chip_paints_over_baseline_marker(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    row = widget.row_lookup["milestone:5"]
    row["label"] = " "
    item = widget.bar_items["milestone:5"]
    label_rect = item._milestone_label_rect()

    chosen_date = None
    for day in range(0, 15):
        candidate = date(2026, 3, 10 + day)
        baseline_x = widget.date_to_scene_x(candidate)
        if label_rect.left() + 6.0 <= baseline_x <= label_rect.right() - 6.0:
            chosen_date = candidate
            break
    assert chosen_date is not None
    row["baseline_date"] = chosen_date.isoformat()

    bounds = item.boundingRect()
    image = QImage(
        int(bounds.width()) + 8,
        int(bounds.height()) + 8,
        QImage.Format.Format_ARGB32,
    )
    fill = widget.palette().base().color()
    image.fill(fill)
    painter = QPainter(image)
    painter.translate(-bounds.left() + 4.0, -bounds.top() + 4.0)
    item.paint(painter, None)
    painter.end()

    sample_x = int(round(widget.date_to_scene_x(chosen_date) - bounds.left() + 4.0))
    sample_y = int(round(label_rect.center().y() - bounds.top() + 4.0))
    sampled = image.pixelColor(sample_x, sample_y)
    assert sampled != QColor("#111827")


def test_gantt_context_menu_emits_item_color_actions(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    widget.row_lookup["task:2"]["gantt_color_hex"] = "#445566"
    task_item = widget.bar_items["task:2"]
    task_pos = widget.view.mapFromScene(task_item.base_rect().center())
    menu = widget.build_context_menu(task_pos)
    labels = [action.text() for action in menu.actions()]
    assert "Set item color…" in labels
    assert "Reset item color to default" in labels

    changed: list[tuple[str, int, object]] = []
    reset: list[tuple[str, int]] = []
    widget.itemColorChangeRequested.connect(
        lambda kind, item_id, color: changed.append((str(kind), int(item_id), color))
    )
    widget.itemColorResetRequested.connect(
        lambda kind, item_id: reset.append((str(kind), int(item_id)))
    )

    with patch("gantt_ui.QColorDialog.getColor", return_value=widget.bar_color_for_row(widget.row_lookup["task:2"]).lighter(130)):
        next(action for action in menu.actions() if action.text() == "Set item color…").trigger()
    next(action for action in menu.actions() if action.text() == "Reset item color to default").trigger()

    assert changed and changed[0][0:2] == ("task", 2)
    assert reset == [("task", 2)]


def test_gantt_context_menu_supports_phase_color_actions(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    widget.row_lookup["phase:10"]["gantt_color_hex"] = "#553377"
    phase_item = widget.bar_items["phase:10"]
    phase_pos = widget.view.mapFromScene(phase_item.base_rect().center())
    menu = widget.build_context_menu(phase_pos)
    labels = [action.text() for action in menu.actions()]

    assert "Set item color…" in labels
    assert "Reset item color to default" in labels

    changed: list[tuple[str, int, object]] = []
    reset: list[tuple[str, int]] = []
    widget.itemColorChangeRequested.connect(
        lambda kind, item_id, color: changed.append((str(kind), int(item_id), color))
    )
    widget.itemColorResetRequested.connect(
        lambda kind, item_id: reset.append((str(kind), int(item_id)))
    )

    with patch("gantt_ui.QColorDialog.getColor", return_value=widget.bar_color_for_row(widget.row_lookup["phase:10"]).lighter(120)):
        next(action for action in menu.actions() if action.text() == "Set item color…").trigger()
    next(action for action in menu.actions() if action.text() == "Reset item color to default").trigger()

    assert changed and changed[0][0:2] == ("phase", 10)
    assert reset == [("phase", 10)]


def test_gantt_context_menu_supports_unassigned_phase_color_actions(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    dashboard = _sample_dashboard()
    dashboard["summary"]["unassigned_phase_gantt_color_hex"] = "#224466"
    dashboard["tasks"].append(
        {
            "id": 7,
            "description": "Loose task",
            "parent_id": 1,
            "phase_id": None,
            "start_date": "2026-03-11",
            "due_date": "2026-03-13",
            "status": "Todo",
            "progress_percent": 0,
            "blocked_by_count": 0,
            "waiting_for": "",
            "sort_order": 3,
        }
    )
    dashboard["timeline_rows"] = build_timeline_rows(
        dashboard["project"],
        dashboard["phases"],
        dashboard["tasks"],
        dashboard["milestones"],
        dashboard["deliverables"],
        dashboard["summary"],
        dashboard["dependencies"],
    )
    widget.set_dashboard(dashboard)
    widget.show()
    qapp.processEvents()

    unassigned_row = widget.row_lookup["phase:unassigned"]
    unassigned_item = widget.bar_items["phase:unassigned"]
    unassigned_pos = widget.view.mapFromScene(unassigned_item.base_rect().center())
    menu = widget.build_context_menu(unassigned_pos)
    labels = [action.text() for action in menu.actions()]

    assert "Set item color…" in labels
    assert "Reset item color to default" in labels

    changed: list[tuple[str, int, object]] = []
    reset: list[tuple[str, int]] = []
    widget.itemColorChangeRequested.connect(
        lambda kind, item_id, color: changed.append((str(kind), int(item_id), color))
    )
    widget.itemColorResetRequested.connect(
        lambda kind, item_id: reset.append((str(kind), int(item_id)))
    )

    with patch(
        "gantt_ui.QColorDialog.getColor",
        return_value=widget.bar_color_for_row(unassigned_row).lighter(120),
    ):
        next(action for action in menu.actions() if action.text() == "Set item color…").trigger()
    next(action for action in menu.actions() if action.text() == "Reset item color to default").trigger()

    assert changed and changed[0][0:2] == ("phase_unassigned", 1)
    assert reset == [("phase_unassigned", 1)]


def test_gantt_context_menu_on_project_baseline_marker_uses_project_row(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    project_row = widget.row_lookup["project:1"]
    project_item = widget.bar_items["project:1"]
    marker_rect = project_item._baseline_marker_rect()
    assert not marker_rect.isEmpty()
    assert marker_rect.center().x() < project_item.base_rect().right()

    marker_pos = widget.view.mapFromScene(marker_rect.center())
    menu = widget.build_context_menu(marker_pos)
    labels = [action.text() for action in menu.actions()]

    assert "Set item color…" in labels

    changed: list[tuple[str, int, object]] = []
    widget.itemColorChangeRequested.connect(
        lambda kind, item_id, color: changed.append((str(kind), int(item_id), color))
    )

    with patch(
        "gantt_ui.QColorDialog.getColor",
        return_value=widget.bar_color_for_row(project_row).lighter(120),
    ):
        next(action for action in menu.actions() if action.text() == "Set item color…").trigger()

    assert changed and changed[0][0:2] == ("project", 1)


def test_baseline_marker_color_follows_row_override(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())
    widget.show()
    qapp.processEvents()

    milestone_row = widget.row_lookup["milestone:5"]
    project_row = widget.row_lookup["project:1"]

    default_milestone_marker = (
        widget.bar_items["milestone:5"]._baseline_marker_color().name().lower()
    )
    default_project_marker = (
        widget.bar_items["project:1"]._baseline_marker_color().name().lower()
    )

    milestone_row["gantt_color_hex"] = "#118833"
    project_row["gantt_color_hex"] = "#663399"

    milestone_override = QColor("#118833")
    milestone_expected = (
        milestone_override.lighter(130)
        if milestone_override.lightness() < 110
        else milestone_override.darker(135)
    )
    project_override = QColor("#663399")
    project_expected = (
        project_override.lighter(130)
        if project_override.lightness() < 110
        else project_override.darker(135)
    )

    assert (
        widget.bar_items["milestone:5"]._baseline_marker_color().name().lower()
        == milestone_expected.name().lower()
    )
    assert (
        widget.bar_items["project:1"]._baseline_marker_color().name().lower()
        == project_expected.name().lower()
    )
    assert default_milestone_marker != milestone_expected.name().lower()
    assert default_project_marker != project_expected.name().lower()


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


def test_gantt_view_delete_requests_emit_for_task_and_project_rows(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_sample_dashboard())

    archived: list[int] = []
    deleted: list[int] = []
    widget.archiveTaskRequested.connect(archived.append)
    widget.deleteTaskRequested.connect(deleted.append)

    widget.select_item("task", 2)
    assert widget.request_delete_selected(permanent=False) is True
    assert widget.request_delete_selected(permanent=True) is True

    widget.select_item("project", 1)
    assert widget.request_delete_selected(permanent=False) is True

    widget.select_item("milestone", 5)
    assert widget.request_delete_selected(permanent=False) is False

    assert archived == [2, 1]
    assert deleted == [2]


def test_gantt_view_vertical_reorder_emits_task_move_request(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_dashboard_with_reorderable_phase_siblings())
    widget.show()
    qapp.processEvents()

    emitted: list[tuple[int, object, int]] = []
    widget.taskMoveRequested.connect(
        lambda task_id, parent_id, row: emitted.append(
            (int(task_id), parent_id, int(row))
        )
    )

    row_index = widget.row_index_for_uid("task:2")
    assert row_index >= 0
    widget.preview_row_reorder("task:7", QPointF(0.0, float(row_index * ROW_HEIGHT) + 1.0))
    assert widget.reorder_preview_y() is not None

    widget.finalize_row_reorder("task:7", QPointF(0.0, float(row_index * ROW_HEIGHT) + 1.0))

    assert emitted == [(7, 1, 0)]
    assert widget.reorder_preview_y() is None


def test_gantt_tree_drop_uses_same_task_move_path(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_dashboard_with_reorderable_phase_siblings())
    widget.show()
    qapp.processEvents()

    emitted: list[tuple[int, object, int]] = []
    widget.taskMoveRequested.connect(
        lambda task_id, parent_id, row: emitted.append(
            (int(task_id), parent_id, int(row))
        )
    )

    widget._handle_tree_row_drop("task:7", "task:2", False)

    assert emitted == [(7, 1, 0)]


def test_gantt_tree_context_menu_matches_chart_move_actions(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_dashboard_with_reorderable_phase_siblings())
    widget.show()
    qapp.processEvents()

    row = widget.row_lookup["task:7"]
    chart_actions = [
        action.text() for action in widget._build_context_menu_for_row(
            row,
            date(2026, 3, 11),
        ).actions()
    ]
    item = widget.item_lookup["task:7"]
    rect = widget.tree.visualItemRect(item)
    tree_actions = [
        action.text()
        for action in widget.build_tree_context_menu(rect.center()).actions()
    ]

    assert "Move up among siblings" in chart_actions
    assert "Move down among siblings" in chart_actions
    assert "Move subtree to previous parent" in chart_actions
    assert "Move subtree to next parent" in chart_actions
    assert "Make subtree independent" in chart_actions
    assert "Move up among siblings" in tree_actions
    assert "Move down among siblings" in tree_actions
    assert "Move subtree to previous parent" in tree_actions
    assert "Move subtree to next parent" in tree_actions
    assert "Make subtree independent" in tree_actions


def test_gantt_chart_and_tree_context_menus_emit_same_parent_context_actions(qapp):
    widget = ProjectGanttView()
    widget.resize(1100, 480)
    widget.set_dashboard(_dashboard_with_reorderable_phase_siblings())
    widget.show()
    qapp.processEvents()

    previous_parent_emits: list[int] = []
    widget.taskMoveToPreviousParentRequested.connect(previous_parent_emits.append)

    row = widget.row_lookup["task:7"]
    chart_menu = widget._build_context_menu_for_row(row, date(2026, 3, 11))
    chart_prev = next(
        action
        for action in chart_menu.actions()
        if action.text() == "Move subtree to previous parent"
    )
    assert chart_prev.isEnabled() is True
    chart_prev.trigger()

    item = widget.item_lookup["task:7"]
    rect = widget.tree.visualItemRect(item)
    tree_menu = widget.build_tree_context_menu(rect.center())
    tree_prev = next(
        action
        for action in tree_menu.actions()
        if action.text() == "Move subtree to previous parent"
    )
    assert tree_prev.isEnabled() is True
    tree_prev.trigger()

    assert previous_parent_emits == [7, 7]


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


def test_project_cockpit_re_emits_timeline_task_archive_and_delete(qapp):
    panel = ProjectCockpitPanel()
    dashboard = _sample_dashboard()
    panel.set_dashboard(dashboard)

    archived: list[int] = []
    deleted: list[int] = []
    panel.archiveTaskRequested.connect(archived.append)
    panel.deleteTaskRequested.connect(deleted.append)

    panel.timeline_widget.select_item("task", 2)
    panel._on_timeline_row_selected("task", 2)
    panel.archive_timeline_task_btn.click()
    panel.delete_timeline_task_btn.click()

    assert archived == [2]
    assert deleted == [2]


def test_project_cockpit_project_actions_emit_current_project_id(qapp):
    panel = ProjectCockpitPanel()
    panel.set_dashboard(_sample_dashboard())

    archived: list[int] = []
    deleted: list[int] = []
    panel.archiveTaskRequested.connect(archived.append)
    panel.deleteTaskRequested.connect(deleted.append)

    panel.archive_project_btn.click()
    panel.delete_project_btn.click()

    assert archived == [1]
    assert deleted == [1]


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


def test_project_cockpit_defers_timeline_rebuild_until_timeline_tab_is_visible(qapp):
    panel = ProjectCockpitPanel()
    panel.tabs.setCurrentIndex(0)

    panel.set_dashboard(_sample_dashboard())

    assert panel.timeline_widget.bar_items == {}

    panel.tabs.setCurrentWidget(panel.timeline_tab_page)
    qapp.processEvents()

    assert "task:2" in panel.timeline_widget.bar_items


def test_project_cockpit_skips_identical_timeline_rebuilds(qapp):
    panel = ProjectCockpitPanel()
    panel.tabs.setCurrentWidget(panel.timeline_tab_page)
    panel.set_dashboard(_sample_dashboard())
    qapp.processEvents()

    with patch.object(panel.timeline_widget, "set_dashboard") as set_dashboard:
        panel.set_dashboard(_sample_dashboard())

    set_dashboard.assert_not_called()
