from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reporting import PdfPageOptions, TimelinePdfExportOptions
from ui_layout import add_form_row, add_left_aligned_buttons, configure_box_layout, configure_form_layout, polish_button_layouts


class _BasePdfDialog(QDialog):
    def __init__(self, *, title: str, default_path: str, default_orientation: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 260)

        root = QVBoxLayout(self)
        configure_box_layout(root, margins=(10, 10, 10, 10), spacing=10)

        intro = QLabel("Choose the export destination and page layout.")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        configure_form_layout(form, label_width=150)
        root.addLayout(form)

        file_row = QHBoxLayout()
        configure_box_layout(file_row, margins=(0, 0, 0, 0), spacing=6)
        self.file_edit = QLineEdit(str(default_path or ""))
        self.browse_btn = QPushButton("Browse…")
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(self.browse_btn)
        add_form_row(form, "Destination", self._wrap(file_row))

        self.orientation_combo = QComboBox()
        self.orientation_combo.addItem("Portrait", "portrait")
        self.orientation_combo.addItem("Landscape", "landscape")
        idx = self.orientation_combo.findData(default_orientation)
        self.orientation_combo.setCurrentIndex(idx if idx >= 0 else 0)
        add_form_row(form, "Orientation", self.orientation_combo)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItem("A4", "A4")
        self.page_size_combo.addItem("Letter", "Letter")
        add_form_row(form, "Page size", self.page_size_combo)

        self.extra_container = QWidget()
        self.extra_layout = QVBoxLayout(self.extra_container)
        configure_box_layout(self.extra_layout, margins=(0, 0, 0, 0), spacing=8)
        self.extra_form = QFormLayout()
        configure_form_layout(self.extra_form, label_width=150)
        self.extra_layout.addLayout(self.extra_form)
        root.addWidget(self.extra_container)

        actions = QHBoxLayout()
        self.ok_btn = QPushButton("Export")
        self.cancel_btn = QPushButton("Cancel")
        add_left_aligned_buttons(actions, self.ok_btn, self.cancel_btn)
        root.addLayout(actions)

        self.browse_btn.clicked.connect(self._browse)
        self.ok_btn.clicked.connect(self._accept_if_valid)
        self.cancel_btn.clicked.connect(self.reject)
        polish_button_layouts(self)

    def _wrap(self, layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), self.file_edit.text().strip(), "PDF files (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path = f"{path}.pdf"
            self.file_edit.setText(path)

    def _accept_if_valid(self):
        path = self.file_edit.text().strip()
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"
            self.file_edit.setText(path)
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.accept()

    def pdf_options(self) -> PdfPageOptions:
        return PdfPageOptions(
            file_path=self.file_edit.text().strip(),
            page_size=str(self.page_size_combo.currentData() or "A4"),
            orientation=str(self.orientation_combo.currentData() or "portrait"),
        )


class TimelineExportDialog(_BasePdfDialog):
    def __init__(self, *, default_path: str, parent=None):
        super().__init__(
            title="Export current timeline to PDF",
            default_path=default_path,
            default_orientation="landscape",
            parent=parent,
        )
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Current visible view", "visible")
        self.scope_combo.addItem("Fit full project", "full")
        add_form_row(self.extra_form, "Range", self.scope_combo)

        self.include_dependencies = QCheckBox("Include dependency connectors")
        self.include_dependencies.setChecked(True)
        self.extra_layout.addWidget(self.include_dependencies)

        self.include_completed = QCheckBox("Include completed items")
        self.include_completed.setChecked(True)
        self.extra_layout.addWidget(self.include_completed)

    def timeline_options(self) -> TimelinePdfExportOptions:
        base = self.pdf_options()
        return TimelinePdfExportOptions(
            file_path=base.file_path,
            page_size=base.page_size,
            orientation=base.orientation,
            margin_mm=base.margin_mm,
            scope=str(self.scope_combo.currentData() or "visible"),
            include_dependencies=self.include_dependencies.isChecked(),
            include_completed=self.include_completed.isChecked(),
        )


class TaskListReportDialog(_BasePdfDialog):
    def __init__(self, *, default_path: str, title: str = "Current task list report", parent=None):
        super().__init__(
            title=title,
            default_path=default_path,
            default_orientation="landscape",
            parent=parent,
        )
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Export to PDF", "pdf")
        self.mode_combo.addItem("Print…", "print")
        add_form_row(self.extra_form, "Output", self.mode_combo)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        self._sync_mode()

    def _sync_mode(self):
        is_pdf = str(self.mode_combo.currentData() or "pdf") == "pdf"
        self.file_edit.setEnabled(is_pdf)
        self.browse_btn.setEnabled(is_pdf)
        self.ok_btn.setText("Export" if is_pdf else "Print")

    def output_mode(self) -> str:
        return str(self.mode_combo.currentData() or "pdf")


class ProjectSummaryExportDialog(_BasePdfDialog):
    def __init__(self, *, default_path: str, parent=None):
        super().__init__(
            title="Export project summary sheet",
            default_path=default_path,
            default_orientation="portrait",
            parent=parent,
        )
