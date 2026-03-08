from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from interaction_utils import WheelFocusGuard


def _wheel_event_for(widget: QWidget, delta_y: int) -> QWheelEvent:
    local_pos = widget.rect().center()
    global_pos = widget.mapToGlobal(local_pos)
    try:
        return QWheelEvent(
            QPointF(local_pos),
            QPointF(global_pos),
            QPoint(0, 0),
            QPoint(0, int(delta_y)),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
            Qt.MouseEventSource.MouseEventNotSynthesized,
        )
    except TypeError:
        return QWheelEvent(
            QPointF(local_pos),
            QPointF(global_pos),
            QPoint(0, 0),
            QPoint(0, int(delta_y)),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )


def test_wheel_guard_scrolls_container_instead_of_changing_unfocused_spinbox(qapp):
    guard = WheelFocusGuard()
    qapp.installEventFilter(guard)
    host = None
    try:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        area = QScrollArea()
        area.setWidgetResizable(True)
        layout.addWidget(area)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(QLabel("Header"))
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(5)
        content_layout.addWidget(spin)
        for idx in range(30):
            content_layout.addWidget(QLabel(f"Line {idx}"))
        area.setWidget(content)

        host.resize(240, 140)
        host.show()
        qapp.processEvents()

        before_value = spin.value()
        before_scroll = area.verticalScrollBar().value()
        QApplication.sendEvent(spin, _wheel_event_for(spin, -120))
        qapp.processEvents()

        assert spin.value() == before_value
        assert area.verticalScrollBar().value() > before_scroll
    finally:
        qapp.removeEventFilter(guard)
        if host is not None:
            host.close()
        qapp.processEvents()


def test_wheel_guard_allows_mouse_armed_spinbox_changes(qapp):
    guard = WheelFocusGuard()
    qapp.installEventFilter(guard)
    spin = None
    try:
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(5)
        spin.show()
        qapp.processEvents()

        QTest.mouseClick(
            spin,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            spin.rect().center(),
        )
        qapp.processEvents()
        QApplication.sendEvent(spin, _wheel_event_for(spin, 120))
        qapp.processEvents()

        assert spin.value() != 5
    finally:
        qapp.removeEventFilter(guard)
        if spin is not None:
            spin.close()
        qapp.processEvents()
