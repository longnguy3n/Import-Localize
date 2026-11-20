from __future__ import annotations

from concurrent.futures import CancelledError
from html import escape
from pathlib import Path
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QTextEdit, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget,
)

from import_localize.services.csv_compare_service import CsvComparison, compare_csv_files
from .change_colors import status_colors
from .transfer_diff_dialog import marked_values
from .feature_workspace import start_feature_worker

STATUS_LABELS = {"added": "+ Key mới", "removed": "− Đã xóa", "changed": "≠ Thay đổi", "unchanged": "= Không đổi"}
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class CompareWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, old_path, new_path, parent=None):
        super().__init__(parent)
        self.paths = old_path, new_path

    def run(self):
        try:
            result = compare_csv_files(*self.paths, cancel_callback=self.isInterruptionRequested)
            self.result_ready.emit(result)
        except CancelledError:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))


class ComparisonModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.result = None

    def filter(self, result, status, query):
        self.beginResetModel()
        self.result = result
        self.rows = []
        query = query.casefold().strip()
        if result:
            for diff in result.differences:
                if status == "differences" and diff.status == "unchanged":
                    continue
                if status not in ("all", "differences") and diff.status != status:
                    continue
                if query and query not in diff.key.casefold():
                    continue
                columns = diff.changed_columns if diff.status == "changed" else tuple(result.columns)
                self.rows.extend((diff, col) for col in (columns or (None,)))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ("Trạng thái", "Key", "Cột", "− Bản cũ", "+ Bản mới")[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        diff, col = self.rows[index.row()]
        column = index.column()
        if role == SORT_ROLE:
            if column == 0:
                return ("added", "changed", "removed", "unchanged").index(diff.status)
            if column == 1:
                return diff.key
            if column == 2:
                return self.result.columns.get(col, "")
            record = diff.before if column == 3 else diff.after
            return (record.get(col, "") if col is not None else diff.key) if record is not None else ""
        if column == 0:
            if role == Qt.ItemDataRole.BackgroundRole:
                return QColor(status_colors()[diff.status][0])
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor(status_colors()[diff.status][1])
            if role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setBold(True)
                return font
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if column < 3:
                return (STATUS_LABELS[diff.status], diff.key, self.result.columns.get(col, "(chỉ key)"))[column]
            record = diff.before if column == 3 else diff.after
            value = record.get(col) if record is not None and col is not None else None
            if col is None:
                return diff.key if record is not None else "Không tồn tại"
            if value is None:
                return "Không tồn tại"
            if value == "":
                return '(rỗng)'
            return value if role == Qt.ItemDataRole.ToolTipRole else value.replace("\r\n", "\n").replace("\n", " ↵ ").replace("\t", " ⇥ ")
        if diff.status != "unchanged" and column in (3, 4) and role in (
            Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole
        ):
            background, foreground = status_colors()["removed" if column == 3 else "added"]
            return QColor(background if role == Qt.ItemDataRole.BackgroundRole else foreground)
        return None


class ComparisonSortModel(QSortFilterProxyModel):
    """Sort raw values, then key and source column order for deterministic ties."""

    def lessThan(self, left, right):
        source = self.sourceModel()
        def sort_key(index):
            value = source.data(index, SORT_ROLE)
            diff, col = source.rows[index.row()]
            primary = (value.casefold(), value) if isinstance(value, str) else (value,)
            return primary, diff.key.casefold(), diff.key, index.row()
        return sort_key(left) < sort_key(right)


class CsvCompareDialog(QDialog):
    log_emitted = Signal(str, str)

    def __init__(self, old_path: str = "", new_path: str = "", parent=None, *, choices=None):
        super().__init__(parent)
        self.setWindowTitle("So sánh CSV theo key")
        self.setObjectName("csvCompareDialog")
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(1120, 760)
        self.setMinimumSize(660, 500)
        self.paths = old_path, new_path
        self.result: CsvComparison | None = None
        self.worker = None
        self._closing = False
        layout = QVBoxLayout(self)
        self.files_label = QLabel()
        self.files_label.setTextFormat(Qt.TextFormat.PlainText)
        self.files_label.setWordWrap(True)
        self.files_label.setProperty("muted", True)
        layout.addWidget(self.files_label)
        controls = QHBoxLayout()
        self.swap_button = QPushButton("Đổi cũ ↔ mới")
        self.filter_combo = QComboBox()
        for text, status in (("Chỉ khác biệt", "differences"), ("Key mới", "added"), ("Key đã xóa", "removed"), ("Key thay đổi", "changed"), ("Không đổi", "unchanged"), ("Tất cả", "all")):
            self.filter_combo.addItem(text, status)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Tìm theo key…")
        self.search_edit.setClearButtonEnabled(True)
        controls.addWidget(self.swap_button)
        controls.addWidget(self.filter_combo)
        controls.addWidget(self.search_edit, 1)
        layout.addLayout(controls)
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.summary_label)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(8)
        splitter.setChildrenCollapsible(False)
        self.table = QTableView()
        self.table.setObjectName("csvComparisonTable")
        self.model = ComparisonModel(self)
        self.sort_model = ComparisonSortModel(self)
        self.sort_model.setSourceModel(self.model)
        self.table.setModel(self.sort_model)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(80)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setToolTip("Kéo mép tiêu đề để chỉnh độ rộng; nhấp đúp để vừa nội dung.")
        for col, width in ((0, 125), (1, 210), (2, 100)):
            header.resizeSection(col, width)
        for col in (3, 4):
            header.resizeSection(col, 300)
        splitter.addWidget(self.table)
        details = QWidget()
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_label = QLabel("Chọn một dòng để xem đầy đủ nội dung và sao chép.")
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_label)
        panes = QSplitter(Qt.Orientation.Horizontal)
        panes.setHandleWidth(8)
        panes.setChildrenCollapsible(False)
        self.old_text = QTextEdit()
        self.new_text = QTextEdit()
        for title, pane in (("Bản cũ", self.old_text), ("Bản mới", self.new_text)):
            pane.setReadOnly(True)
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(title)
            label.setProperty("sectionTitle", True)
            panel_layout.addWidget(label)
            panel_layout.addWidget(pane)
            panes.addWidget(panel)
        detail_layout.addWidget(panes)
        splitter.addWidget(details)
        splitter.setSizes([400, 180])
        layout.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.visible_label = QLabel()
        footer.addWidget(self.visible_label, 1)
        close = QPushButton("Đóng")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.action_messages = (self.summary_label, self.visible_label)
        self.action_buttons = (self.swap_button, close)
        self.swap_button.clicked.connect(self._swap)
        self.filter_combo.currentIndexChanged.connect(self._filter)
        self.search_edit.textChanged.connect(self._filter)
        self.table.selectionModel().currentRowChanged.connect(self._show_detail)
        self.pickers = []
        if choices is not None:
            row = QHBoxLayout()
            for index, title in enumerate(("Bản cũ", "Bản mới")):
                picker = QComboBox()
                picker.setAccessibleName(title)
                for path in choices:
                    picker.addItem(Path(path).name, path)
                    picker.setItemData(picker.count() - 1, path, Qt.ItemDataRole.ToolTipRole)
                picker.setCurrentIndex(min(index, len(choices) - 1))
                self.pickers.append(picker)
                row.addWidget(QLabel(title))
                row.addWidget(picker, 1)
            layout.insertLayout(0, row)
            self.files_label.hide()
            for picker in self.pickers:
                picker.currentIndexChanged.connect(self._start)
        self._start()

    def _start(self):
        self.result = None
        self._filter()
        if self.pickers:
            self.paths = tuple(picker.currentData() for picker in self.pickers)
            if not all(self.paths) or self.paths[0] == self.paths[1]:
                self.swap_button.setEnabled(False)
                self.summary_label.setText("Cần hai CSV khác nhau từ thư mục upload hoặc export để so sánh.")
                return
            for picker in self.pickers:
                picker.setEnabled(False)
        self.files_label.setText(f"Bản cũ: {Path(self.paths[0]).name}\nBản mới: {Path(self.paths[1]).name}")
        self.files_label.setToolTip(f"Bản cũ: {self.paths[0]}\nBản mới: {self.paths[1]}")
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.summary_label.setText("Đang đọc và so sánh theo key…")
        self.swap_button.setEnabled(False)
        self.worker = CompareWorker(*self.paths, self)
        self.worker.result_ready.connect(self._loaded)
        self.worker.failed.connect(self.compare_failed)
        self.worker.finished.connect(self._finished)
        start_feature_worker(self)

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.swap_button.setEnabled(True)
        for picker in self.pickers:
            picker.setEnabled(True)
        if self._closing:
            super().reject()

    def compare_failed(self, message):
        self.summary_label.setText(message)
        self.log_emitted.emit("FAIL", message)

    def _loaded(self, result):
        self.log_emitted.emit("SUCCESS", f"Đã so sánh {Path(self.paths[0]).name} và {Path(self.paths[1]).name}.")
        self.result = result
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        colors = status_colors()
        summary = " &nbsp; ".join(
            f'<span style="background-color:{colors[status][0]};color:{colors[status][1]};">'
            f'&nbsp;<b>{label}: {result.count(status)}</b>&nbsp;</span>'
            for status, label in (("added", "Key mới"), ("removed", "Đã xóa"), ("changed", "Thay đổi"), ("unchanged", "Không đổi"))
        )
        for label, columns in (("Cột mới", result.added_columns), ("Cột đã xóa", result.removed_columns)):
            if columns:
                summary += f"<br>{label}: " + ", ".join(escape(result.columns[col]) for col in columns)
        self.summary_label.setText(summary)
        self._filter()

    def _filter(self, *_args):
        self.model.filter(self.result, self.filter_combo.currentData(), self.search_edit.text())
        count = len({diff.key for diff, _ in self.model.rows})
        self.visible_label.setText(f"Đang hiển thị {count} key / {len(self.model.rows)} ô dữ liệu")
        if self.result and not self.model.rows:
            self.visible_label.setText("Không có key phù hợp bộ lọc hoặc hai CSV không có khác biệt.")
        self.old_text.clear()
        self.new_text.clear()
        self.detail_label.setText("Chọn một dòng để xem đầy đủ nội dung và sao chép.")
        if self.model.rows:
            self.table.setCurrentIndex(self.sort_model.index(0, 0))

    def _show_detail(self, current, _previous):
        if not current.isValid():
            return
        source_index = self.sort_model.mapToSource(current)
        diff, col = self.model.rows[source_index.row()]
        self.detail_label.setText(f"{diff.key} · {self.result.columns.get(col, 'key')} — Bản cũ (trái) / Bản mới (phải)")
        values = [None if record is None else diff.key if col is None else record.get(col)
                  for record in (diff.before, diff.after)]
        marked = marked_values(values[0] or "", values[1] or "")
        for widget, value, html in zip((self.old_text, self.new_text), values, marked):
            if value is None:
                widget.setPlainText("Không tồn tại")
            else:
                widget.setHtml(f'<span style="white-space:pre-wrap">{html}</span>')

    def _swap(self):
        self.paths = self.paths[1], self.paths[0]
        for picker, path in zip(self.pickers, self.paths):
            picker.blockSignals(True)
            picker.setCurrentIndex(picker.findData(path))
            picker.blockSignals(False)
        self._start()

    def reject(self):
        if self.worker is not None:
            self._closing = True
            self.worker.requestInterruption()
            self.summary_label.setText("Đang dừng so sánh…")
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
