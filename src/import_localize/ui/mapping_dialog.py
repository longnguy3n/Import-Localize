"""Offline mapping audit and explicit, sparse Google Sheet status updates."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


def snapshots(paths):
    result = {}
    for path in paths:
        try:
            result[str(path)] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError:
            result[str(path)] = None
    return result


class MappingWorker(QThread):
    progress = Signal(int, int, str)

    def __init__(self, mapping, paths, *, keys=None, sheet_url="", snapshot=None, parent=None):
        super().__init__(parent)
        self.mapping, self.paths = Path(mapping), list(map(Path, paths))
        self.keys, self.sheet_url = keys, sheet_url
        self.snapshot = snapshot
        self.result = None
        self.error = ""

    def run(self):
        try:
            inputs = [self.mapping, *self.paths]
            if self.keys is None:
                from import_localize.services.mapping_audit_service import audit_mapping
                before = snapshots(inputs)
                self.result = audit_mapping(self.mapping, self.paths,
                    progress_callback=self.progress.emit, cancel_callback=self.isInterruptionRequested)
                if snapshots(inputs) != before:
                    raise ValueError("File đã thay đổi trong lúc kiểm tra. Hãy kiểm tra lại.")
                self.snapshot = before
            else:
                from import_localize.services.google_service import connect_to_spreadsheet
                from import_localize.services.mapping_sheet_service import mark_wrong_mapping
                if snapshots(inputs) != self.snapshot:
                    raise ValueError("Mapping hoặc CSV đã thay đổi. Hãy kiểm tra lại trước khi ghi Sheet.")
                self.progress.emit(0, 0, "Đang kết nối Google…")
                connection = connect_to_spreadsheet(self.sheet_url,
                    progress_callback=lambda n, text: self.progress.emit(0, 0, text),
                    cancel_callback=self.isInterruptionRequested)
                if snapshots(inputs) != self.snapshot:
                    raise ValueError("Mapping hoặc CSV đã thay đổi. Hãy kiểm tra lại trước khi ghi Sheet.")
                self.result = mark_wrong_mapping(connection, self.keys,
                    progress_callback=lambda n, text: self.progress.emit(n, 100, text),
                    cancel_callback=self.isInterruptionRequested)
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__


class MappingDialog(QDialog):
    def __init__(self, settings, paths=(), parent=None):
        super().__init__(parent)
        self.settings = settings
        self.paths = list(dict.fromkeys(Path(p) for p in (settings.mapping_csv_files or paths)))
        self.report = None
        self.snapshot = None
        self.worker = None
        self.visible_issues = []
        self.setWindowTitle("Kiểm tra mapping — CSV → Translate_Data")
        self.resize(1180, 800)
        layout = QVBoxLayout(self)
        intro = QLabel("Đối chiếu thuật ngữ trong CSV với mapping.json v2. "
                       "Chỉ các key thuộc nhóm Sai mapping được đánh dấu trên Sheet; nhóm Cần xem ngữ cảnh giữ nguyên.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        path_row = QHBoxLayout()
        self.mapping_edit = QLineEdit(settings.mapping_path)
        if not self.mapping_edit.text():
            for path in self.paths:
                candidate = path.parent / "data" / "mapping.json"
                if candidate.is_file():
                    self.mapping_edit.setText(str(candidate))
                    break
        self.mapping_button = QPushButton("Chọn mapping.json…")
        path_row.addWidget(self.mapping_edit, 1)
        path_row.addWidget(self.mapping_button)
        form.addRow("Mapping", path_row)
        self.sheet_edit = QLineEdit(settings.sheet_url)
        self.sheet_edit.setPlaceholderText("Link Google Sheet để cập nhật Translate_Data")
        form.addRow("Sheet đích", self.sheet_edit)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.folder_button = QPushButton("Chọn thư mục DG…")
        self.files_button = QPushButton("Chọn nhiều CSV…")
        self.scan_button = QPushButton("Kiểm tra mapping")
        self.stop_button = QPushButton("Dừng")
        for button in (self.folder_button, self.files_button, self.scan_button, self.stop_button):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        filters = QHBoxLayout()
        self.filter_combo = QComboBox()
        for label, value in (("Tất cả phát hiện", ""), ("Sai mapping", "wrong"), ("Cần xem ngữ cảnh", "review")):
            self.filter_combo.addItem(label, value)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm key, thuật ngữ hoặc nội dung…")
        filters.addWidget(self.filter_combo)
        filters.addWidget(self.search, 1)
        layout.addLayout(filters)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.files_table = self._table(["File CSV (bấm để lọc)", "Sai mapping", "Cần xem ngữ cảnh", "Đọc dữ liệu"])
        self.issues_table = self._table(["Trạng thái", "File / Dòng", "Key", "Ngôn ngữ", "Mapping chuẩn", "Hiện tại"])
        splitter.addWidget(self.files_table)
        splitter.addWidget(self.issues_table)
        splitter.setSizes([170, 310])
        layout.addWidget(splitter, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(150)
        self.detail.setPlaceholderText("Chọn một phát hiện để xem đầy đủ nguồn, bản dịch và lý do.")
        layout.addWidget(self.detail)
        bottom = QHBoxLayout()
        self.all_files_button = QPushButton("Hiện tất cả file")
        self.mark_button = QPushButton("Ghi Wrong mapping vào Translate_Data!C")
        self.close_button = QPushButton("Đóng")
        bottom.addWidget(self.all_files_button)
        bottom.addStretch()
        bottom.addWidget(self.mark_button)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)
        self.mapping_button.clicked.connect(self.choose_mapping)
        self.folder_button.clicked.connect(self.choose_folder)
        self.files_button.clicked.connect(self.choose_files)
        self.scan_button.clicked.connect(self.scan)
        self.stop_button.clicked.connect(self.stop)
        self.close_button.clicked.connect(self.reject)
        self.mark_button.clicked.connect(self.mark)
        self.mapping_edit.textChanged.connect(self.invalidate)
        self.files_table.itemSelectionChanged.connect(self.filter_rows)
        self.filter_combo.currentIndexChanged.connect(self.filter_rows)
        self.search.textChanged.connect(self.filter_rows)
        self.issues_table.itemSelectionChanged.connect(self.show_detail)
        self.all_files_button.clicked.connect(self.files_table.clearSelection)
        self.invalidate()

    def _table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setWordWrap(False)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def invalidate(self):
        self.report = None
        self.snapshot = None
        self.files_table.setRowCount(0)
        self.issues_table.setRowCount(0)
        self.detail.clear()
        self.status.setText(f"Đã chọn {len(self.paths)} file CSV. Bấm Kiểm tra mapping để đọc toàn bộ các file này.")
        for path in self.paths:
            row = self.files_table.rowCount()
            self.files_table.insertRow(row)
            item = QTableWidgetItem(path.name)
            item.setToolTip(str(path))
            self.files_table.setItem(row, 0, item)
        self.set_busy(False)

    def set_busy(self, busy):
        for widget in (self.mapping_edit, self.mapping_button, self.folder_button,
                       self.files_button, self.scan_button, self.sheet_edit):
            widget.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.close_button.setEnabled(not busy)
        self.mark_button.setEnabled(not busy and bool(self.report and self.report.wrong_keys))

    def choose_mapping(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn mapping.json", self.mapping_edit.text(), "JSON (*.json)")
        if path:
            self.mapping_edit.setText(path)

    def choose_folder(self):
        initial = str(self.paths[0].parent) if self.paths else str(Path(self.mapping_edit.text()).parent)
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục DG chứa CSV và data/mapping.json", initial)
        if folder:
            root = Path(folder)
            self.paths = sorted(root.glob("*.csv"))
            candidate = root / "data" / "mapping.json"
            self.mapping_edit.setText(str(candidate))
            self.invalidate()

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn toàn bộ CSV cần đối chiếu (kèm tiếng Anh)",
            str(self.paths[0].parent) if self.paths else "", "CSV (*.csv)")
        if paths:
            self.paths = list(map(Path, paths))
            self.invalidate()

    def launch(self, worker):
        self.worker = worker
        self.set_busy(True)
        self.progress.setRange(0, 0)
        worker.progress.connect(self.on_progress)
        worker.finished.connect(self.finished_work)
        worker.start()

    def scan(self):
        if self.worker:
            return
        if not self.mapping_edit.text().strip() or not self.paths:
            self.status.setText("Chọn mapping.json và ít nhất một file CSV trước khi kiểm tra.")
            return
        self.invalidate()
        self.launch(MappingWorker(self.mapping_edit.text().strip(), self.paths, parent=self))

    def stop(self):
        if self.worker:
            self.worker.requestInterruption()
            self.status.setText("Đang dừng… Nếu một lệnh ghi đã gửi, cần chờ Google trả kết quả.")
            self.stop_button.setEnabled(False)

    @Slot(int, int, str)
    def on_progress(self, done, total, text):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(text)

    @Slot()
    def finished_work(self):
        worker = self.worker
        worker.wait()
        self.worker = None
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        if worker.error:
            self.status.setText(f"Không hoàn tất: {worker.error}")
        elif worker.keys is None:
            self.report, self.snapshot = worker.result, worker.snapshot
            self.render_report()
        else:
            result = worker.result
            self.status.setText(f"Đã ghi Wrong mapping: {result.updated_rows} hàng; "
                f"đã có sẵn: {result.already_marked_rows} hàng; không tìm thấy: {len(result.missing_keys)} key.")
            self.detail.setPlainText("Key không tìm thấy trong Translate_Data:\n" + "\n".join(sorted(result.missing_keys)))
        worker.deleteLater()
        self.set_busy(False)

    def render_report(self):
        report = self.report
        self.files_table.setRowCount(0)
        for path in report.files:
            issues = [issue for issue in report.issues if issue.path == path]
            values = [path.name, str(sum(i.status == "wrong" for i in issues)),
                      str(sum(i.status == "review" for i in issues)), report.errors.get(str(path), "Đã đọc")]
            row = self.files_table.rowCount()
            self.files_table.insertRow(row)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(str(path) if col == 0 else value)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.files_table.setItem(row, col, item)
        self.status.setText(f"Đã kiểm tra {report.checked_cells} ô / {len(report.files)} file · "
            f"{len(report.wrong_keys)} key sai mapping · {sum(i.status == 'review' for i in report.issues)} cần xem ngữ cảnh · "
            f"{report.unmapped_cells} ô chưa có mapping áp dụng · {len(report.errors)} file lỗi. "
            "Các bộ lọc chỉ thay đổi hiển thị; nút ghi xử lý toàn bộ key sai xác định.")
        self.filter_rows()

    def filter_rows(self):
        if not self.report:
            return
        rows = self.files_table.selectionModel().selectedRows()
        path = self.files_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None
        status, query = self.filter_combo.currentData(), self.search.text().casefold()
        self.visible_issues = [i for i in self.report.issues if (not path or str(i.path) == path)
            and (not status or i.status == status)
            and (not query or query in f"{i.key} {i.source} {i.actual} {i.expected} {i.reason}".casefold())]
        self.issues_table.setRowCount(0)
        for issue in self.visible_issues:
            row = self.issues_table.rowCount()
            self.issues_table.insertRow(row)
            values = ["Sai mapping" if issue.status == "wrong" else "Cần xem ngữ cảnh",
                      f"{issue.path.name} : {issue.line}", issue.key, issue.locale, issue.expected, issue.actual]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value.replace("\n", " ↵ "))
                item.setToolTip(value)
                if col == 0:
                    item.setBackground(QColor("#fee2e2" if issue.status == "wrong" else "#fef3c7"))
                    item.setForeground(QColor("#7f1d1d" if issue.status == "wrong" else "#78350f"))
                self.issues_table.setItem(row, col, item)

    def show_detail(self):
        rows = self.issues_table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self.visible_issues):
            self.detail.clear()
            return
        issue = self.visible_issues[rows[0].row()]
        self.detail.setPlainText(f"{issue.path}\nDòng {issue.line} · {issue.key} · {issue.locale}\n"
            f"Lý do: {issue.reason}\nMapping chuẩn: {issue.expected}\nNguồn: {issue.source}\nHiện tại: {issue.actual}")

    def mark(self):
        if self.worker or not self.report or not self.report.wrong_keys:
            return
        url = self.sheet_edit.text().strip()
        if not url:
            self.status.setText("Nhập link Google Sheet đích trước khi ghi Wrong mapping.")
            return
        keys = set(self.report.wrong_keys)
        text = (f"Ghi Wrong mapping vào cột C (Custom(modified)) của Translate_Data cho {len(keys)} key sai xác định?\n\n"
                f"Sheet: {url}\n\nCác trạng thái cũ ở đúng các key này sẽ được thay thế. "
                "Không sửa bản dịch hay các key chỉ cần xem ngữ cảnh. "
                "Không sắp xếp hoặc chỉnh sửa tab trong lúc đang ghi.")
        if QMessageBox.question(self, "Đánh dấu các key sai mapping", text) != QMessageBox.StandardButton.Yes:
            return
        self.launch(MappingWorker(self.mapping_edit.text().strip(), self.paths, keys=keys,
            sheet_url=url, snapshot=self.snapshot, parent=self))

    def reject(self):
        if self.worker:
            self.stop()
            return
        self.settings.mapping_path = self.mapping_edit.text().strip()
        self.settings.mapping_csv_files = [str(p) for p in self.paths]
        super().reject()

    def closeEvent(self, event):
        if self.worker:
            self.stop()
            event.ignore()
        else:
            self.reject()
            event.accept()
