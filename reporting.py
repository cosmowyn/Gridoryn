from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QMarginsF, QPoint, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
    QPolygonF,
    QTextDocument,
)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import QApplication, QWidget

PAGE_SIZES = {
    "A4": QPageSize.PageSizeId.A4,
    "Letter": QPageSize.PageSizeId.Letter,
}
ORIENTATIONS = {
    "portrait": QPageLayout.Orientation.Portrait,
    "landscape": QPageLayout.Orientation.Landscape,
}


@dataclass(slots=True)
class PdfPageOptions:
    file_path: str
    page_size: str = "A4"
    orientation: str = "portrait"
    margin_mm: float = 12.0


@dataclass(slots=True)
class TimelinePdfExportOptions(PdfPageOptions):
    scope: str = "visible"
    include_dependencies: bool = True
    include_completed: bool = True


@dataclass(slots=True)
class TaskListReportRow:
    task: str
    status: str
    due_date: str
    priority: str
    project: str = ""
    category: str = ""
    blocked_waiting: str = ""
    row_kind: str = "task"
    depth: int = 0
    selected: bool = False


@dataclass(slots=True)
class TaskListReport:
    title: str
    subtitle_lines: list[str]
    rows: list[TaskListReportRow]
    exported_at: str
    columns: list[tuple[str, str]] = field(
        default_factory=lambda: [
            ("Task", "task"),
            ("Status", "status"),
            ("Due", "due_date"),
            ("Priority", "priority"),
            ("Project", "project"),
            ("Category", "category"),
            ("Blocked / waiting", "blocked_waiting"),
        ]
    )


@dataclass(slots=True)
class ProjectSummaryReport:
    title: str
    subtitle_lines: list[str]
    exported_at: str
    facts: list[tuple[str, str]]
    sections: list[tuple[str, list[str]]]


@dataclass(slots=True)
class WidgetPdfRenderPayload:
    title: str
    subtitle_lines: list[str]
    footer_lines: list[str]
    widget: QWidget
    options: PdfPageOptions


@dataclass(slots=True)
class TimelineRenderRow:
    uid: str
    label: str
    kind: str
    render_style: str
    depth: int
    start_date: date | None
    end_date: date | None
    baseline_date: date | None
    fill: QColor
    border: QColor
    text: QColor
    selected: bool = False


@dataclass(slots=True)
class TimelineRenderDependency:
    predecessor_uid: str
    successor_uid: str
    color: QColor
    soft: bool = False


@dataclass(slots=True)
class TimelinePdfRenderPayload:
    title: str
    subtitle_lines: list[str]
    footer_lines: list[str]
    options: TimelinePdfExportOptions
    rows: list[TimelineRenderRow]
    dependencies: list[TimelineRenderDependency]
    range_start: date
    range_end: date


@dataclass(slots=True)
class TimelinePageMetrics:
    resolution: int
    margin_px: float
    page_width_px: float
    page_height_px: float
    content_padding: float
    row_height: float
    month_header_height: float
    day_header_height: float
    title_height: float
    subtitle_line_height: float
    footer_line_height: float
    label_font_size: float
    summary_font_size: float
    header_font_size: float
    day_font_size: float
    milestone_label_font_size: float
    indent_px: float
    tree_width: float
    gap: float
    chart_width: float


class ReportError(RuntimeError):
    pass


def timestamp_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def sanitize_filename(text: str, fallback: str) -> str:
    raw = str(text or "").strip() or fallback
    cleaned = []
    for ch in raw:
        if ch.isalnum() or ch in {"-", "_", " ", "."}:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    out = "".join(cleaned).strip().strip(".")
    return out or fallback


def _page_size_id(name: str) -> QPageSize.PageSizeId:
    return PAGE_SIZES.get(str(name or "A4"), QPageSize.PageSizeId.A4)


def _orientation(name: str) -> QPageLayout.Orientation:
    return ORIENTATIONS.get(str(name or "portrait"), QPageLayout.Orientation.Portrait)


def create_pdf_writer(options: PdfPageOptions) -> QPdfWriter:
    out_path = Path(str(options.file_path)).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = QPdfWriter(str(out_path))
    writer.setResolution(144)
    writer.setPageSize(QPageSize(_page_size_id(options.page_size)))
    writer.setPageOrientation(_orientation(options.orientation))
    writer.setPageMargins(
        QMarginsF(
            float(options.margin_mm),
            float(options.margin_mm),
            float(options.margin_mm),
            float(options.margin_mm),
        ),
        QPageLayout.Unit.Millimeter,
    )
    return writer


def create_custom_pdf_writer(
    options: PdfPageOptions,
    *,
    page_width_px: float,
    page_height_px: float,
    resolution: int = 144,
) -> QPdfWriter:
    out_path = Path(str(options.file_path)).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = QPdfWriter(str(out_path))
    writer.setResolution(int(resolution))
    width_px = float(page_width_px)
    height_px = float(page_height_px)
    long_px = max(width_px, height_px)
    short_px = min(width_px, height_px)
    if str(options.orientation or "portrait") == "landscape":
        width_px, height_px = long_px, short_px
    else:
        width_px, height_px = short_px, long_px
    writer.setPageSize(
        QPageSize(
            QSizeF(
                width_px * 25.4 / float(resolution),
                height_px * 25.4 / float(resolution),
            ),
            QPageSize.Unit.Millimeter,
            "GridorynTimelineExport",
        )
    )
    writer.setPageMargins(
        QMarginsF(
            float(options.margin_mm),
            float(options.margin_mm),
            float(options.margin_mm),
            float(options.margin_mm),
        ),
        QPageLayout.Unit.Millimeter,
    )
    return writer


def estimate_widget_render_size(
    options: PdfPageOptions,
    *,
    subtitle_line_count: int = 0,
    footer_line_count: int = 0,
) -> QSize:
    resolution = 144
    layout = QPageLayout(
        QPageSize(_page_size_id(options.page_size)),
        _orientation(options.orientation),
        QMarginsF(
            float(options.margin_mm),
            float(options.margin_mm),
            float(options.margin_mm),
            float(options.margin_mm),
        ),
        QPageLayout.Unit.Millimeter,
    )
    rect = layout.paintRectPixels(resolution)
    header_px = 40 + (18 * max(0, int(subtitle_line_count))) + 16
    footer_px = (18 * max(0, int(footer_line_count))) + 12
    width = max(960, int(rect.width()))
    height = max(540, int(rect.height()) - header_px - footer_px)
    return QSize(width, height)


def _page_rect(device) -> QRectF:
    resolution = int(device.resolution()) if hasattr(device, "resolution") else 144
    rect = device.pageLayout().paintRectPixels(resolution)
    return QRectF(rect)


def _render_document_to_paged_device(doc: QTextDocument, device) -> None:
    page_rect = _page_rect(device)
    doc.setPageSize(QSizeF(page_rect.width(), page_rect.height()))
    painter = QPainter(device)
    try:
        page_count = max(1, int(doc.pageCount()))
        for page in range(page_count):
            painter.save()
            painter.translate(page_rect.left(), page_rect.top() - (page * page_rect.height()))
            clip = QRectF(0.0, page * page_rect.height(), page_rect.width(), page_rect.height())
            doc.drawContents(painter, clip)
            painter.restore()
            if page < page_count - 1:
                device.newPage()
    finally:
        painter.end()


def render_html_to_pdf(html: str, options: PdfPageOptions) -> str:
    writer = create_pdf_writer(options)
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(QApplication.font())
    document.setHtml(html)
    _render_document_to_paged_device(document, writer)
    return str(Path(options.file_path))


def print_html_report(html: str, *, title: str, parent=None, page_size: str = "A4", orientation: str = "portrait") -> bool:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(str(title or "Gridoryn report"))
    printer.setPageSize(QPageSize(_page_size_id(page_size)))
    printer.setPageOrientation(_orientation(orientation))
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return False
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(QApplication.font())
    document.setHtml(html)
    _render_document_to_paged_device(document, printer)
    return True


def _css() -> str:
    return """
    body { font-family: sans-serif; color: #111827; font-size: 10pt; }
    h1 { font-size: 18pt; margin: 0 0 6px 0; }
    h2 { font-size: 12pt; margin: 16px 0 6px 0; padding-bottom: 2px; border-bottom: 1px solid #d1d5db; }
    .subtitle { color: #4b5563; margin: 0 0 2px 0; }
    .meta { margin: 12px 0 16px 0; }
    .fact-grid { width: 100%; border-collapse: collapse; margin: 10px 0 14px 0; }
    .fact-grid td { padding: 6px 8px; border: 1px solid #d1d5db; vertical-align: top; }
    .fact-grid td.label { width: 28%; font-weight: bold; background: #f3f4f6; }
    table.report { width: 100%; border-collapse: collapse; margin-top: 10px; }
    table.report th, table.report td { border: 1px solid #d1d5db; padding: 5px 7px; text-align: left; vertical-align: top; }
    table.report th { background: #f3f4f6; font-weight: bold; }
    table.report tbody tr.folder-row td { background: #eef2ff; font-weight: 700; color: #1f2937; }
    table.report tbody tr.folder-row td:not(:first-child) { color: #6b7280; }
    table.report tbody tr.selected-row td { background: #eff6ff; }
    .task-cell { white-space: nowrap; }
    .task-indent { display: inline-block; }
    .folder-marker { color: #4338ca; margin-right: 6px; }
    ul.compact { margin: 6px 0 0 18px; padding: 0; }
    ul.compact li { margin: 0 0 4px 0; }
    .footer { color: #6b7280; font-size: 8.5pt; margin-top: 18px; }
    """


def _task_cell_html(row: TaskListReportRow) -> str:
    indent_px = max(0, int(row.depth)) * 18
    text = escape(str(row.task or ""))
    marker = ""
    if str(row.row_kind or "task") == "folder":
        marker = "<span class='folder-marker'>▸</span>"
    return (
        f"<span class='task-indent' style='margin-left: {indent_px}px;'>"
        f"{marker}{text}</span>"
    )


def build_task_list_report_html(report: TaskListReport) -> str:
    rows_html: list[str] = []
    for row in report.rows:
        cell_values = []
        for _label, key in report.columns:
            if key == "task":
                value = _task_cell_html(row)
                cell_values.append(f"<td class='task-cell'>{value}</td>")
                continue
            value = escape(str(getattr(row, key, "") or ""))
            cell_values.append(f"<td>{value}</td>")
        row_classes: list[str] = []
        if str(row.row_kind or "task") == "folder":
            row_classes.append("folder-row")
        if bool(row.selected):
            row_classes.append("selected-row")
        class_attr = f" class='{' '.join(row_classes)}'" if row_classes else ""
        rows_html.append(f"<tr{class_attr}>{''.join(cell_values)}</tr>")
    header_html = "".join(f"<th>{escape(label)}</th>" for label, _key in report.columns)
    subtitles = "".join(f"<div class='subtitle'>{escape(line)}</div>" for line in report.subtitle_lines)
    if not rows_html:
        rows_html.append(f"<tr><td colspan='{len(report.columns)}'>No tasks match the current view.</td></tr>")
    return f"""
    <html>
      <head><style>{_css()}</style></head>
      <body>
        <h1>{escape(report.title)}</h1>
        {subtitles}
        <div class='meta'><strong>Exported:</strong> {escape(report.exported_at)}</div>
        <table class='report'>
          <thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>
        <div class='footer'>Generated locally by Gridoryn.</div>
      </body>
    </html>
    """


def build_project_summary_html(report: ProjectSummaryReport) -> str:
    facts = "".join(
        f"<tr><td class='label'>{escape(label)}</td><td>{escape(value or '-')}</td></tr>"
        for label, value in report.facts
    )
    sections = []
    for title, items in report.sections:
        bullet_items = "".join(f"<li>{escape(item)}</li>" for item in items if str(item).strip())
        if not bullet_items:
            continue
        sections.append(f"<h2>{escape(title)}</h2><ul class='compact'>{bullet_items}</ul>")
    subtitles = "".join(f"<div class='subtitle'>{escape(line)}</div>" for line in report.subtitle_lines)
    return f"""
    <html>
      <head><style>{_css()}</style></head>
      <body>
        <h1>{escape(report.title)}</h1>
        {subtitles}
        <div class='meta'><strong>Exported:</strong> {escape(report.exported_at)}</div>
        <table class='fact-grid'>{facts}</table>
        {''.join(sections)}
        <div class='footer'>Generated locally by Gridoryn.</div>
      </body>
    </html>
    """


def render_widget_to_pdf(payload: WidgetPdfRenderPayload) -> str:
    writer = create_pdf_writer(payload.options)
    page_rect = _page_rect(writer)
    painter = QPainter(writer)
    try:
        painter.fillRect(page_rect, QColor("white"))
        title_font = QFont(QApplication.font())
        title_font.setPointSizeF(max(16.0, title_font.pointSizeF() + 4.0))
        title_font.setBold(True)
        subtitle_font = QFont(QApplication.font())
        subtitle_font.setPointSizeF(max(9.5, subtitle_font.pointSizeF()))

        top = page_rect.top()
        left = page_rect.left()
        width = page_rect.width()

        painter.setPen(QColor("#111827"))
        painter.setFont(title_font)
        painter.drawText(QRectF(left, top, width, 28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, payload.title)
        top += 32

        painter.setPen(QColor("#4b5563"))
        painter.setFont(subtitle_font)
        for line in payload.subtitle_lines:
            painter.drawText(QRectF(left, top, width, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            top += 18
        if payload.footer_lines:
            top += 4

        bottom_footer = 0.0
        if payload.footer_lines:
            footer_top = page_rect.bottom() - (18.0 * len(payload.footer_lines))
            painter.setPen(QColor("#6b7280"))
            for line in payload.footer_lines:
                painter.drawText(QRectF(left, footer_top, width, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
                footer_top += 16
            bottom_footer = (18.0 * len(payload.footer_lines)) + 8.0

        available = QRectF(
            left,
            top + 8.0,
            width,
            max(40.0, page_rect.height() - (top - page_rect.top()) - bottom_footer - 12.0),
        )

        widget = payload.widget
        widget.layout().activate() if widget.layout() is not None else None
        source_size = widget.size()
        if source_size.width() <= 0 or source_size.height() <= 0:
            source_size = widget.sizeHint()
        if source_size.width() <= 0 or source_size.height() <= 0:
            raise ReportError("Export widget has no valid size.")
        scale = min(available.width() / float(source_size.width()), available.height() / float(source_size.height()))
        scale = max(0.1, min(scale, 2.0))
        render_width = float(source_size.width()) * scale
        render_height = float(source_size.height()) * scale
        target_x = available.left() + ((available.width() - render_width) / 2.0)
        target_y = available.top()

        painter.save()
        painter.translate(target_x, target_y)
        painter.scale(scale, scale)
        widget.render(painter, QPoint(0, 0))
        painter.restore()
    finally:
        painter.end()
    return str(Path(payload.options.file_path))


def timeline_row_label(row: dict) -> str:
    label = str(row.get("label") or "").strip()
    kind = str(row.get("kind") or "").strip().lower()
    phase_name = str(row.get("phase_name") or "").strip()
    if kind == "task" and phase_name and not bool(row.get("summary_row")):
        return f"{label} [{phase_name}]"
    return label


def build_timeline_pdf_payload(
    timeline_widget,
    *,
    title: str,
    subtitle_lines: list[str],
    footer_lines: list[str],
    options: TimelinePdfExportOptions,
    range_start: date | None = None,
    range_end: date | None = None,
) -> TimelinePdfRenderPayload:
    rows: list[TimelineRenderRow] = []
    row_lookup = {
        str(row.get("uid") or ""): dict(row)
        for row in list(getattr(timeline_widget, "visible_rows", []) or [])
    }
    if not row_lookup:
        raise ReportError("Timeline export has no visible rows.")

    def depth_for(uid: str) -> int:
        depth = 0
        cur = row_lookup.get(uid)
        guard = 0
        while cur is not None and cur.get("parent_uid") is not None and guard < 64:
            parent_uid = str(cur.get("parent_uid") or "")
            parent = row_lookup.get(parent_uid)
            if parent is None:
                break
            depth += 1
            cur = parent
            guard += 1
        return depth

    selected_uid = str(getattr(timeline_widget, "selected_uid", "") or "")
    for row in list(getattr(timeline_widget, "visible_rows", []) or []):
        uid = str(row.get("uid") or "")
        rows.append(
            TimelineRenderRow(
                uid=uid,
                label=timeline_row_label(row),
                kind=str(row.get("kind") or ""),
                render_style=str(row.get("render_style") or "task"),
                depth=depth_for(uid),
                start_date=_parse_row_date(row, "display_start_date", "start_date"),
                end_date=_parse_row_date(row, "display_end_date", "end_date"),
                baseline_date=_parse_row_date(row, "baseline_date"),
                fill=QColor(timeline_widget.bar_color_for_row(row)),
                border=QColor(timeline_widget.bar_border_for_row(row)),
                text=QColor(timeline_widget.bar_text_color_for_row(row)),
                selected=(uid == selected_uid),
            )
        )

    current_uids = {row.uid for row in rows}
    deps: list[TimelineRenderDependency] = []
    dashboard = getattr(timeline_widget, "_dashboard", {}) or {}
    for dep in dashboard.get("dependencies") or []:
        predecessor_uid = _timeline_uid(
            dep.get("predecessor_kind"),
            int(dep.get("predecessor_id") or 0),
        )
        successor_uid = _timeline_uid(
            dep.get("successor_kind"),
            int(dep.get("successor_id") or 0),
        )
        if predecessor_uid not in current_uids or successor_uid not in current_uids:
            continue
        deps.append(
            TimelineRenderDependency(
                predecessor_uid=predecessor_uid,
                successor_uid=successor_uid,
                color=QColor("#64748B"),
                soft=bool(dep.get("is_soft")),
            )
        )

    content_start, content_end = _timeline_content_range(rows)
    resolved_start = range_start or getattr(timeline_widget, "range_start", None)
    resolved_end = range_end or getattr(timeline_widget, "range_end", None)
    if resolved_start is None or resolved_end is None:
        resolved_start, resolved_end = content_start, content_end
    if options.scope == "full":
        resolved_start, resolved_end = content_start, content_end
    else:
        resolved_start = max(content_start, resolved_start)
        resolved_end = min(content_end, resolved_end)
        if resolved_start > resolved_end:
            resolved_start, resolved_end = content_start, content_end
    return TimelinePdfRenderPayload(
        title=title,
        subtitle_lines=list(subtitle_lines),
        footer_lines=list(footer_lines),
        options=options,
        rows=rows,
        dependencies=deps,
        range_start=resolved_start,
        range_end=resolved_end,
    )


def render_timeline_to_pdf(payload: TimelinePdfRenderPayload) -> str:
    metrics = _timeline_page_metrics(payload)
    writer = create_custom_pdf_writer(
        payload.options,
        page_width_px=metrics.page_width_px,
        page_height_px=metrics.page_height_px,
        resolution=metrics.resolution,
    )
    painter = QPainter(writer)
    try:
        _render_timeline_pages(painter, writer, payload, metrics)
    finally:
        painter.end()
    return str(Path(payload.options.file_path))


def _parse_row_date(row: dict, *keys: str) -> date | None:
    for key in keys:
        raw = str(row.get(key) or "").strip()
        if raw:
            return date.fromisoformat(raw[:10])
    return None


def _timeline_uid(kind: str | None, item_id: int) -> str:
    return f"{str(kind or '').strip().lower()}:{int(item_id)}"


def _timeline_content_range(rows: list[TimelineRenderRow]) -> tuple[date, date]:
    dates: list[date] = []
    for row in rows:
        if row.start_date is not None:
            dates.append(row.start_date)
        if row.end_date is not None:
            dates.append(row.end_date)
        if row.baseline_date is not None:
            dates.append(row.baseline_date)
    if not dates:
        raise ReportError("Timeline export has no dated rows.")
    return min(dates), max(dates)


def _timeline_page_metrics(payload: TimelinePdfRenderPayload) -> TimelinePageMetrics:
    resolution = 144
    margin_px = float(payload.options.margin_mm) * float(resolution) / 25.4
    day_count = max(1, (payload.range_end - payload.range_start).days + 1)

    base_font = QFont(QApplication.font())
    base_size = max(10.5, base_font.pointSizeF())
    label_font_size = base_size + 1.0
    summary_font_size = label_font_size + 0.5
    header_font_size = label_font_size + 1.5
    day_font_size = max(10.0, base_size)
    milestone_label_font_size = max(10.5, label_font_size)

    indent_px = 18.0
    label_font = QFont(base_font)
    label_font.setPointSizeF(label_font_size)
    summary_font = QFont(label_font)
    summary_font.setBold(True)

    max_text_width = 0.0
    for row in payload.rows:
        row_font = summary_font if row.render_style == "summary" else label_font
        row_metrics = QFontMetricsF(row_font)
        max_text_width = max(
            max_text_width,
            (row.depth * indent_px) + row_metrics.horizontalAdvance(row.label),
        )

    content_padding = 32.0
    tree_width = max(500.0, min(980.0, max_text_width + 96.0))
    gap = 20.0
    desired_day_width = 60.0 if payload.options.scope == "visible" else 52.0
    minimum_day_width = 32.0 if payload.options.scope == "visible" else 28.0
    chart_width = day_count * desired_day_width
    if day_count > 0 and (chart_width / float(day_count)) < minimum_day_width:
        chart_width = float(day_count) * minimum_day_width
    chart_width = max(900.0, chart_width)

    row_height = 38.0
    month_header_height = 52.0
    day_header_height = 38.0
    title_height = 50.0
    subtitle_line_height = 28.0
    footer_line_height = 22.0
    footer_count = max(0, len(payload.footer_lines))
    subtitle_count = max(0, len(payload.subtitle_lines))
    header_block = title_height + (subtitle_count * subtitle_line_height) + 12.0
    footer_block = (footer_count * footer_line_height) + (8.0 if footer_count else 0.0)
    page_height_px = max(
        900.0,
        (2.0 * margin_px)
        + (2.0 * content_padding)
        + header_block
        + footer_block
        + month_header_height
        + day_header_height
        + (len(payload.rows) * row_height)
        + 24.0,
    )
    page_width_px = max(
        1400.0,
        (2.0 * margin_px) + (2.0 * content_padding) + tree_width + gap + chart_width,
    )
    return TimelinePageMetrics(
        resolution=resolution,
        margin_px=margin_px,
        page_width_px=page_width_px,
        page_height_px=page_height_px,
        content_padding=content_padding,
        row_height=row_height,
        month_header_height=month_header_height,
        day_header_height=day_header_height,
        title_height=title_height,
        subtitle_line_height=subtitle_line_height,
        footer_line_height=footer_line_height,
        label_font_size=label_font_size,
        summary_font_size=summary_font_size,
        header_font_size=header_font_size,
        day_font_size=day_font_size,
        milestone_label_font_size=milestone_label_font_size,
        indent_px=indent_px,
        tree_width=tree_width,
        gap=gap,
        chart_width=chart_width,
    )


def _timeline_page_header(
    painter: QPainter,
    page_rect: QRectF,
    payload: TimelinePdfRenderPayload,
    metrics: TimelinePageMetrics,
) -> tuple[QRectF, float]:
    painter.fillRect(page_rect, QColor("white"))
    title_font = QFont(QApplication.font())
    title_font.setPointSizeF(metrics.header_font_size + 3.0)
    title_font.setBold(True)
    subtitle_font = QFont(QApplication.font())
    subtitle_font.setPointSizeF(metrics.label_font_size)

    top = page_rect.top() + metrics.content_padding
    left = page_rect.left() + metrics.content_padding
    width = page_rect.width() - (2.0 * metrics.content_padding)

    painter.setPen(QColor("#111827"))
    painter.setFont(title_font)
    painter.drawText(
        QRectF(left, top, width, metrics.title_height),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        payload.title,
    )
    top += metrics.title_height + 8.0

    painter.setPen(QColor("#4B5563"))
    painter.setFont(subtitle_font)
    for line in payload.subtitle_lines:
        painter.drawText(
            QRectF(left, top, width, metrics.subtitle_line_height),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            line,
        )
        top += metrics.subtitle_line_height

    footer_height = 0.0
    if payload.footer_lines:
        footer_top = page_rect.bottom() - metrics.content_padding - (
            metrics.footer_line_height * len(payload.footer_lines)
        )
        painter.setPen(QColor("#6B7280"))
        for line in payload.footer_lines:
            painter.drawText(
                QRectF(left, footer_top, width, metrics.footer_line_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )
            footer_top += metrics.footer_line_height
        footer_height = (
            metrics.footer_line_height * len(payload.footer_lines)
        ) + 8.0

    body = QRectF(
        left,
        top + 12.0,
        width,
        max(
            80.0,
            page_rect.height()
            - (top - page_rect.top())
            - footer_height
            - metrics.content_padding
            - 12.0,
        ),
    )
    return body, footer_height


def _render_timeline_pages(
    painter: QPainter,
    writer: QPdfWriter,
    payload: TimelinePdfRenderPayload,
    metrics: TimelinePageMetrics,
) -> None:
    page_rect = _page_rect(writer)
    if not payload.rows:
        raise ReportError("Timeline export has no rows to render.")

    body_rect, _footer_height = _timeline_page_header(
        painter,
        page_rect,
        payload,
        metrics,
    )
    _render_timeline_page_body(
        painter,
        body_rect,
        payload,
        payload.rows,
        0,
        metrics,
    )


def _render_timeline_page_body(
    painter: QPainter,
    body_rect: QRectF,
    payload: TimelinePdfRenderPayload,
    page_rows: list[TimelineRenderRow],
    page_index: int,
    metrics: TimelinePageMetrics,
) -> None:
    label_font = QFont(QApplication.font())
    label_font.setPointSizeF(metrics.label_font_size)
    summary_font = QFont(label_font)
    summary_font.setBold(True)
    chart_rect = QRectF(
        body_rect.left() + metrics.tree_width + metrics.gap,
        body_rect.top(),
        max(260.0, body_rect.width() - metrics.tree_width - metrics.gap),
        body_rect.height(),
    )
    tree_rect = QRectF(
        body_rect.left(),
        body_rect.top(),
        metrics.tree_width,
        body_rect.height(),
    )
    chart_header_height = metrics.month_header_height + metrics.day_header_height
    tree_header_rect = QRectF(tree_rect.left(), tree_rect.top(), tree_rect.width(), chart_header_height)
    chart_header_rect = QRectF(chart_rect.left(), chart_rect.top(), chart_rect.width(), chart_header_height)
    rows_top = tree_rect.top() + chart_header_height
    day_count = max(1, (payload.range_end - payload.range_start).days + 1)
    day_width = chart_rect.width() / float(day_count)
    row_top_by_uid: dict[str, float] = {}
    chart_rows_rect = QRectF(
        chart_rect.left(),
        rows_top,
        chart_rect.width(),
        len(page_rows) * metrics.row_height,
    )

    painter.save()
    painter.setPen(QColor("#9CA3AF"))
    painter.setBrush(QColor("#F3F4F6"))
    painter.drawRect(tree_header_rect)
    painter.drawRect(chart_header_rect)
    painter.setPen(QColor("#111827"))
    painter.setFont(summary_font)
    painter.drawText(
        tree_header_rect.adjusted(10, 0, -10, -metrics.day_header_height),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        "Structure",
    )
    painter.setFont(label_font)
    painter.drawText(
        chart_header_rect.adjusted(0, 0, 0, -metrics.day_header_height),
        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
        _timeline_header_title(payload.range_start, payload.range_end),
    )
    painter.save()
    painter.setClipRect(chart_header_rect)
    _draw_timeline_day_headers(
        painter,
        chart_header_rect.adjusted(0, metrics.month_header_height, 0, 0),
        payload.range_start,
        day_count,
        day_width,
        metrics,
    )
    painter.restore()

    for index, row in enumerate(page_rows):
        y = rows_top + (index * metrics.row_height)
        row_rect = QRectF(
            tree_rect.left(),
            y,
            tree_rect.width() + metrics.gap + chart_rect.width(),
            metrics.row_height,
        )
        bg = QColor("#F9FAFB") if index % 2 == 0 else QColor("#FFFFFF")
        painter.fillRect(row_rect, bg)
        row_top_by_uid[row.uid] = y

        row_font = summary_font if row.render_style == "summary" else label_font
        painter.setFont(row_font)
        painter.setPen(QColor("#111827"))
        label_rect = QRectF(
            tree_rect.left() + 10.0 + (row.depth * metrics.indent_px),
            y,
            tree_rect.width() - 20.0 - (row.depth * metrics.indent_px),
            metrics.row_height,
        )
        elided = QFontMetricsF(row_font).elidedText(
            row.label,
            Qt.TextElideMode.ElideRight,
            max(20, int(label_rect.width())),
        )
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        painter.setPen(QPen(QColor("#D1D5DB"), 1))
        painter.drawLine(
            tree_rect.left(),
            y + metrics.row_height,
            chart_rect.right(),
            y + metrics.row_height,
        )

    painter.save()
    painter.setClipRect(chart_rows_rect)
    _draw_timeline_grid(
        painter,
        chart_rect,
        rows_top,
        len(page_rows),
        payload.range_start,
        day_count,
        day_width,
        metrics,
    )
    _draw_timeline_dependencies(
        painter,
        chart_rect,
        rows_top,
        payload,
        page_rows,
        row_top_by_uid,
        day_width,
        metrics,
    )
    for row in page_rows:
        _draw_timeline_row_bar(
            painter,
            chart_rect,
            row_top_by_uid[row.uid],
            payload.range_start,
            day_width,
            row,
            metrics,
        )
    painter.restore()
    painter.restore()


def _timeline_header_title(range_start: date, range_end: date) -> str:
    if range_start.month == range_end.month and range_start.year == range_end.year:
        return range_start.strftime("%B %Y")
    return f"{range_start.strftime('%b %Y')} – {range_end.strftime('%b %Y')}"


def _draw_timeline_day_headers(
    painter: QPainter,
    rect: QRectF,
    range_start: date,
    day_count: int,
    day_width: float,
    metrics: TimelinePageMetrics,
) -> None:
    font = QFont(QApplication.font())
    font.setPointSizeF(metrics.day_font_size)
    painter.setFont(font)
    for offset in range(day_count):
        current = range_start + timedelta(days=offset)
        x = rect.left() + (offset * day_width)
        cell = QRectF(x, rect.top(), day_width, rect.height())
        painter.setPen(QPen(QColor("#D1D5DB"), 1))
        painter.drawRect(cell)
        if day_width >= 16.0:
            painter.setPen(QColor("#111827"))
            painter.drawText(cell, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, str(current.day))


def _draw_timeline_grid(
    painter: QPainter,
    chart_rect: QRectF,
    rows_top: float,
    row_count: int,
    range_start: date,
    day_count: int,
    day_width: float,
    metrics: TimelinePageMetrics,
) -> None:
    grid_top = rows_top
    grid_bottom = rows_top + (row_count * metrics.row_height)
    for offset in range(day_count + 1):
        x = chart_rect.left() + (offset * day_width)
        current = range_start + timedelta(days=min(offset, max(0, day_count - 1)))
        color = QColor("#9CA3AF") if current.weekday() < 5 else QColor("#CBD5E1")
        pen = QPen(color, 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(x, grid_top, x, grid_bottom)


def _draw_timeline_row_bar(
    painter: QPainter,
    chart_rect: QRectF,
    row_top: float,
    range_start: date,
    day_width: float,
    row: TimelineRenderRow,
    metrics: TimelinePageMetrics,
) -> None:
    if row.start_date is None:
        return
    end_date = row.end_date or row.start_date
    start_x = chart_rect.left() + ((row.start_date - range_start).days * day_width)
    end_x = chart_rect.left() + (((end_date - range_start).days + 1) * day_width)
    width = max(10.0, end_x - start_x)
    bar_height = max(20.0, metrics.row_height - 10.0)
    bar_top = row_top + ((metrics.row_height - bar_height) / 2.0)
    rect = QRectF(start_x, bar_top, width, bar_height)

    if row.baseline_date is not None:
        baseline_x = chart_rect.left() + ((row.baseline_date - range_start).days * day_width)
        painter.setPen(QPen(row.border, 2))
        painter.drawLine(
            baseline_x,
            row_top + 3.0,
            baseline_x,
            row_top + metrics.row_height - 3.0,
        )

    painter.setPen(QPen(row.border, 1.4))
    painter.setBrush(row.fill)
    if row.render_style == "milestone":
        center = QPoint(rect.center().x(), rect.center().y())
        radius = min(rect.height() * 0.5, 7.0)
        diamond = QPolygonF(
            [
                QPoint(rect.center().x(), rect.center().y() - radius),
                QPoint(rect.center().x() + radius, rect.center().y()),
                QPoint(rect.center().x(), rect.center().y() + radius),
                QPoint(rect.center().x() - radius, rect.center().y()),
            ]
        )
        painter.drawPolygon(diamond)
        label_rect = QRectF(
            rect.right() + 8.0,
            row_top + 3.0,
            min(260.0, chart_rect.right() - rect.right() - 12.0),
            metrics.row_height - 6.0,
        )
        if label_rect.width() > 24.0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRoundedRect(label_rect, 4.0, 4.0)
            painter.setPen(QColor("#111827"))
            font = QFont(QApplication.font())
            font.setPointSizeF(metrics.milestone_label_font_size)
            painter.setFont(font)
            label = QFontMetricsF(font).elidedText(row.label, Qt.TextElideMode.ElideRight, int(label_rect.width() - 10.0))
            painter.drawText(label_rect.adjusted(6.0, 0.0, -4.0, 0.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        return
    if row.render_style == "summary":
        path = QPainterPath()
        path.moveTo(rect.left(), rect.center().y())
        path.lineTo(rect.left() + 8.0, rect.top())
        path.lineTo(rect.right() - 8.0, rect.top())
        path.lineTo(rect.right(), rect.center().y())
        path.lineTo(rect.right() - 8.0, rect.bottom())
        path.lineTo(rect.left() + 8.0, rect.bottom())
        path.closeSubpath()
        painter.drawPath(path)
        return
    painter.drawRoundedRect(rect, 4.0, 4.0)


def _draw_timeline_dependencies(
    painter: QPainter,
    chart_rect: QRectF,
    rows_top: float,
    payload: TimelinePdfRenderPayload,
    page_rows: list[TimelineRenderRow],
    row_top_by_uid: dict[str, float],
    day_width: float,
    metrics: TimelinePageMetrics,
) -> None:
    if not payload.options.include_dependencies:
        return
    row_map = {row.uid: row for row in page_rows}
    for dep in payload.dependencies:
        predecessor = row_map.get(dep.predecessor_uid)
        successor = row_map.get(dep.successor_uid)
        if predecessor is None or successor is None:
            continue
        if predecessor.start_date is None or successor.start_date is None:
            continue
        predecessor_end = predecessor.end_date or predecessor.start_date
        succ_end = successor.end_date or successor.start_date
        start_x = chart_rect.left() + (((predecessor_end - payload.range_start).days + 1) * day_width)
        end_x = chart_rect.left() + ((successor.start_date - payload.range_start).days * day_width)
        start_y = row_top_by_uid[predecessor.uid] + (metrics.row_height / 2.0)
        end_y = row_top_by_uid[successor.uid] + (metrics.row_height / 2.0)
        mid_x = max(start_x + 12.0, end_x - 12.0)
        pen = QPen(dep.color, 1.2, Qt.PenStyle.DashLine if dep.soft else Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.drawLine(start_x, start_y, mid_x, start_y)
        painter.drawLine(mid_x, start_y, mid_x, end_y)
        painter.drawLine(mid_x, end_y, end_x, end_y)
