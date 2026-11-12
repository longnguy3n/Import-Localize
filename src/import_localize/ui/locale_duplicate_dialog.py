from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Qt, Slot, Signal, QEvent
from PySide6.QtGui import QDesktopServices, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QTextBrowser, QProgressBar, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QFrame, QToolButton,
)

from import_localize.app.paths import USER_CONFIG_DIR
from import_localize.config.settings import AppSettings
from import_localize.services.locale_duplicate_service import scan_duplicates, prepare_duplicate_cleanup
from import_localize.services.unity_locale_service import apply_plan
from .locale_diff import variant_documents


class DuplicateWorker(QThread):
    def __init__(self, task, parent):
        super().__init__(parent)
        self.task, self.result, self.error = task, None, ""

    def run(self):
        try:
            self.result = self.task()
        except Exception as exc:
            self.error = str(exc)


class VariantPanel(QFrame):
    chosen = Signal(int)

    def __init__(self, index, label, document):
        super().__init__()
        self.index, self.label = index, label
        self.setObjectName("duplicateVariant")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        column = QVBoxLayout(self)
        column.setContentsMargins(6, 6, 6, 6)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        column.addWidget(self.title)
        self.content = QTextBrowser()
        self.content.setReadOnly(True)
        self.content.setOpenLinks(False)
        self.content.setOpenExternalLinks(False)
        self.content.setHtml(document)
        column.addWidget(self.content)
        for widget in (self, self.title, self.content.viewport()):
            widget.installEventFilter(self)
        self.set_selected(False)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.index)
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.chosen.emit(self.index)
            event.accept()
        else:
            super().keyPressEvent(event)

    def set_selected(self, selected):
        self.setProperty("selected", selected)
        self.title.setText(("ĐANG GIỮ BẢN NÀY · " if selected else "Bấm để giữ · ") + self.label)
        border = "#2772d8" if selected else "#b8c9c1"
        background = "#e7f1ff" if selected else "transparent"
        self.setStyleSheet(f"QFrame#duplicateVariant {{ border: 2px solid {border}; "
                           f"border-radius: 6px; background: {background}; }}")
        self.title.setStyleSheet("QLabel { color: #174b8a; font-weight: bold; }" if selected else "")


class LocaleDuplicateDialog(QDialog):
    def __init__(self, paths: list[Path], parent=None, *, settings: AppSettings | None = None):
        super().__init__(parent)
        self.settings = settings if settings is not None else AppSettings()
        self.paths = list(paths)
        self._files_chosen = False
        self.restore_message = ""
        if not self.paths and self.settings.unity_duplicate_files is not None:
            self.paths = [Path(path) for path in self.settings.unity_duplicate_files]
        if not self.paths and self.settings.unity_duplicate_files is None and self.settings.unity_locale_dir:
            folder = Path(self.settings.unity_locale_dir)
            try:
                if folder.is_dir():
                    self.paths = sorted(path for path in folder.glob("locale*.asset") if path.is_file())
                    if not self.paths:
                        self.restore_message = "Thư mục đã lưu không có locale*.asset. Chọn thư mục hoặc file khác."
                else:
                    self.restore_message = "Thư mục đã lưu không còn tồn tại. Chọn lại thư mục chứa asset."
            except OSError as exc:
                self.restore_message = f"Không đọc được thư mục đã lưu: {exc}"
        self.scan_result = None
        self.choices = {}
        self.worker = None
        self.backup_path = None
        self.wrote_files = False
        self.setWindowTitle("Unity Locale — Kiểm tra và xóa duplicate key")
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(1120, 780)
        layout = QVBoxLayout(self)
        intro_row = QHBoxLayout()
        intro = QLabel("Nội dung giống nhau: giữ bản đầu. Nội dung khác nhau: chọn bản cần giữ trước khi xóa.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        intro_row.addWidget(intro, 1)
        self.rules_button = QToolButton()
        self.rules_button.setText("Quy tắc so sánh")
        self.rules_button.setCheckable(True)
        self.rules_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.rules_button.setArrowType(Qt.ArrowType.RightArrow)
        intro_row.addWidget(self.rules_button)
        layout.addLayout(intro_row)
        self.rules_label = QLabel("Kiểm tra key giống chính xác (phân biệt hoa/thường) trong từng file. "
                       "Cùng key ở các file khác nhau không bị xóa.\n"
                       "Chỉ so sánh key và Languages; bỏ qua cờ New/Flags và các trường phụ. "
                       "Chỉ ghi file khi bấm Xóa bản trùng; luôn sao lưu trước khi ghi.")
        self.rules_label.setWordWrap(True)
        self.rules_label.hide()
        layout.addWidget(self.rules_label)
        self.rules_button.toggled.connect(self._set_rules_expanded)
        buttons = QHBoxLayout()
        self.files_label = QLabel()
        self.files_label.setWordWrap(True)
        self.choose_button = QPushButton("Chọn locale*.asset…")
        self.folder_button = QPushButton("Chọn thư mục…")
        self.scan_button = QPushButton("Kiểm tra lại")
        buttons.addWidget(self.files_label, 1)
        buttons.addWidget(self.choose_button)
        buttons.addWidget(self.folder_button)
        buttons.addWidget(self.scan_button)
        layout.addLayout(buttons)
        self.folder_label = QLabel()
        self.folder_label.setTextFormat(Qt.TextFormat.PlainText)
        self.folder_label.setWordWrap(True)
        self.folder_label.setProperty("muted", True)
        layout.addWidget(self.folder_label)
        self.summary = QLabel("Chưa kiểm tra.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.groups = QTableWidget(0, 5)
        self.groups.setHorizontalHeaderLabels(["File", "Key trùng", "Số bản ghi", "Sẽ xóa", "Bản giữ lại"])
        self.groups.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.groups.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.groups.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.groups.verticalHeader().hide()
        self.groups.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.groups.horizontalHeader().setMinimumSectionSize(70)
        self.groups.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((250, 280, 105, 90, 300)):
            self.groups.setColumnWidth(column, width)
        self.groups.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.groups.horizontalHeader().setToolTip("Kéo vạch giữa hai tiêu đề để đổi độ rộng; nhấp đúp để vừa nội dung.")
        self.groups.setMinimumHeight(140)
        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setHandleWidth(8)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.groups)
        comparison = QWidget()
        comparison_layout = QVBoxLayout(comparison)
        comparison_layout.setContentsMargins(0, 4, 0, 0)
        self.content_splitter.addWidget(comparison)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 3)
        self.content_splitter.setSizes([180, 400])
        self._comparison_sized = False
        layout.addWidget(self.content_splitter, 1)
        self.group_label = QLabel("Chọn một key để xem đầy đủ các bản ghi.")
        self.group_label.setWordWrap(True)
        self.group_label.setTextFormat(Qt.TextFormat.PlainText)
        comparison_layout.addWidget(self.group_label)
        legend = QLabel('<span style="background-color:#ffe7a3;color:#603e00;"> Đoạn khác nhau </span>'
                        ' · <span style="background-color:#e2e7ee;color:#526172;"> Không có đoạn tương ứng </span>'
                        ' · Dấu “·” = khoảng trắng; [xuống dòng] = xuống dòng trong đoạn khác.')
        legend.setWordWrap(True)
        comparison_layout.addWidget(legend)
        choice_row = QHBoxLayout()
        choice_row.addWidget(QLabel("Giữ lại:"))
        self.keep_combo = QComboBox()
        self.keep_combo.setEnabled(False)
        choice_row.addWidget(self.keep_combo, 1)
        self.next_button = QPushButton("Key cần chọn tiếp theo")
        self.next_button.setEnabled(False)
        choice_row.addWidget(self.next_button)
        comparison_layout.addLayout(choice_row)
        self.variants = QSplitter(Qt.Orientation.Horizontal)
        self.variants.setMinimumHeight(150)
        self.variants.setChildrenCollapsible(False)
        comparison_layout.addWidget(self.variants, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)
        safety = QLabel("Lưu asset và thoát Play Mode trong Unity trước khi xóa bản trùng.")
        safety.setProperty("muted", True)
        safety.setWordWrap(True)
        layout.addWidget(safety)
        actions = QHBoxLayout()
        self.backup_button = QPushButton("Mở bản sao lưu")
        self.backup_button.setEnabled(False)
        self.apply_button = QPushButton("Xóa bản trùng")
        self.apply_button.setProperty("primaryAction", True)
        self.apply_button.setEnabled(False)
        self.close_button = QPushButton("Đóng")
        actions.addWidget(self.backup_button)
        actions.addStretch()
        actions.addWidget(self.apply_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.choose_button.clicked.connect(self.choose_files)
        self.folder_button.clicked.connect(self.choose_folder)
        self.scan_button.clicked.connect(self.scan)
        self.groups.itemSelectionChanged.connect(self.show_group)
        self.keep_combo.currentIndexChanged.connect(self.choose_variant)
        self.next_button.clicked.connect(self.next_conflict)
        self.apply_button.clicked.connect(self.cleanup)
        self.close_button.clicked.connect(self.reject)
        self.backup_button.clicked.connect(self.open_backup)
        self._files_label()
        self.status.setText(self.restore_message)

    def _files_label(self):
        names = ", ".join(path.name for path in self.paths)
        self.files_label.setText(f"{len(self.paths)} file · " + (names if len(names) <= 140 else names[:137] + "…"))
        self.files_label.setToolTip("\n".join(str(path) for path in self.paths))
        folder = str(self.paths[0].parent) if self.paths else self.settings.unity_locale_dir
        self.folder_label.setText("Thư mục asset: " + (folder or "chưa chọn"))

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn locale*.asset để kiểm tra",
                                               str(self.paths[0].parent) if self.paths else self.settings.unity_locale_dir,
                                               "Unity Locale (*.asset)")
        if paths:
            self._files_chosen = True
            self.paths = [Path(path) for path in paths]
            self.settings.unity_locale_dir = str(self.paths[0].parent)
            self._files_label()
            self.scan()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Thư mục chứa locale*.asset", self.settings.unity_locale_dir)
        if folder:
            self._files_chosen = True
            self.settings.unity_locale_dir = folder
            try:
                self.paths = sorted(path for path in Path(folder).glob("locale*.asset") if path.is_file())
            except OSError:
                self.paths = []
            self._files_label()
            self.scan()

    @Slot(bool)
    def _set_rules_expanded(self, opened):
        self.rules_label.setVisible(opened)
        self.rules_button.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)

    def _run(self, task, writing=False):
        if self.worker:
            return
        self.progress.show()
        self._writing = writing
        self.worker = DuplicateWorker(task, self)
        for widget in (self.choose_button, self.folder_button, self.scan_button, self.groups, self.keep_combo,
                       self.next_button, self.apply_button, self.close_button, self.variants):
            widget.setEnabled(False)
        self.progress.setRange(0, 0)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def scan(self):
        if self.worker:
            return
        self.scan_result = None
        self.choices = {}
        self.groups.setRowCount(0)
        self.show_group()
        self.summary.setText("Đang kiểm tra toàn bộ term trong các file đã chọn…")
        self.status.setText("")
        paths = list(self.paths)
        self._run(lambda: scan_duplicates(paths))

    def show_group(self):
        self.keep_combo.blockSignals(True)
        self.keep_combo.clear()
        while self.variants.count():
            widget = self.variants.widget(0)
            widget.setParent(None)
            widget.deleteLater()
        row = self.groups.currentRow()
        if self.scan_result is None or not 0 <= row < len(self.scan_result.groups):
            self.group_label.setText("Chọn một key để xem đầy đủ các bản ghi.")
            self.keep_combo.setEnabled(False)
            self.keep_combo.blockSignals(False)
            return
        group = self.scan_result.groups[row]
        asset = next(asset for asset in self.scan_result.assets if asset.path == group.path)
        different = [lang["Name"] for i, lang in enumerate(asset.languages)
                     if len({variant.term["Languages"][i] for variant in group.variants}) > 1]
        self.group_label.setText(f"{group.path.name} · Key: {group.key}"
                                 + (" · Khác: " + ", ".join(different) if different else " · Giống nội dung ngôn ngữ")
                                 )
        self.group_label.setToolTip(str(group.path) + "\nBấm khung nội dung để giữ bản đó; app chuyển tới key cần chọn tiếp theo.")
        if group.conflict:
            self.keep_combo.addItem("— Chọn bản giữ lại sau khi so sánh nội dung —", None)
        documents = variant_documents(group.variants, asset.languages)
        for index, variant in enumerate(group.variants):
            positions = ", ".join(str(i + 1) for i in variant.indices)
            label = f"Bản {index + 1} · {len(variant.indices)} bản ghi · vị trí term {positions}"
            self.keep_combo.addItem(label, index)
            panel = VariantPanel(index, label, documents[index])
            panel.chosen.connect(self.select_panel)
            self.variants.addWidget(panel)
        selected = self.choices.get((group.path, group.key))
        self.keep_combo.setCurrentIndex(selected + 1 if group.conflict and selected is not None else 0)
        self.keep_combo.setEnabled(group.conflict and self.worker is None)
        self.keep_combo.blockSignals(False)
        self._highlight_choice()

    @Slot(int)
    def select_panel(self, index):
        if self.worker is None and self.scan_result is not None:
            item_index = self.keep_combo.findData(index)
            if item_index == self.keep_combo.currentIndex():
                self.next_conflict()
            else:
                self.keep_combo.setCurrentIndex(item_index)

    def _highlight_choice(self):
        selected = self.keep_combo.currentData()
        for index in range(self.variants.count()):
            self.variants.widget(index).set_selected(index == selected)

    def choose_variant(self):
        if self.scan_result is None:
            return
        row = self.groups.currentRow()
        if row < 0:
            return
        group = self.scan_result.groups[row]
        value = self.keep_combo.currentData()
        if value is None:
            self.choices.pop((group.path, group.key), None)
        else:
            self.choices[(group.path, group.key)] = value
        self._update_choices()
        self._highlight_choice()
        if value is not None:
            self.next_conflict()

    def _update_choices(self):
        if self.scan_result is None:
            self.apply_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return
        unresolved = 0
        for row, group in enumerate(self.scan_result.groups):
            choice = self.choices.get((group.path, group.key))
            text = "Giống nhau · tự giữ bản đầu"
            if group.conflict:
                text = "Khác nội dung · cần chọn" if choice is None else f"Khác nội dung · giữ bản {choice + 1}"
                unresolved += choice is None
            self.groups.item(row, 4).setText(text)
            self.groups.item(row, 4).setForeground(QColor("#a85b00" if group.conflict and choice is None else "#187548"))
        self.apply_button.setEnabled(bool(self.scan_result.groups) and not unresolved and self.worker is None)
        self.next_button.setEnabled(bool(unresolved) and self.worker is None)
        self.status.setText(f"Còn {unresolved} key khác nội dung cần chọn bản giữ. Chưa ghi thay đổi nào."
                            if unresolved else "Đã chọn đủ. Bấm Xóa bản trùng để sao lưu và xóa các bản ghi dư."
                            if self.scan_result.groups else "Không có duplicate key. Không cần ghi file.")

    def next_conflict(self):
        if self.scan_result is None:
            return
        count = len(self.scan_result.groups)
        for offset in range(1, count + 1):
            row = (self.groups.currentRow() + offset) % count
            group = self.scan_result.groups[row]
            if group.conflict and (group.path, group.key) not in self.choices:
                self.groups.selectRow(row)
                return

    def cleanup(self):
        if self.worker or self.scan_result is None:
            return
        try:
            plan = prepare_duplicate_cleanup(self.scan_result, self.choices)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._removed = sum(group.count - 1 for group in self.scan_result.groups)
        self._changed_files = len(plan.changes)
        self.status.setText("Đang sao lưu và xóa các bản ghi dư…")
        self._run(lambda: apply_plan(plan, USER_CONFIG_DIR / "unity_backups"), writing=True)

    @Slot()
    def _finished(self):
        worker = self.worker
        worker.wait()
        self.worker = None
        for widget in (self.choose_button, self.folder_button, self.scan_button, self.groups, self.close_button, self.variants):
            widget.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.hide()
        if worker.error:
            self.scan_result = None
            self.groups.setRowCount(0)
            self.show_group()
            self.summary.setText("Không thể hoàn tất. Kiểm tra lại trước khi tiếp tục.")
            self.status.setText("LỖI: " + worker.error)
        elif self._writing:
            self.wrote_files = True
            self.backup_path = worker.result
            self.backup_button.setEnabled(True)
            self.scan_result = None
            self.groups.setRowCount(0)
            self.show_group()
            self.summary.setText(f"Đã xóa {self._removed} bản ghi dư trong {self._changed_files} file; mỗi key còn một bản.")
            self.status.setText(f"Bản sao lưu: {self.backup_path}\nQuay lại Unity và Refresh (Ctrl+R).")
        else:
            self.scan_result = worker.result
            groups = self.scan_result.groups
            conflicts = sum(group.conflict for group in groups)
            self.summary.setText(f"{len(self.scan_result.assets)} file · {len(groups)} key trùng · "
                                 f"{len(groups) - conflicts} key giống nội dung ngôn ngữ · {conflicts} key cần chọn · "
                                 f"{sum(group.count - 1 for group in groups)} bản ghi dư sẽ xóa")
            self.groups.setRowCount(len(groups))
            for row, group in enumerate(groups):
                for col, value in enumerate((group.path.name, group.key, group.count, group.count - 1, "")):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(group.path) if col == 0 else str(value))
                    self.groups.setItem(row, col, item)
            self._update_choices()
            self.groups.resizeRowsToContents()
            if not self._comparison_sized:
                table_height = min(240, max(140, self.groups.horizontalHeader().height() + sum(self.groups.rowHeight(i) for i in range(min(len(groups), 5))) + 8))
                self.content_splitter.setSizes([table_height, max(300, self.content_splitter.height() - table_height)])
                self._comparison_sized = True
            if groups:
                self.groups.selectRow(0)
        worker.deleteLater()

    def open_backup(self):
        if self.backup_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backup_path)))

    def reject(self):
        if self.worker is None:
            if self.paths or self._files_chosen:
                self.settings.unity_duplicate_files = [str(path) for path in self.paths]
            super().reject()

    def closeEvent(self, event):
        if self.worker:
            event.ignore()
        else:
            super().closeEvent(event)
