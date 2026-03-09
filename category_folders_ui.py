from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QColorDialog,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
)

from ui_layout import (
    DEFAULT_DIALOG_MARGINS,
    SectionPanel,
    add_form_row,
    add_left_aligned_buttons,
    configure_box_layout,
    configure_form_layout,
    polish_button_layouts,
)


CATEGORY_ICON_CHOICES = [
    ("folder", "Folder"),
    ("home", "Home"),
    ("briefcase", "Briefcase"),
    ("bookmark", "Bookmark"),
    ("flag", "Flag"),
    ("star", "Star"),
    ("tag", "Tag"),
]


def folder_display_name(folder: dict | None) -> str:
    if not folder:
        return ""
    identifier = str(folder.get("identifier") or "").strip()
    name = str(folder.get("name") or "").strip()
    return f"[{identifier}] {name}" if identifier else name


def folder_icon(icon_name: str | None) -> QIcon:
    name = str(icon_name or "folder").strip().lower() or "folder"
    theme_names = {
        "folder": ["folder"],
        "home": ["user-home", "go-home"],
        "briefcase": ["folder-documents", "document-open-recent"],
        "bookmark": ["bookmark-new", "bookmarks"],
        "flag": ["flag", "emblem-important"],
        "star": ["starred", "rating"],
        "tag": ["tag", "tag-new"],
    }
    style_fallbacks = {
        "folder": QStyle.StandardPixmap.SP_DirIcon,
        "home": QStyle.StandardPixmap.SP_DirHomeIcon,
        "briefcase": QStyle.StandardPixmap.SP_FileDialogDetailedView,
        "bookmark": QStyle.StandardPixmap.SP_FileDialogContentsView,
        "flag": QStyle.StandardPixmap.SP_MessageBoxWarning,
        "star": QStyle.StandardPixmap.SP_DialogApplyButton,
        "tag": QStyle.StandardPixmap.SP_FileDialogListView,
    }
    for theme_name in theme_names.get(name, [name]):
        icon = QIcon.fromTheme(theme_name)
        if not icon.isNull():
            return icon
    style = QApplication.style()
    if style is not None:
        return style.standardIcon(style_fallbacks.get(name, QStyle.StandardPixmap.SP_DirIcon))
    return QIcon()


def _set_color_button(button: QPushButton, color_hex: str | None):
    color = str(color_hex or "").strip()
    button.setText(color if color else "Default")
    if color:
        button.setStyleSheet(
            "QPushButton {"
            f"background:{color};"
            "color:#000000;"
            "}"
        )
    else:
        button.setStyleSheet("")


class CategoryFolderDialog(QDialog):
    def __init__(self, folder: dict | None = None, parent=None):
        super().__init__(parent)
        self._folder = dict(folder or {})
        self._color_hex = str(self._folder.get("color_hex") or "").strip() or None
        self.setWindowTitle("Category properties")
        self.resize(460, 240)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=DEFAULT_DIALOG_MARGINS, spacing=10)

        section = SectionPanel(
            "Category folder",
            "Customize the label, icon, and color used for this category.",
        )
        root.addWidget(section, 1)

        form = QFormLayout()
        configure_form_layout(form, label_width=110)
        section.body_layout.addLayout(form)

        self.name_edit = QLineEdit(str(self._folder.get("name") or ""))
        add_form_row(form, "Name", self.name_edit)

        self.identifier_edit = QLineEdit(str(self._folder.get("identifier") or ""))
        self.identifier_edit.setPlaceholderText("Optional short identifier")
        add_form_row(form, "Identifier", self.identifier_edit)

        self.icon_combo = QComboBox()
        for key, label in CATEGORY_ICON_CHOICES:
            self.icon_combo.addItem(folder_icon(key), label, key)
        icon_index = self.icon_combo.findData(str(self._folder.get("icon_name") or "folder"))
        self.icon_combo.setCurrentIndex(icon_index if icon_index >= 0 else 0)
        add_form_row(form, "Icon", self.icon_combo)

        color_row = QHBoxLayout()
        configure_box_layout(color_row)
        self.color_btn = QPushButton()
        _set_color_button(self.color_btn, self._color_hex)
        self.clear_color_btn = QPushButton("Clear")
        color_row.addWidget(self.color_btn)
        color_row.addWidget(self.clear_color_btn)
        add_form_row(form, "Color", color_row)

        preview_row = QHBoxLayout()
        configure_box_layout(preview_row)
        self.preview_icon_label = QLabel()
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        preview_row.addWidget(self.preview_icon_label)
        preview_row.addWidget(self.preview_label, 1)
        section.body_layout.addLayout(preview_row)

        actions = QHBoxLayout()
        configure_box_layout(actions)
        self.save_btn = QPushButton("Save")
        self.cancel_btn = QPushButton("Cancel")
        add_left_aligned_buttons(actions, self.save_btn, self.cancel_btn)
        section.body_layout.addLayout(actions)

        self.color_btn.clicked.connect(self._pick_color)
        self.clear_color_btn.clicked.connect(self._clear_color)
        self.name_edit.textChanged.connect(self._update_preview)
        self.identifier_edit.textChanged.connect(self._update_preview)
        self.icon_combo.currentIndexChanged.connect(self._update_preview)
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

        polish_button_layouts(self)
        self._update_preview()

    def _pick_color(self):
        chosen = QColorDialog.getColor(parent=self)
        if not chosen.isValid():
            return
        self._color_hex = chosen.name()
        _set_color_button(self.color_btn, self._color_hex)
        self._update_preview()

    def _clear_color(self):
        self._color_hex = None
        _set_color_button(self.color_btn, None)
        self._update_preview()

    def _update_preview(self):
        preview_folder = {
            "name": self.name_edit.text().strip(),
            "identifier": self.identifier_edit.text().strip(),
        }
        text = folder_display_name(preview_folder) or "(unnamed category)"
        self.preview_label.setText(f"Preview: {text}")
        self.preview_icon_label.setPixmap(folder_icon(self.icon_combo.currentData()).pixmap(16, 16))

    def payload(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "identifier": self.identifier_edit.text().strip() or None,
            "icon_name": str(self.icon_combo.currentData() or "folder"),
            "color_hex": self._color_hex,
        }
