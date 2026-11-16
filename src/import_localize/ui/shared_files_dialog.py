"""Edit the ordered files reused by the transfer workflows."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from import_localize.app.constants import MAX_CSV_FILES
from import_localize.services.csv_service import CsvImportError, inspect_csv
from .unity_locale_dialog import FileOrderList


class SharedFilesDialog(QDialog):
    def __init__(self, csv_paths, asset_paths, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tệp dùng chung")
        self.resize(690, 360)
        self.csv_dir = settings.last_csv_dir
        self.asset_dir = settings.unity_locale_dir
        self.initial_csvs = [Path(path) for path in csv_paths]
        self.csv_infos = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.csv_list = self.add_list(
            "CSV upload", "Nguồn để nhập lên Sheet. Có thể dùng làm file nhận khi xuất từ Unity.",
            self.initial_csvs,
        )
        self.asset_list = self.add_list(
            "Unity locale", "Các asset dùng cho cả CSV ↔ Unity và Sheet ↔ Unity.",
            [Path(path) for path in asset_paths],
        )
        controls = QHBoxLayout()
        self.add_button = QPushButton("Thêm tệp…")
        self.up_button = QPushButton("Lên")
        self.down_button = QPushButton("Xuống")
        self.remove_button = QPushButton("Bỏ tệp đã chọn")
        self.clear_button = QPushButton("Bỏ tất cả")
        self.up_button.clicked.connect(lambda: self.active_list().move_selected(-1))
        self.down_button.clicked.connect(lambda: self.active_list().move_selected(1))
        self.remove_button.clicked.connect(lambda: self.active_list().remove_selected())
        self.clear_button.clicked.connect(lambda: self.active_list().clear_files())
        self.add_button.clicked.connect(self.choose_files)
        for button in (self.add_button, self.up_button, self.down_button, self.remove_button, self.clear_button):
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Lưu lựa chọn")
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("primaryAction", True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.tabs.currentChanged.connect(self.update_controls)
        for view in (self.csv_list, self.asset_list):
            view.itemSelectionChanged.connect(self.update_controls)
            view.order_changed.connect(self.update_controls)
        self.update_controls()

    def add_list(self, title, description, paths):
        page = QWidget()
        layout = QVBoxLayout(page)
        help_label = QLabel(description)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        view = FileOrderList()
        view.setAccessibleName(title)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.set_paths(paths)
        layout.addWidget(view)
        self.tabs.addTab(page, title)
        return view

    def active_list(self):
        return self.csv_list if self.tabs.currentIndex() == 0 else self.asset_list

    def update_controls(self):
        for idx, title, view in ((0, "CSV upload", self.csv_list), (1, "Unity locale", self.asset_list)):
            self.tabs.setTabText(idx, f"{title} ({view.count()})")
        view = self.active_list()
        rows = [view.row(item) for item in view.selectedItems()]
        self.up_button.setEnabled(bool(rows) and min(rows) > 0)
        self.down_button.setEnabled(bool(rows) and max(rows) < view.count() - 1)
        self.remove_button.setEnabled(bool(rows))
        self.clear_button.setEnabled(bool(view.count()))

    def choose_files(self):
        view = self.active_list()
        csv = view is self.csv_list
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Chọn CSV upload" if csv else "Chọn Unity locale",
            self.csv_dir if csv else self.asset_dir,
            "CSV (*.csv)" if csv else "Unity locale (locale*.asset);;Unity asset (*.asset)",
        )
        if paths:
            if csv:
                self.csv_dir = str(Path(paths[0]).parent)
            else:
                self.asset_dir = str(Path(paths[0]).parent)
            view.set_paths(list(dict.fromkeys([*view.paths(), *(Path(p).resolve() for p in paths)])))
            self.update_controls()

    def accept(self):
        paths = self.csv_list.paths()
        if paths != self.initial_csvs:
            try:
                if len(paths) > MAX_CSV_FILES:
                    raise CsvImportError(f"Chọn tối đa {MAX_CSV_FILES} file CSV.")
                self.csv_infos = [inspect_csv(str(p), require_localization_name=False) for p in paths]
            except (CsvImportError, OSError) as exc:
                self.tabs.setCurrentIndex(0)
                QMessageBox.warning(self, "Kiểm tra lại CSV", str(exc))
                return
        super().accept()
