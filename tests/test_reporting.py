from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QSettings

import main as main_module
from main import MainWindow
from reporting import (
    TimelinePdfExportOptions,
    build_timeline_pdf_payload,
    build_task_list_report_html,
    create_custom_pdf_writer,
    _timeline_page_metrics,
    render_timeline_to_pdf,
)
from workspace_profiles import WorkspaceProfileManager


def _build_window(tmp_path, qapp, monkeypatch):
    QSettings().setValue("ui/onboarding_completed", True)
    monkeypatch.setattr(
        main_module.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: False),
    )
    monkeypatch.setattr(
        MainWindow,
        "_install_optional_global_capture_hotkey",
        lambda self: None,
    )
    manager = WorkspaceProfileManager(base_dir=str(tmp_path / "workspace-data"))
    workspace = manager.create_workspace(
        "Reporting Test",
        db_path=str(tmp_path / "reporting.sqlite3"),
        inherit_current_state=False,
    )
    manager.set_current_workspace(str(workspace["id"]))
    window = MainWindow(manager, str(workspace["id"]))
    window.show()
    qapp.processEvents()
    return window


def test_task_list_report_uses_current_proxy_context(tmp_path, qapp, monkeypatch):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Alpha current task", priority=1, due_date="2026-03-20")
        assert window.model.add_task_with_values("Beta hidden task", priority=3, due_date="2026-03-22")
        qapp.processEvents()

        window.search.setText("Alpha")
        qapp.processEvents()

        report = window._build_current_task_list_report()

        assert len(report.rows) == 1
        assert report.rows[0].task.strip() == "Alpha current task"
        assert report.rows[0].priority == "1"
        assert any("Search: Alpha" in line for line in report.subtitle_lines)
    finally:
        window.close()
        qapp.processEvents()


def test_hierarchical_task_list_report_preserves_visible_tree_structure(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        folder_id = window.model.create_category_folder("Operations")
        assert window.model.add_task_with_values(
            "Renew contract",
            category_folder_id=folder_id,
        )
        parent_id = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Collect quotes", parent_id=parent_id)
        child_id = int(window.model.last_added_task_id())
        qapp.processEvents()

        folder_node = window.model.folder_node_for_id(folder_id)
        folder_src = window.model._index_for_node(folder_node, 0)
        folder_proxy = window.proxy.mapFromSource(folder_src)
        parent_src = window.model._index_for_node(window.model.node_for_id(parent_id), 0)
        parent_proxy = window.proxy.mapFromSource(parent_src)
        window.view.expand(folder_proxy)
        window.view.expand(parent_proxy)
        qapp.processEvents()

        report = window._build_current_hierarchical_task_list_report()
        labels = [row.task for row in report.rows]

        assert "Operations" in labels
        assert "Renew contract" in labels
        assert "Collect quotes" in labels

        folder_row = next(row for row in report.rows if row.task == "Operations")
        parent_row = next(row for row in report.rows if row.task == "Renew contract")
        child_row = next(row for row in report.rows if row.task == "Collect quotes")

        assert folder_row.row_kind == "folder"
        assert folder_row.depth == 0
        assert parent_row.depth == 1
        assert child_row.depth == 2

        html = build_task_list_report_html(report)
        assert "folder-row" in html
    finally:
        window.close()
        qapp.processEvents()


def test_selected_scope_task_report_for_category_includes_folder_subtree(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        root_folder_id = window.model.create_category_folder("Operations")
        sub_folder_id = window.model.create_category_folder(
            "Internal",
            parent_folder_id=root_folder_id,
        )
        assert window.model.add_task_with_values(
            "Ops checklist",
            category_folder_id=root_folder_id,
        )
        assert window.model.add_task_with_values(
            "Internal rollout",
            category_folder_id=sub_folder_id,
        )
        assert window.model.add_task_with_values("Loose task")
        qapp.processEvents()

        folder_node = window.model.folder_node_for_id(root_folder_id)
        src_index = window.model._index_for_node(folder_node, 0)
        proxy_index = window.proxy.mapFromSource(src_index)
        window.view.setCurrentIndex(proxy_index)
        qapp.processEvents()

        report = window._build_selected_scope_task_list_report()
        assert report is not None
        labels = [row.task for row in report.rows]
        assert labels[0] == "Operations"
        assert "Internal" in labels
        assert "Ops checklist" in labels
        assert "Internal rollout" in labels
        assert "Loose task" not in labels
    finally:
        window.close()
        qapp.processEvents()


def test_selected_scope_task_report_for_parent_includes_siblings_and_children(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Parent A")
        parent_a = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Child A1", parent_id=parent_a)
        assert window.model.add_task_with_values("Parent B")
        parent_b = int(window.model.last_added_task_id())
        qapp.processEvents()

        window._focus_task_by_id(parent_a)
        qapp.processEvents()

        report = window._build_selected_scope_task_list_report()
        assert report is not None
        labels = [row.task for row in report.rows]
        assert "Parent A" in labels
        assert "Child A1" in labels
        assert "Parent B" in labels
        assert "Scope: Selected parent task with sibling context" in report.subtitle_lines
    finally:
        window.close()
        qapp.processEvents()


def test_selected_scope_task_report_for_leaf_includes_only_selected_task(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Parent A")
        parent_a = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Leaf task", parent_id=parent_a)
        leaf_id = int(window.model.last_added_task_id())
        assert window.model.add_task_with_values("Sibling leaf", parent_id=parent_a)
        qapp.processEvents()

        window._focus_task_by_id(leaf_id)
        qapp.processEvents()

        report = window._build_selected_scope_task_list_report()
        assert report is not None
        labels = [row.task for row in report.rows]
        assert labels == ["Leaf task"]
        assert report.subtitle_lines == ["Scope: Selected task only"]
    finally:
        window.close()
        qapp.processEvents()


def test_project_summary_report_uses_current_dashboard_data(tmp_path, qapp, monkeypatch):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Launch customer portal")
        project_id = int(window.model.last_added_task_id())
        window.model.save_project_profile(
            project_id,
            {
                "objective": "Launch the first customer-facing portal release.",
                "owner": "Operations",
                "category": "Delivery",
                "target_date": "2026-04-15",
            },
        )
        phase_id = int(window.model.add_project_phase(project_id, "Build"))
        window.model.upsert_milestone(
            {
                "project_task_id": project_id,
                "title": "Stakeholder sign-off",
                "phase_id": phase_id,
                "target_date": "2026-04-10",
                "status": "planned",
            }
        )
        qapp.processEvents()

        dashboard = window.model.fetch_project_dashboard(project_id)
        report = window._build_project_summary_report(dashboard)
        facts = dict(report.facts)

        assert report.title == "Project summary: Launch customer portal"
        assert facts["Owner"] == "Operations"
        assert facts["Category"] == "Delivery"
        assert facts["Target date"] == "2026-04-15"
        assert "Stakeholder sign-off" in facts["Next milestone"]
    finally:
        window.close()
        qapp.processEvents()


def test_timeline_export_path_writes_pdf(tmp_path, qapp, monkeypatch):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Factory refit")
        project_id = int(window.model.last_added_task_id())
        phase_id = int(window.model.add_project_phase(project_id, "Field work"))
        assert window.model.add_task_with_values(
            "Install fixtures",
            parent_id=project_id,
            due_date="2026-03-24",
        )
        task_id = int(window.model.last_added_task_id())
        window.model.set_task_start_date(task_id, "2026-03-20")
        window.model.set_task_phase(task_id, phase_id)
        qapp.processEvents()

        window._focus_task_by_id(project_id)
        window._refresh_project_panel()
        qapp.processEvents()

        dashboard = window.model.fetch_project_dashboard(project_id)
        export_view = window._create_timeline_export_view(
            dashboard,
            TimelinePdfExportOptions(
                file_path=str(tmp_path / "timeline.pdf"),
                orientation="landscape",
                scope="full",
            ),
        )
        try:
            payload = build_timeline_pdf_payload(
                export_view,
                title="Timeline: Factory refit",
                subtitle_lines=["Range: 2026-03-20 -> 2026-03-24"],
                footer_lines=["Exported: test"],
                options=TimelinePdfExportOptions(
                    file_path=str(tmp_path / "timeline.pdf"),
                    orientation="landscape",
                    scope="full",
                ),
            )
            out_path = render_timeline_to_pdf(payload)
        finally:
            export_view.deleteLater()
        pdf_path = Path(out_path)
        assert pdf_path.exists()
        assert pdf_path.read_bytes().startswith(b"%PDF")
    finally:
        window.close()
        qapp.processEvents()


def test_project_cockpit_export_buttons_emit_signals(tmp_path, qapp, monkeypatch):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        timeline_hits: list[str] = []
        summary_hits: list[str] = []
        window.project_panel.exportTimelineRequested.connect(
            lambda: timeline_hits.append("timeline")
        )
        window.project_panel.exportSummaryRequested.connect(
            lambda: summary_hits.append("summary")
        )

        window.project_panel.export_timeline_btn.click()
        window.project_panel.export_summary_btn.click()
        qapp.processEvents()

        assert timeline_hits == ["timeline"]
        assert summary_hits == ["summary"]
    finally:
        window.close()
        qapp.processEvents()


def test_timeline_export_full_scope_uses_wider_layout_and_refits_project(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Customer conference rollout")
        project_id = int(window.model.last_added_task_id())
        phase_id = int(window.model.add_project_phase(project_id, "Delivery and sign-off"))
        for idx in range(1, 5):
            assert window.model.add_task_with_values(
                f"Task with a deliberately long label {idx}",
                parent_id=project_id,
                due_date=f"2026-04-{10 + idx:02d}",
            )
            task_id = int(window.model.last_added_task_id())
            window.model.set_task_start_date(task_id, f"2026-04-{idx + 1:02d}")
            window.model.set_task_phase(task_id, phase_id)
        qapp.processEvents()

        window._focus_task_by_id(project_id)
        window._refresh_project_panel()
        qapp.processEvents()

        source = window.project_panel.timeline_widget
        source._set_zoom_pixels_per_day(96.0, mode="custom")
        qapp.processEvents()

        dashboard = window.model.fetch_project_dashboard(project_id)
        visible_export = window._create_timeline_export_view(
            dashboard,
            TimelinePdfExportOptions(
                file_path=str(tmp_path / "visible.pdf"),
                orientation="landscape",
                scope="visible",
            ),
        )
        full_export = window._create_timeline_export_view(
            dashboard,
            TimelinePdfExportOptions(
                file_path=str(tmp_path / "full.pdf"),
                orientation="landscape",
                scope="full",
            ),
        )
        try:
            assert full_export.pixels_per_day < visible_export.pixels_per_day
            assert full_export.splitter.sizes()[0] >= 340
            assert visible_export.splitter.sizes()[0] >= 340
        finally:
            visible_export.deleteLater()
            full_export.deleteLater()
    finally:
        window.close()
        qapp.processEvents()


def test_timeline_pdf_payload_uses_different_ranges_for_visible_and_full(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Project")
        project_id = int(window.model.last_added_task_id())
        phase_id = int(window.model.add_project_phase(project_id, "Execution reporting"))
        for idx in range(12):
            assert window.model.add_task_with_values(
                f"Work item {idx}",
                parent_id=project_id,
                due_date=f"2026-05-{18 + idx:02d}",
            )
            task_id = int(window.model.last_added_task_id())
            window.model.set_task_start_date(task_id, f"2026-05-{1 + idx:02d}")
            window.model.set_task_phase(task_id, phase_id)
        qapp.processEvents()

        window._focus_task_by_id(project_id)
        window._refresh_project_panel()
        qapp.processEvents()
        source = window.project_panel.timeline_widget
        source._set_zoom_pixels_per_day(120.0, mode="custom")
        source.view.horizontalScrollBar().setValue(
            max(120, source.view.horizontalScrollBar().maximum() // 3)
        )
        qapp.processEvents()

        dashboard = window.model.fetch_project_dashboard(project_id)
        visible_export = window._create_timeline_export_view(
            dashboard,
            TimelinePdfExportOptions(
                file_path=str(tmp_path / "visible.pdf"),
                orientation="landscape",
                scope="visible",
            ),
        )
        full_export = window._create_timeline_export_view(
            dashboard,
            TimelinePdfExportOptions(
                file_path=str(tmp_path / "full.pdf"),
                orientation="landscape",
                scope="full",
            ),
        )
        try:
            rect = (
                source.view
                .mapToScene(source.view.viewport().rect())
                .boundingRect()
            )
            visible_payload = build_timeline_pdf_payload(
                visible_export,
                title="Timeline: Project",
                subtitle_lines=[],
                footer_lines=[],
                options=TimelinePdfExportOptions(
                    file_path=str(tmp_path / "visible.pdf"),
                    orientation="landscape",
                    scope="visible",
                ),
                range_start=source.scene_x_to_date(rect.left()),
                range_end=source.scene_x_to_date(rect.right()),
            )
            full_payload = build_timeline_pdf_payload(
                full_export,
                title="Timeline: Project",
                subtitle_lines=[],
                footer_lines=[],
                options=TimelinePdfExportOptions(
                    file_path=str(tmp_path / "full.pdf"),
                    orientation="landscape",
                    scope="full",
                ),
            )
            assert visible_payload.range_start >= full_payload.range_start
            assert visible_payload.range_end <= full_payload.range_end
            assert len(visible_payload.rows) == len(full_payload.rows)
        finally:
            visible_export.deleteLater()
            full_export.deleteLater()
    finally:
        window.close()
        qapp.processEvents()


def test_timeline_pdf_payload_full_scope_trims_to_actual_content_range(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Project")
        project_id = int(window.model.last_added_task_id())
        phase_id = int(window.model.add_project_phase(project_id, "Execution reporting range"))
        expected_start = None
        expected_end = None
        for idx, (start_iso, end_iso) in enumerate(
            [
                ("2026-06-03", "2026-06-07"),
                ("2026-06-10", "2026-06-12"),
            ]
        ):
            assert window.model.add_task_with_values(
                f"Work item {idx}",
                parent_id=project_id,
                due_date=end_iso,
            )
            task_id = int(window.model.last_added_task_id())
            window.model.set_task_start_date(task_id, start_iso)
            window.model.set_task_phase(task_id, phase_id)
            start_date = date.fromisoformat(start_iso)
            end_date = date.fromisoformat(end_iso)
            expected_start = (
                start_date if expected_start is None else min(expected_start, start_date)
            )
            expected_end = (
                end_date if expected_end is None else max(expected_end, end_date)
            )
        qapp.processEvents()

        window._focus_task_by_id(project_id)
        window._refresh_project_panel()
        qapp.processEvents()
        dashboard = window.model.fetch_project_dashboard(project_id)
        full_export = window._create_timeline_export_view(
            dashboard,
            TimelinePdfExportOptions(
                file_path=str(tmp_path / "full.pdf"),
                orientation="landscape",
                scope="full",
            ),
        )
        try:
            payload = build_timeline_pdf_payload(
                full_export,
                title="Timeline: Project",
                subtitle_lines=[],
                footer_lines=[],
                options=TimelinePdfExportOptions(
                    file_path=str(tmp_path / "full.pdf"),
                    orientation="landscape",
                    scope="full",
                ),
            )
            assert payload.range_start == expected_start
            assert payload.range_end == expected_end
        finally:
            full_export.deleteLater()
    finally:
        window.close()
        qapp.processEvents()


def test_custom_timeline_pdf_writer_preserves_landscape_width(tmp_path):
    options = TimelinePdfExportOptions(
        file_path=str(tmp_path / "custom.pdf"),
        orientation="landscape",
        scope="full",
    )
    writer = create_custom_pdf_writer(
        options,
        page_width_px=1600,
        page_height_px=1000,
        resolution=144,
    )
    layout = writer.pageLayout()
    paint_rect = layout.paintRectPixels(writer.resolution())
    assert paint_rect.width() > paint_rect.height()


def test_timeline_export_metrics_use_single_content_sized_page(
    tmp_path,
    qapp,
    monkeypatch,
):
    window = _build_window(tmp_path, qapp, monkeypatch)
    try:
        assert window.model.add_task_with_values("Project")
        project_id = int(window.model.last_added_task_id())
        phase_id = int(window.model.add_project_phase(project_id, "Execution reporting metrics"))
        for idx in range(18):
            assert window.model.add_task_with_values(
                f"Timeline item {idx}",
                parent_id=project_id,
                due_date=f"2026-07-{10 + idx:02d}",
            )
            task_id = int(window.model.last_added_task_id())
            window.model.set_task_start_date(task_id, f"2026-07-{1 + idx:02d}")
            window.model.set_task_phase(task_id, phase_id)
        qapp.processEvents()

        window._focus_task_by_id(project_id)
        window._refresh_project_panel()
        qapp.processEvents()
        dashboard = window.model.fetch_project_dashboard(project_id)
        export_view = window._create_timeline_export_view(
            dashboard,
            TimelinePdfExportOptions(
                file_path=str(tmp_path / "metrics.pdf"),
                orientation="landscape",
                scope="full",
            ),
        )
        try:
            payload = build_timeline_pdf_payload(
                export_view,
                title="Timeline: Project",
                subtitle_lines=[],
                footer_lines=[],
                options=TimelinePdfExportOptions(
                    file_path=str(tmp_path / "metrics.pdf"),
                    orientation="landscape",
                    scope="full",
                ),
            )
            metrics = _timeline_page_metrics(payload)
            assert metrics.page_width_px > 1700
            assert metrics.page_height_px > 900
        finally:
            export_view.deleteLater()
    finally:
        window.close()
        qapp.processEvents()
