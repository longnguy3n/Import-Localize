"""Offline CSV language results with per-column summaries and row inspection."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QTableView,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from import_localize.services.csv_language_service import STATUS, COLORS, language_name
from import_localize.services.language_audit_process import read_report


class LanguageWorker(QThread):
    progress = Signal(int, int, str)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.result = None
        self.error = ""
        self.cancelled = False

    def run(self):
        try:
            with tempfile.TemporaryDirectory(prefix="import-localize-language-") as directory:
                folder = Path(directory)
                (folder / "request.json").write_text(json.dumps({"paths": [str(p.resolve()) for p in self.paths]}), encoding="utf-8")
                command = [sys.executable]
                if not getattr(sys, "frozen", False):
                    command.append(str(Path(__file__).resolve().parents[2] / "main.py"))
                command.extend(["--language-audit", str(folder)])
                environment = os.environ.copy()
                environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                # Bound model parallelism so the UI and other apps retain CPU.
                environment["RAYON_NUM_THREADS"] = "4"
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                with (folder / "progress.jsonl").open("w+", encoding="utf-8") as stream:
                    process = subprocess.Popen(command, env=environment, creationflags=flags,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    try:
                        cancelled_at = None
                        pending = ""
                        while True:
                            if self.isInterruptionRequested() and cancelled_at is None:
                                self.cancelled = True
                                cancelled_at = time.monotonic()
                                (folder / "cancel").touch()
                            pending += stream.read()
                            lines = pending.split("\n")
                            pending = lines.pop()
                            for line in lines:
                                self.progress.emit(*json.loads(line))
                            if process.poll() is not None:
                                break
                            if cancelled_at is not None and time.monotonic() - cancelled_at > 5:
                                process.terminate()
                            self.msleep(50)
                        if self.isInterruptionRequested():
                            self.cancelled = True
                        if not self.cancelled:
                            result_path = folder / "result.json"
                            if process.returncode or not result_path.exists():
                                raise RuntimeError(f"Tiến trình nhận diện kết thúc bất thường (mã {process.returncode}).")
                            response = json.loads(result_path.read_text(encoding="utf-8"))
                            self.error = response.get("error", "")
                            self.cancelled = response.get("cancelled", False)
                            if "report" in response:
                                self.result = read_report(response["report"])
                    finally:
                        if process.poll() is None:
                            process.kill()
                        process.wait()
        except Exception as exc:
            self.error = str(exc)


class LanguageRowsModel(QAbstractTableModel):
    headers = ("Trạng thái", "File", "Dòng CSV", "Key", "Cột", "Khai báo", "Nhận diện", "Nội dung")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        cell = self.rows[index.row()]
        if role in (Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole) and index.column() == 0:
            return QColor(COLORS[cell.status][0 if role == Qt.ItemDataRole.BackgroundRole else 1])
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{cell.path}\nDòng bắt đầu bản ghi: {cell.line}\n{cell.text}"
        if role == Qt.ItemDataRole.DisplayRole:
            predicted = language_name(cell.prediction.code)
            if cell.prediction.code and not cell.prediction.reliable:
                predicted += " (gợi ý)"
            return (STATUS[cell.status], cell.path.name, cell.line, cell.key, cell.column,
                    language_name(cell.expected), predicted, cell.text.replace("\n", " ↵ "))[index.column()]


class CsvLanguageDialog(QDialog):
    def __init__(self, paths=(), parent=None):
        super().__init__(parent)
        self.paths = list(map(Path, paths))
        self.worker = None
        self.report = None
        self._closing = False
        self.setWindowTitle("Nhận diện ngôn ngữ CSV — Offline")
        self.resize(1180, 820)
        layout = QVBoxLayout(self)
        intro = QLabel("Phân tích nội dung từng cột rồi so với tên cột. Chạy offline, không sửa CSV.\n"
                       "Cảnh báo là dự đoán cần kiểm tra; tên riêng/câu ngắn có thể chưa đủ dữ liệu. "
                       "Không phân biệt biến thể vùng như pt-BR/pt-PT.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        actions = QHBoxLayout()
        self.choose_button = QPushButton("Chọn CSV…")
        self.scan_button = QPushButton("Kiểm tra lại")
        self.stop_button = QPushButton("Dừng")
        self.close_button = QPushButton("Đóng")
        for button in (self.choose_button, self.scan_button, self.stop_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.files_label = QLabel()
        self.files_label.setWordWrap(True)
        layout.addWidget(self.files_label)
        self.summary = QTableWidget(0, 7)
        self.summary.setHorizontalHeaderLabels(["File / Cột", "Ngôn ngữ khai báo", "Nội dung nhận diện", "Tổng ô", "Phù hợp", "Nghi sai", "Chưa kết luận"])
        self.summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.summary.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.summary.verticalHeader().hide()
        self.summary.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for i in (0, 2):
            self.summary.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.summary.setMaximumHeight(220)
        layout.addWidget(self.summary, 1)
        filters = QHBoxLayout()
        self.column_combo = QComboBox()
        self.column_combo.addItem("Tất cả file / cột", None)
        self.filter_combo = QComboBox()
        for text, value in (("Dòng nghi sai", "mismatch"), ("Chưa kết luận", "unresolved"), ("Tất cả dòng", "all"), ("Phù hợp", "match")):
            self.filter_combo.addItem(text, value)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm key hoặc nội dung…")
        filters.addWidget(self.column_combo, 2)
        filters.addWidget(self.filter_combo)
        filters.addWidget(self.search, 2)
        layout.addLayout(filters)
        self.result_label = QLabel()
        layout.addWidget(self.result_label)
        self.table = QTableView()
        self.model = LanguageRowsModel(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 3)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setPlaceholderText("Chọn một dòng để xem đầy đủ nội dung gốc, ngôn ngữ và lý do cảnh báo.")
        self.content.setMaximumHeight(155)
        layout.addWidget(self.content, 1)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a1232b")
        layout.addWidget(self.error_label)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.choose_button.clicked.connect(self.choose_files)
        self.scan_button.clicked.connect(self.start_scan)
        self.stop_button.clicked.connect(self.stop)
        self.close_button.clicked.connect(self.reject)
        self.column_combo.currentIndexChanged.connect(self.filter_rows)
        self.filter_combo.currentIndexChanged.connect(self.filter_rows)
        self.search.textChanged.connect(self.filter_rows)
        self.summary.itemSelectionChanged.connect(self.select_column)
        self.table.selectionModel().selectionChanged.connect(self.show_content)
        self._set_busy(False)
        if self.paths:
            self.start_scan()

    def _set_busy(self, busy):
        self.choose_button.setEnabled(not busy)
        self.scan_button.setEnabled(not busy and bool(self.paths))
        self.stop_button.setEnabled(busy)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn CSV để nhận diện ngôn ngữ",
            str(self.paths[0].parent) if self.paths else "", "CSV UTF-8 (*.csv)")
        if paths:
            self.paths = list(map(Path, paths))
            self.start_scan()

    def start_scan(self):
        if self.worker or not self.paths:
            return
        self.report = None
        self.summary.setRowCount(0)
        self.column_combo.clear()
        self.column_combo.addItem("Tất cả file / cột", None)
        self.filter_rows()
        self.error_label.clear()
        self.files_label.setText(f"{len(self.paths)} file · " + ", ".join(p.name for p in self.paths))
        self.files_label.setToolTip("\n".join(map(str, self.paths)))
        self._set_busy(True)
        self.progress.setRange(0, 0)
        self.status.setText("Đang đọc CSV và chuẩn bị mô hình offline…")
        self.worker = LanguageWorker(self.paths, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.finished_scan)
        self.worker.start()

    @Slot(int, int, str)
    def on_progress(self, done, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(message)

    @Slot()
    def finished_scan(self):
        worker = self.worker
        worker.wait()
        self.worker = None
        self._set_busy(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0 if worker.cancelled or worker.error else 1)
        if worker.cancelled:
            self.status.setText("Đã dừng. Chưa có kết quả đầy đủ; bấm Kiểm tra lại để chạy lại.")
        elif worker.error:
            self.status.setText("Không thể hoàn tất nhận diện.")
            self.error_label.setText(worker.error)
        else:
            self.report = worker.result
            self.summary.setRowCount(len(self.report.columns))
            for i, col in enumerate(self.report.columns):
                counts = col.counts
                detected = "; ".join(f"{language_name(code)}: {count} ô" for code, count in col.languages.most_common()) or "Chưa đủ kết quả chắc chắn"
                values = (f"{col.path.name} / {col.column}", language_name(col.expected), detected,
                          len(col.cells), counts["match"], counts["mismatch"], len(col.cells) - counts["match"] - counts["mismatch"])
                for j, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(col.path) if j == 0 else str(value))
                    if j == 5 and counts["mismatch"]:
                        item.setBackground(QColor("#ffe5e5"))
                        item.setForeground(QColor("#a1232b"))
                    self.summary.setItem(i, j, item)
                self.column_combo.addItem(f"{col.path.name} / {col.column}", i)
            self.error_label.setText("\n".join(self.report.errors))
            self.status.setText("Đã kiểm tra xong" + (f" · {len(self.report.errors)} file lỗi" if self.report.errors else "") +
                ". Số liệu nhận diện tính theo ô; chưa kết luận không có nghĩa là đúng ngôn ngữ.")
            self.filter_rows()
        worker.deleteLater()
        if self._closing:
            super().reject()

    def select_column(self):
        row = self.summary.currentRow()
        if row >= 0:
            self.column_combo.setCurrentIndex(row + 1)

    def filter_rows(self, *_):
        selected = self.column_combo.currentData()
        status = self.filter_combo.currentData()
        query = self.search.text().strip().casefold()
        rows = []
        if self.report:
            for i, column in enumerate(self.report.columns):
                if selected is not None and selected != i:
                    continue
                for cell in column.cells:
                    if status == "unresolved" and cell.status in ("match", "mismatch"):
                        continue
                    if status not in ("all", "unresolved") and cell.status != status:
                        continue
                    if query and query not in cell.key.casefold() and query not in cell.text.casefold():
                        continue
                    rows.append(cell)
        self.model.beginResetModel()
        self.model.rows = rows
        self.model.endResetModel()
        self.content.clear()
        self.result_label.setText(f"Hiển thị {len(rows)} ô · Dòng CSV là dòng bắt đầu bản ghi, kể cả ô chứa nhiều dòng.")

    def show_content(self, *_):
        index = self.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.model.rows):
            return
        cell = self.model.rows[index.row()]
        p = cell.prediction
        detail = f"{cell.path}\nDòng {cell.line} · Key: {cell.key} · Cột: {cell.column}\n"
        detail += f"Khai báo: {language_name(cell.expected)} → Nhận diện: {language_name(p.code)} · {STATUS[cell.status]}\n"
        if p.code:
            detail += f"Điểm mô hình: {p.score:.3f}; chênh lệch với ngôn ngữ kế tiếp: {p.margin:.3f}. Đây không phải tỷ lệ chính xác đã kiểm chứng.\n"
        if cell.status == "mismatch":
            detail += "Nội dung có dấu hiệu thuộc ngôn ngữ khác tên cột. Kiểm tra tên riêng hoặc câu cố ý giữ nguyên trước khi sửa.\n"
        if cell.status == "unmapped":
            detail += "Tên cột không có tên/mã ngôn ngữ được hỗ trợ nên chưa thể đối chiếu.\n"
        if p.sampled:
            detail += "Ô dài: mô hình phân tích 2.000 ký tự đầu và 2.000 ký tự cuối.\n"
        self.content.setPlainText(detail + "\nNỘI DUNG GỐC\n" + cell.text)

    def stop(self):
        if self.worker:
            self.worker.requestInterruption()
            self.stop_button.setEnabled(False)
            self.status.setText("Đang dừng sau ô hiện tại…")

    def reject(self):
        if self.worker:
            self._closing = True
            self.stop()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            self._closing = True
            self.stop()
            event.ignore()
        else:
            super().closeEvent(event)
