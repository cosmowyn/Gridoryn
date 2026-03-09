from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QIcon,
    QNativeGestureEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from platform_utils import is_macos
from project_management import parse_iso_date, today_local
from ui_layout import add_left_aligned_buttons, configure_box_layout

ROW_HEIGHT = 28
HEADER_HEIGHT = 58
LEFT_COLUMN_WIDTH = 300
DAY_MARGIN_BEFORE = 3
DAY_MARGIN_AFTER = 10
HANDLE_WIDTH = 7.0
BAR_TEXT_PADDING_X = 8.0
BAR_TEXT_PADDING_Y = 3.0
MIN_PIXELS_PER_DAY = 2.5
MAX_PIXELS_PER_DAY = 64.0
GANTT_SCALE_PRESETS = {
    "day": ("Day", 28.0),
    "week": ("Week", 12.0),
    "month": ("Month", 4.5),
}


def _timeline_uid(kind: str, item_id: int | str) -> str:
    return f"{str(kind or '').strip().lower()}:{item_id}"


def _ensure_date(value: str | None) -> date | None:
    return parse_iso_date(value)


def _best_contrast(bg: QColor) -> QColor:
    return QColor("#111827") if bg.lightness() > 135 else QColor("#F9FAFB")


def _fit_button_to_text(button: QPushButton, *, extra_padding: int = 28):
    metrics = QFontMetrics(button.font())
    text = str(button.text() or "").replace("&", "")
    width = metrics.horizontalAdvance(text) + int(extra_padding)
    button.setMinimumWidth(max(72, width))


def _configure_combo_for_contents(combo: QComboBox, *, extra_padding: int = 44):
    metrics = QFontMetrics(combo.font())
    longest = 0
    for index in range(combo.count()):
        longest = max(longest, metrics.horizontalAdvance(combo.itemText(index)))
    combo.setMinimumWidth(max(84, longest + int(extra_padding)))
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)


def _text_layout(
    base_font: QFont,
    text: str,
    width: float,
    height: float,
    *,
    padding_x: float = 0.0,
    padding_y: float = 0.0,
) -> tuple[QFont, QFontMetricsF, str]:
    font = QFont(base_font)
    metrics = QFontMetricsF(font)
    available_width = max(0.0, float(width) - (padding_x * 2.0))
    available_height = max(0.0, float(height) - (padding_y * 2.0))
    text_value = str(text or "")
    if not text_value or available_width <= 0.0 or available_height <= 0.0:
        return font, metrics, ""
    if (
        metrics.height() <= available_height
        and metrics.horizontalAdvance(text_value) <= available_width
    ):
        return font, metrics, text_value
    if (
        metrics.height() <= available_height
        and metrics.horizontalAdvance(".") <= available_width
    ):
        return font, metrics, "."
    return font, metrics, ""


def _row_label(row: dict) -> str:
    kind = str(row.get("kind") or "").strip().lower()
    label = str(row.get("label") or "").strip() or kind.title()
    if kind == "phase":
        return label
    phase_name = str(row.get("phase_name") or "").strip()
    if kind == "task" and phase_name and not row.get("summary_row"):
        return f"{label} [{phase_name}]"
    return label


class TimelineTreeWidget(QTreeWidget):
    rowActivated = Signal(str, int)
    taskMoveRequested = Signal(int, object, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(False)
        self.setColumnCount(1)
        self.setHeaderLabels(["Structure"])
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setRootIsDecorated(True)
        self.setIndentation(14)
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setSelectionMode(self.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            kind = str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "")
            item_id = int(item.data(0, Qt.ItemDataRole.UserRole + 2) or 0)
            if kind and item_id > 0:
                self.rowActivated.emit(kind, item_id)
        super().mouseDoubleClickEvent(event)

    def mimeTypes(self):
        return ["application/x-customtodo-gantt-row"]

    def mimeData(self, items):
        if not items:
            return QMimeData()
        item = items[0]
        row = item.data(0, Qt.ItemDataRole.UserRole + 3) or {}
        if str(row.get("kind") or "") != "task":
            return QMimeData()
        mime = QMimeData()
        mime.setData(
            "application/x-customtodo-gantt-row",
            QByteArray(str(item.data(0, Qt.ItemDataRole.UserRole)).encode("utf-8")),
        )
        return mime

    def dropEvent(self, event):
        if not event.mimeData().hasFormat("application/x-customtodo-gantt-row"):
            event.ignore()
            return
        current = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        if current is None or target is None or current is target:
            event.ignore()
            return
        dragged_row = current.data(0, Qt.ItemDataRole.UserRole + 3) or {}
        target_row = target.data(0, Qt.ItemDataRole.UserRole + 3) or {}
        if str(dragged_row.get("kind") or "") != "task" or str(target_row.get("kind") or "") != "task":
            event.ignore()
            return
        if current.parent() is not target.parent():
            event.ignore()
            return
        actual_parent = dragged_row.get("actual_parent_task_id")
        if actual_parent != target_row.get("actual_parent_task_id"):
            event.ignore()
            return
        visual_parent = current.parent()
        sibling_tasks: list[QTreeWidgetItem] = []
        if visual_parent is None:
            for index in range(self.topLevelItemCount()):
                item = self.topLevelItem(index)
                row = item.data(0, Qt.ItemDataRole.UserRole + 3) or {}
                if str(row.get("kind") or "") == "task":
                    sibling_tasks.append(item)
        else:
            for index in range(visual_parent.childCount()):
                item = visual_parent.child(index)
                row = item.data(0, Qt.ItemDataRole.UserRole + 3) or {}
                if str(row.get("kind") or "") == "task":
                    sibling_tasks.append(item)
        if target not in sibling_tasks:
            event.ignore()
            return
        target_rect = self.visualItemRect(target)
        target_index = sibling_tasks.index(target)
        if event.position().y() > target_rect.center().y():
            target_index += 1
        self.taskMoveRequested.emit(
            int(dragged_row.get("item_id") or 0),
            actual_parent,
            max(0, target_index),
        )
        event.acceptProposedAction()


class PlannerGraphicsView(QGraphicsView):
    def __init__(self, owner, scene):
        super().__init__(scene)
        self.owner = owner

    @staticmethod
    def _zoom_modifier_active(modifiers) -> bool:
        required = (
            Qt.KeyboardModifier.MetaModifier
            if is_macos()
            else Qt.KeyboardModifier.ControlModifier
        )
        return bool(modifiers & required)

    def wheelEvent(self, event):
        if self._zoom_modifier_active(event.modifiers()):
            delta_y = int(event.angleDelta().y())
            if delta_y == 0:
                delta_y = int(event.pixelDelta().y())
            if delta_y != 0:
                self.owner.zoom_from_pointer_delta(delta_y, event.position())
                event.accept()
                return
        super().wheelEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.NativeGesture:
            if (
                isinstance(event, QNativeGestureEvent)
                and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture
            ):
                self.owner.zoom_from_pinch_delta(
                    float(event.value()),
                    event.position(),
                )
                event.accept()
                return True
        return super().viewportEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Left:
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.owner.nudge_selection("resize_start", -1)
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.owner.nudge_selection("resize_end", -1)
                event.accept()
                return
            self.owner.nudge_selection("move", -1)
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.owner.nudge_selection("resize_start", 1)
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.owner.nudge_selection("resize_end", 1)
                event.accept()
                return
            self.owner.nudge_selection("move", 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.itemAt(event.position().toPoint()) is None
        ):
            self.owner.create_task_at_scene_pos(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TimelineHeaderWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._range_start: date | None = None
        self._range_end: date | None = None
        self._pixels_per_day = GANTT_SCALE_PRESETS["week"][1]
        self._scroll_x = 0
        self._reserved_right = 0
        self.setMinimumHeight(HEADER_HEIGHT)
        self.setMaximumHeight(HEADER_HEIGHT)
        self.setAutoFillBackground(True)

    def set_range(self, range_start: date | None, range_end: date | None, pixels_per_day: float):
        self._range_start = range_start
        self._range_end = range_end
        self._pixels_per_day = float(max(2.0, pixels_per_day))
        self.update()

    def set_scroll_x(self, value: int):
        self._scroll_x = int(value)
        self.update()

    def set_reserved_right(self, value: int):
        self._reserved_right = max(0, int(value))
        self.update()

    def _major_band_height(self) -> int:
        metrics = QFontMetrics(self.font())
        return max(22, metrics.height() + 8)

    def _major_band_rect(self) -> QRect:
        return QRect(0, 0, self.width(), self._major_band_height())

    def _minor_band_rect(self) -> QRect:
        top = self._major_band_height()
        return QRect(0, top, self.width(), max(0, self.height() - top))

    def _today_badge_rect(self) -> QRect:
        major_band = self._major_band_rect()
        metrics = QFontMetrics(self.font())
        badge_text = "Today"
        preferred = max(72, metrics.horizontalAdvance(badge_text) + 18)
        available_right = max(6, self.width() - self._reserved_right)
        width = min(preferred, max(72, int(available_right * 0.24)))
        height = max(18, metrics.height() + 6)
        return QRect(
            max(6, available_right - width - 8),
            max(3, major_band.top() + 3),
            width,
            min(height, max(18, major_band.height() - 6)),
        )

    @staticmethod
    def _month_start(value: date) -> date:
        return date(value.year, value.month, 1)

    @staticmethod
    def _next_month(value: date) -> date:
        if value.month == 12:
            return date(value.year + 1, 1, 1)
        return date(value.year, value.month + 1, 1)

    @staticmethod
    def _major_label_for(value: date) -> str:
        return value.strftime("%B %Y")

    @staticmethod
    def _minor_label_for(value: date) -> str:
        return str(value.day)

    def _draw_label(
        self,
        painter: QPainter,
        rect: QRectF,
        text: str,
        *,
        alignment: Qt.AlignmentFlag | Qt.Alignment = (
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        ),
        padding: int = 6,
    ):
        if rect.width() <= (padding * 2) or rect.height() <= 4:
            return
        painter.save()
        painter.setClipRect(rect)
        font, _metrics, elided = _text_layout(
            self.font(),
            str(text or ""),
            rect.width(),
            rect.height(),
            padding_x=float(padding),
        )
        painter.setFont(font)
        painter.drawText(
            rect.adjusted(padding, 0, -padding, 0),
            alignment,
            elided,
        )
        painter.restore()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = self.rect()
        major_band = self._major_band_rect()
        minor_band = self._minor_band_rect()
        border_color = self.palette().mid().color()
        text_color = self.palette().text().color()
        major_bg = self.palette().window().color()
        minor_bg = self.palette().base().color().lighter(102)

        painter.fillRect(rect, major_bg)
        painter.fillRect(major_band, major_bg)
        painter.fillRect(minor_band, minor_bg)

        if self._range_start is None or self._range_end is None:
            painter.setPen(text_color)
            self._draw_label(
                painter,
                rect.adjusted(0, 0, 0, -1),
                "Timeline",
                alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                padding=8,
            )
            painter.setPen(border_color)
            painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
            return

        view_width = self.width()

        painter.setPen(border_color)
        painter.drawLine(0, major_band.bottom(), self.width(), major_band.bottom())
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

        today = today_local()
        today_badge = QRect()
        if self._range_start <= today <= self._range_end:
            today_x = int(
                round(
                    ((today - self._range_start).days * self._pixels_per_day)
                    - self._scroll_x
                )
            )
            today_rect = QRect(
                today_x,
                0,
                max(2, int(round(self._pixels_per_day))),
                self.height(),
            )
            painter.fillRect(today_rect, QColor(239, 68, 68, 28))
            painter.setPen(QPen(QColor("#DC2626"), 1))
            painter.drawLine(
                today_x,
                major_band.bottom() + 1,
                today_x,
                self.height(),
            )
            painter.drawLine(today_x, 0, today_x, max(0, major_band.height() - 4))
            today_badge = self._today_badge_rect()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#DC2626"))
            painter.drawRoundedRect(today_badge, 8, 8)
            painter.setPen(QColor("#F9FAFB"))
            painter.save()
            badge_text = "Today"
            badge_font, _badge_metrics, badge_label = _text_layout(
                self.font(),
                badge_text,
                float(today_badge.width()),
                float(today_badge.height()),
                padding_x=9.0,
                padding_y=2.0,
            )
            painter.setFont(badge_font)
            painter.drawText(
                today_badge.adjusted(8, 0, -8, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                badge_label,
            )
            painter.restore()

        def scene_x_for(day_value: date) -> int:
            return int(
                round(
                    ((day_value - self._range_start).days * self._pixels_per_day)
                    - self._scroll_x
                )
            )

        current = self._month_start(self._range_start)
        painter.setPen(text_color)
        while current <= self._range_end:
            next_current = self._next_month(current)
            label = self._major_label_for(current)
            start_x = scene_x_for(current)
            end_x = scene_x_for(next_current)
            band_rect = QRectF(
                start_x,
                major_band.top(),
                max(0.0, float(end_x - start_x)),
                float(major_band.height()),
            )
            if band_rect.right() < 0 or band_rect.left() > view_width:
                current = next_current
                continue
            if today_badge.isValid() and band_rect.intersects(QRectF(today_badge)):
                band_rect.setRight(min(band_rect.right(), float(today_badge.left() - 6)))
            self._draw_label(
                painter,
                band_rect,
                label,
                alignment=Qt.AlignmentFlag.AlignCenter,
                padding=8,
            )
            current = next_current

        current = self._range_start
        while current <= self._range_end:
            x = scene_x_for(current)
            next_x = scene_x_for(current + timedelta(days=1))
            if x < -48 or x > view_width + 48:
                current += timedelta(days=1)
                continue
            painter.setPen(border_color)
            painter.drawLine(x, minor_band.top(), x, self.height())
            painter.setPen(text_color)
            label = self._minor_label_for(current)
            self._draw_label(
                painter,
                QRectF(
                    x,
                    minor_band.top(),
                    max(0.0, float(next_x - x)),
                    float(minor_band.height()),
                ),
                label,
                alignment=Qt.AlignmentFlag.AlignCenter,
                padding=3,
            )
            current += timedelta(days=1)


class PlannerScene(QGraphicsScene):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, self.owner.palette().base())
        range_start = self.owner.range_start
        if range_start is None:
            return

        first_row = max(0, int(rect.top() // ROW_HEIGHT))
        last_row = int(rect.bottom() // ROW_HEIGHT) + 1
        selected_uid = self.owner.selected_uid
        for row_index in range(first_row, min(last_row, len(self.owner.visible_rows))):
            y = row_index * ROW_HEIGHT
            row_rect = QRectF(rect.left(), y, rect.width(), ROW_HEIGHT)
            if row_index % 2 == 0:
                painter.fillRect(row_rect, self.owner.palette().alternateBase())
            row = self.owner.visible_rows[row_index]
            if selected_uid and str(row.get("uid") or "") == selected_uid:
                painter.fillRect(row_rect, QColor(59, 130, 246, 30))

        if self.owner.range_end is None:
            return
        total_days = max(1, (self.owner.range_end - range_start).days)
        for offset in range(total_days + 1):
            day = range_start + timedelta(days=offset)
            x = offset * self.owner.pixels_per_day
            col_rect = QRectF(x, rect.top(), self.owner.pixels_per_day, rect.height())
            if day.weekday() >= 5:
                painter.fillRect(col_rect, QColor(17, 24, 39, 18))
            painter.setPen(QPen(self.owner.palette().mid().color(), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        today = today_local()
        if range_start <= today <= self.owner.range_end:
            x = ((today - range_start).days * self.owner.pixels_per_day)
            painter.setPen(QPen(QColor("#DC2626"), 2))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))


class TimelineBarItem(QGraphicsItem):
    def __init__(self, owner, row: dict, y: float):
        super().__init__()
        self.owner = owner
        self.row = row
        self.y = float(y)
        self.preview_start = _ensure_date(str(row.get("display_start_date") or row.get("start_date") or None))
        self.preview_end = _ensure_date(str(row.get("display_end_date") or row.get("end_date") or None))
        self._drag_mode: str | None = None
        self._press_scene = QPointF()
        self._press_start = self.preview_start
        self._press_end = self.preview_end
        self.setAcceptHoverEvents(True)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, False)
        self.setZValue(4)
        self.setToolTip(self._tooltip_text())

    @property
    def uid(self) -> str:
        return str(self.row.get("uid") or "")

    def _tooltip_text(self) -> str:
        start = str(self.row.get("display_start_date") or self.row.get("start_date") or "–")
        end = str(self.row.get("display_end_date") or self.row.get("end_date") or "–")
        blocked = "Blocked" if bool(self.row.get("blocked")) else "Active"
        return (
            f"{str(self.row.get('label') or '')}\n"
            f"{str(self.row.get('kind') or '').title()} | {blocked}\n"
            f"{start} -> {end}"
        )

    def dates(self) -> tuple[date | None, date | None]:
        return self.preview_start, self.preview_end

    def set_dates(self, start: date | None, end: date | None):
        self.prepareGeometryChange()
        self.preview_start = start
        self.preview_end = end
        self.update()

    def base_rect(self) -> QRectF:
        return self.owner.bar_rect_for_row(self.row, self.preview_start, self.preview_end, self.y)

    def _label_font_metrics(self) -> QFontMetricsF:
        return QFontMetricsF(QApplication.font())

    def _label_box_height(self) -> float:
        metrics = self._label_font_metrics()
        return max(18.0, metrics.height() + (BAR_TEXT_PADDING_Y * 2.0))

    def _preferred_label_width(self) -> float:
        metrics = self._label_font_metrics()
        text = str(self.row.get("label") or "")
        return min(260.0, max(72.0, metrics.horizontalAdvance(text) + (BAR_TEXT_PADDING_X * 2.0)))

    def _use_external_text_label(self) -> bool:
        style = str(self.row.get("render_style") or "")
        if style not in {"task", "deliverable"}:
            return False
        rect = self.base_rect()
        text = str(self.row.get("label") or "")
        internal_width = rect.width() - (BAR_TEXT_PADDING_X * 2.0)
        metrics = self._label_font_metrics()
        if metrics.horizontalAdvance(text) > max(0.0, internal_width):
            return True
        return internal_width < 36.0

    def _external_label_rect(self) -> QRectF:
        rect = self.base_rect()
        height = self._label_box_height()
        width = self._preferred_label_width()
        top = rect.center().y() - (height / 2.0)
        return QRectF(rect.right() + 6.0, top, width, height)

    def _milestone_label_rect(self) -> QRectF:
        rect = self.base_rect()
        if not str(self.row.get("label") or ""):
            return QRectF()
        width = self._preferred_label_width()
        height = self._label_box_height()
        return QRectF(
            rect.right() + 6.0,
            rect.center().y() - (height / 2.0),
            width,
            height,
        )

    def boundingRect(self) -> QRectF:
        rect = self.base_rect()
        bounds = rect.adjusted(-8, -4, 8, 4)
        style = str(self.row.get("render_style") or "")
        if style == "milestone":
            bounds = bounds.united(self._milestone_label_rect().adjusted(-2, -2, 2, 2))
        elif self._use_external_text_label():
            bounds = bounds.united(self._external_label_rect().adjusted(-2, -2, 2, 2))
        return bounds

    def anchor_start(self) -> QPointF:
        rect = self.base_rect()
        return QPointF(rect.left(), rect.center().y())

    def anchor_end(self) -> QPointF:
        rect = self.base_rect()
        return QPointF(rect.right(), rect.center().y())

    def _handle_mode(self, pos: QPointF) -> str | None:
        if not self.owner.row_is_editable(self.row):
            return None
        style = str(self.row.get("render_style") or "")
        rect = self.base_rect()
        local_x = pos.x()
        if style == "task":
            if abs(local_x - rect.left()) <= HANDLE_WIDTH:
                return "resize_start"
            if abs(local_x - rect.right()) <= HANDLE_WIDTH:
                return "resize_end"
        return "move"

    def hoverMoveEvent(self, event):
        mode = self._handle_mode(event.pos())
        if mode == "resize_start" or mode == "resize_end":
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif mode == "move":
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.owner.select_uid(self.uid, from_chart=False, ensure_visible=False)
        self._drag_mode = self._handle_mode(event.pos())
        if self._drag_mode is None:
            self._drag_mode = "select_only"
            event.accept()
            return
        self._press_scene = event.scenePos()
        self._press_start = self.preview_start
        self._press_end = self.preview_end
        self.setCursor(Qt.CursorShape.ClosedHandCursor if self._drag_mode == "move" else Qt.CursorShape.SizeHorCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_mode == "select_only":
            event.accept()
            return
        if not self._drag_mode or self._press_start is None or self._press_end is None:
            super().mouseMoveEvent(event)
            return
        delta_days = self.owner.days_from_scene_delta(event.scenePos().x() - self._press_scene.x())
        if delta_days == 0:
            return
        start = self._press_start
        end = self._press_end
        if self._drag_mode == "move":
            start = start + timedelta(days=delta_days)
            end = end + timedelta(days=delta_days)
        elif self._drag_mode == "resize_start":
            candidate = start + timedelta(days=delta_days)
            start = min(candidate, end)
        elif self._drag_mode == "resize_end":
            candidate = end + timedelta(days=delta_days)
            end = max(start, candidate)
        self.owner.preview_row_dates(self.uid, start, end)
        event.accept()

    def mouseReleaseEvent(self, event):
        if not self._drag_mode:
            super().mouseReleaseEvent(event)
            return
        if self._drag_mode == "select_only":
            self.owner.emit_chart_selection(self.uid)
            self._drag_mode = None
            event.accept()
            return
        owner = self.owner
        uid = self.uid
        start = self.preview_start
        end = self.preview_end
        self._drag_mode = None
        self.unsetCursor()
        event.accept()
        QTimer.singleShot(0, lambda: owner.finalize_interaction(uid, start, end))

    def mouseDoubleClickEvent(self, event):
        self.owner.activate_row(self.row)
        event.accept()

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.base_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        row = self.row
        color = self.owner.bar_color_for_row(row)
        border = self.owner.bar_border_for_row(row)
        text_color = _best_contrast(color)
        style = str(row.get("render_style") or "task")
        is_selected = self.owner.selected_uid == self.uid
        metrics = self._label_font_metrics()
        base_font = QApplication.font()

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border, 1.4 if not is_selected else 2.2))
        painter.setBrush(color)

        if style == "milestone":
            center = rect.center()
            radius = min(rect.height() * 0.55, 7.5)
            diamond = QPolygonF(
                [
                    QPointF(center.x(), center.y() - radius),
                    QPointF(center.x() + radius, center.y()),
                    QPointF(center.x(), center.y() + radius),
                    QPointF(center.x() - radius, center.y()),
                ]
            )
            painter.drawPolygon(diamond)
            label_rect = self._milestone_label_rect()
            if not label_rect.isEmpty():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.owner.palette().base().color().rgba()))
                painter.drawRoundedRect(label_rect, 5, 5)
                painter.setPen(self.owner.palette().text().color())
                painter.save()
                label_font, _label_metrics, label_text = _text_layout(
                    base_font,
                    str(row.get("label") or ""),
                    label_rect.width(),
                    label_rect.height(),
                    padding_x=BAR_TEXT_PADDING_X,
                    padding_y=BAR_TEXT_PADDING_Y,
                )
                painter.setFont(label_font)
                painter.drawText(
                    label_rect.adjusted(BAR_TEXT_PADDING_X, 0, -BAR_TEXT_PADDING_X, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label_text,
                )
                painter.restore()
        elif style == "deliverable":
            painter.drawRoundedRect(rect, 6, 6)
            if self._use_external_text_label():
                label_rect = self._external_label_rect()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.owner.palette().base().color().rgba()))
                painter.drawRoundedRect(label_rect, 5, 5)
                painter.setPen(self.owner.palette().text().color())
                painter.save()
                label_font, _label_metrics, label_text = _text_layout(
                    base_font,
                    str(row.get("label") or ""),
                    label_rect.width(),
                    label_rect.height(),
                    padding_x=BAR_TEXT_PADDING_X,
                    padding_y=BAR_TEXT_PADDING_Y,
                )
                painter.setFont(label_font)
                painter.drawText(
                    label_rect.adjusted(
                        BAR_TEXT_PADDING_X,
                        0,
                        -BAR_TEXT_PADDING_X,
                        0,
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label_text,
                )
                painter.restore()
            else:
                painter.setPen(text_color)
                painter.save()
                label_font, _label_metrics, label_text = _text_layout(
                    base_font,
                    str(row.get("label") or ""),
                    rect.width(),
                    rect.height(),
                    padding_x=BAR_TEXT_PADDING_X,
                    padding_y=BAR_TEXT_PADDING_Y,
                )
                painter.setFont(label_font)
                painter.drawText(
                    rect.adjusted(
                        BAR_TEXT_PADDING_X,
                        0,
                        -BAR_TEXT_PADDING_X,
                        0,
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label_text,
                )
                painter.restore()
        elif style == "summary":
            path = QPainterPath()
            path.moveTo(rect.left(), rect.center().y())
            path.lineTo(rect.left() + 10, rect.top())
            path.lineTo(rect.right() - 10, rect.top())
            path.lineTo(rect.right(), rect.center().y())
            path.lineTo(rect.right() - 10, rect.bottom())
            path.lineTo(rect.left() + 10, rect.bottom())
            path.closeSubpath()
            painter.drawPath(path)
            painter.setPen(text_color)
            painter.save()
            label_font, _label_metrics, label_text = _text_layout(
                base_font,
                str(row.get("label") or ""),
                rect.width(),
                rect.height(),
                padding_x=10.0,
                padding_y=BAR_TEXT_PADDING_Y,
            )
            painter.setFont(label_font)
            painter.drawText(
                rect.adjusted(10, 0, -10, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label_text,
            )
            painter.restore()
        else:
            painter.drawRoundedRect(rect, 5, 5)
            progress = max(0, min(100, int(row.get("progress_percent") or 0)))
            if progress > 0 and progress < 100:
                fill_rect = QRectF(rect)
                fill_rect.setWidth(max(4.0, rect.width() * (progress / 100.0)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 45))
                painter.drawRoundedRect(fill_rect, 5, 5)
                painter.setPen(QPen(border, 1.4 if not is_selected else 2.2))
                painter.setBrush(color)
            if self._use_external_text_label():
                label_rect = self._external_label_rect()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.owner.palette().base().color().rgba()))
                painter.drawRoundedRect(label_rect, 5, 5)
                painter.setPen(self.owner.palette().text().color())
                painter.save()
                label_font, _label_metrics, label_text = _text_layout(
                    base_font,
                    str(row.get("label") or ""),
                    label_rect.width(),
                    label_rect.height(),
                    padding_x=BAR_TEXT_PADDING_X,
                    padding_y=BAR_TEXT_PADDING_Y,
                )
                painter.setFont(label_font)
                painter.drawText(
                    label_rect.adjusted(
                        BAR_TEXT_PADDING_X,
                        0,
                        -BAR_TEXT_PADDING_X,
                        0,
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label_text,
                )
                painter.restore()
            else:
                painter.setPen(text_color)
                painter.save()
                label_font, _label_metrics, label_text = _text_layout(
                    base_font,
                    str(row.get("label") or ""),
                    rect.width(),
                    rect.height(),
                    padding_x=BAR_TEXT_PADDING_X,
                    padding_y=BAR_TEXT_PADDING_Y,
                )
                painter.setFont(label_font)
                painter.drawText(
                    rect.adjusted(
                        BAR_TEXT_PADDING_X,
                        0,
                        -BAR_TEXT_PADDING_X,
                        0,
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label_text,
                )
                painter.restore()

        baseline = _ensure_date(str(row.get("baseline_date") or None))
        if baseline is not None and self.owner.range_start is not None:
            baseline_x = self.owner.date_to_scene_x(baseline)
            painter.setPen(QPen(QColor("#111827"), 2))
            painter.drawLine(
                QPointF(baseline_x, rect.top() - 4),
                QPointF(baseline_x, rect.bottom() + 4),
            )

        if (
            is_selected
            and style not in {"milestone"}
            and self.owner.row_is_editable(row)
            and rect.width() >= 28.0
        ):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#F9FAFB"))
            left_handle = QRectF(rect.left() - HANDLE_WIDTH / 2.0, rect.top() + 2, HANDLE_WIDTH, rect.height() - 4)
            right_handle = QRectF(rect.right() - HANDLE_WIDTH / 2.0, rect.top() + 2, HANDLE_WIDTH, rect.height() - 4)
            painter.drawRoundedRect(left_handle, 2, 2)
            if style == "task":
                painter.drawRoundedRect(right_handle, 2, 2)


class ProjectGanttView(QWidget):
    recordSelected = Signal(str, int)
    recordActivated = Signal(str, int)
    scheduleEditRequested = Signal(str, int, object, object)
    dependencyEditRequested = Signal(str, int)
    taskCreateRequested = Signal(object)
    milestoneCreateRequested = Signal(object)
    deliverableCreateRequested = Signal(object)
    taskMoveRelativeRequested = Signal(int, int)
    taskMoveRequested = Signal(int, object, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dashboard: dict | None = None
        self.rows: list[dict] = []
        self.row_lookup: dict[str, dict] = {}
        self.visible_rows: list[dict] = []
        self.item_lookup: dict[str, QTreeWidgetItem] = {}
        self.bar_items: dict[str, TimelineBarItem] = {}
        self.connector_items: list[QGraphicsPathItem] = []
        self.selected_uid: str | None = None
        self._collapsed_uids: set[str] = set()
        self._suspend_tree_selection_emit = False
        self.range_start: date | None = None
        self.range_end: date | None = None
        self.pixels_per_day = GANTT_SCALE_PRESETS["week"][1]
        self._zoom_mode = "preset"
        self._zoom_preset_key = "week"

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(0, 0, 0, 0), spacing=6)

        controls_panel = QWidget()
        controls_panel.setSizePolicy(
            controls_panel.sizePolicy().horizontalPolicy(),
            controls_panel.sizePolicy().verticalPolicy(),
        )
        controls_root = QVBoxLayout(controls_panel)
        configure_box_layout(controls_root, spacing=4)

        controls = QHBoxLayout()
        configure_box_layout(controls, spacing=6)
        self.zoom_out_btn = QToolButton()
        self.zoom_in_btn = QToolButton()
        self._configure_zoom_button(
            self.zoom_out_btn,
            fallback_text="Zoom out",
            icon_name="zoom-out",
            tooltip="Zoom out the timeline",
        )
        self._configure_zoom_button(
            self.zoom_in_btn,
            fallback_text="Zoom in",
            icon_name="zoom-in",
            tooltip="Zoom in on the timeline",
        )
        self.scale_combo = QComboBox()
        for key, (label, _pixels) in GANTT_SCALE_PRESETS.items():
            self.scale_combo.addItem(label, key)
        self.scale_combo.addItem("Custom", None)
        self.today_btn = QPushButton("Today")
        self.jump_selected_btn = QPushButton("Selected")
        self.fit_project_btn = QPushButton("Fit project")
        self.fit_selection_btn = QPushButton("Fit selection")
        self.expand_btn = QPushButton("Expand all")
        self.collapse_btn = QPushButton("Collapse all")
        self.zoom_state_label = QLabel()
        self.zoom_state_label.setTextFormat(Qt.TextFormat.PlainText)
        self.zoom_state_label.setMinimumWidth(190)
        self.zoom_state_label.setToolTip(
            "Current timeline zoom state. Presets, fit modes, wheel zoom, and "
            "buttons all update this indicator."
        )
        self.summary_label = QLabel("Select a chart row to inspect and edit its schedule.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setMinimumWidth(260)
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.summary_label.setToolTip(
            "Chart interactions: drag bars to move them, drag task handles to resize, "
            "double-click to focus the item, and right-click for timeline actions."
        )
        _configure_combo_for_contents(self.scale_combo)
        for button in (
            self.today_btn,
            self.jump_selected_btn,
            self.fit_project_btn,
            self.fit_selection_btn,
            self.expand_btn,
            self.collapse_btn,
        ):
            _fit_button_to_text(button)
        add_left_aligned_buttons(
            controls,
            self.today_btn,
            self.jump_selected_btn,
            self.fit_project_btn,
            self.fit_selection_btn,
            self.expand_btn,
            self.collapse_btn,
            trailing_stretch=False,
        )
        self.zoom_panel = QWidget()
        self.zoom_panel.setObjectName("GanttZoomPanel")
        self.zoom_panel.setToolTip(
            "Timeline zoom controls. Use the preset selector, zoom buttons, "
            "Command/Ctrl + mouse wheel, or trackpad pinch to change the "
            "visible timeline scale."
        )
        zoom_panel_layout = QHBoxLayout(self.zoom_panel)
        configure_box_layout(
            zoom_panel_layout,
            margins=(0, 0, 0, 0),
            spacing=6,
        )
        zoom_panel_layout.addWidget(self.zoom_state_label)
        zoom_panel_layout.addWidget(self.scale_combo)
        zoom_panel_layout.addWidget(self.zoom_out_btn)
        zoom_panel_layout.addWidget(self.zoom_in_btn)
        controls.addStretch(1)
        controls.addWidget(self.zoom_panel)
        controls_root.addLayout(controls)
        controls_root.addWidget(self.summary_label)
        root.addWidget(controls_panel)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        configure_box_layout(left_layout)
        self.structure_header = QLabel("Structure")
        self.structure_header.setObjectName("GanttStructureHeader")
        left_layout.addWidget(self.structure_header)
        self.tree = TimelineTreeWidget()
        left_layout.addWidget(self.tree, 1)
        self.splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        configure_box_layout(right_layout)
        self.header = TimelineHeaderWidget()
        right_layout.addWidget(self.header)
        self.scene = PlannerScene(self)
        self.view = PlannerGraphicsView(self, self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.view.setFrameShape(self.view.Shape.NoFrame)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        right_layout.addWidget(self.view, 1)
        self.splitter.addWidget(right_panel)
        self.splitter.setSizes([LEFT_COLUMN_WIDTH, 760])

        self.zoom_out_btn.clicked.connect(lambda: self._step_zoom(-1))
        self.zoom_in_btn.clicked.connect(lambda: self._step_zoom(1))
        self.scale_combo.currentIndexChanged.connect(self._apply_scale_from_combo)
        self.today_btn.clicked.connect(self.jump_to_today)
        self.jump_selected_btn.clicked.connect(self.jump_to_selection)
        self.fit_project_btn.clicked.connect(self.fit_project)
        self.fit_selection_btn.clicked.connect(self.fit_selection)
        self.expand_btn.clicked.connect(self.expand_all)
        self.collapse_btn.clicked.connect(self.collapse_all)
        self.tree.currentItemChanged.connect(self._on_tree_selection_changed)
        self.tree.rowActivated.connect(self.recordActivated.emit)
        self.tree.taskMoveRequested.connect(self.taskMoveRequested.emit)
        self.tree.itemExpanded.connect(self._on_tree_expanded)
        self.tree.itemCollapsed.connect(self._on_tree_collapsed)
        self.tree.verticalScrollBar().valueChanged.connect(self._sync_tree_to_chart_scroll)
        self.view.verticalScrollBar().valueChanged.connect(self._sync_chart_to_tree_scroll)
        self.view.horizontalScrollBar().valueChanged.connect(self.header.set_scroll_x)
        self.view.customContextMenuRequested.connect(self._open_context_menu_at)
        self._sync_zoom_controls()

    def sizeHint(self) -> QSize:
        return QSize(960, 420)

    def minimumSizeHint(self) -> QSize:
        return QSize(680, 320)

    def bar_color_for_row(self, row: dict) -> QColor:
        style = str(row.get("render_style") or "task")
        status = str(row.get("status") or "").strip().lower()
        blocked = bool(row.get("blocked"))
        display_end = _ensure_date(str(row.get("display_end_date") or row.get("end_date") or None))
        is_overdue = bool(display_end is not None and display_end < today_local() and status not in {"completed", "done"})
        if style == "summary":
            kind = str(row.get("kind") or "")
            if kind == "project":
                health = str(row.get("status") or "").strip().lower()
                palette = {
                    "on_track": QColor("#16A34A"),
                    "at_risk": QColor("#F59E0B"),
                    "delayed": QColor("#DC2626"),
                    "blocked": QColor("#B91C1C"),
                    "awaiting_external_input": QColor("#D97706"),
                    "scope_drifting": QColor("#7C3AED"),
                }
                return palette.get(health, QColor("#2563EB"))
            return QColor("#4B5563")
        if blocked:
            return QColor("#DC2626")
        if status in {"completed", "done", "on_track"}:
            return QColor("#16A34A")
        if is_overdue:
            return QColor("#F97316")
        if style == "milestone":
            return QColor("#7C3AED")
        if style == "deliverable":
            return QColor("#0F766E")
        return QColor("#2563EB")

    def bar_border_for_row(self, row: dict) -> QColor:
        color = self.bar_color_for_row(row)
        return color.darker(130)

    def row_is_editable(self, row: dict) -> bool:
        return bool(row.get("editable_move") or row.get("editable_start") or row.get("editable_end"))

    def set_dashboard(self, dashboard: dict | None):
        self._dashboard = dashboard or {}
        self.rows = list((self._dashboard or {}).get("timeline_rows") or [])
        self.row_lookup = {str(row.get("uid") or ""): row for row in self.rows}
        self._rebuild_tree()
        self._rebuild_chart()
        self._update_summary_label()

    def set_active_task(self, task_id: int | None):
        if task_id is None:
            return
        self.select_item("task", int(task_id), ensure_visible=False)

    def expand_all(self):
        self.tree.expandAll()
        self._collapsed_uids.clear()
        self._rebuild_chart()

    def collapse_all(self):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None:
                item.setExpanded(True)
                for child_index in range(item.childCount()):
                    child = item.child(child_index)
                    if child is not None:
                        child.setExpanded(False)
                        uid = str(child.data(0, Qt.ItemDataRole.UserRole) or "")
                        if uid:
                            self._collapsed_uids.add(uid)
        self._rebuild_chart()

    def _rebuild_tree(self):
        self.tree.blockSignals(True)
        current_uid = self.selected_uid
        self.tree.clear()
        self.item_lookup = {}
        children_map: dict[str | None, list[dict]] = {}
        for row in self.rows:
            parent_uid = str(row.get("parent_uid")) if row.get("parent_uid") is not None else None
            children_map.setdefault(parent_uid, []).append(row)
        for bucket in children_map.values():
            bucket.sort(key=lambda row: (int(row.get("sort_index") or 0), str(row.get("label") or "").lower()))

        def add_children(parent_item: QTreeWidgetItem | None, parent_uid: str | None):
            for row in children_map.get(parent_uid, []):
                item = QTreeWidgetItem([_row_label(row)])
                uid = str(row.get("uid") or "")
                item.setData(0, Qt.ItemDataRole.UserRole, uid)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, str(row.get("kind") or ""))
                item.setData(0, Qt.ItemDataRole.UserRole + 2, int(row.get("item_id") or 0))
                item.setData(0, Qt.ItemDataRole.UserRole + 3, dict(row))
                font = QFont(self.tree.font())
                if row.get("summary_row"):
                    font.setBold(True)
                item.setFont(0, font)
                tip = self._row_tooltip(row)
                item.setToolTip(0, tip)
                if parent_item is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                self.item_lookup[uid] = item
                add_children(item, uid)
                item.setExpanded(uid not in self._collapsed_uids)

        add_children(None, None)
        self.tree.blockSignals(False)
        if current_uid:
            self._select_uid_in_tree(current_uid, ensure_visible=False)

    def _rebuild_chart(self):
        self.visible_rows = []
        self.bar_items = {}
        self.connector_items = []
        self.scene.clear()
        self._collect_visible_rows()
        self._update_range()
        self.header.set_range(self.range_start, self.range_end, self.pixels_per_day)
        if not self.visible_rows or self.range_start is None or self.range_end is None:
            self.scene.setSceneRect(0, 0, 240, 220)
            return

        total_days = max(1, (self.range_end - self.range_start).days + 1)
        width = (total_days * self.pixels_per_day) + 64
        height = max(220, len(self.visible_rows) * ROW_HEIGHT)
        self.scene.setSceneRect(0, 0, width, height)

        for index, row in enumerate(self.visible_rows):
            y = float(index * ROW_HEIGHT)
            if _ensure_date(str(row.get("display_start_date") or row.get("start_date") or None)) is None:
                continue
            item = TimelineBarItem(self, row, y)
            self.scene.addItem(item)
            self.bar_items[str(row.get("uid") or "")] = item

        self._rebuild_dependency_paths()
        self._update_summary_label()
        if self.selected_uid:
            self._ensure_selection_visible()

    def _collect_visible_rows(self):
        def walk(item: QTreeWidgetItem):
            uid = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            row = self.row_lookup.get(uid)
            if row is None:
                return
            self.visible_rows.append(row)
            if item.isExpanded():
                for i in range(item.childCount()):
                    walk(item.child(i))

        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            if top is not None:
                walk(top)

    def _update_range(self):
        all_dates: list[date] = [today_local()]
        for row in self.visible_rows:
            for key in ("display_start_date", "display_end_date", "baseline_date"):
                parsed = _ensure_date(str(row.get(key) or None))
                if parsed is not None:
                    all_dates.append(parsed)
        if not all_dates:
            self.range_start = None
            self.range_end = None
            return
        self.range_start = min(all_dates) - timedelta(days=DAY_MARGIN_BEFORE)
        self.range_end = max(all_dates) + timedelta(days=DAY_MARGIN_AFTER)
        if self.range_end <= self.range_start:
            self.range_end = self.range_start + timedelta(days=1)

    def _row_tooltip(self, row: dict) -> str:
        parts = [
            str(row.get("kind") or "").title(),
            str(row.get("status") or "").replace("_", " ").title() if row.get("status") else "",
        ]
        if row.get("phase_name"):
            parts.append(str(row.get("phase_name")))
        return "\n".join(part for part in parts if part)

    def date_to_scene_x(self, value: date) -> float:
        if self.range_start is None:
            return 0.0
        return float((value - self.range_start).days * self.pixels_per_day) + 24.0

    def scene_x_to_date(self, scene_x: float) -> date:
        if self.range_start is None:
            return today_local()
        days = int(round((float(scene_x) - 24.0) / self.pixels_per_day))
        return self.range_start + timedelta(days=days)

    def days_from_scene_delta(self, delta_x: float) -> int:
        return int(round(float(delta_x) / self.pixels_per_day))

    def row_index_for_uid(self, uid: str) -> int:
        for index, row in enumerate(self.visible_rows):
            if str(row.get("uid") or "") == str(uid):
                return index
        return -1

    def bar_rect_for_row(
        self,
        row: dict,
        start_date: date | None,
        end_date: date | None,
        y: float,
    ) -> QRectF:
        if start_date is None:
            return QRectF()
        effective_end = end_date or start_date
        start_x = self.date_to_scene_x(start_date)
        end_x = self.date_to_scene_x(effective_end + timedelta(days=1))
        width = max(10.0, end_x - start_x)
        style = str(row.get("render_style") or "")
        text_height = max(
            18.0,
            QFontMetricsF(QApplication.font()).height() + (BAR_TEXT_PADDING_Y * 2.0),
        )
        if style == "milestone":
            diamond_size = min(float(ROW_HEIGHT - 8), max(14.0, text_height - 2.0))
            top = y + ((ROW_HEIGHT - diamond_size) / 2.0)
            return QRectF(start_x - (diamond_size / 2.0), top, diamond_size, diamond_size)
        if style == "summary":
            bar_height = min(float(ROW_HEIGHT - 8), max(16.0, text_height))
            top = y + ((ROW_HEIGHT - bar_height) / 2.0)
            return QRectF(start_x, top, width, bar_height)
        if style == "deliverable":
            bar_height = min(float(ROW_HEIGHT - 8), max(16.0, text_height))
            top = y + ((ROW_HEIGHT - bar_height) / 2.0)
            return QRectF(start_x, top, max(14.0, width), bar_height)
        bar_height = min(float(ROW_HEIGHT - 8), max(16.0, text_height))
        top = y + ((ROW_HEIGHT - bar_height) / 2.0)
        return QRectF(start_x, top, width, bar_height)

    def _rebuild_dependency_paths(self):
        for item in self.connector_items:
            self.scene.removeItem(item)
        self.connector_items = []
        if not self._dashboard:
            return
        for dep in self._dashboard.get("dependencies") or []:
            predecessor_uid = _timeline_uid(dep.get("predecessor_kind"), int(dep.get("predecessor_id") or 0))
            successor_uid = _timeline_uid(dep.get("successor_kind"), int(dep.get("successor_id") or 0))
            pre_item = self.bar_items.get(predecessor_uid)
            succ_item = self.bar_items.get(successor_uid)
            if pre_item is None or succ_item is None:
                continue
            start = pre_item.anchor_end()
            end = succ_item.anchor_start()
            mid_x = max(start.x() + 18.0, end.x() - 18.0)
            path = QPainterPath(start)
            path.lineTo(mid_x, start.y())
            path.lineTo(mid_x, end.y())
            path.lineTo(end)
            connector = QGraphicsPathItem(path)
            pen = QPen(QColor("#DC2626") if succ_item.row.get("blocked") else QColor("#64748B"), 1.4)
            if bool(dep.get("is_soft")):
                pen.setStyle(Qt.PenStyle.DashLine)
            connector.setPen(pen)
            connector.setZValue(0)
            connector.setToolTip(
                f"Dependency: {dep.get('predecessor_kind')} {dep.get('predecessor_id')} -> "
                f"{dep.get('successor_kind')} {dep.get('successor_id')}"
            )
            self.scene.addItem(connector)
            self.connector_items.append(connector)
            arrow = QGraphicsPathItem(self._arrow_path(end))
            arrow.setPen(Qt.PenStyle.NoPen)
            arrow.setBrush(pen.color())
            arrow.setZValue(0)
            self.scene.addItem(arrow)
            self.connector_items.append(arrow)

    @staticmethod
    def _arrow_path(point: QPointF) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(point)
        path.lineTo(point.x() - 6, point.y() - 4)
        path.lineTo(point.x() - 6, point.y() + 4)
        path.closeSubpath()
        return path

    @staticmethod
    def _preset_for_pixels(pixels_per_day: float) -> str | None:
        for key, (_label, preset_pixels) in GANTT_SCALE_PRESETS.items():
            if abs(float(pixels_per_day) - float(preset_pixels)) < 0.01:
                return key
        return None

    def _zoom_state_text(self) -> str:
        preset_key = self._preset_for_pixels(self.pixels_per_day)
        preset_label = (
            GANTT_SCALE_PRESETS[preset_key][0]
            if preset_key is not None
            else "Custom"
        )
        mode_label = {
            "preset": preset_label,
            "custom": f"Custom ({preset_label})",
            "fit_project": "Fit project",
            "fit_selection": "Fit selection",
        }.get(str(self._zoom_mode or "custom"), preset_label)
        return f"Zoom: {mode_label} · {self.pixels_per_day:.1f} px/day"

    def _sync_zoom_controls(self):
        preset_key = self._preset_for_pixels(self.pixels_per_day)
        self.scale_combo.blockSignals(True)
        target_index = self.scale_combo.findData(preset_key)
        if target_index < 0:
            target_index = self.scale_combo.findData(None)
        self.scale_combo.setCurrentIndex(max(0, target_index))
        self.scale_combo.blockSignals(False)
        self.zoom_state_label.setText(self._zoom_state_text())
        at_min = self.pixels_per_day <= (MIN_PIXELS_PER_DAY + 0.01)
        at_max = self.pixels_per_day >= (MAX_PIXELS_PER_DAY - 0.01)
        self.zoom_out_btn.setEnabled(not at_min)
        self.zoom_in_btn.setEnabled(not at_max)
        self.header.set_reserved_right(0)

    def _visible_center_date(self) -> date | None:
        if self.range_start is None:
            return None
        viewport_center = self.view.horizontalScrollBar().value() + (
            self.view.viewport().width() / 2.0
        )
        return self.scene_x_to_date(float(viewport_center))

    def _date_anchor_for_viewport_pos(
        self,
        viewport_pos: QPointF | QPoint | None,
    ) -> tuple[date | None, float | None]:
        if self.range_start is None or viewport_pos is None:
            return None, None
        x = float(viewport_pos.x())
        scene_x = float(self.view.horizontalScrollBar().value()) + x
        return self.scene_x_to_date(scene_x), x

    def _center_date_in_view(self, target_date: date | None):
        if target_date is None or self.range_start is None:
            return
        x = self.date_to_scene_x(target_date)
        self.view.horizontalScrollBar().setValue(
            int(max(0.0, x - (self.view.viewport().width() / 2.0)))
        )

    def _anchor_date_in_view(
        self,
        target_date: date | None,
        viewport_x: float | None,
    ):
        if (
            target_date is None
            or viewport_x is None
            or self.range_start is None
        ):
            return
        x = self.date_to_scene_x(target_date)
        self.view.horizontalScrollBar().setValue(
            int(max(0.0, x - float(viewport_x)))
        )

    def _set_zoom_pixels_per_day(
        self,
        pixels_per_day: float,
        *,
        mode: str,
        center_date: date | None = None,
        anchor_date: date | None = None,
        anchor_viewport_x: float | None = None,
    ):
        clamped = max(MIN_PIXELS_PER_DAY, min(MAX_PIXELS_PER_DAY, float(pixels_per_day)))
        self.pixels_per_day = clamped
        self._zoom_mode = str(mode or "custom")
        self._zoom_preset_key = self._preset_for_pixels(clamped)
        self._sync_zoom_controls()
        self._rebuild_chart()
        if anchor_date is not None and anchor_viewport_x is not None:
            self._anchor_date_in_view(anchor_date, anchor_viewport_x)
        elif center_date is not None:
            self._center_date_in_view(center_date)

    @staticmethod
    def _configure_zoom_button(
        button: QToolButton,
        *,
        fallback_text: str,
        icon_name: str,
        tooltip: str,
    ):
        icon = QIcon.fromTheme(icon_name)
        if not icon.isNull():
            button.setIcon(icon)
            button.setText("")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setAutoRaise(True)
            button.setMinimumSize(28, 28)
        else:
            button.setText(fallback_text)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            _fit_button_to_text(button, extra_padding=22)
        button.setToolTip(tooltip)
        button.setAccessibleName(fallback_text)

    def _apply_scale_from_combo(self):
        key = self.scale_combo.currentData()
        if key is None:
            return
        center_date = self._visible_center_date()
        self._set_zoom_pixels_per_day(
            float(GANTT_SCALE_PRESETS.get(str(key), GANTT_SCALE_PRESETS["week"])[1]),
            mode="preset",
            center_date=center_date,
        )

    def _step_zoom(self, direction: int):
        factor = 1.2 if int(direction) > 0 else (1.0 / 1.2)
        self._zoom_with_factor(factor)

    def _zoom_with_factor(
        self,
        factor: float,
        *,
        viewport_pos: QPointF | QPoint | None = None,
    ):
        anchor_date, anchor_x = self._date_anchor_for_viewport_pos(viewport_pos)
        center_date = None if anchor_date is not None else self._visible_center_date()
        self._set_zoom_pixels_per_day(
            self.pixels_per_day * float(factor),
            mode="custom",
            center_date=center_date,
            anchor_date=anchor_date,
            anchor_viewport_x=anchor_x,
        )

    def zoom_from_pointer_delta(
        self,
        delta_y: float,
        viewport_pos: QPointF | QPoint | None = None,
    ):
        if float(delta_y) == 0.0:
            return
        factor = 1.2 if float(delta_y) > 0.0 else (1.0 / 1.2)
        self._zoom_with_factor(factor, viewport_pos=viewport_pos)

    def zoom_from_pinch_delta(
        self,
        pinch_value: float,
        viewport_pos: QPointF | QPoint | None = None,
    ):
        if abs(float(pinch_value)) < 0.001:
            return
        factor = max(0.5, min(2.0, 1.0 + float(pinch_value)))
        self._zoom_with_factor(factor, viewport_pos=viewport_pos)

    def jump_to_today(self):
        if self.range_start is None:
            return
        x = self.date_to_scene_x(today_local())
        bar = self.view.horizontalScrollBar()
        bar.setValue(int(max(0.0, x - (self.view.viewport().width() / 2.0))))

    def jump_to_selection(self):
        self._ensure_selection_visible()

    def fit_project(self):
        if self.range_start is None or self.range_end is None:
            return
        width = max(1, (self.range_end - self.range_start).days + 1)
        viewport = max(240, self.view.viewport().width() - 48)
        midpoint = self.range_start + timedelta(days=max(0, width // 2))
        self._set_zoom_pixels_per_day(
            float(viewport) / float(width),
            mode="fit_project",
            center_date=midpoint,
        )

    def fit_selection(self):
        row = self.row_lookup.get(self.selected_uid or "")
        if row is None:
            self.fit_project()
            return
        start = _ensure_date(str(row.get("display_start_date") or row.get("start_date") or None))
        end = _ensure_date(str(row.get("display_end_date") or row.get("end_date") or None)) or start
        if start is None or end is None:
            self.fit_project()
            return
        span = max(1, (end - start).days + 3)
        viewport = max(240, self.view.viewport().width() - 60)
        midpoint = start + timedelta(days=max(0, span // 2))
        self._set_zoom_pixels_per_day(
            float(viewport) / float(span),
            mode="fit_selection",
            center_date=midpoint,
        )

    def preview_row_dates(self, uid: str, start: date | None, end: date | None):
        item = self.bar_items.get(str(uid))
        if item is None:
            return
        item.set_dates(start, end)
        self._rebuild_dependency_paths()

    def commit_row_dates(self, uid: str, start: date | None, end: date | None):
        row = self.row_lookup.get(str(uid))
        if row is None:
            return
        item = self.bar_items.get(str(uid))
        current_start = _ensure_date(str(row.get("display_start_date") or row.get("start_date") or None))
        current_end = _ensure_date(str(row.get("display_end_date") or row.get("end_date") or None)) or current_start
        if item is not None:
            item.set_dates(current_start, current_end)
        self._rebuild_dependency_paths()
        start_iso = start.isoformat() if start is not None else None
        end_iso = end.isoformat() if end is not None else None
        current_start_iso = current_start.isoformat() if current_start is not None else None
        current_end_iso = current_end.isoformat() if current_end is not None else None
        if start_iso == current_start_iso and end_iso == current_end_iso:
            return
        self.scheduleEditRequested.emit(str(row.get("kind") or ""), int(row.get("item_id") or 0), start_iso, end_iso)

    def finalize_interaction(self, uid: str, start: date | None, end: date | None):
        self.commit_row_dates(uid, start, end)
        self.emit_chart_selection(uid)

    def activate_row(self, row: dict):
        self.recordActivated.emit(str(row.get("kind") or ""), int(row.get("item_id") or 0))

    def select_item(self, kind: str, item_id: int, *, ensure_visible: bool = True):
        self.select_uid(_timeline_uid(kind, int(item_id)), from_chart=False, ensure_visible=ensure_visible)

    def select_uid(self, uid: str, *, from_chart: bool, ensure_visible: bool):
        target_uid = str(uid or "")
        if not target_uid:
            return
        if target_uid not in self.row_lookup:
            return
        self.selected_uid = target_uid
        self._select_uid_in_tree(target_uid, ensure_visible=ensure_visible)
        self.scene.update()
        self._update_summary_label()
        if ensure_visible:
            self._ensure_selection_visible()
        row = self.row_lookup.get(target_uid)
        if row and from_chart:
            self.recordSelected.emit(str(row.get("kind") or ""), int(row.get("item_id") or 0))

    def emit_chart_selection(self, uid: str):
        row = self.row_lookup.get(str(uid or ""))
        if row is None:
            return
        self.recordSelected.emit(str(row.get("kind") or ""), int(row.get("item_id") or 0))

    def _select_uid_in_tree(self, uid: str, *, ensure_visible: bool):
        item = self.item_lookup.get(str(uid))
        if item is None:
            return
        expanded_any = False
        parent = item.parent()
        while parent is not None:
            if not parent.isExpanded():
                parent.setExpanded(True)
                expanded_any = True
            self._collapsed_uids.discard(str(parent.data(0, Qt.ItemDataRole.UserRole) or ""))
            parent = parent.parent()
        self.tree.blockSignals(True)
        self._suspend_tree_selection_emit = True
        self.tree.setCurrentItem(item)
        self._suspend_tree_selection_emit = False
        self.tree.blockSignals(False)
        if expanded_any:
            self._rebuild_chart()
        if ensure_visible:
            self.tree.scrollToItem(item, self.tree.ScrollHint.PositionAtCenter)

    def _ensure_selection_visible(self):
        if not self.selected_uid:
            return
        item = self.bar_items.get(self.selected_uid)
        if item is None:
            return
        rect = item.base_rect()
        self.view.ensureVisible(rect.adjusted(-60, -ROW_HEIGHT, 60, ROW_HEIGHT))

    def _on_tree_selection_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None):
        del previous
        if current is None:
            return
        uid = str(current.data(0, Qt.ItemDataRole.UserRole) or "")
        row = self.row_lookup.get(uid)
        if row is None:
            return
        self.selected_uid = uid
        self.scene.update()
        self._update_summary_label()
        if self._suspend_tree_selection_emit:
            return
        self.recordSelected.emit(str(row.get("kind") or ""), int(row.get("item_id") or 0))

    def _on_tree_expanded(self, item: QTreeWidgetItem):
        uid = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        self._collapsed_uids.discard(uid)
        self._rebuild_chart()

    def _on_tree_collapsed(self, item: QTreeWidgetItem):
        uid = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if uid:
            self._collapsed_uids.add(uid)
        self._rebuild_chart()

    def _sync_tree_to_chart_scroll(self, value: int):
        bar = self.view.verticalScrollBar()
        if bar.value() == int(value):
            return
        bar.blockSignals(True)
        bar.setValue(int(value))
        bar.blockSignals(False)

    def _sync_chart_to_tree_scroll(self, value: int):
        bar = self.tree.verticalScrollBar()
        if bar.value() == int(value):
            return
        bar.blockSignals(True)
        bar.setValue(int(value))
        bar.blockSignals(False)

    def _selected_row(self) -> dict | None:
        return self.row_lookup.get(self.selected_uid or "")

    def _project_task_id(self) -> int | None:
        project = (self._dashboard or {}).get("project") or {}
        project_id = int(project.get("id") or 0)
        return project_id if project_id > 0 else None

    def _row_for_scene_pos(self, scene_pos: QPointF) -> dict | None:
        if not self.visible_rows:
            return None
        row_index = int(max(0.0, scene_pos.y()) // ROW_HEIGHT)
        if 0 <= row_index < len(self.visible_rows):
            return self.visible_rows[row_index]
        return None

    def _task_creation_payload(
        self,
        row: dict | None,
        anchor_date: date,
        *,
        child_mode: bool = False,
    ) -> dict | None:
        project_id = self._project_task_id()
        if project_id is None:
            return None
        phase_id = None
        parent_id = project_id
        if row is not None:
            item_kind = str(row.get("kind") or "").strip().lower()
            phase_id = row.get("phase_id")
            if item_kind == "task":
                if bool(child_mode):
                    parent_id = int(row.get("item_id") or 0) or project_id
                    phase_id = row.get("phase_id")
                else:
                    parent_id = row.get("actual_parent_task_id")
                    if parent_id is None:
                        parent_id = project_id
                    else:
                        parent_id = int(parent_id)
            elif item_kind == "project":
                parent_id = project_id
                phase_id = None
            elif item_kind == "phase":
                parent_id = project_id
                phase_id = None if int(row.get("item_id") or -1) <= 0 else int(
                    row.get("item_id") or 0
                )
            else:
                parent_id = project_id
        return {
            "project_task_id": int(project_id),
            "parent_id": int(parent_id),
            "phase_id": None if phase_id is None else int(phase_id),
            "start_date": anchor_date.isoformat(),
            "due_date": anchor_date.isoformat(),
            "description": "New task",
        }

    def _milestone_creation_payload(self, row: dict | None, anchor_date: date) -> dict | None:
        project_id = self._project_task_id()
        if project_id is None:
            return None
        phase_id = row.get("phase_id") if row is not None else None
        if row is not None and str(row.get("kind") or "").strip().lower() == "phase":
            phase_id = None if int(row.get("item_id") or -1) <= 0 else int(
                row.get("item_id") or 0
            )
        return {
            "project_task_id": int(project_id),
            "title": "",
            "description": "",
            "phase_id": None if phase_id is None else int(phase_id),
            "linked_task_id": None,
            "start_date": anchor_date.isoformat(),
            "target_date": anchor_date.isoformat(),
            "baseline_target_date": None,
            "status": "planned",
            "progress_percent": 0,
            "completed_at": None,
            "dependencies": [],
        }

    def _deliverable_creation_payload(self, row: dict | None, anchor_date: date) -> dict | None:
        project_id = self._project_task_id()
        if project_id is None:
            return None
        phase_id = row.get("phase_id") if row is not None else None
        if row is not None and str(row.get("kind") or "").strip().lower() == "phase":
            phase_id = None if int(row.get("item_id") or -1) <= 0 else int(
                row.get("item_id") or 0
            )
        return {
            "project_task_id": int(project_id),
            "title": "",
            "description": "",
            "phase_id": None if phase_id is None else int(phase_id),
            "linked_task_id": None,
            "linked_milestone_id": None,
            "due_date": anchor_date.isoformat(),
            "baseline_due_date": None,
            "acceptance_criteria": "",
            "version_ref": "",
            "status": "planned",
            "completed_at": None,
        }

    def create_task_at(
        self,
        row_uid: str | None = None,
        anchor_date: date | None = None,
        *,
        child_mode: bool = False,
    ):
        row = self.row_lookup.get(str(row_uid or "")) if row_uid else None
        anchor = anchor_date or today_local()
        payload = self._task_creation_payload(row, anchor, child_mode=bool(child_mode))
        if payload is not None:
            self.taskCreateRequested.emit(payload)

    def create_milestone_at(self, row_uid: str | None = None, anchor_date: date | None = None):
        row = self.row_lookup.get(str(row_uid or "")) if row_uid else None
        anchor = anchor_date or today_local()
        payload = self._milestone_creation_payload(row, anchor)
        if payload is not None:
            self.milestoneCreateRequested.emit(payload)

    def create_deliverable_at(
        self,
        row_uid: str | None = None,
        anchor_date: date | None = None,
    ):
        row = self.row_lookup.get(str(row_uid or "")) if row_uid else None
        anchor = anchor_date or today_local()
        payload = self._deliverable_creation_payload(row, anchor)
        if payload is not None:
            self.deliverableCreateRequested.emit(payload)

    def create_task_at_scene_pos(self, scene_pos: QPointF):
        row = self._row_for_scene_pos(scene_pos)
        anchor_date = self.scene_x_to_date(scene_pos.x())
        row_uid = str(row.get("uid") or "") if row else None
        self.create_task_at(row_uid, anchor_date, child_mode=False)

    def _update_summary_label(self):
        row = self._selected_row()
        if row is None:
            count = len(self.visible_rows)
            self.summary_label.setText(
                f"{count} visible row(s). Double-click empty space to add a task, "
                "drag bars to reschedule work."
            )
            return
        start = str(row.get("display_start_date") or row.get("start_date") or "–")
        end = str(row.get("display_end_date") or row.get("end_date") or "–")
        status = str(row.get("status") or "").replace("_", " ").title() or "No status"
        self.summary_label.setText(
            f"Selected: {str(row.get('label') or '')} | "
            f"{str(row.get('kind') or '').title()} | "
            f"{start} -> {end} | {status}"
        )

    def _open_context_menu_at(self, pos: QPoint):
        scene_pos = self.view.mapToScene(pos)
        hit_item = self.view.itemAt(pos)
        row = None
        if isinstance(hit_item, TimelineBarItem):
            row = hit_item.row
            self.select_uid(hit_item.uid, from_chart=False, ensure_visible=False)
        elif self.visible_rows:
            row = self._row_for_scene_pos(scene_pos)
        anchor_date = self.scene_x_to_date(scene_pos.x())
        row_uid = str(row.get("uid") or "") if row else None
        menu = QMenu(self)

        add_task_action = QAction("Add task here", menu)
        add_task_action.triggered.connect(
            lambda: self.create_task_at(row_uid, anchor_date, child_mode=False)
        )
        menu.addAction(add_task_action)

        if row is not None and str(row.get("kind") or "").strip().lower() in {"project", "task"}:
            add_child_action = QAction("Add child task here", menu)
            add_child_action.triggered.connect(
                lambda: self.create_task_at(row_uid, anchor_date, child_mode=True)
            )
            menu.addAction(add_child_action)

        add_milestone_action = QAction("Add milestone here…", menu)
        add_milestone_action.triggered.connect(
            lambda: self.create_milestone_at(row_uid, anchor_date)
        )
        menu.addAction(add_milestone_action)

        add_deliverable_action = QAction("Add deliverable here…", menu)
        add_deliverable_action.triggered.connect(
            lambda: self.create_deliverable_at(row_uid, anchor_date)
        )
        menu.addAction(add_deliverable_action)

        if row is not None:
            menu.addSeparator()
            focus_action = QAction("Focus item", menu)
            focus_action.triggered.connect(lambda: self.activate_row(row))
            menu.addAction(focus_action)

        jump_action = QAction("Jump to selected", menu)
        jump_action.triggered.connect(self.jump_to_selection)
        menu.addAction(jump_action)

        jump_today_action = QAction("Jump to today", menu)
        jump_today_action.triggered.connect(self.jump_to_today)
        menu.addAction(jump_today_action)

        fit_project_action = QAction("Fit project", menu)
        fit_project_action.triggered.connect(self.fit_project)
        menu.addAction(fit_project_action)

        fit_selection_action = QAction("Fit selection", menu)
        fit_selection_action.triggered.connect(self.fit_selection)
        fit_selection_action.setEnabled(self._selected_row() is not None)
        menu.addAction(fit_selection_action)

        if row is not None and str(row.get("kind") or "") in {"task", "milestone"}:
            dep_action = QAction("Edit dependencies…", menu)
            dep_action.triggered.connect(
                lambda: self.dependencyEditRequested.emit(
                    str(row.get("kind") or ""),
                    int(row.get("item_id") or 0),
                )
            )
            menu.addAction(dep_action)

        if row is not None and str(row.get("kind") or "") == "task":
            move_up_action = QAction("Move up among siblings", menu)
            move_up_action.triggered.connect(
                lambda: self.taskMoveRelativeRequested.emit(int(row.get("item_id") or 0), -1)
            )
            move_down_action = QAction("Move down among siblings", menu)
            move_down_action.triggered.connect(
                lambda: self.taskMoveRelativeRequested.emit(int(row.get("item_id") or 0), 1)
            )
            menu.addAction(move_up_action)
            menu.addAction(move_down_action)

        menu.exec(self.view.viewport().mapToGlobal(pos))

    def nudge_selection(self, mode: str, delta_days: int):
        row = self._selected_row()
        if row is None or not self.row_is_editable(row):
            return
        start = _ensure_date(str(row.get("display_start_date") or row.get("start_date") or None))
        end = _ensure_date(str(row.get("display_end_date") or row.get("end_date") or None)) or start
        if start is None or end is None:
            return
        mode_key = str(mode or "move").strip().lower()
        delta = int(delta_days or 0)
        if delta == 0:
            return
        if mode_key == "move":
            start = start + timedelta(days=delta)
            end = end + timedelta(days=delta)
        elif mode_key == "resize_start":
            start = min(start + timedelta(days=delta), end)
        elif mode_key == "resize_end":
            end = max(start, end + timedelta(days=delta))
        self.scheduleEditRequested.emit(
            str(row.get("kind") or ""),
            int(row.get("item_id") or 0),
            start.isoformat() if start is not None else None,
            end.isoformat() if end is not None else None,
        )
