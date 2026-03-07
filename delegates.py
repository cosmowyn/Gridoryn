from __future__ import annotations

from PySide6.QtCore import Qt, QDate, QDateTime, QTime, Signal, QEvent
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QStyledItemDelegate, QDateEdit, QSpinBox, QComboBox, QTreeView,
    QWidget, QHBoxLayout, QToolButton, QPushButton
)

from model import STATUSES
from time_picker_ui import TimeDialDialog


class _CalendarAwareDateEdit(QDateEdit):
    def __init__(self, parent=None):
        super().__init__(parent)

    def showPopup(self):
        target = self.date()
        if not target.isValid():
            target = QDate.currentDate()
        cal = self.calendarWidget()
        if cal is not None and target.isValid():
            cal.setSelectedDate(target)
            if hasattr(cal, "showSelectedDate"):
                cal.showSelectedDate()
        super().showPopup()


class DateEditorWithClear(QWidget):
    clearRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._has_value = False

        self.date_edit = _CalendarAwareDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MMM-yyyy")
        self.date_edit.dateChanged.connect(self._on_date_changed)
        cal = self.date_edit.calendarWidget()
        if cal is not None:
            cal.clicked.connect(self._mark_has_value)
            cal.activated.connect(self._mark_has_value)
        self._set_date(QDate.currentDate(), has_value=False)

        self.clear_btn = QToolButton(self)
        self.clear_btn.setText("✕")
        self.clear_btn.setToolTip("Clear date")
        self.clear_btn.clicked.connect(self._on_clear_clicked)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.date_edit, 1)
        lay.addWidget(self.clear_btn, 0)

    def _on_clear_clicked(self):
        self._set_date(QDate.currentDate(), has_value=False)
        self.clearRequested.emit()

    def _on_date_changed(self, _date: QDate):
        self._has_value = True

    def _mark_has_value(self, *_):
        self._has_value = True

    def _set_date(self, qd: QDate, has_value: bool):
        self.date_edit.blockSignals(True)
        self.date_edit.setDate(qd)
        self.date_edit.blockSignals(False)
        self._has_value = bool(has_value)

    def set_iso_date(self, value):
        s = str(value).strip() if value is not None else ""
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
            qd = QDate(y, m, d)
            if qd.isValid():
                self._set_date(qd, has_value=True)
                return
        self._set_date(QDate.currentDate(), has_value=False)

    def iso_date(self):
        if not self._has_value:
            return None
        qd = self.date_edit.date()
        return qd.toString("yyyy-MM-dd")


class DateTimeEditorWithClear(QWidget):
    clearRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._has_value = False
        self._time = QTime.currentTime()
        self._dialog_open = False

        self.date_edit = _CalendarAwareDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MMM-yyyy")
        self.date_edit.dateChanged.connect(self._on_date_changed)
        cal = self.date_edit.calendarWidget()
        if cal is not None:
            cal.clicked.connect(self._mark_has_value)
            cal.activated.connect(self._mark_has_value)
        self.time_btn = QPushButton(self)
        self.time_btn.setToolTip("Choose time with the radial clock dial.")
        self.time_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.time_btn.setAutoDefault(False)
        self.time_btn.pressed.connect(self._pick_time)
        self._set_datetime(QDateTime.currentDateTime(), has_value=False)

        self.clear_btn = QToolButton(self)
        self.clear_btn.setText("✕")
        self.clear_btn.setToolTip("Clear date/time")
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.clicked.connect(self._on_clear_clicked)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.date_edit, 1)
        lay.addWidget(self.time_btn, 0)
        lay.addWidget(self.clear_btn, 0)
        control_h = max(self.date_edit.sizeHint().height(), self.fontMetrics().height() + 12)
        self.date_edit.setMinimumHeight(control_h)
        self.time_btn.setMinimumHeight(control_h)
        self.clear_btn.setMinimumHeight(control_h)

    def _on_clear_clicked(self):
        self._set_datetime(QDateTime.currentDateTime(), has_value=False)
        self.clearRequested.emit()

    def _on_date_changed(self, _date: QDate):
        self._has_value = True

    def _mark_has_value(self, *_):
        self._has_value = True

    def picker_open(self) -> bool:
        return bool(self._dialog_open)

    def _pick_time(self):
        initial_time = self._time if self._time.isValid() else QTime.currentTime()
        self._dialog_open = True
        try:
            chosen, ok = TimeDialDialog.get_time(initial_time=initial_time, parent=self.window())
            if not ok or chosen is None or not chosen.isValid():
                return
            self._time = QTime(chosen.hour(), chosen.minute(), 0)
            self._has_value = True
            self._refresh_time_button()
        finally:
            self._dialog_open = False

    def _refresh_time_button(self):
        qtime = self._time if self._time.isValid() else QTime.currentTime()
        self.time_btn.setText(qtime.toString("HH:mm"))

    def _set_datetime(self, qdt: QDateTime, has_value: bool):
        if not qdt.isValid():
            qdt = QDateTime.currentDateTime()
        self.date_edit.blockSignals(True)
        self.date_edit.setDate(qdt.date())
        self.date_edit.blockSignals(False)
        self._time = QTime(qdt.time().hour(), qdt.time().minute(), 0)
        self._has_value = bool(has_value)
        self._refresh_time_button()

    def set_iso_datetime(self, value):
        s = str(value).strip() if value is not None else ""
        if not s:
            self._set_datetime(QDateTime.currentDateTime(), has_value=False)
            return
        qdt = QDateTime.fromString(s.replace("T", " "), "yyyy-MM-dd HH:mm:ss")
        if not qdt.isValid():
            qdt = QDateTime.fromString(s.replace("T", " "), "yyyy-MM-dd HH:mm")
        if not qdt.isValid():
            self._set_datetime(QDateTime.currentDateTime(), has_value=False)
            return
        self._set_datetime(qdt, has_value=True)

    def iso_datetime(self):
        if not self._has_value:
            return None
        qdt = QDateTime(self.date_edit.date(), QTime(self._time.hour(), self._time.minute(), 0))
        return qdt.toString("yyyy-MM-dd HH:mm:ss")


class SmartDelegate(QStyledItemDelegate):
    """
    One delegate for core + custom columns:
    - Date picker for any column with col_type == 'date'
    - Spinbox for ints (priority column 1..5; other ints wide)
    - Combobox for status and bool
    - Row height adapts to font size
    - Theme-driven borders:
        * cells
        * siblings (rows with children)
    - Proxy-safe
    """

    EXTRA_VPAD = 10
    MIN_ROW_HEIGHT = 38

    def _install_editor_event_filters(self, root: QWidget):
        if root is None:
            return
        root.setProperty("_delegate_editor_root", True)
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            child.installEventFilter(self)

    def _editor_root_for_widget(self, widget) -> QWidget | None:
        cur = widget if isinstance(widget, QWidget) else None
        while cur is not None:
            try:
                if bool(cur.property("_delegate_editor_root")):
                    return cur
            except Exception:
                pass
            cur = cur.parentWidget()
        return None

    def _source_model_and_index(self, index):
        m = index.model()
        if hasattr(m, "mapToSource"):
            try:
                src = m.mapToSource(index)
                sm = m.sourceModel()
                return sm, src
            except Exception:
                return None, None
        return m, index

    def _col_type(self, index) -> str:
        sm, src = self._source_model_and_index(index)
        if sm is None or src is None or not src.isValid():
            return "text"
        col = src.column()
        if hasattr(sm, "col_type_for_column"):
            try:
                return str(sm.col_type_for_column(col))
            except Exception:
                return "text"
        if hasattr(sm, "_col_type"):
            try:
                return str(sm._col_type(col))
            except Exception:
                return "text"
        return "text"

    def _is_priority_column(self, index) -> bool:
        return self._column_key(index) == "priority"

    def _is_status_column(self, index) -> bool:
        return self._column_key(index) == "status"

    def _column_key(self, index) -> str:
        sm, src = self._source_model_and_index(index)
        if sm is None or src is None or not src.isValid():
            return ""
        if hasattr(sm, "column_key"):
            try:
                return str(sm.column_key(src.column()))
            except Exception:
                return ""
        return ""

    def _list_options(self, index) -> list[str]:
        sm, src = self._source_model_and_index(index)
        if sm is None or src is None or not src.isValid():
            return []
        col = src.column()
        if hasattr(sm, "list_options_for_column"):
            try:
                vals = sm.list_options_for_column(col)
                return [str(v) for v in vals]
            except Exception:
                return []
        return []

    def _has_children(self, index) -> bool:
        idx0 = index.siblingAtColumn(0)
        sm, src = self._source_model_and_index(idx0)
        if sm is None or src is None or not src.isValid():
            return False
        try:
            return sm.rowCount(src) > 0
        except Exception:
            return False

    def _current_theme(self, index) -> dict:
        sm, _src = self._source_model_and_index(index)
        if sm is None:
            return {}
        try:
            mgr = getattr(sm, "theme_mgr", None)
            if mgr is None:
                return {}
            return mgr.load_theme(mgr.current_theme_name())
        except Exception:
            return {}

    def _border_cfg(self, index, section: str, side: str) -> dict:
        theme = self._current_theme(index)
        return (
            theme.get("borders", {})
            .get(section, {})
            .get(side, {})
        ) or {}

    def _pen_style(self, style_name: str):
        name = str(style_name or "solid").lower()
        mapping = {
            "solid": Qt.PenStyle.SolidLine,
            "dash": Qt.PenStyle.DashLine,
            "dot": Qt.PenStyle.DotLine,
            "dashdot": Qt.PenStyle.DashDotLine,
            "dashdotdot": Qt.PenStyle.DashDotDotLine,
        }
        return mapping.get(name, Qt.PenStyle.SolidLine)

    def _draw_side(self, painter: QPainter, x1: int, y1: int, x2: int, y2: int, cfg: dict):
        enabled = bool(cfg.get("enabled", False))
        width = int(cfg.get("width", 0))
        color = QColor(str(cfg.get("color", "#000000")))
        style = self._pen_style(str(cfg.get("style", "solid")))

        if not enabled or width <= 0 or not color.isValid():
            return

        pen = QPen(color)
        pen.setWidth(width)
        pen.setStyle(style)
        painter.setPen(pen)
        painter.drawLine(x1, y1, x2, y2)

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        fm = option.fontMetrics
        min_h = max(fm.height() + self.EXTRA_VPAD, self.MIN_ROW_HEIGHT)
        if base.height() < min_h:
            base.setHeight(min_h)
        return base

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                root = self._editor_root_for_widget(editor)
                if root is not None:
                    self.commitData.emit(root)
                    self.closeEditor.emit(root, QStyledItemDelegate.EndEditHint.NoHint)
                    return True
        if isinstance(editor, DateTimeEditorWithClear):
            if editor.picker_open() and event.type() in {QEvent.Type.FocusOut, QEvent.Type.Hide}:
                return True
        root = self._editor_root_for_widget(editor)
        if isinstance(root, DateTimeEditorWithClear):
            if root.picker_open() and event.type() in {QEvent.Type.FocusOut, QEvent.Type.Hide}:
                return True
        return super().eventFilter(editor, event)

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)

        painter.save()
        r = option.rect

        # Cell borders
        self._draw_side(painter, r.left(), r.top(), r.right(), r.top(), self._border_cfg(index, "cells", "top"))
        self._draw_side(painter, r.right(), r.top(), r.right(), r.bottom(), self._border_cfg(index, "cells", "right"))
        self._draw_side(painter, r.left(), r.bottom(), r.right(), r.bottom(), self._border_cfg(index, "cells", "bottom"))
        self._draw_side(painter, r.left(), r.top(), r.left(), r.bottom(), self._border_cfg(index, "cells", "left"))

        # Sibling borders (only on rows that have children, draw once per row)
        if index.column() == 0 and self._has_children(index):
            view = self.parent()
            if isinstance(view, QTreeView):
                vr = view.viewport().rect()
                top = r.top()
                bottom = r.bottom()
                left = vr.left()
                right = vr.right()

                self._draw_side(painter, left, top, right, top, self._border_cfg(index, "siblings", "top"))
                self._draw_side(painter, right, top, right, bottom, self._border_cfg(index, "siblings", "right"))
                self._draw_side(painter, left, bottom, right, bottom, self._border_cfg(index, "siblings", "bottom"))
                self._draw_side(painter, left, top, left, bottom, self._border_cfg(index, "siblings", "left"))

        painter.restore()

    def createEditor(self, parent, option, index):
        ctype = self._col_type(index)

        if ctype == "date":
            ed = DateEditorWithClear(parent)
            ed.setMinimumHeight(option.fontMetrics.height() + self.EXTRA_VPAD)
            ed.clearRequested.connect(lambda: self.commitData.emit(ed))
            ed.clearRequested.connect(lambda: self.closeEditor.emit(ed, QStyledItemDelegate.EndEditHint.NoHint))
            self._install_editor_event_filters(ed)
            return ed

        if ctype == "datetime":
            ed = DateTimeEditorWithClear(parent)
            ed.setMinimumHeight(option.fontMetrics.height() + self.EXTRA_VPAD)
            ed.clearRequested.connect(lambda: self.commitData.emit(ed))
            ed.clearRequested.connect(lambda: self.closeEditor.emit(ed, QStyledItemDelegate.EndEditHint.NoHint))
            self._install_editor_event_filters(ed)
            return ed

        if ctype == "int":
            ed = QSpinBox(parent)
            if self._is_priority_column(index):
                ed.setRange(1, 5)
            else:
                ed.setRange(-1_000_000_000, 1_000_000_000)
            ed.setMinimumHeight(option.fontMetrics.height() + self.EXTRA_VPAD)
            self._install_editor_event_filters(ed)
            return ed

        if ctype == "bool":
            cb = QComboBox(parent)
            cb.addItems(["No", "Yes"])
            cb.setMinimumHeight(option.fontMetrics.height() + self.EXTRA_VPAD)
            self._install_editor_event_filters(cb)
            return cb

        if ctype == "status" or self._is_status_column(index):
            cb = QComboBox(parent)
            cb.addItems(STATUSES)
            cb.setMinimumHeight(option.fontMetrics.height() + self.EXTRA_VPAD)
            self._install_editor_event_filters(cb)
            return cb

        if ctype == "list":
            cb = QComboBox(parent)
            cb.setEditable(True)
            cb.addItems(self._list_options(index))
            cb.setMinimumHeight(option.fontMetrics.height() + self.EXTRA_VPAD)
            self._install_editor_event_filters(cb)
            return cb

        ed = super().createEditor(parent, option, index)
        if isinstance(ed, QWidget):
            self._install_editor_event_filters(ed)
        return ed

    def setEditorData(self, editor, index):
        ctype = self._col_type(index)
        v = index.model().data(index, Qt.ItemDataRole.EditRole)

        if isinstance(editor, DateEditorWithClear):
            editor.set_iso_date(v)
            return

        if isinstance(editor, DateTimeEditorWithClear):
            editor.set_iso_datetime(v)
            return

        if isinstance(editor, QSpinBox):
            try:
                editor.setValue(int(v))
            except Exception:
                editor.setValue(3 if self._is_priority_column(index) else 0)
            return

        if isinstance(editor, QComboBox):
            if ctype == "bool":
                sv = str(v).strip().lower() if v is not None else "0"
                editor.setCurrentIndex(1 if sv in {"1", "true", "yes", "y"} else 0)
            elif ctype == "list":
                sv = str(v).strip() if v is not None else ""
                if sv and editor.findText(sv) < 0:
                    editor.addItem(sv)
                editor.setEditText(sv)
            else:
                sv = str(v or "")
                i = editor.findText(sv)
                editor.setCurrentIndex(i if i >= 0 else 0)
            return

        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        ctype = self._col_type(index)

        if isinstance(editor, DateEditorWithClear):
            model.setData(index, editor.iso_date(), Qt.ItemDataRole.EditRole)
            return

        if isinstance(editor, DateTimeEditorWithClear):
            model.setData(index, editor.iso_datetime(), Qt.ItemDataRole.EditRole)
            return

        if isinstance(editor, QSpinBox):
            model.setData(index, editor.value(), Qt.ItemDataRole.EditRole)
            return

        if isinstance(editor, QComboBox):
            if ctype == "bool":
                model.setData(index, "1" if editor.currentIndex() == 1 else "0", Qt.ItemDataRole.EditRole)
            elif ctype == "list":
                model.setData(index, editor.currentText().strip(), Qt.ItemDataRole.EditRole)
            else:
                model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
            return

        super().setModelData(editor, model, index)


def install_delegates(view, model):
    view.setItemDelegate(SmartDelegate(view))
