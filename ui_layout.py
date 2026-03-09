from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


DEFAULT_DIALOG_MARGINS = (10, 10, 10, 10)
DEFAULT_PANEL_MARGINS = (8, 8, 8, 8)
DEFAULT_SPACING = 8
DEFAULT_LABEL_WIDTH = 140
DEFAULT_BUTTON_MIN_WIDTH = 112
DEFAULT_BUTTON_MIN_HEIGHT = 28
DEFAULT_COMPACT_BUTTON_MIN_SIZE = 22
DEFAULT_BUTTON_TEXT_PADDING = 24
DEFAULT_BUTTON_ICON_GAP = 8
MIN_BUTTON_ROW_SPACING = 2
DEFAULT_SECTION_SPACING = 6


def configure_box_layout(
    layout,
    margins=(0, 0, 0, 0),
    spacing: int = DEFAULT_SPACING,
):
    layout.setContentsMargins(*margins)
    layout.setSpacing(int(spacing))
    return layout


def configure_form_layout(
    layout: QFormLayout,
    label_width: int = DEFAULT_LABEL_WIDTH,
):
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


def configure_grid_layout(
    layout: QGridLayout,
    margins=(0, 0, 0, 0),
    spacing: int = DEFAULT_SPACING,
):
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


def add_left_aligned_buttons(
    layout: QHBoxLayout,
    *buttons,
    trailing_stretch: bool = True,
):
    configure_box_layout(layout)
    layout.setSpacing(max(layout.spacing(), MIN_BUTTON_ROW_SPACING))
    layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for btn in buttons:
        if btn is None:
            continue
        apply_button_layout_policy(btn)
        layout.addWidget(btn)
    if trailing_stretch:
        layout.addStretch(1)
    return layout


def _button_text(button: QAbstractButton) -> str:
    try:
        return str(button.text() or "").replace("&", "").strip()
    except Exception:
        return ""


def button_minimum_size(
    button: QAbstractButton,
    *,
    extra_padding: int = DEFAULT_BUTTON_TEXT_PADDING,
) -> QSize:
    text = _button_text(button)
    metrics = button.fontMetrics()
    hint = button.sizeHint()
    try:
        icon = button.icon()
        has_icon = bool(icon and not icon.isNull())
    except Exception:
        has_icon = False
    try:
        icon_width = int(button.iconSize().width()) if has_icon else 0
    except Exception:
        icon_width = 0
    icon_width = max(icon_width, 16) if has_icon else 0

    if text:
        width = metrics.horizontalAdvance(text) + int(extra_padding)
        if has_icon:
            width += icon_width + DEFAULT_BUTTON_ICON_GAP
        width = max(width, hint.width(), DEFAULT_BUTTON_MIN_WIDTH)
        height = max(
            hint.height(),
            metrics.height() + 12,
            DEFAULT_BUTTON_MIN_HEIGHT,
        )
    else:
        compact_min = max(DEFAULT_COMPACT_BUTTON_MIN_SIZE, icon_width + 10)
        width = max(hint.width(), compact_min)
        height = max(hint.height(), compact_min)
        if isinstance(button, QToolButton):
            height = max(height, DEFAULT_COMPACT_BUTTON_MIN_SIZE)
    return QSize(int(width), int(height))


def apply_button_layout_policy(
    button: QAbstractButton,
    *,
    extra_padding: int = DEFAULT_BUTTON_TEXT_PADDING,
):
    minimum = button_minimum_size(button, extra_padding=extra_padding)
    try:
        button.setMinimumWidth(max(button.minimumWidth(), minimum.width()))
    except Exception:
        pass
    try:
        button.setMinimumHeight(max(button.minimumHeight(), minimum.height()))
    except Exception:
        pass
    return button


def _layout_button_count(layout: QLayout) -> int:
    count = 0
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        widget = item.widget()
        child_layout = item.layout()
        if isinstance(widget, QAbstractButton):
            count += 1
        elif child_layout is not None:
            count += _layout_button_count(child_layout)
    return count


def _apply_button_spacing(layout: QLayout):
    if _layout_button_count(layout) >= 2:
        if isinstance(layout, QGridLayout):
            layout.setHorizontalSpacing(
                max(layout.horizontalSpacing(), MIN_BUTTON_ROW_SPACING)
            )
            layout.setVerticalSpacing(
                max(layout.verticalSpacing(), MIN_BUTTON_ROW_SPACING)
            )
        else:
            layout.setSpacing(max(layout.spacing(), MIN_BUTTON_ROW_SPACING))
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        child_layout = item.layout()
        if child_layout is not None:
            _apply_button_spacing(child_layout)


def polish_button_layouts(root: QWidget):
    if root is None:
        return root
    layout = root.layout()
    if layout is not None:
        _apply_button_spacing(layout)
    for button in root.findChildren(QAbstractButton):
        apply_button_layout_policy(button)
    return root


class SectionPanel(QFrame):
    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: QWidget | None = None,
        *,
        show_subtitle: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("SectionPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._show_subtitle = bool(show_subtitle)
        self._subtitle_text = ""

        root = QVBoxLayout(self)
        configure_box_layout(
            root,
            margins=DEFAULT_PANEL_MARGINS,
            spacing=DEFAULT_SECTION_SPACING,
        )

        header_row = QHBoxLayout()
        configure_box_layout(header_row, spacing=DEFAULT_SECTION_SPACING)

        title_col = QVBoxLayout()
        configure_box_layout(title_col, spacing=2)

        self.title_label = QLabel(str(title or ""))
        self.title_label.setObjectName("SectionTitleLabel")
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.title_label.setWordWrap(True)
        title_col.addWidget(self.title_label)

        self.subtitle_label = QLabel(str(subtitle or ""))
        self.subtitle_label.setObjectName("SectionSubtitleLabel")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(False)
        title_col.addWidget(self.subtitle_label)

        header_row.addLayout(title_col, 1)

        self.header_actions = QHBoxLayout()
        configure_box_layout(self.header_actions, spacing=6)
        self.header_actions.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        header_row.addLayout(self.header_actions)
        root.addLayout(header_row)

        self.body_layout = QVBoxLayout()
        configure_box_layout(self.body_layout, spacing=DEFAULT_SECTION_SPACING)
        root.addLayout(self.body_layout, 1)
        self.set_subtitle(subtitle)

    def set_subtitle(self, subtitle: str):
        text = str(subtitle or "")
        self._subtitle_text = text
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text.strip()) and self._show_subtitle)
        if text.strip():
            self.title_label.setToolTip(text)
            self.setToolTip(text)
        else:
            self.title_label.setToolTip("")
            self.setToolTip("")


class EmptyStatePanel(QFrame):
    def __init__(
        self,
        title: str,
        message: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("EmptyStatePanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(20, 20, 20, 20), spacing=6)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel(str(title or ""))
        self.title_label.setObjectName("EmptyStateTitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        root.addWidget(self.title_label)

        self.message_label = QLabel(str(message or ""))
        self.message_label.setObjectName("EmptyStateMessageLabel")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(bool(str(message or "").strip()))
        root.addWidget(self.message_label)

    def set_text(self, title: str, message: str = ""):
        self.title_label.setText(str(title or ""))
        self.message_label.setText(str(message or ""))
        self.message_label.setVisible(bool(str(message or "").strip()))


class EmptyStateStack(QWidget):
    def __init__(
        self,
        content_widget: QWidget,
        empty_title: str,
        empty_message: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._content_widget = content_widget
        self.empty_panel = EmptyStatePanel(empty_title, empty_message, self)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._content_widget)
        self._stack.addWidget(self.empty_panel)
        self.set_has_content(True)

    def set_has_content(self, has_content: bool):
        self._stack.setCurrentWidget(
            self._content_widget if has_content else self.empty_panel
        )

    def set_empty_state(self, title: str, message: str = ""):
        self.empty_panel.set_text(title, message)

    def content_widget(self) -> QWidget:
        return self._content_widget


class SummaryCard(QFrame):
    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("SummaryCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=4)

        self.title_label = QLabel(str(title or ""))
        self.title_label.setObjectName("SummaryCardTitle")
        self.title_label.setWordWrap(True)
        root.addWidget(self.title_label)

        self.value_label = QLabel("-")
        self.value_label.setObjectName("SummaryCardValue")
        self.value_label.setWordWrap(True)
        root.addWidget(self.value_label)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("SummaryCardDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setVisible(False)
        root.addWidget(self.detail_label)

    def set_value(self, value: str, detail: str = ""):
        self.value_label.setText(str(value or ""))
        text = str(detail or "")
        self.detail_label.setText(text)
        self.detail_label.setVisible(bool(text.strip()))

    def sizeHint(self) -> QSize:
        return QSize(180, 92)


def configure_data_table(
    table: QTableWidget,
    *,
    stretch_column: int | None = None,
    resize_to_contents: list[int] | tuple[int, ...] = (),
    min_height: int = 160,
    max_height: int | None = None,
):
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setAlternatingRowColors(True)
    table.setMinimumHeight(int(min_height))
    if max_height is not None:
        table.setMaximumHeight(int(max_height))
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(42)
    header.setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    for column in range(table.columnCount()):
        if column == stretch_column:
            mode = QHeaderView.ResizeMode.Stretch
        elif column in resize_to_contents:
            mode = QHeaderView.ResizeMode.ResizeToContents
        else:
            mode = QHeaderView.ResizeMode.Interactive
        header.setSectionResizeMode(column, mode)
    table.verticalHeader().setVisible(False)
    return table
