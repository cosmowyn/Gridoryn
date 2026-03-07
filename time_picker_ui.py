from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSettings, QTime, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from theme import ThemeManager
from ui_layout import DEFAULT_DIALOG_MARGINS, add_left_aligned_buttons, configure_box_layout


def _contrast_color(bg: QColor) -> QColor:
    if not bg.isValid():
        return QColor("#ffffff")
    luminance = (0.299 * bg.red()) + (0.587 * bg.green()) + (0.114 * bg.blue())
    return QColor("#111111") if luminance > 160 else QColor("#ffffff")


def _active_theme_colors() -> dict:
    try:
        tm = ThemeManager(QSettings())
        theme = tm.load_theme(tm.current_theme_name())
        colors = theme.get("colors", {})
        return colors if isinstance(colors, dict) else {}
    except Exception:
        return {}


class RadialTimeDial(QWidget):
    timeChanged = Signal(object)
    modeChanged = Signal(str)

    def __init__(self, parent=None, theme_colors: dict | None = None):
        super().__init__(parent)
        self._mode = "hour"
        self._hour = 0
        self._minute = 0
        self._dragging = False
        self._last_angle = 0.0
        self._drag_origin_value = 0
        self._accumulated_degrees = 0.0
        self._theme_colors = {}
        self.setMinimumSize(300, 300)
        self.setObjectName("RadialTimeDial")
        self.setToolTip("Drag the clock dial to set the time.")
        self.set_theme_colors(theme_colors)

    def mode(self) -> str:
        return self._mode

    def time(self) -> QTime:
        return QTime(int(self._hour), int(self._minute), 0)

    def set_time(self, qtime: QTime):
        if not isinstance(qtime, QTime) or not qtime.isValid():
            qtime = QTime.currentTime()
        self._hour = max(0, min(23, int(qtime.hour())))
        self._minute = max(0, min(59, int(qtime.minute())))
        self.timeChanged.emit(self.time())
        self.update()

    def reset_to_hour_mode(self):
        self._mode = "hour"
        self.modeChanged.emit(self._mode)
        self.update()

    def set_theme_colors(self, theme_colors: dict | None):
        self._theme_colors = dict(theme_colors or _active_theme_colors())
        self.update()

    def _hour_display_text(self) -> str:
        hour12 = self._hour % 12
        return "12" if hour12 == 0 else str(hour12)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(18, 18, -18, -18)
        radius = min(rect.width(), rect.height()) / 2.0
        center = QPointF(rect.center())

        palette = self.palette()
        colors = self._theme_colors or {}
        face = QColor(str(colors.get("clock_face_bg") or palette.base().color().name()))
        face_border = QColor(str(colors.get("clock_face_border") or palette.mid().color().name()))
        text_color = QColor(str(colors.get("clock_text") or palette.windowText().color().name()))
        tick_color = QColor(str(colors.get("clock_tick") or face_border.name()))
        hand_color = QColor(str(colors.get("clock_hand") or palette.highlight().color().name()))
        accent = QColor(str(colors.get("clock_accent") or palette.highlight().color().name()))
        accent_text = QColor(str(colors.get("clock_accent_text") or palette.highlightedText().color().name()))
        center_dot = QColor(str(colors.get("clock_center_dot") or accent.name()))
        if not face.isValid():
            face = palette.base().color()
        if not face_border.isValid():
            face_border = palette.mid().color()
        if not text_color.isValid():
            text_color = palette.windowText().color()
        if not tick_color.isValid():
            tick_color = face_border
        if not hand_color.isValid():
            hand_color = accent
        if not accent.isValid():
            accent = palette.highlight().color()
        if not accent_text.isValid():
            accent_text = _contrast_color(accent)
        if not center_dot.isValid():
            center_dot = accent

        painter.setPen(QPen(face_border, 2))
        painter.setBrush(face)
        painter.drawEllipse(center, radius, radius)

        if self._mode == "minute":
            self._draw_minute_ticks(painter, center, radius, tick_color)

        if self._mode == "hour":
            target = self._point_for_angle(center, radius * 0.78, self._hour_angle(self._hour))
            self._draw_hour_labels(painter, center, radius, text_color)
            self._draw_hand(
                painter,
                center,
                target,
                hand_color,
                accent,
                accent_text,
                value_text=self._hour_display_text(),
                bubble_size=40.0,
            )
        else:
            target = self._point_for_angle(center, radius * 0.80, self._minute_angle(self._minute))
            self._draw_minute_labels(painter, center, radius, text_color)
            self._draw_hand(
                painter,
                center,
                target,
                hand_color,
                accent,
                accent_text,
                value_text=f"{self._minute:02d}",
                bubble_size=36.0,
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(center_dot)
        painter.drawEllipse(center, 5, 5)

    def _draw_hour_labels(self, painter, center: QPointF, radius: float, text_color: QColor):
        for idx in range(12):
            label = "12" if idx == 0 else str(idx)
            point = self._point_for_angle(center, radius * 0.78, idx * 30.0)
            self._draw_clock_label(painter, point, label, False, QColor(), QColor(), text_color)

    def _draw_minute_labels(self, painter, center: QPointF, radius: float, text_color: QColor):
        for minute in range(0, 60, 5):
            label = f"{minute:02d}"
            point = self._point_for_angle(center, radius * 0.80, minute * 6.0)
            self._draw_clock_label(painter, point, label, False, QColor(), QColor(), text_color)

    def _draw_clock_label(
        self,
        painter: QPainter,
        point: QPointF,
        text: str,
        selected: bool,
        accent: QColor,
        accent_text: QColor,
        text_color: QColor,
    ):
        label_rect = QRectF(point.x() - 20, point.y() - 20, 40, 40)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(label_rect)
            painter.setPen(accent_text)
        else:
            painter.setPen(text_color)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_minute_ticks(self, painter: QPainter, center: QPointF, radius: float, tick_color: QColor):
        for minute in range(60):
            angle = minute * 6.0
            outer = self._point_for_angle(center, radius * 0.92, angle)
            inner_scale = 0.78 if minute % 5 == 0 else 0.84
            inner = self._point_for_angle(center, radius * inner_scale, angle)
            pen = QPen(tick_color, 2 if minute % 5 == 0 else 1)
            painter.setPen(pen)
            painter.drawLine(inner, outer)

    def _draw_hand(
        self,
        painter: QPainter,
        center: QPointF,
        end: QPointF,
        hand_color: QColor,
        accent: QColor,
        accent_text: QColor,
        value_text: str = "",
        bubble_size: float = 36.0,
    ):
        painter.setPen(QPen(hand_color, 3))
        painter.drawLine(center, end)
        bubble_rect = QRectF(
            end.x() - (bubble_size / 2.0),
            end.y() - (bubble_size / 2.0),
            bubble_size,
            bubble_size,
        )
        painter.setPen(QPen(accent, 2))
        painter.setBrush(accent)
        painter.drawEllipse(bubble_rect)
        painter.setPen(accent_text)
        painter.drawText(bubble_rect, Qt.AlignmentFlag.AlignCenter, value_text)

    def _hour_angle(self, hour: int) -> float:
        return float((hour % 12) * 30)

    def _minute_angle(self, minute: int) -> float:
        return float(minute * 6)

    def _point_for_angle(self, center: QPointF, radius: float, angle_deg: float) -> QPointF:
        radians = math.radians(angle_deg - 90.0)
        return QPointF(
            center.x() + (math.cos(radians) * radius),
            center.y() + (math.sin(radians) * radius),
        )

    def _pos_angle(self, pos) -> float:
        center = self.rect().center()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        angle = math.degrees(math.atan2(dy, dx)) + 90.0
        if angle < 0:
            angle += 360.0
        return angle

    def _unwrapped_delta(self, new_angle: float, old_angle: float) -> float:
        delta = new_angle - old_angle
        while delta <= -180.0:
            delta += 360.0
        while delta > 180.0:
            delta -= 360.0
        return delta

    def _apply_drag(self):
        if self._mode == "hour":
            raw = int(round(self._drag_origin_value + (self._accumulated_degrees / 30.0)))
            self._hour = raw % 24
        else:
            raw = int(round(self._drag_origin_value + (self._accumulated_degrees / 6.0)))
            self._minute = raw % 60
        self.timeChanged.emit(self.time())
        self.update()

    def _set_value_from_angle(self, angle: float):
        if self._mode == "hour":
            base = int(round(angle / 30.0)) % 12
            candidates = [base, base + 12]
            current = int(self._hour)
            def dist(candidate: int) -> int:
                delta = abs(candidate - current) % 24
                return min(delta, 24 - delta)
            self._hour = min(candidates, key=lambda candidate: (dist(candidate), candidate != current))
        else:
            self._minute = int(round(angle / 6.0)) % 60
        self.timeChanged.emit(self.time())
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        angle = self._pos_angle(event.position())
        self._set_value_from_angle(angle)
        self._last_angle = angle
        self._drag_origin_value = self._hour if self._mode == "hour" else self._minute
        self._accumulated_degrees = 0.0
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        angle = self._pos_angle(event.position())
        self._accumulated_degrees += self._unwrapped_delta(angle, self._last_angle)
        self._last_angle = angle
        self._apply_drag()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            self._dragging = False
            self._apply_drag()
            self._mode = "minute" if self._mode == "hour" else "hour"
            self.modeChanged.emit(self._mode)
            self.update()
        event.accept()


class TimeDialDialog(QDialog):
    def __init__(self, initial_time: QTime | None = None, parent=None, theme_colors: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Set time")
        self.setModal(True)
        self.resize(380, 470)
        self.setObjectName("TimeDialDialog")

        if not isinstance(initial_time, QTime) or not initial_time.isValid():
            initial_time = QTime.currentTime()

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        self.time_label = QLabel()
        self.time_label.setObjectName("TimeDialTimeLabel")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setToolTip("Selected time in 24-hour format.")
        font = self.time_label.font()
        font.setPointSize(max(font.pointSize() + 6, 16))
        font.setBold(True)
        self.time_label.setFont(font)
        root.addWidget(self.time_label)

        self.mode_label = QLabel("Set hour")
        self.mode_label.setObjectName("TimeDialModeLabel")
        self.mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.mode_label)

        self.dial = RadialTimeDial(self, theme_colors=theme_colors)
        self.dial.timeChanged.connect(self._sync_label)
        self.dial.modeChanged.connect(self._sync_mode)
        self.dial.set_time(initial_time)
        self.dial.reset_to_hour_mode()
        root.addWidget(self.dial, 1)

        btn_row = QHBoxLayout()
        self.accept_btn = QPushButton("Accept")
        self.accept_btn.setToolTip("Use the selected time.")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Close without changing the time.")
        add_left_aligned_buttons(btn_row, self.accept_btn, self.cancel_btn)
        root.addLayout(btn_row)

        self.accept_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

        self._sync_label(self.dial.time())
        self._sync_mode(self.dial.mode())

    def _sync_label(self, qtime: QTime):
        if not isinstance(qtime, QTime) or not qtime.isValid():
            qtime = QTime.currentTime()
        self.time_label.setText(qtime.toString("HH:mm"))

    def _sync_mode(self, mode: str):
        self.mode_label.setText("Set hour" if mode == "hour" else "Set minute")

    def selected_time(self) -> QTime:
        return self.dial.time()

    @staticmethod
    def get_time(initial_time: QTime | None = None, parent=None, theme_colors: dict | None = None) -> tuple[QTime | None, bool]:
        dlg = TimeDialDialog(initial_time=initial_time, parent=parent, theme_colors=theme_colors)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        return (dlg.selected_time() if ok else None), ok
