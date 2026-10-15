from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, QUrl, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from import_localize.app.paths import USER_CONFIG_DIR
from import_localize.config.settings import AppSettings
from import_localize.services.unity_locale_service import (
    LocalePlan, apply_plan, prepare_export, prepare_import,
)


class LocaleWorker(QThread):
    def __init__(self, task: Callable, parent=None):
        super().__init__(parent)
        self.task = task
        self.result = None
        self.error = ""

    def run(self):
        try:
            self.result = self.task()
        except Exception as exc:
            self.error = str(exc)


class UnityLocaleDialog(QDialog):
    """Local files only; independent from Google authentication and sheet settings."""

    def __init__(self, settings: AppSettings, csv_paths: list[Path] | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.asset_paths: list[Path] = []
        self.csv_paths = csv_paths or []
        self.plan: LocalePlan | None = None
        self.worker: LocaleWorker | None = None
        self._applying = False
        self.backup_path: Path | None = None
        self.setWindowTitle("Unity Locale — Replace Import / Export")
        self.resize(1000, 720)
        layout = QVBoxLayout(self)
        intro = QLabel("I2 Localization / Dicegeon • Chọn file → Xem trước → Thực hiện Replace.\n"
                       "Import thay toàn bộ term trong asset bằng CSV. Hãy lưu asset và thoát Play Mode trong Unity trước khi thực hiện.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.controls = QWidget()
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        mode_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Replace Import: CSV → Unity .asset", "Replace Export: Unity .asset → CSV"])
        self.delimiter_combo = QComboBox()
        for label, value in [("Tự nhận diện (export dùng dấu phẩy)", "auto"), ("Dấu phẩy ,", ","), ("Chấm phẩy ;", ";"), ("Tab", "\t")]:
            self.delimiter_combo.addItem(label, value)
        mode_row.addWidget(self.mode_combo, 1)
        mode_row.addWidget(QLabel("Phân cách:"))
        mode_row.addWidget(self.delimiter_combo)
        controls.addLayout(mode_row)
        asset_row = QHBoxLayout()
        self.assets_button = QPushButton("Chọn locale*.asset…")
        self.folder_button = QPushButton("Chọn thư mục locale…")
        self.asset_label = QLabel("Chưa chọn asset")
        asset_row.addWidget(self.assets_button)
        asset_row.addWidget(self.folder_button)
        asset_row.addWidget(self.asset_label, 1)
        controls.addLayout(asset_row)
        self.import_controls = QWidget()
        csv_row = QHBoxLayout(self.import_controls)
        csv_row.setContentsMargins(0, 0, 0, 0)
        self.csv_button = QPushButton("Chọn CSV đã dịch…")
        self.csv_label = QLabel()
        csv_row.addWidget(self.csv_button)
        csv_row.addWidget(self.csv_label, 1)
        controls.addWidget(self.import_controls)
        self.export_controls = QWidget()
        export_layout = QVBoxLayout(self.export_controls)
        export_layout.setContentsMargins(0, 0, 0, 0)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit(settings.unity_export_dir)
        self.output_edit.setPlaceholderText("Thư mục lưu CSV")
        self.output_button = QPushButton("Chọn thư mục xuất…")
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self.output_button)
        export_layout.addLayout(output_row)
        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("Tên bảng tính:"))
        self.prefix_edit = QLineEdit(settings.unity_export_prefix)
        prefix_row.addWidget(self.prefix_edit, 1)
        prefix_row.addWidget(QLabel("→ [Tên bảng tính] - upload_en.csv"))
        export_layout.addLayout(prefix_row)
        controls.addWidget(self.export_controls)
        layout.addWidget(self.controls)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File đích", "Thay đổi", "Trạng thái"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 2)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Kết quả kiểm tra, cảnh báo key trùng và đường dẫn sao lưu sẽ hiện ở đây.")
        layout.addWidget(self.details, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.backup_button = QPushButton("Mở bản sao lưu")
        self.backup_button.setEnabled(False)
        self.preview_button = QPushButton("1. Xem trước")
        self.apply_button = QPushButton("2. Thực hiện Replace Import")
        self.close_button = QPushButton("Đóng")
        actions.addWidget(self.backup_button)
        actions.addStretch()
        for button in (self.preview_button, self.apply_button, self.close_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.assets_button.clicked.connect(self.choose_assets)
        self.folder_button.clicked.connect(self.choose_folder)
        self.csv_button.clicked.connect(self.choose_csv)
        self.output_button.clicked.connect(self.choose_output)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.delimiter_combo.currentIndexChanged.connect(self.invalidate)
        self.output_edit.textChanged.connect(self.invalidate)
        self.prefix_edit.textChanged.connect(self.invalidate)
        self.preview_button.clicked.connect(self.preview)
        self.apply_button.clicked.connect(self.apply)
        self.close_button.clicked.connect(self.reject)
        self.backup_button.clicked.connect(self.open_backup)
        self._mode_changed()
        self._update_labels()

    def _mode_changed(self):
        importing = self.mode_combo.currentIndex() == 0
        self.import_controls.setVisible(importing)
        self.export_controls.setVisible(not importing)
        self.apply_button.setText("2. Thực hiện Replace " + ("Import" if importing else "Export"))
        self.invalidate()

    def invalidate(self):
        self.plan = None
        self.apply_button.setEnabled(False)
        self.table.setRowCount(0)
        self.progress.setValue(0)

    def _update_labels(self):
        for label, paths in ((self.asset_label, self.asset_paths), (self.csv_label, self.csv_paths)):
            label.setText(f"{len(paths)} file đã chọn")
            label.setToolTip("\n".join(map(str, paths)))

    def choose_assets(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn I2 LanguageSourceAsset", self.settings.unity_locale_dir,
                                               "Unity locale (locale*.asset);;Unity asset (*.asset)")
        if paths:
            self.set_assets([Path(p) for p in paths])

    def set_assets(self, paths: list[Path]):
        self.asset_paths = paths
        if paths:
            self.settings.unity_locale_dir = str(paths[0].parent)
        self._update_labels()
        self.invalidate()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Thư mục chứa locale_*.asset", self.settings.unity_locale_dir)
        if folder:
            self.settings.unity_locale_dir = folder
            self.set_assets(sorted(Path(folder).glob("locale*.asset")))
            if not self.asset_paths:
                self.details.setPlainText("Không có locale*.asset trong thư mục này. Chọn thư mục Assets/AssetBundle/Localization của Dicegeon.")

    def choose_csv(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn CSV tương ứng với các asset", self.settings.unity_csv_dir or self.settings.last_export_dir,
                                               "CSV UTF-8 (*.csv)")
        if paths:
            self.csv_paths = [Path(p) for p in paths]
            self.settings.unity_csv_dir = str(self.csv_paths[0].parent)
            self._update_labels()
            self.invalidate()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Thư mục xuất CSV", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def _run(self, task: Callable, applying: bool):
        if self.worker:
            return
        self.controls.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self._applying = applying
        self.worker = LocaleWorker(task, self)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def preview(self):
        self.invalidate()
        assets, csv_paths = list(self.asset_paths), list(self.csv_paths)
        delimiter = self.delimiter_combo.currentData()
        self.details.setPlainText("Đang kiểm tra toàn bộ file…")
        if self.mode_combo.currentIndex() == 0:
            task = lambda: prepare_import(assets, csv_paths, delimiter)
        else:
            folder, prefix = Path(self.output_edit.text()), self.prefix_edit.text()
            if not self.output_edit.text().strip():
                self.details.setPlainText("Chọn thư mục xuất CSV trước khi xem trước.")
                return
            task = lambda: prepare_export(assets, folder, prefix, "," if delimiter == "auto" else delimiter)
        self._run(task, False)

    def apply(self):
        if self.plan:
            plan = self.plan
            self.details.appendPlainText("Đang sao lưu và ghi các file đã xem trước…")
            self._run(lambda: apply_plan(plan, USER_CONFIG_DIR / "unity_backups"), True)

    @Slot()
    def _finished(self):
        worker = self.worker
        worker.wait()
        applying = self._applying
        self.worker = None
        self.controls.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.progress.setRange(0, 1)
        if worker.error:
            self.plan = None
            self.details.appendPlainText("LỖI: " + worker.error)
            self.apply_button.setEnabled(False)
        elif applying:
            self.plan = None
            self.backup_path = worker.result
            self.backup_button.setEnabled(True)
            self.progress.setValue(1)
            for row in range(self.table.rowCount()):
                self.table.item(row, 2).setText("Đã ghi")
            self.details.appendPlainText(f"Hoàn tất. Bản sao lưu: {self.backup_path}\n"
                                         "Import: quay lại Unity và Refresh (Ctrl+R) nếu asset chưa cập nhật.\n"
                                         "Export: CSV upload_* có thể thêm trực tiếp vào luồng upload Google Sheets của ứng dụng.")
        else:
            self.plan = worker.result
            self.table.setRowCount(len(self.plan.changes))
            details = ["Kiểm tra thành công. Replace sẽ ghi đè các file dưới đây; file cũ được sao lưu ngoài thư mục Unity."]
            for row, change in enumerate(self.plan.changes):
                for col, value in enumerate((change.path.name, change.summary, "Ghi đè" if change.before is not None else "Tạo mới")):
                    item = QTableWidgetItem(value)
                    item.setToolTip(str(change.path) if col == 0 else value)
                    self.table.setItem(row, col, item)
                details.append(f"{change.path}\n{change.summary}")
                details.extend("  • " + warning for warning in change.warnings)
            self.details.setPlainText("\n\n".join(details))
            self.apply_button.setEnabled(True)
            self.progress.setValue(1)
        worker.deleteLater()

    def open_backup(self):
        if self.backup_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backup_path)))

    def reject(self):
        if self.worker:
            return
        self.settings.unity_export_dir = self.output_edit.text()
        self.settings.unity_export_prefix = self.prefix_edit.text()
        super().reject()

    def closeEvent(self, event: QCloseEvent):
        if self.worker:
            event.ignore()
        else:
            self.reject()
            event.accept()
