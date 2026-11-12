"""Offline CSV language results with per-column summaries and row inspection."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QTableView,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
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
            palette = self.parent().table.palette()
            dark_colors = {"match": ("#173d2a", "#bbf7d0"), "mismatch": ("#4c2020", "#fecaca"),
                           "uncertain": ("#45371d", "#fde68a"), "short": ("#293932", "#d2ded7"),
                           "unmapped": ("#45371d", "#fde68a")}
            colors = dark_colors if palette.color(QPalette.ColorRole.Base).lightness() < 128 else COLORS
            return QColor(colors[cell.status][0 if role == Qt.ItemDataRole.BackgroundRole else 1])
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
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(1180, 820)
        layout = QVBoxLayout(self)
        intro = QLabel("So sánh ngôn ngữ nội dung với tên cột. Xử lý offline, không thay đổi CSV.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        layout.addWidget(intro)
        actions = QHBoxLayout()
        self.choose_button = QPushButton("Chọn CSV…")
        self.scan_button = QPushButton("Kiểm tra lại")
        self.scan_button.setProperty("primaryAction", True)
        self.stop_button = QPushButton("Dừng")
        self.stop_button.setProperty("dangerAction", True)
        self.close_button = QPushButton("Đóng")
        for button in (self.choose_button, self.scan_button, self.stop_button):
            actions.addWidget(button)
        actions.addStretch()
        self.help_button = QToolButton()
        self.help_button.setText("Giới hạn nhận diện")
        self.help_button.setCheckable(True)
        self.help_button.setArrowType(Qt.ArrowType.RightArrow)
        self.help_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        actions.addWidget(self.help_button)
        layout.addLayout(actions)
        self.guidance = QLabel("Cảnh báo là dự đoán cần xem lại, không phải kết luận lỗi. "
                              "Tên riêng hoặc câu ngắn có thể chưa đủ dữ liệu. "
                              "Mô hình không phân biệt biến thể vùng như pt-BR/pt-PT. "
                              "Dòng CSV là dòng bắt đầu bản ghi, kể cả ô chứa nhiều dòng.")
        self.guidance.setWordWrap(True)
        self.guidance.setProperty("muted", True)
        self.guidance.hide()
        layout.addWidget(self.guidance)
        self.files_label = QLabel()
        self.files_label.setText("Chọn file CSV để bắt đầu nhận diện ngôn ngữ.")
        self.files_label.setWordWrap(True)
        layout.addWidget(self.files_label)
        self.summary = QTableWidget(0, 7)
        self.summary.setHorizontalHeaderLabels(["File / Cột", "Ngôn ngữ khai báo", "Nội dung nhận diện", "Tổng ô", "Phù hợp", "Nghi sai", "Chưa kết luận"])
        self.summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.summary.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.summary.verticalHeader().hide()
        self.summary.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.summary.horizontalHeader().setMinimumSectionSize(70)
        self.summary.horizontalHeader().setStretchLastSection(True)
        self.summary.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.summary.setMaximumHeight(220)
        self.summary.setWordWrap(True)
        self.summary.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.summary.viewport().installEventFilter(self)
        self.summary.setToolTip("Chọn một file/cột để lọc kết quả. Kéo vạch tiêu đề để đổi độ rộng; Shift + cuộn để cuộn ngang.")
        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.setInterval(80)
        self._summary_timer.timeout.connect(self.resize_summary)
        self.summary.horizontalHeader().sectionResized.connect(lambda *_: self._summary_timer.start())
        for i, width in enumerate((300, 180, 300, 90, 100, 90, 140)):
            self.summary.setColumnWidth(i, width)
        layout.addWidget(self.summary, 1)
        filters = QHBoxLayout()
        self.column_combo = QComboBox()
        self.column_combo.addItem("Tất cả file / cột", None)
        self.filter_combo = QComboBox()
        for text, value in (("Dòng nghi sai", "mismatch"), ("Chưa kết luận", "unresolved"), ("Tất cả dòng", "all"), ("Phù hợp", "match")):
            self.filter_combo.addItem(text, value)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm key hoặc nội dung…")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.column_combo, 2)
        filters.addWidget(self.filter_combo)
        filters.addWidget(self.search, 2)
        self.fit_button = QPushButton("Căn lại cột")
        filters.addWidget(self.fit_button)
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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setMinimumSectionSize(60)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.viewport().installEventFilter(self)
        self.table.setToolTip("Chọn dòng để xem nguyên văn bên dưới. Kéo vạch tiêu đề để chỉnh cột; Shift + cuộn để cuộn ngang.")
        for i, width in enumerate((185, 200, 90, 180, 130, 145, 150, 420)):
            self.table.setColumnWidth(i, width)
        layout.addWidget(self.table, 3)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setPlaceholderText("Chọn một dòng để xem đầy đủ nội dung gốc, ngôn ngữ và lý do cảnh báo.")
        self.content.setMaximumHeight(155)
        self.content.hide()
        layout.addWidget(self.content, 1)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a1232b")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.choose_button.clicked.connect(self.choose_files)
        self.scan_button.clicked.connect(self.start_scan)
        self.stop_button.clicked.connect(self.stop)
        self.close_button.clicked.connect(self.reject)
        self.column_combo.currentIndexChanged.connect(self.filter_rows)
        self.filter_combo.currentIndexChanged.connect(self.filter_rows)
        self.search.textChanged.connect(self.filter_rows)
        self.fit_button.clicked.connect(self.fit_columns)
        self.help_button.toggled.connect(self.toggle_guidance)
        self.summary.itemSelectionChanged.connect(self.select_column)
        self.table.selectionModel().selectionChanged.connect(self.show_content)
        self._set_busy(False)
        if self.paths:
            self.start_scan()

    def toggle_guidance(self, expanded):
        self.guidance.setVisible(expanded)
        self.help_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            table = self.summary if watched is self.summary.viewport() else self.table
            delta = event.pixelDelta().x() or event.pixelDelta().y()
            if not delta:
                delta = (event.angleDelta().x() or event.angleDelta().y()) / 120 * 80
            bar = table.horizontalScrollBar()
            bar.setValue(bar.value() - round(delta))
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def fit_columns(self):
        for table in (self.summary, self.table):
            header = table.horizontalHeader()
            header.setStretchLastSection(False)
            table.resizeColumnsToContents()
            for column in range(table.model().columnCount()):
                limit = (300, 170, 320, 90, 100, 100, 150)[column] if table is self.summary else (175, 170, 90, 190, 120, 125, 140, 420)[column]
                table.setColumnWidth(column, min(limit, max(90, table.columnWidth(column) + 18)))
            header.setStretchLastSection(True)
        self._summary_timer.start()

    def resize_summary(self):
        self.summary.resizeRowsToContents()
        height = self.summary.horizontalHeader().height() + sum(self.summary.rowHeight(row) for row in range(min(3, self.summary.rowCount()))) + 22
        self.summary.setMinimumHeight(min(220, max(100, height)))

    def _set_busy(self, busy):
        self.choose_button.setEnabled(not busy)
        self.scan_button.setEnabled(not busy and bool(self.paths))
        self.stop_button.setEnabled(busy)
        self.stop_button.setVisible(busy)
        self.progress.setVisible(busy)
        for widget in (self.column_combo, self.filter_combo, self.search, self.fit_button):
            widget.setEnabled(not busy and self.report is not None)

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
        self.error_label.hide()
        names = ", ".join(p.name for p in self.paths[:2])
        if len(self.paths) > 2:
            names += f" · và {len(self.paths) - 2} file khác"
        self.files_label.setText(f"{len(self.paths)} CSV · {names}")
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
                        self.summary.ensurePolished()
                        dark = self.summary.palette().color(QPalette.ColorRole.Base).lightness() < 128
                        item.setBackground(QColor("#4c2020" if dark else "#ffe5e5"))
                        item.setForeground(QColor("#fecaca" if dark else "#a1232b"))
                    self.summary.setItem(i, j, item)
                self.column_combo.addItem(f"{col.path.name} / {col.column}", i)
            self.error_label.setText("\n".join(self.report.errors))
            self.status.setText(f"Đã kiểm tra {len(self.report.columns)} cột" +
                (f" · {len(self.report.errors)} file lỗi" if self.report.errors else "") + ". Chọn dòng để xem nguyên văn.")
            self.filter_rows()
            self.fit_columns()
        self.error_label.setVisible(bool(self.error_label.text()))
        self.ensurePolished()
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        self.error_label.setStyleSheet("color: " + ("#fecaca" if dark else "#a1232b"))
        self._set_busy(False)
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
        self.content.hide()
        if self.report:
            self.result_label.setText(f"{len(rows)} ô theo bộ lọc" if rows else "Không có ô phù hợp bộ lọc. Thử chọn Tất cả dòng hoặc bỏ tìm kiếm.")
        else:
            self.result_label.setText("Chưa có kết quả nhận diện.")

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
        self.content.show()

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
