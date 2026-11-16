"""Offline mapping audit and review decisions for outgoing Desc fields."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from import_localize.services.desc_annotations import DescAnnotations, WRONG_MAPPING

from PySide6.QtCore import QItemSelectionModel, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
    QWidget,
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

    def __init__(self, mapping, paths, *, sources=None, parent=None):
        super().__init__(parent)
        self.mapping, self.paths = Path(mapping), list(map(Path, paths))
        self.sources = sources
        self.snapshot = None
        self.result = None
        self.error = ""

    def run(self):
        try:
            from import_localize.services.mapping_audit_service import audit_mapping
            inputs = [self.mapping] if self.sources is not None else [self.mapping, *self.paths]
            before = snapshots(inputs)
            self.result = audit_mapping(self.mapping, self.paths, sources=self.sources,
                progress_callback=self.progress.emit, cancel_callback=self.isInterruptionRequested)
            if snapshots(inputs) != before:
                raise ValueError("Dữ liệu đã thay đổi trong lúc kiểm tra. Hãy kiểm tra lại.")
            self.snapshot = before
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__


class MappingTable(QTableWidget):
    """Content-sized initial columns with user resizing and wrapped row heights."""

    def __init__(self, columns, parent=None):
        super().__init__(0, columns, parent)
        self.columns_fitted = False
        self._shown_once = False
        self.setObjectName("mappingTable")
        self.setShowGrid(True)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setMinimumSectionSize(60)
        self.horizontalHeader().setStretchLastSection(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.horizontalHeader().setToolTip("Kéo vạch dọc giữa hai tiêu đề để chỉnh cột. Nhấp đúp để vừa nội dung.")
        self.setStyleSheet("QTableWidget#mappingTable { border-radius: 0px; }")
        self._row_timer = QTimer(self)
        self._row_timer.setSingleShot(True)
        self._row_timer.setInterval(80)
        self._row_timer.timeout.connect(self.resize_wrapped_rows)
        self.horizontalHeader().sectionResized.connect(lambda *_: self._row_timer.start())

    def fit_content(self, *, reset=False):
        if self.rowCount() and (reset or not self.columns_fitted):
            self.horizontalHeader().setStretchLastSection(False)
            self.ensurePolished()
            self.horizontalHeader().ensurePolished()
            self.resizeColumnsToContents()
            # Long descriptions wrap instead of creating multi-screen columns.
            # This limit applies only to the initial fit, never to user drags.
            for column in range(self.columnCount()):
                heading = self.horizontalHeaderItem(column)
                header_width = self.horizontalHeader().fontMetrics().horizontalAdvance(heading.text()) + 38 if heading else 100
                self.setColumnWidth(column, min(480, max(100, header_width, self.columnWidth(column) + 12)))
            if self.property("keyCheckboxes"):
                self.setColumnWidth(0, 60)
            self.columns_fitted = True
            self.horizontalHeader().setStretchLastSection(True)
        self._row_timer.start()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = event.pixelDelta().x() or event.pixelDelta().y()
            if not delta:
                angle = event.angleDelta().x() or event.angleDelta().y()
                delta = angle / 120 * max(60, self.horizontalScrollBar().singleStep() * 3)
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - round(delta))
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if (self.property("keyCheckboxes") and index.isValid() and index.column() == 0
                and event.button() == Qt.MouseButton.LeftButton):
            item = self.item(index.row(), 0)
            self.setCurrentCell(index.row(), 1, QItemSelectionModel.SelectionFlag.NoUpdate)
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def resize_wrapped_rows(self):
        self.resizeRowsToContents()
        if self.property("summaryTable"):
            height = self.horizontalHeader().height() + sum(self.rowHeight(row) for row in range(min(4, self.rowCount()))) + 22
            self.setMinimumHeight(min(260, max(100, height)))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            self.fit_content(reset=True)


class MappingDialog(QDialog):
    def __init__(self, settings, paths=(), parent=None, *, annotations=None, sources=None):
        super().__init__(parent)
        self.settings = settings
        self.annotations = annotations if annotations is not None else DescAnnotations()
        self.sources = sources
        self.paths = list(sources) if sources is not None else list(dict.fromkeys(Path(p) for p in (paths or settings.mapping_csv_files)))
        self.report = None
        self.snapshot = None
        self.worker = None
        self.visible_issues = []
        self.visible_keys = []
        self.key_issues = {}
        self.references = {}
        self.selected_keys = set()
        self._selection_sync = False
        self._busy = False
        self.focus_mode = False
        self._normal_geometry = None
        self.setWindowTitle("Kiểm tra mapping")
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(1180, 800)
        layout = QVBoxLayout(self)
        self.setup_panel = QWidget(self)
        setup_layout = QVBoxLayout(self.setup_panel)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.setup_panel)
        intro = QLabel("Chọn key để đánh dấu Wrong mapping trong Desc khi xuất CSV hoặc lên Sheet.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        setup_layout.addWidget(intro)
        source_bar = QHBoxLayout()
        self.source_toggle = QToolButton()
        self.source_toggle.setText("Nguồn kiểm tra")
        self.source_toggle.setCheckable(True)
        self.source_toggle.setChecked(True)
        self.source_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.source_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.source_summary = QLabel()
        self.source_summary.setProperty("muted", True)
        self.source_summary.setWordWrap(True)
        self.scan_button = QPushButton("Kiểm tra mapping")
        self.scan_button.setProperty("primaryAction", True)
        self.stop_button = QPushButton("Dừng")
        self.stop_button.setProperty("dangerAction", True)
        source_bar.addWidget(self.source_toggle)
        source_bar.addWidget(self.source_summary, 1)
        source_bar.addWidget(self.stop_button)
        source_bar.addWidget(self.scan_button)
        setup_layout.addLayout(source_bar)
        self.source_panel = QWidget()
        source_layout = QVBoxLayout(self.source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
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
        source_layout.addLayout(form)
        actions = QHBoxLayout()
        self.folder_button = QPushButton("Chọn thư mục DG…")
        self.files_button = QPushButton("Chọn nhiều CSV…")
        for button in (self.folder_button, self.files_button):
            actions.addWidget(button)
        if self.sources is not None:
            self.folder_button.hide()
            self.files_button.hide()
        actions.addStretch()
        source_layout.addLayout(actions)
        setup_layout.addWidget(self.source_panel)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        setup_layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        setup_layout.addWidget(self.progress)
        filters = QHBoxLayout()
        self.filter_combo = QComboBox()
        for label, value in (("Tất cả phát hiện", ""), ("Sai mapping", "wrong"), ("Cần xem ngữ cảnh", "review")):
            self.filter_combo.addItem(label, value)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm key, thuật ngữ hoặc nội dung…")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.filter_combo)
        filters.addWidget(self.search, 1)
        self.fit_button = QPushButton("Căn lại cột")
        self.focus_button = QPushButton("Phóng to bảng")
        self.focus_button.setToolTip("Toàn màn hình riêng vùng đối chiếu; Esc để trở lại.")
        filters.addWidget(self.fit_button)
        filters.addWidget(self.focus_button)
        layout.addLayout(filters)
        selection_actions = QHBoxLayout()
        self.select_visible_button = QPushButton("Chọn tất cả đang hiện")
        self.select_visible_button.setToolTip("Chọn các key đang hiển thị. Giữ Ctrl/Shift hoặc dùng ô tick để chọn từng nhóm.")
        self.clear_selection_button = QPushButton("Bỏ chọn hết")
        self.selection_label = QLabel("Đã chọn 0 key")
        self.selection_label.setWordWrap(True)
        self.mark_button = QPushButton("Đánh dấu Desc (0)")
        self.unmark_button = QPushButton("Gỡ dấu Desc")
        self.unmark_button.clicked.connect(self.unmark)
        self.mark_button.setProperty("primaryAction", True)
        self.focus_stop_button = QPushButton("Dừng kiểm tra")
        self.focus_stop_button.hide()
        for widget in (self.select_visible_button, self.clear_selection_button, self.selection_label):
            selection_actions.addWidget(widget, 1 if widget is self.selection_label else 0)
        selection_actions.addWidget(self.focus_stop_button)
        selection_actions.addWidget(self.unmark_button)
        selection_actions.addWidget(self.mark_button)
        layout.addLayout(selection_actions)
        self.focus_status = QLabel()
        self.focus_status.setWordWrap(True)
        self.focus_status.hide()
        layout.addWidget(self.focus_status)
        splitter = self.tables_splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("mappingSplitter")
        splitter.setHandleWidth(9)
        splitter.setChildrenCollapsible(False)
        self.files_table = self._table(["File CSV (bấm để lọc)", "Sai mapping", "Cần xem ngữ cảnh", "Đọc dữ liệu"])
        self.files_table.setProperty("summaryTable", True)
        self.issues_table = self._table(["Chọn", "Trạng thái", "Key", "Desc khi xuất", "Mapping chuẩn / Lý do"])
        self.issues_table.setProperty("keyCheckboxes", True)
        self.issues_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.issues_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        splitter.addWidget(self.files_table)
        splitter.addWidget(self.issues_table)
        splitter.setSizes([170, 310])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(90)
        self.detail.setPlaceholderText("Chọn một phát hiện để xem đầy đủ nguồn, bản dịch và lý do.")
        self.detail.hide()
        layout.addWidget(self.detail)
        self.bottom_panel = QWidget(self)
        bottom = QHBoxLayout(self.bottom_panel)
        bottom.setContentsMargins(0, 0, 0, 0)
        self.all_files_button = QPushButton("Hiện tất cả file")
        self.all_files_button.setToolTip("Bỏ bộ lọc file được chọn trong bảng tổng hợp phía trên.")
        self.close_button = QPushButton("Đóng")
        bottom.addWidget(self.all_files_button)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        layout.addWidget(self.bottom_panel)
        self.fit_button.clicked.connect(self.fit_columns)
        self.focus_button.clicked.connect(self.toggle_focus_mode)
        self.source_toggle.toggled.connect(self.toggle_sources)
        self.mapping_button.clicked.connect(self.choose_mapping)
        self.folder_button.clicked.connect(self.choose_folder)
        self.files_button.clicked.connect(self.choose_files)
        self.scan_button.clicked.connect(self.scan)
        self.stop_button.clicked.connect(self.stop)
        self.close_button.clicked.connect(self.reject)
        self.mark_button.clicked.connect(self.mark)
        self.focus_stop_button.clicked.connect(self.stop)
        self.select_visible_button.clicked.connect(self.select_visible)
        self.clear_selection_button.clicked.connect(self.clear_key_selection)
        self.mapping_edit.textChanged.connect(self.invalidate)
        self.files_table.itemSelectionChanged.connect(self.filter_rows)
        self.filter_combo.currentIndexChanged.connect(self.filter_rows)
        self.search.textChanged.connect(self.filter_rows)
        self.issues_table.itemSelectionChanged.connect(self.show_detail)
        self.issues_table.itemSelectionChanged.connect(self.rows_selected)
        self.issues_table.itemChanged.connect(self.checkbox_changed)
        self.all_files_button.clicked.connect(self.files_table.clearSelection)
        self.invalidate()

    def toggle_sources(self, expanded):
        self.source_panel.setVisible(expanded)
        self.source_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def update_source_summary(self):
        mapping = Path(self.mapping_edit.text()).name if self.mapping_edit.text() else "chưa chọn mapping"
        self.source_summary.setText(f"{len(self.paths)} CSV · {mapping}")
        self.source_summary.setToolTip("\n".join([self.mapping_edit.text(), *map(str, self.paths)]))

    def fit_columns(self):
        for table in (self.files_table, self.issues_table):
            table.fit_content(reset=True)

    def toggle_focus_mode(self):
        host = getattr(self, "workspace", None)
        window = host.owner if host else self
        if not self.focus_mode:
            self._normal_geometry = window.saveGeometry()
            self._was_maximized = window.isMaximized()
            self._splitter_sizes = self.tables_splitter.sizes()
            self._scroll_position = (self.issues_table.horizontalScrollBar().value(),
                                     self.issues_table.verticalScrollBar().value())
            self.focus_mode = True
            for widget in (self.setup_panel, self.files_table, self.detail, self.bottom_panel):
                widget.hide()
            self.focus_button.setText("Thu gọn bảng (Esc)")
            if host:
                self._chrome = [w for w in (window.workspace_toolbar, window.action_card, window.log_card, window.top_bar) if not w.isHidden()]
                for widget in self._chrome:
                    widget.hide()
            window.showFullScreen()
            self.focus_status.setVisible(bool(self.focus_status.text()))
        else:
            self.focus_mode = False
            window.showNormal()
            if host:
                for widget in self._chrome:
                    widget.show()
            for widget in (self.setup_panel, self.files_table, self.detail, self.bottom_panel):
                widget.show()
            self.detail.setVisible(bool(self.detail.toPlainText()))
            window.restoreGeometry(self._normal_geometry)
            if self._was_maximized:
                window.showMaximized()
            self.tables_splitter.setSizes(self._splitter_sizes)
            self.focus_button.setText("Phóng to bảng")
            self.issues_table.horizontalScrollBar().setValue(self._scroll_position[0])
            self.issues_table.verticalScrollBar().setValue(self._scroll_position[1])
            self.focus_status.hide()
            self.focus_stop_button.hide()

    def _table(self, headers):
        table = MappingTable(len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().hide()
        return table

    def invalidate(self):
        self.report = None
        self.key_issues = {}
        self.visible_keys = []
        self.visible_issues = []
        self.focus_status.clear()
        self.focus_status.hide()
        self.selected_keys.clear()
        self._selection_sync = True
        self.snapshot = None
        self.files_table.setRowCount(0)
        self.issues_table.setRowCount(0)
        self.issues_table.columns_fitted = False
        self.detail.clear()
        self.detail.hide()
        self.update_source_summary()
        self.status.setText("Bấm Kiểm tra mapping để đối chiếu các CSV đã chọn." if self.paths else "Chọn thư mục DG hoặc các file CSV để bắt đầu.")
        for path in self.paths:
            row = self.files_table.rowCount()
            self.files_table.insertRow(row)
            item = QTableWidgetItem(path.name)
            item.setToolTip(str(path))
            self.files_table.setItem(row, 0, item)
        self.files_table.fit_content(reset=True)
        self._selection_sync = False
        self.set_busy(False)

    def set_busy(self, busy):
        self._busy = busy
        for widget in (self.mapping_edit, self.mapping_button, self.folder_button,
                       self.files_button, self.scan_button):
            widget.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.stop_button.setVisible(busy)
        self.progress.setVisible(busy)
        self.source_toggle.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        self.focus_button.setEnabled(not busy)
        self.issues_table.setEnabled(not busy)
        self.focus_stop_button.setVisible(busy and self.focus_mode)
        self.focus_stop_button.setEnabled(busy)
        self.update_selection_ui()

    def update_selection_ui(self):
        hidden = len(self.selected_keys - set(self.visible_keys))
        self.selection_label.setText(f"Đã chọn {len(self.selected_keys)} key" + (f" · {hidden} đang ẩn bởi bộ lọc" if hidden else ""))
        self.mark_button.setText(f"Đánh dấu Desc ({len(self.selected_keys)})")
        self.mark_button.setToolTip("Thêm Wrong mapping cho tất cả ngôn ngữ có phát hiện ở các key đã chọn.")
        self.mark_button.setEnabled(not self._busy and bool(self.report and self.selected_keys))
        self.unmark_button.setEnabled(self.mark_button.isEnabled())
        self.select_visible_button.setEnabled(not self._busy and bool(self.report and self.visible_keys))
        self.clear_selection_button.setEnabled(not self._busy and bool(self.selected_keys))

    def mark_description(self, key):
        locales = sorted({issue.locale for issue in self.key_issues[key]
                          if self.annotations.has(issue.locale, key, WRONG_MAPPING)})
        if locales:
            return ", ".join(locales), "Desc khi xuất: Wrong mapping (" + ", ".join(locales) + ")"
        return "—", "Chưa đánh dấu Wrong mapping."

    def set_mark_cell(self, row, key):
        text, tooltip = self.mark_description(key)
        item = QTableWidgetItem(text)
        item.setToolTip(tooltip)
        self.issues_table.setItem(row, 3, item)

    def sync_key_selection(self):
        self._selection_sync = True
        table = self.issues_table
        table.clearSelection()
        for row, key in enumerate(self.visible_keys):
            checked = key in self.selected_keys
            table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            if checked:
                table.selectionModel().select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self._selection_sync = False
        self.update_selection_ui()

    def rows_selected(self):
        if self._selection_sync or not self.report:
            return
        selected = {self.visible_keys[index.row()] for index in self.issues_table.selectionModel().selectedRows()}
        self.selected_keys.difference_update(self.visible_keys)
        self.selected_keys.update(selected)
        self._selection_sync = True
        for row, key in enumerate(self.visible_keys):
            self.issues_table.item(row, 0).setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)
        self._selection_sync = False
        self.update_selection_ui()

    def checkbox_changed(self, item):
        if self._selection_sync or not self.report or item.column() != 0:
            return
        key = self.visible_keys[item.row()]
        if item.checkState() == Qt.CheckState.Checked:
            self.selected_keys.add(key)
        else:
            self.selected_keys.discard(key)
        self.sync_key_selection()

    def select_visible(self):
        self.selected_keys.update(self.visible_keys)
        self.sync_key_selection()

    def clear_key_selection(self):
        self.selected_keys.clear()
        self.sync_key_selection()

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
        self.launch(MappingWorker(self.mapping_edit.text().strip(), self.paths, sources=self.sources, parent=self))

    def stop(self):
        if self.worker:
            self.worker.requestInterruption()
            self.status.setText("Đang dừng kiểm tra…")
            self.focus_status.setText(self.status.text())
            self.stop_button.setEnabled(False)
            self.focus_stop_button.setEnabled(False)

    @Slot(int, int, str)
    def on_progress(self, done, total, text):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(text)
        self.focus_status.setText(text)
        self.focus_status.setVisible(self.focus_mode)

    @Slot()
    def finished_work(self):
        worker = self.worker
        worker.wait()
        self.worker = None
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        if worker.error:
            self.status.setText(f"Không hoàn tất: {worker.error}")
        else:
            self.report, self.snapshot = worker.result, worker.snapshot
            self.render_report()
        worker.deleteLater()
        self.set_busy(False)
        self.focus_status.setText(self.status.text())
        self.focus_status.setVisible(self.focus_mode)

    def render_report(self):
        report = self.report
        self._selection_sync = True
        self.selected_keys.clear()
        self.key_issues = defaultdict(list)
        self.references = defaultdict(lambda: defaultdict(list))
        for issue in report.issues:
            self.key_issues[issue.key].append(issue)
        for record in getattr(report, "records", []):
            for locale, value in record.values.items():
                self.references[record.key][locale].append((record.path, record.line, value))
        # Reports created by older integrations may not carry full records.
        for issue in report.issues:
            reference = (issue.path, issue.line, issue.actual)
            if reference not in self.references[issue.key][issue.locale]:
                self.references[issue.key][issue.locale].append(reference)
        self.issues_table.setColumnCount(len(report.files) + 5)
        self.issues_table.setHorizontalHeaderLabels(["Chọn", "Trạng thái", "Key", "Desc khi xuất", *[p.name for p in report.files], "Mapping chuẩn / Lý do"])
        for col, path in enumerate(report.files, start=4):
            self.issues_table.horizontalHeaderItem(col).setToolTip(str(path))
        self.issues_table.columns_fitted = False
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
        self.files_table.fit_content(reset=True)
        self.status.setText(f"Đã kiểm tra {report.checked_cells} ô / {len(report.files)} file · "
            f"{len(report.wrong_keys)} key sai mapping · {sum(i.status == 'review' for i in report.issues)} cần xem ngữ cảnh · "
            f"{report.unmapped_cells} ô chưa có mapping · {len(report.errors)} file lỗi.")
        self.status.setToolTip("Mỗi key một dòng; mỗi CSV một cột. Ctrl/Shift để chọn nhiều key. "
                               "Shift + cuộn chuột để cuộn ngang. Đánh dấu các key đã chọn cho những ngôn ngữ có phát hiện.")
        self.source_toggle.setChecked(False)
        self.filter_rows()

    def filter_rows(self):
        if not self.report:
            return
        self.issues_table.ensurePolished()
        dark = self.issues_table.palette().color(QPalette.ColorRole.Base).lightness() < 128
        rows = self.files_table.selectionModel().selectedRows()
        path = self.files_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None
        status, query = self.filter_combo.currentData(), self.search.text().casefold()
        self.visible_keys = []
        for key, issues in self.key_issues.items():
            if not any((not path or str(i.path) == path) and (not status or i.status == status) for i in issues):
                continue
            search_text = " ".join(f"{i.key} {i.source} {i.actual} {i.expected} {i.reason}" for i in issues)
            search_text += " ".join(v for refs in self.references[key].values() for _, _, v in refs)
            if not query or query in search_text.casefold():
                self.visible_keys.append(key)
        self.visible_issues = [self.key_issues[key][0] for key in self.visible_keys]
        self._selection_sync = True
        self.issues_table.blockSignals(True)
        self.issues_table.setRowCount(0)
        for key in self.visible_keys:
            issues = self.key_issues[key]
            wrong = any(i.status == "wrong" for i in issues)
            row = self.issues_table.rowCount()
            self.issues_table.insertRow(row)
            values = ["", "Sai mapping" if wrong else "Cần xem ngữ cảnh", key, ""]
            for file_path in self.report.files:
                refs = [(locale, line, value) for locale, entries in self.references[key].items()
                        for p, line, value in entries if p == file_path]
                if len(refs) == 1:
                    values.append(refs[0][2] or "[Ô trống]")
                elif refs:
                    values.append("\n\n".join(f"{locale} · Dòng {line}\n{value or '[Ô trống]'}" for locale, line, value in refs))
                else:
                    values.append("[Không đọc được file]" if str(file_path) in self.report.errors else "[Không có key trong file]")
            values.append("\n".join(dict.fromkeys(f"{i.locale}: {i.expected or '[Cần ngữ cảnh]'} — {i.reason}" for i in issues)))
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if key in self.selected_keys else Qt.CheckState.Unchecked)
                item.setToolTip(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                file_column = 4 <= col < len(self.report.files) + 4
                affected = issues if col == 1 else [i for i in issues if file_column and i.path == self.report.files[col - 4]]
                if affected:
                    definite = any(i.status == "wrong" for i in affected)
                    item.setBackground(QColor(("#4c2020" if definite else "#45371d") if dark else ("#fee2e2" if definite else "#fef3c7")))
                    item.setForeground(QColor(("#fecaca" if definite else "#fde68a") if dark else ("#7f1d1d" if definite else "#78350f")))
                if file_column:
                    file_path = self.report.files[col - 4]
                    refs = [(locale, line, v) for locale, entries in self.references[key].items()
                            for p, line, v in entries if p == file_path]
                    item.setToolTip(str(file_path) + "\n\n" + "\n\n".join(f"{locale} · Dòng {line}\n{v}" for locale, line, v in refs))
                self.issues_table.setItem(row, col, item)
            self.set_mark_cell(row, key)
        self.issues_table.fit_content()
        self.issues_table.blockSignals(False)
        self.sync_key_selection()

    def show_detail(self):
        rows = self.issues_table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self.visible_keys):
            self.detail.clear()
            self.detail.hide()
            return
        key = self.visible_keys[rows[0].row()]
        lines = [f"Key: {key}", self.mark_description(key)[1]]
        for file_path in self.report.files:
            lines.append(f"\n{file_path} — Tham chiếu")
            refs = [(locale, line, v) for locale, entries in self.references[key].items()
                    for p, line, v in entries if p == file_path]
            lines.extend(f"{locale} · Dòng {line}\n{value or '[Ô trống]'}" for locale, line, value in refs)
            if not refs:
                lines.append("Không có key trong file này.")
        for issue in self.key_issues[key]:
            lines.append(f"\n{issue.locale} · {issue.path.name} · Dòng {issue.line}\nLý do: {issue.reason}\n"
                         f"Mapping chuẩn: {issue.expected}\nNguồn: {issue.source}\nHiện tại: {issue.actual}")
        self.detail.setPlainText("\n".join(lines))
        self.detail.setVisible(not self.focus_mode)

    def mark(self):
        self.set_desc_marks(True)

    def unmark(self):
        self.set_desc_marks(False)

    def set_desc_marks(self, enabled):
        if self.worker or not self.report or not self.selected_keys:
            return
        if self.snapshot is not None and snapshots(self.snapshot) != self.snapshot:
            self.status.setText("Mapping hoặc CSV đã thay đổi. Hãy kiểm tra lại.")
            self.focus_status.setText(self.status.text())
            self.focus_status.setVisible(self.focus_mode)
            return
        pairs = {(issue.locale, key) for key in self.selected_keys for issue in self.key_issues[key]}
        for locale, key in pairs:
            self.annotations.set_mark(locale, key, WRONG_MAPPING, enabled)
        for row, key in enumerate(self.visible_keys):
            if key in self.selected_keys:
                self.set_mark_cell(row, key)
        self.clear_key_selection()
        verb = "Đã đánh dấu" if enabled else "Đã gỡ dấu"
        self.status.setText(f"{verb} Wrong mapping cho {len(pairs)} cặp key/ngôn ngữ của bản xuất.")
        self.focus_status.setText(self.status.text())
        self.focus_status.setVisible(self.focus_mode)

    def reject(self):
        if self.focus_mode:
            self.toggle_focus_mode()
            return
        if self.worker:
            self.stop()
            return
        self.settings.mapping_path = self.mapping_edit.text().strip()
        if self.sources is None:
            self.settings.mapping_csv_files = [str(p) for p in self.paths]
        super().reject()

    def closeEvent(self, event):
        if self.focus_mode:
            self.toggle_focus_mode()
            event.ignore()
        elif self.worker:
            self.stop()
            event.ignore()
        else:
            self.reject()
            event.accept()
