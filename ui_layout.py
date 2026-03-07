from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QLabel


DEFAULT_DIALOG_MARGINS = (10, 10, 10, 10)
DEFAULT_PANEL_MARGINS = (8, 8, 8, 8)
DEFAULT_SPACING = 8
DEFAULT_LABEL_WIDTH = 140
DEFAULT_BUTTON_MIN_WIDTH = 112


def configure_box_layout(layout, margins=(0, 0, 0, 0), spacing: int = DEFAULT_SPACING):
    layout.setContentsMargins(*margins)
    layout.setSpacing(int(spacing))
    return layout


def configure_form_layout(layout: QFormLayout, label_width: int = DEFAULT_LABEL_WIDTH):
    configure_box_layout(layout)
    layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    layout.setHorizontalSpacing(12)
    layout.setVerticalSpacing(DEFAULT_SPACING)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setProperty("_label_width", int(label_width))
    return layout


def configure_grid_layout(layout: QGridLayout, margins=(0, 0, 0, 0), spacing: int = DEFAULT_SPACING):
    configure_box_layout(layout, margins=margins, spacing=spacing)
    layout.setHorizontalSpacing(12)
    layout.setVerticalSpacing(spacing)
    return layout


def form_label(text: str, label_width: int | None = None) -> QLabel:
    width = DEFAULT_LABEL_WIDTH if label_width is None else int(label_width)
    label = QLabel(str(text))
    label.setMinimumWidth(width)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


def add_form_row(layout: QFormLayout, label: str, field):
    label_width = int(layout.property("_label_width") or DEFAULT_LABEL_WIDTH)
    layout.addRow(form_label(label, label_width), field)


def add_left_aligned_buttons(layout: QHBoxLayout, *buttons, trailing_stretch: bool = True):
    configure_box_layout(layout)
    layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for btn in buttons:
        if btn is None:
            continue
        try:
            btn.setMinimumWidth(DEFAULT_BUTTON_MIN_WIDTH)
        except Exception:
            pass
        layout.addWidget(btn)
    if trailing_stretch:
        layout.addStretch(1)
    return layout
