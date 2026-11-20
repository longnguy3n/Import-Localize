from concurrent.futures import CancelledError
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMenu,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
)

from .transfer_preview import TransferPreview
from .feature_workspace import TransferDirections, open_child_feature
from import_localize.app.paths import USER_CONFIG_DIR
from import_localize.services.direct_transfer import apply_transfer, prepare_transfer
from import_localize.services.desc_annotations import DescAnnotations, upload_mapping_path
from .unity_audit import asset_audit_sources, review_sources


class TransferWorker(QThread):
    progress = Signal(int, str)

    def __init__(self, operation, task, parent):
        super().__init__(parent)
        self.operation = operation
        self.task = task
        self.result = None
        self.error = None
        self.cancelled = False

    def run(self):
        try:
            self.result = self.task(self.progress.emit, self.isInterruptionRequested)
        except CancelledError as exc:
            self.cancelled = True
            self.error = str(exc) or "Đã dừng tác vụ."
        except Exception as exc:
            self.error = str(exc) or "Đã dừng tác vụ."


class DirectSheetDialog(QDialog):
    log_emitted = Signal(str, str)

    def __init__(self, settings, direction, parent=None, *, annotations=None, folder_only=False):
        super().__init__(parent)
        if direction not in ("upload", "download"):
            raise ValueError("Chiều truyền không hợp lệ.")
        self.direction = direction
        self.upload = direction == "upload"
        self.folder_only = folder_only
        self.settings = settings
        self.annotations = annotations if annotations is not None else DescAnnotations()
        self.url = settings.sheet_url.strip()
        self.paths = [Path(p) for p in settings.unity_asset_files]
        self.asset_folder = settings.unity_folder
        self.folder_issues = ()
        if self.folder_only and not self.asset_folder:
            self.paths = []
        self.plan = None
        self.backup_path = None
        self.worker = None
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(950, 630)
        layout = QVBoxLayout(self)
        direction_row = QHBoxLayout()
        self.direction_combo = TransferDirections([("Unity → Sheet", "upload"), ("Sheet → Unity", "download")])
        self.direction_combo.setCurrentIndex(self.direction_combo.findData(direction))
        direction_row.addWidget(self.direction_combo)
        direction_row.addStretch()
        layout.addLayout(direction_row)
        self.sheet = QLabel(self.url or "Dán link bảng tính trên màn hình chính để bắt đầu.")
        self.sheet.setTextFormat(Qt.TextFormat.PlainText)
        self.sheet.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sheet.setWordWrap(True)
        layout.addWidget(self.sheet)

        toolbar = QHBoxLayout()
        self.add_button = QPushButton("Thêm asset…")
        self.folder_button = QPushButton("Chọn thư mục…")
        self.remove_button = QPushButton("Bỏ file đã chọn")
        for button in (self.add_button, self.folder_button, self.remove_button):
            toolbar.addWidget(button)
            button.setVisible(not folder_only)
        toolbar.addStretch()
        self.audit_button = QToolButton()
        self.audit_button.setText("Kiểm tra dữ liệu")
        self.audit_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.audit_button)
        self.mapping_action = menu.addAction("Kiểm tra mapping…", self.check_mapping)
        self.language_action = menu.addAction("Nhận diện ngôn ngữ…", self.check_language)
        menu.addAction("Kiểm tra key trùng trong asset…", self.check_duplicates)
        self.audit_button.setMenu(menu)
        self.audit_button.setVisible(not folder_only)
        toolbar.addWidget(self.audit_button)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 190)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 104)
        layout.addWidget(self.table, 1)
        self.changes = TransferPreview()
        layout.addWidget(self.changes)

        self.status = QLabel()
        self.status.setAccessibleName("Trạng thái truyền giữa Sheet và Unity")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.backup_button = QPushButton("Mở bản sao lưu")
        self.backup_button.hide()
        actions.addWidget(self.backup_button)
        actions.addStretch()
        self.stop_button = QPushButton("Dừng")
        self.stop_button.setProperty("dangerAction", True)
        self.preview_button = QPushButton("Xem trước")
        self.apply_button = QPushButton()
        self.close_button = QPushButton("Đóng")
        for button in (self.stop_button, self.preview_button, self.apply_button, self.close_button):
            actions.addWidget(button)
            button.setAutoDefault(False)
        layout.addLayout(actions)
        self.action_messages = (self.status, self.progress)
        self.action_buttons = (self.preview_button, self.apply_button, self.backup_button, self.stop_button, self.close_button)
        self.add_button.clicked.connect(self.choose_files)
        self.folder_button.clicked.connect(self.choose_folder)
        self.remove_button.clicked.connect(self.remove_selected)
        self.preview_button.clicked.connect(self.preview)
        self.apply_button.clicked.connect(self.apply)
        self.close_button.clicked.connect(self.reject)
        self.stop_button.clicked.connect(self.stop)
        self.backup_button.clicked.connect(self.open_backup)
        self.table.itemSelectionChanged.connect(self.update_controls)
        self.direction_combo.currentChanged.connect(self._direction_changed)
        self._direction_changed()

    def _direction_changed(self):
        if self.worker is not None:
            with QSignalBlocker(self.direction_combo):
                self.direction_combo.setCurrentIndex(self.direction_combo.findData(self.direction))
            return
        self.direction = self.direction_combo.currentData()
        self.settings.direct_direction = self.direction
        self.upload = self.direction == "upload"
        self.setWindowTitle("Unity → Google Sheets" if self.upload else "Google Sheets → Unity")
        source, target = ("Asset nguồn", "Tab nhận") if self.upload else ("Tab nguồn", "Asset nhận")
        self.table.setHorizontalHeaderLabels([source, target, "Dòng dữ liệu", "Thay đổi"])
        self.mapping_action.setVisible(self.upload)
        self.language_action.setVisible(self.upload)
        self.apply_button.setText("Ghi lên Sheet" if self.upload else "Ghi vào Unity")
        self.invalidate()

    def set_sheet_context(self, url, annotations):
        if self.url != url or self.annotations is not annotations:
            self.url = url
            self.annotations = annotations
            self.invalidate()

    def set_folder_files(self, paths, folder, issues=()):
        self.asset_folder = str(folder or "")
        self.paths = [Path(path) for path in paths]
        self.folder_issues = tuple(issues)
        self.invalidate()

    def invalidate(self):
        self.plan = None
        self.backup_button.hide()
        self.sheet.setText(self.url or "Dán link bảng tính trên màn hình chính để bắt đầu.")
        self.sheet.setToolTip(self.url)
        self.table.setRowCount(0)
        self.changes.hide()
        self.table.setVisible(not self.folder_only)
        shown = [] if self.folder_only else self.paths
        self.table.setRowCount(len(shown))
        for row, path in enumerate(shown):
            item = QTableWidgetItem(path.name)
            item.setToolTip(str(path))
            self.table.setItem(row, 0 if self.upload else 1, item)
        requirements = []
        if not self.url:
            requirements.append("Dán link Google Sheets.")
        if self.folder_issues:
            requirements.append(self.folder_issues[0])
        elif not self.paths:
            if self.folder_only and self.asset_folder:
                requirements.append("Chưa tìm thấy locale_<mã>.asset trong thư mục Unity locale. Kiểm tra thư mục rồi bấm Quét lại.")
            elif self.folder_only:
                requirements.append("Chọn thư mục Unity locale.")
            else:
                requirements.append("Chọn file locale*.asset để ghép với tab theo mã ngôn ngữ.")
        if requirements:
            message = " ".join(requirements)
        elif self.upload:
            message = f"{len(self.paths)} asset → các tab upload_* cùng mã ngôn ngữ."
        else:
            message = f"Các tab export_* → {len(self.paths)} asset cùng mã ngôn ngữ."
        self.status.setText(message)
        self.preview_button.setToolTip(message if requirements else "Đối chiếu các tab với asset theo mã ngôn ngữ và xem các key sẽ thay đổi.")
        self.update_controls()

    def update_controls(self):
        busy = self.worker is not None
        if hasattr(self, "workspace"):
            self.workspace.owner._sync_feature_controls()
        edit_files = not busy and not self.asset_folder and not self.folder_only
        self.add_button.setEnabled(edit_files)
        self.direction_combo.setEnabled(not busy)
        self.folder_button.setEnabled(edit_files)
        self.remove_button.setEnabled(edit_files and bool(self.table.selectionModel().selectedRows()))
        self.audit_button.setEnabled(not busy and bool(self.paths))
        self.preview_button.setEnabled(not busy and bool(self.paths) and bool(self.url) and not self.folder_issues)
        self.apply_button.setEnabled(not busy and self.plan is not None)
        if self.plan is None:
            self.apply_button.setToolTip("Xem trước các thay đổi để có thể ghi dữ liệu.")
        self.close_button.setEnabled(not busy)
        self.stop_button.setVisible(busy and (self.upload or self.worker.operation != "apply"))
        self.stop_button.setEnabled(busy and not self.worker.isInterruptionRequested())
        self.progress.setVisible(busy)
        for button, primary in ((self.preview_button, self.plan is None), (self.apply_button, self.plan is not None)):
            if button.property("primaryAction") != primary:
                button.setProperty("primaryAction", primary)
                button.style().unpolish(button)
                button.style().polish(button)

    def add_paths(self, added):
        if not added or self.asset_folder:
            return
        self.paths = list(dict.fromkeys([*self.paths, *(Path(p).resolve() for p in added)]))
        self.settings.unity_asset_files = [str(p) for p in self.paths]
        self.settings.unity_locale_dir = str(Path(added[0]).parent)
        self.invalidate()

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn asset", self.settings.unity_locale_dir,
                                                "Unity locale (locale*.asset);;Unity asset (*.asset)")
        self.add_paths(files)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Thư mục chứa locale*.asset", self.settings.unity_locale_dir)
        if folder:
            paths = sorted(Path(folder).glob("locale*.asset"))
            if paths:
                self.add_paths(paths)
            else:
                self.status.setText("Thư mục này không có file locale*.asset.")

    def remove_selected(self):
        if self.asset_folder:
            return
        selected = {i.row() for i in self.table.selectionModel().selectedRows()}
        self.paths = [p for i, p in enumerate(self.paths) if i not in selected]
        self.settings.unity_asset_files = [str(p) for p in self.paths]
        self.invalidate()

    def start_task(self, operation, task):
        if self.worker:
            return
        self.log_emitted.emit("INFO", f"{self.windowTitle()} · {self.status.text()}")
        self.worker = TransferWorker(operation, task, self)
        self.worker.progress.connect(self.show_progress)
        self.worker.finished.connect(self.task_finished)
        self.progress.setRange(0, 0)
        self.update_controls()
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.requestInterruption()
            self.status.setText("Đang dừng…")
            self.stop_button.setEnabled(False)
            self.log_emitted.emit("WARNING", "Đã yêu cầu dừng tác vụ.")

    def preview(self):
        self.invalidate()
        direction, url, paths = self.direction, self.url, list(self.paths)
        asset_folder = self.asset_folder
        option = self.settings.value_input_option
        mapping = upload_mapping_path(self.settings)
        annotations = self.annotations.snapshot(include_verified=not mapping)
        self.status.setText("Đang xác định bảng tính và ghép các tab…")
        self.start_task("preview", lambda progress, cancel: prepare_transfer(
            direction, url, paths, value_input_option=option, progress_callback=progress,
            cancel_callback=cancel, annotations=annotations, asset_folder=asset_folder, mapping_path=mapping,
        ))

    def apply(self):
        if self.plan is None or self.worker:
            return
        plan = self.plan
        self.plan = None
        self.status.setText("Đang ghi dữ liệu đã xem trước…")
        self.start_task("apply", lambda progress, cancel: apply_transfer(
            plan, USER_CONFIG_DIR / "unity_backups", progress_callback=progress, cancel_callback=cancel,
            log_callback=lambda message: self.log_emitted.emit("INFO", message),
        ))

    def check_mapping(self):
        self.review("mapping")

    def check_language(self):
        self.review("language")

    def review(self, kind):
        self.invalidate()
        paths = list(self.paths)
        self.status.setText("Đang đọc nội dung các asset…")
        self.start_task(kind, lambda progress, cancel: asset_audit_sources(paths, progress, cancel))

    def check_duplicates(self):
        if self.folder_only and not self.paths:
            return
        from .locale_duplicate_dialog import LocaleDuplicateDialog
        dialog = LocaleDuplicateDialog(self.paths, self, settings=self.settings)
        if dialog.paths:
            dialog.scan()
        def after_review():
            if dialog.wrote_files:
                self.invalidate()
        open_child_feature(self, dialog, after_review)

    @Slot(int, str)
    def show_progress(self, percent, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(percent)
        self.status.setText(message)
        self.log_emitted.emit("INFO", message)

    @Slot()
    def task_finished(self):
        worker = self.worker
        worker.wait()
        self.worker = None
        worker.deleteLater()
        if worker.error is not None:
            self.changes.hide()
            self.plan = None
            self.status.setText(worker.error)
            self.log_emitted.emit("WARNING" if worker.cancelled else "FAIL", worker.error)
        elif worker.operation == "preview":
            self.plan = worker.result
            self.sheet.setText(self.plan.spreadsheet_name)
            self.log_emitted.emit("SUCCESS", f"Đã xem trước {len(self.plan.pairs)} cặp · {self.plan.spreadsheet_name}")
            self.table.setVisible(not self.folder_only)
            self.table.setRowCount(len(self.plan.pairs))
            for row, pair in enumerate(self.plan.pairs):
                source, target = (pair.asset_path.name, pair.tab_name) if self.upload else (pair.tab_name, pair.asset_path.name)
                for col, text in enumerate((source, target, str(pair.row_count), pair.summary)):
                    item = QTableWidgetItem(text)
                    item.setToolTip(str(pair.asset_path) if col == (0 if self.upload else 1) else text)
                    self.table.setItem(row, col, item)
            changes = []
            for pair in self.plan.pairs:
                names = (pair.asset_path.name, pair.tab_name) if self.upload else (pair.tab_name, pair.asset_path.name)
                changes.append((*names, pair.stats, pair.summary))
                self.log_emitted.emit("INFO", f"{names[0]} → {names[1]} · {pair.summary}")
            self.changes.show_changes(changes)
            self.table.resizeRowsToContents()
            self.table.setMinimumHeight(min(280, self.table.horizontalHeader().height() + self.table.verticalHeader().length() + 6))
            count, title = len(self.plan.pairs), self.plan.spreadsheet_name
            self.apply_button.setToolTip(f"Ghi {count} tab vào bảng tính {title}." if self.upload else
                                         f"Ghi {count} asset từ bảng tính {title}.")
            if self.upload:
                new = sum(pair.tab_id is None for pair in self.plan.pairs)
                actions = []
                if new:
                    actions.append(f"tạo {new} tab")
                if new < count:
                    actions.append(f"thay nội dung {count - new} tab")
                self.status.setText(f"Khi ghi vào {title}, app sẽ " + " và ".join(actions) + ".")
            else:
                self.status.setText(f"Sẵn sàng ghi {count} asset từ {title}. Lưu asset và thoát Play Mode trước khi ghi. App sẽ tạo bản sao lưu.")
        elif worker.operation in ("mapping", "language"):
            self.update_controls()
            review_sources(worker.operation, self, self.settings, worker.result, self.annotations)
            self.invalidate()
        else:
            self.backup_path = worker.result
            self.backup_button.setVisible(self.backup_path is not None)
            self.status.setText(f"Đã ghi {self.table.rowCount()} tab." if self.upload else
                                f"Đã ghi {self.table.rowCount()} asset. Mở lại Unity hoặc Refresh để nạp bản dịch.")
            self.log_emitted.emit("SUCCESS", self.status.text())
        self.update_controls()

    def open_backup(self):
        if self.backup_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backup_path)))

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            event.ignore()
        else:
            super().closeEvent(event)
