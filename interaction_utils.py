from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt, QObject
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QAbstractScrollArea,
    QAbstractSpinBox,
    QComboBox,
    QSlider,
    QWidget,
)


class WheelFocusGuard(QObject):
    """
    Prevent accidental wheel-based value changes on editor controls.

    Wheel input is allowed only when the user has intentionally focused the
    control. Otherwise the wheel event is forwarded to the nearest scrollable
    ancestor so the surrounding page continues to scroll naturally.
    """

    _ARMED_PROPERTY = "_wheel_guard_armed"

    def eventFilter(self, watched, event):
        etype = event.type()
        if etype not in {
            QEvent.Type.Wheel,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.FocusOut,
            QEvent.Type.Leave,
            QEvent.Type.Hide,
            QEvent.Type.Close,
            QEvent.Type.WindowDeactivate,
        }:
            return False
        control = self._wheel_sensitive_ancestor(watched)
        if control is None:
            return False
        if etype == QEvent.Type.MouseButtonPress:
            self._set_armed(control, True)
            return False
        if etype in {
            QEvent.Type.FocusOut,
            QEvent.Type.Leave,
            QEvent.Type.Hide,
            QEvent.Type.Close,
            QEvent.Type.WindowDeactivate,
        }:
            self._set_armed(control, False)
            return False
        if self._allow_direct_wheel(control):
            return False
        return self._forward_to_scroll_area(control, event)

    def _wheel_sensitive_ancestor(self, watched) -> QWidget | None:
        cur = watched if isinstance(watched, QWidget) else None
        while cur is not None:
            if isinstance(cur, (QAbstractSpinBox, QComboBox, QSlider)):
                return cur
            cur = cur.parentWidget()
        return None

    def _allow_direct_wheel(self, control: QWidget) -> bool:
        if isinstance(control, QComboBox):
            try:
                popup_view = control.view()
            except Exception:
                popup_view = None
            if popup_view is not None and popup_view.isVisible():
                return True
        return bool(control.property(self._ARMED_PROPERTY))

    def _set_armed(self, control: QWidget, armed: bool):
        try:
            control.setProperty(self._ARMED_PROPERTY, bool(armed))
        except Exception:
            pass

    def _forward_to_scroll_area(
        self,
        control: QWidget,
        event: QWheelEvent,
    ) -> bool:
        target = self._nearest_scroll_target(control)
        if target is None:
            event.accept()
            return True

        local_pos = QPointF(target.mapFromGlobal(event.globalPosition().toPoint()))
        try:
            cloned = QWheelEvent(
                local_pos,
                event.globalPosition(),
                event.pixelDelta(),
                event.angleDelta(),
                event.buttons(),
                event.modifiers(),
                event.phase(),
                event.inverted(),
                event.source(),
                event.pointingDevice(),
            )
        except TypeError:
            cloned = QWheelEvent(
                local_pos,
                event.globalPosition(),
                event.pixelDelta(),
                event.angleDelta(),
                event.buttons(),
                event.modifiers(),
                event.phase(),
                event.inverted(),
                event.source(),
            )
        QApplication.sendEvent(target, cloned)
        event.accept()
        return True

    def _nearest_scroll_target(self, control: QWidget) -> QWidget | None:
        parent = control.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                return parent.viewport()
            parent = parent.parentWidget()
        return None
