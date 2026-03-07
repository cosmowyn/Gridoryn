from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCalendarWidget


class TaskCalendarWidget(QCalendarWidget):
    """Calendar that renders due-task dates with completion-colored backgrounds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._completion_by_date: dict[str, float] = {}

    def set_completion_summary(self, completion_by_date: dict[str, float]):
        normalized: dict[str, float] = {}
        for key, pct in (completion_by_date or {}).items():
            iso = str(key or "").strip()
            if len(iso) < 10:
                continue
            try:
                val = float(pct)
            except Exception:
                val = 0.0
            normalized[iso[:10]] = max(0.0, min(100.0, val))
        self._completion_by_date = normalized
        self.updateCells()

    def _color_for_percent(self, percent: float) -> QColor:
        # Match app reminder gradient family: red -> orange -> green.
        if percent >= 99.999:
            return QColor("#00C853")
        if percent >= 60.0:
            return QColor("#FF9800")
        return QColor("#D50000")

    def paintCell(self, painter, rect, date: QDate):
        super().paintCell(painter, rect, date)

        iso = date.toString("yyyy-MM-dd")
        pct = self._completion_by_date.get(iso)
        if pct is None:
            return

        color = self._color_for_percent(float(pct))
        painter.save()

        fill = QColor(color)
        fill.setAlpha(36)
        painter.fillRect(rect.adjusted(1, 1, -1, -1), fill)

        painter.restore()
