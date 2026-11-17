from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, QUrl, Slot, Signal, QSize, Qt, QSignalBlocker, QRect
from PySide6.QtGui import QCloseEvent, QDesktopServices, QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar,
    QPushButton, QMenu, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QToolButton,
)

from .transfer_preview import TransferPreview
from .transfer_folders_card import TransferFoldersCard
from .feature_workspace import TransferDirections, open_child_feature, start_feature_worker
from import_localize.app.paths import USER_CONFIG_DIR
from import_localize.config.settings import AppSettings
from .locale_progress_dialog import LocaleProgressDialog
from .unity_audit import asset_audit_sources, review_sources
from import_localize.services.desc_annotations import DescAnnotations
from import_localize.services.unity_locale_service import (
    LocalePlan, apply_plan, match_locale_targets, prepare_export_pairs, prepare_import_pairs,
    upload_destinations,
)


class FileRowDelegate(QStyledItemDelegate):
    """Compact filename/location columns with the normal Qt selection colors."""
    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        filename = styled.text
        styled.text = ""
        styled.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        rect = option.rect.adjusted(7, 0, -7, 0)
        width = int(rect.width() * 0.60)
        name_rect = QRect(rect.x(), rect.y(), width - 8, rect.height())
        path_rect = QRect(rect.x() + width, rect.y(), rect.width() - width, rect.height())
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        color = option.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        painter.save()
        painter.setClipRect(option.rect)
        painter.setFont(option.font)
        painter.setPen(color)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter,
                         option.fontMetrics.elidedText(filename, Qt.TextElideMode.ElideMiddle, name_rect.width()))
        color.setAlpha(180)
        painter.setPen(color)
        location = str(Path(index.data(Qt.ItemDataRole.UserRole)).parent)
        painter.drawText(path_rect, Qt.AlignmentFlag.AlignVCenter,
                         option.fontMetrics.elidedText(location, Qt.TextElideMode.ElideMiddle, path_rect.width()))
        painter.restore()


class ChangeCellDelegate(QStyledItemDelegate):
    """Keep preview colors visible even when the app theme styles table items."""
    def paint(self, painter, option, index):
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if background is None:
            super().paint(painter, option, index)
            return
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        painter.save()
        painter.setClipRect(option.rect)
        painter.fillRect(option.rect.adjusted(0, 0, -1, -1), background)
        painter.setPen(index.data(Qt.ItemDataRole.ForegroundRole).color())
        painter.setFont(styled.font)
        rect = option.rect.adjusted(7, 0, -7, 0)
        painter.drawText(rect, styled.displayAlignment | Qt.AlignmentFlag.AlignVCenter,
                         styled.fontMetrics.elidedText(styled.text, Qt.TextElideMode.ElideMiddle, rect.width()))
        painter.restore()


class FileOrderList(QListWidget):
    """One file per row; only moves within this list are accepted."""
    order_changed = Signal()
    activated_side = Signal(object)
    ROW_HEIGHT = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setItemDelegate(FileRowDelegate(self))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.setAlternatingRowColors(True)
        self.setSpacing(0)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model().rowsMoved.connect(self._moved)

    def paths(self) -> list[Path]:
        return [Path(self.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.count())]

    def set_paths(self, paths: list[Path], *, allow_new: bool = False):
        self.allow_new = allow_new
        self.clear()
        for path in paths:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setSizeHint(QSize(0, self.ROW_HEIGHT))
            self.addItem(item)
        self._number_rows()

    def _number_rows(self):
        for row, path in enumerate(self.paths()):
            item = self.item(row)
            item.setText(f"{row + 1:02d}.  {path.name}")
            item.setToolTip(str(path))
            missing = not path.is_file() and not (self.allow_new and not path.exists() and path.parent.is_dir())
            if missing:
                item.setText(f"{row + 1:02d}.  [Thiếu file] {path.name}")
                item.setToolTip(f"Không tìm thấy file: {path}\nChọn lại hoặc bỏ khỏi danh sách; vị trí ghép cặp được giữ nguyên.")
                item.setForeground(QColor("#b45309"))

    def _moved(self, *_):
        self._number_rows()
        self.order_changed.emit()

    def move_selected(self, offset: int):
        rows = sorted(self.row(item) for item in self.selectedItems())
        if not rows or (offset < 0 and rows[0] == 0) or (offset > 0 and rows[-1] == self.count() - 1):
            return
        paths = self.paths()
        selected = {paths[row] for row in rows}
        for row in rows if offset < 0 else reversed(rows):
            paths[row], paths[row + offset] = paths[row + offset], paths[row]
        with QSignalBlocker(self):
            self.set_paths(paths)
            for row, path in enumerate(paths):
                self.item(row).setSelected(path in selected)
        self._moved()
        self.itemSelectionChanged.emit()

    def remove_selected(self):
        rows = sorted((self.row(item) for item in self.selectedItems()), reverse=True)
        for row in rows:
            self.takeItem(row)
        if rows:
            self._moved()

    def clear_files(self):
        self.clear()
        self._moved()

    def mousePressEvent(self, event):
        self.activated_side.emit(self)
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self.activated_side.emit(self)
        super().focusInEvent(event)

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        super().dropEvent(event)


class LocaleWorker(QThread):
    progress_changed = Signal(int, int, str)

    def __init__(self, task: Callable, parent=None, *, reports_progress=False):
        super().__init__(parent)
        self.task = task
        self.result = None
        self.error = ""
        self.reports_progress = reports_progress

    def run(self):
        try:
            self.result = self.task(self.progress_changed.emit) if self.reports_progress else self.task()
        except Exception as exc:
            self.error = str(exc)


class UnityLocaleDialog(QDialog):
    log_emitted = Signal(str, str)

    """Visible source/destination row pairs, independent of Google settings."""

    def __init__(self, settings: AppSettings, csv_paths: list[Path] | None = None, parent=None, *, annotations=None, folder_only=False):
        super().__init__(parent)
        self.folder_only = folder_only
        self.settings = settings
        self.desc_annotations = annotations if annotations is not None else DescAnnotations()
        self.audit_kind = None
        self.asset_paths = [Path(p) for p in settings.unity_asset_files]
        self.csv_paths = ([Path(p) for p in settings.unity_import_csv_files]
                          if settings.unity_import_csv_files is not None else list(csv_paths or []))
        self.export_paths = [Path(p) for p in settings.unity_export_csv_files]
        self.upload_paths = [Path(p) for p in settings.selected_csv_files]
        self.folders = {role: getattr(settings, role + "_folder", "") for role in ("upload", "export", "unity")}
        if folder_only:
            if not self.folders["unity"]:
                self.asset_paths = []
            if not self.folders["export"]:
                self.csv_paths = []
            if not self.folders["upload"]:
                self.upload_paths, self.export_paths = [], []
        self.folder_issues = {}
        self.pair_error = ""
        self.plan: LocalePlan | None = None
        self.worker: LocaleWorker | None = None
        self.loading_dialog = None
        self._applying = False
        self._generating = False
        self.backup_path: Path | None = None
        self.setWindowTitle("Unity Locale — Replace Import / Export")
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(1120, 850)
        layout = QVBoxLayout(self)
        intro = QLabel("Ghép file theo mã ngôn ngữ. Xem trước để kiểm tra tên file, cột bản dịch và mã bên trong asset.")
        intro.setProperty("muted", True)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        intro.setVisible(not folder_only)
        self.controls = QWidget()
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        mode_row = QHBoxLayout()
        self.mode_combo = TransferDirections([("CSV → Unity", "import"), ("Unity → CSV", "export")])
        self.mode_combo.setCurrentIndex(1 if settings.unity_mode == "export" else 0)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()
        self.options_button = QToolButton()
        self.options_button.setText("Tùy chọn CSV")
        self.options_button.setCheckable(True)
        self.options_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.options_button.setArrowType(Qt.ArrowType.RightArrow)
        mode_row.addWidget(self.options_button)
        self.review_button = QToolButton()
        self.review_button.setText("Kiểm tra bản xuất")
        self.review_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        review_menu = QMenu(self.review_button)
        review_menu.addAction("Kiểm tra mapping…", self.review_mapping)
        review_menu.addAction("Nhận diện ngôn ngữ…", self.review_language)
        self.review_button.setMenu(review_menu)
        mode_row.addWidget(self.review_button)
        self.direct_button = QPushButton()
        self.direct_button.clicked.connect(self.open_direct)
        mode_row.addWidget(self.direct_button)
        controls.addLayout(mode_row)
        self.csv_options = QWidget()
        csv_options = QHBoxLayout(self.csv_options)
        csv_options.setContentsMargins(0, 0, 0, 0)
        self.delimiter_combo = QComboBox()
        for label, value in [("Tự nhận diện (xuất dấu phẩy)", "auto"), ("Dấu phẩy ,", ","), ("Chấm phẩy ;", ";"), ("Tab", "\t")]:
            self.delimiter_combo.addItem(label, value)
        csv_options.addWidget(QLabel("Dấu phân cách:"))
        csv_options.addWidget(self.delimiter_combo)
        csv_options.addStretch()
        self.language_check_button = QPushButton("Nhận diện ngôn ngữ CSV…")
        csv_options.addWidget(self.language_check_button)
        controls.addWidget(self.csv_options)
        self.csv_options.hide()
        self.options_button.toggled.connect(self._set_csv_options_expanded)

        self.export_controls = QWidget()
        export_layout = QHBoxLayout(self.export_controls)
        export_layout.setContentsMargins(0, 0, 0, 0)
        self.output_edit = QLineEdit(self.folders["upload"] or settings.unity_export_dir)
        self.output_edit.setPlaceholderText("Thư mục tạo CSV mới")
        self.output_button = QPushButton("Thư mục…")
        self.prefix_edit = QLineEdit(settings.unity_export_prefix)
        self.prefix_edit.setPlaceholderText("Tên bảng tính")
        self.prefix_edit.setMaximumWidth(200)
        self.generate_button = QPushButton("Tạo danh sách CSV đích")
        export_layout.addWidget(self.output_edit, 1)
        export_layout.addWidget(self.output_button)
        export_layout.addWidget(self.prefix_edit)
        export_layout.addWidget(self.generate_button)
        controls.addWidget(self.export_controls)

        self.source_list = FileOrderList()
        self.target_list = FileOrderList()
        self._active_list = self.source_list
        self._selection_sync = False
        headers_panel = QWidget()
        headers = QHBoxLayout(headers_panel)
        headers.setContentsMargins(0, 0, 0, 0)
        for side, file_list in (("source", self.source_list), ("target", self.target_list)):
            panel = QVBoxLayout()
            title = QLabel()
            setattr(self, side + "_title", title)
            panel.addWidget(title)
            pickers = QHBoxLayout()
            choose = QPushButton()
            extra = QPushButton()
            setattr(self, side + "_choose_button", choose)
            setattr(self, side + "_extra_button", extra)
            pickers.addWidget(choose)
            pickers.addWidget(extra)
            pickers.addStretch()
            panel.addLayout(pickers)
            columns = QHBoxLayout()
            columns.addWidget(QLabel("Tên file"), 3)
            columns.addWidget(QLabel("Vị trí"), 2)
            panel.addLayout(columns)
            headers.addLayout(panel, 1)
        controls.addWidget(headers_panel)
        headers_panel.setVisible(not folder_only)
        self.export_target_menu = QMenu(self.target_extra_button)
        self.use_uploads_action = self.export_target_menu.addAction("", self.use_upload_targets)
        self.export_target_menu.addAction("Thêm CSV mới…", self.choose_new_csv)
        # One scroll area keeps both sides aligned even with different counts.
        self.pair_scroll = QScrollArea()
        self.pair_scroll.setWidgetResizable(True)
        self.pair_scroll.setMinimumHeight(65)
        pair_contents = QWidget()
        pair_layout = QHBoxLayout(pair_contents)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        pair_layout.addWidget(self.source_list, 1)
        self.arrow_column = QWidget()
        self.arrow_column.setFixedWidth(24)
        self.arrow_layout = QVBoxLayout(self.arrow_column)
        self.arrow_layout.setContentsMargins(0, 2, 0, 2)
        self.arrow_layout.setSpacing(0)
        self.arrow_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        pair_layout.addWidget(self.arrow_column)
        pair_layout.addWidget(self.target_list, 1)
        self.pair_scroll.setWidget(pair_contents)
        controls.addWidget(self.pair_scroll)
        toolbar = QHBoxLayout()
        self.selection_label = QLabel()
        self.selection_label.setWordWrap(True)
        self.selection_label.setToolTip("Giữ Ctrl hoặc Shift để chọn nhiều file trong cùng một bên.")
        toolbar.addWidget(self.selection_label, 1)
        self.up_button = QPushButton("↑ Lên")
        self.down_button = QPushButton("↓ Xuống")
        self.remove_button = QPushButton("Bỏ chọn")
        self.clear_button = QPushButton("Xóa hết")
        self.duplicates_button = QPushButton("Kiểm tra key trùng…")
        self.duplicates_button.setToolTip("Kiểm tra các file locale trong thư mục; gộp bản giống nhau và chọn bản giữ khi khác nội dung.")
        self.clear_button.setToolTip("Xóa toàn bộ file khỏi danh sách bên đang thao tác; không xóa file trên máy.")
        for button in (self.up_button, self.down_button, self.remove_button, self.clear_button):
            toolbar.addWidget(button)
        self.duplicates_button.setVisible(not folder_only)
        toolbar.addWidget(self.duplicates_button)
        controls.addLayout(toolbar)
        self.pair_status = QLabel()
        self.pair_status.setWordWrap(True)
        controls.addWidget(self.pair_status)
        layout.addWidget(self.controls)

        metrics = QHBoxLayout()
        self.source_metric = QLabel()
        self.before_metric = QLabel()
        self.after_metric = QLabel()
        for label, background, foreground in ((self.source_metric, "#e7f1ff", "#174b8a"),
                                              (self.before_metric, "#f0f2f5", "#39475a"),
                                              (self.after_metric, "#eeeaff", "#5531a0")):
            label.setWordWrap(True)
            label.setStyleSheet(f"QLabel {{ background: {background}; color: {foreground}; border-radius: 6px; padding: 9px; }}")
            metrics.addWidget(label, 1)
        layout.addLayout(metrics)
        self.stats_note = QLabel("Thêm / Xóa / Sửa / Giữ được tính theo key; Sửa là khác bản dịch, loại hoặc mô tả.")
        self.stats_note.setWordWrap(True)
        layout.addWidget(self.stats_note)
        self.table = QTableWidget(0, 10)
        self.table.setItemDelegate(ChangeCellDelegate(self.table))
        self.table.setHorizontalHeaderLabels(["Nguồn →", "File nhận", "Nguồn", "Đích trước", "Đích sau", "+ Thêm", "− Xóa", "~ Sửa", "= Giữ", "Trạng thái"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for column in (0, 1):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(135)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 3)
        self.changes = TransferPreview()
        layout.addWidget(self.changes)
        details_header = QHBoxLayout()
        self.preview_status = QLabel("Chọn file nguồn và file nhận để bắt đầu.")
        self.preview_status.setAccessibleName("Trạng thái truyền giữa CSV và Unity")
        self.preview_status.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_status.setWordWrap(True)
        details_header.addWidget(self.preview_status, 1)
        self.details_button = QToolButton()
        self.details_button.setText("Chi tiết")
        self.details_button.setToolTip("Xem chi tiết và cảnh báo của các cặp file")
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        if folder_only:
            mode_row.addWidget(self.details_button)
        else:
            details_header.addWidget(self.details_button)
        layout.addLayout(details_header)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Kết quả xem trước, cảnh báo và đường dẫn sao lưu.")
        self.details.setMinimumHeight(65)
        self.details.setMaximumHeight(110)
        layout.addWidget(self.details, 1)
        self.details.hide()
        self.details_button.toggled.connect(self._set_details_expanded)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)
        safety = self.safety_label = QLabel()
        safety.setWordWrap(True)
        safety.setProperty("muted", True)
        layout.addWidget(safety)
        actions = QHBoxLayout()
        self.backup_button = QPushButton("Mở bản sao lưu")
        self.backup_button.hide()
        self.backup_button.setEnabled(False)
        self.preview_button = QPushButton("Xem trước")
        self.apply_button = QPushButton()
        self.close_button = QPushButton("Đóng")
        actions.addWidget(self.backup_button)
        actions.addStretch()
        for button in (self.preview_button, self.apply_button, self.close_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.action_messages = (self.preview_status, self.safety_label, self.progress)
        self.action_buttons = (self.preview_button, self.apply_button, self.backup_button, self.close_button)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)

        self.source_choose_button.clicked.connect(self.choose_source)
        self.target_choose_button.clicked.connect(self.choose_target)
        self.source_extra_button.clicked.connect(self.choose_folder)
        self.target_extra_button.clicked.connect(self.choose_target_extra)
        self.output_button.clicked.connect(self.choose_output)
        self.generate_button.clicked.connect(self.generate_destinations)
        self.source_list.order_changed.connect(self._lists_changed)
        self.target_list.order_changed.connect(self._lists_changed)
        for view in (self.source_list, self.target_list):
            view.activated_side.connect(self._activate_list)
            view.itemSelectionChanged.connect(lambda view=view: self._selection_changed(view))
        self.up_button.clicked.connect(lambda: self._active_list.move_selected(-1))
        self.down_button.clicked.connect(lambda: self._active_list.move_selected(1))
        self.remove_button.clicked.connect(lambda: self._active_list.remove_selected())
        self.clear_button.clicked.connect(lambda: self._active_list.clear_files())
        self.duplicates_button.clicked.connect(self.check_duplicates)
        self.language_check_button.clicked.connect(self.check_csv_languages)
        self.mode_combo.currentChanged.connect(self._mode_changed)
        self.delimiter_combo.currentIndexChanged.connect(self.invalidate)
        self.output_edit.textChanged.connect(self.invalidate)
        self.prefix_edit.textChanged.connect(self._refresh_lists)
        self.preview_button.clicked.connect(self.preview)
        self.apply_button.clicked.connect(self.apply)
        self.close_button.clicked.connect(self.reject)
        self.backup_button.clicked.connect(self.open_backup)
        if folder_only:
            toolbar.insertStretch(0, 1)
            for widget in (self.pair_scroll, self.selection_label, self.up_button, self.down_button,
                           self.remove_button, self.clear_button, self.pair_status, self.source_metric,
                           self.before_metric, self.after_metric, self.stats_note):
                widget.hide()
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._mode_changed()
        if self.asset_paths or self.csv_paths or self.export_paths:
            self.details.setPlainText("Đã nạp danh sách file. Mỗi mã ngôn ngữ phải có một nguồn và một đích.\n"
                                      "Bấm Xem trước để kiểm tra dữ liệu hiện tại trước khi thực hiện.")

    def importing(self):
        return self.mode_combo.currentIndex() == 0

    def set_sheet_context(self, url, annotations):
        if self.desc_annotations is not annotations:
            self.desc_annotations = annotations
            if not self.importing():
                self.invalidate()

    def open_direct(self):
        from .direct_sheet_dialog import DirectSheetDialog
        self.settings.unity_asset_files = [str(p) for p in self.asset_paths]
        dialog = DirectSheetDialog(self.settings, "download" if self.importing() else "upload",
                                   self, annotations=self.desc_annotations)
        open_child_feature(self, dialog, lambda: self.set_assets([Path(p) for p in self.settings.unity_asset_files]))

    def review_mapping(self):
        self.start_audit("mapping")

    def review_language(self):
        self.start_audit("language")

    def start_audit(self, kind):
        if self.worker or not self.asset_paths:
            return
        self.invalidate()
        paths = list(self.asset_paths)
        self.audit_kind = kind
        self._run(lambda: asset_audit_sources(paths), False)

    def check_csv_languages(self):
        from .csv_language_dialog import CsvLanguageDialog
        dialog = CsvLanguageDialog(self.csv_paths, self, annotations=self.desc_annotations)
        dialog.setStyleSheet(self.styleSheet())
        open_child_feature(self, dialog)

    def check_duplicates(self):
        if self.folder_only and not self.asset_paths:
            return
        from .locale_duplicate_dialog import LocaleDuplicateDialog
        dialog = LocaleDuplicateDialog(self.asset_paths, self, settings=self.settings)
        if dialog.paths:
            dialog.scan()
        def after_review():
            if dialog.wrote_files:
                self.invalidate()
                self.backup_path = dialog.backup_path
                self.backup_button.show()
                self.backup_button.setEnabled(True)
                self.details.setPlainText("Đã xử lý duplicate key. Bấm Xem trước lại trước khi import/export.\n"
                                          f"Bản sao lưu: {self.backup_path}")
        open_child_feature(self, dialog, after_review)

    def _mode_changed(self):
        importing = self.importing()
        self.setWindowTitle("Replace Import · CSV → Unity" if importing else "Replace Export · Unity → CSV")
        self.safety_label.setText("Replace Import thay toàn bộ term trong asset. Lưu asset và thoát Play Mode trong Unity trước khi ghi."
                                 if importing else "Replace Export ghi vào các CSV bên nhận. File có sẵn được sao lưu trước khi ghi đè.")
        self.export_controls.setVisible(not importing and not self.folder_only)
        self.review_button.setVisible(not importing and not self.folder_only)
        self.language_check_button.setVisible(importing and not self.folder_only)
        self.direct_button.setText("Sheet → Unity…" if importing else "Unity → Sheet…")
        self.source_choose_button.setText("Thêm CSV đã dịch…" if importing else "Thêm asset…")
        self.source_extra_button.setText("Thư mục…")
        self.source_extra_button.setVisible(not importing)
        self.target_choose_button.setText("Thêm asset…" if importing else "Chọn CSV nhận…")
        self.set_upload_paths(self.upload_paths)
        self.apply_button.setText("Ghi vào Unity" if importing else "Ghi vào CSV upload")
        self._refresh_lists()

    def invalidate(self):
        self.plan = None
        self.apply_button.setEnabled(False)
        self.review_button.setEnabled(bool(self.asset_paths))
        self.table.setRowCount(0)
        if self.folder_only:
            self.changes.hide()
            self.backup_button.hide()
            self.safety_label.hide()
            self.table.hide()
            self.details_button.setChecked(False)
            self.details_button.hide()
            self.duplicates_button.setEnabled(bool(self.asset_paths))
        self.progress.setValue(0)
        paired = bool(self.csv_paths if self.importing() else self.asset_paths) and not self.pair_error
        self.preview_button.setEnabled(paired and self.worker is None)
        if self.folder_only:
            count = len(self.csv_paths if self.importing() else self.asset_paths)
            summary = (f"{count} CSV export → asset cùng mã ngôn ngữ." if self.importing() else
                       f"{count} asset → CSV upload cùng mã ngôn ngữ.")
            self.preview_status.setText(self.pair_error or (summary if paired else "Thư mục nguồn chưa có file phù hợp."))
        else:
            self.preview_status.setText(self.pair_error or ("Bấm Xem trước để đối chiếu nội dung với mã trên tên file."
                                        if paired else "Chọn thư mục hoặc file nguồn và đích."))
        self.preview_button.setToolTip("Đối chiếu nội dung theo key trước khi ghi." if paired else self.preview_status.text())
        self._update_action_emphasis()
        self.source_metric.setText("NGUỒN · chưa xem trước")
        self.before_metric.setText("ĐÍCH TRƯỚC · chưa xem trước")
        self.after_metric.setText("ĐÍCH SAU · chưa xem trước")
        self.stats_note.setText("Thêm / Xóa / Sửa / Giữ được tính theo key; Sửa là khác bản dịch, loại hoặc mô tả.")

    @Slot(bool)
    def _set_csv_options_expanded(self, opened):
        self.csv_options.setVisible(opened)
        self.options_button.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)

    @Slot(bool)
    def _set_details_expanded(self, opened):
        self.details.setVisible(opened)
        self.details_button.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)

    def _update_action_emphasis(self):
        if self.plan is None:
            self.apply_button.setToolTip("Xem trước các thay đổi để có thể ghi dữ liệu.")
        else:
            target = "asset Unity" if self.importing() else "file CSV upload"
            self.apply_button.setToolTip(f"Ghi dữ liệu đã xem trước vào {len(self.plan.changes)} {target}.")
        for button, primary in ((self.preview_button, self.plan is None), (self.apply_button, self.plan is not None)):
            if button.property("primaryAction") != primary:
                button.setProperty("primaryAction", primary)
                button.style().unpolish(button)
                button.style().polish(button)

    def set_folder_files(self, role, paths, folder, issues=()):
        previous_folder = self.folders[role]
        self.folders[role] = str(folder) if folder else ""
        self.folder_issues[role] = tuple(issues)
        if role == "upload":
            self.set_upload_paths(list(paths))
            self.export_paths = list(paths)
            if folder or previous_folder:
                self.output_edit.setText(self.folders[role])
        elif role == "export":
            self.csv_paths = list(paths)
        else:
            self.asset_paths = list(paths)
        self._refresh_lists()

    def _roles(self):
        return ("export", "unity") if self.importing() else ("unity", "upload")

    def _match_paths(self, *, anchor_target=False):
        source_role, target_role = self._roles()
        self.pair_error = ""
        try:
            if self.folder_only:
                missing = [TransferFoldersCard.roles[role] for role in self._roles() if not self.folders[role]]
                if missing:
                    raise ValueError("Chọn thư mục " + " và ".join(missing) + ".")
            issues = [message for role in (source_role, target_role) for message in self.folder_issues.get(role, ())]
            if issues:
                raise ValueError("\n".join(issues))
            if target_role == "upload" and self.folders["upload"]:
                self.export_paths = upload_destinations(self.asset_paths, self.upload_paths, self.folders["upload"], "")
            source = self.csv_paths if self.importing() else self.asset_paths
            target = self.asset_paths if self.importing() else self.export_paths
            if self.folder_only:
                empty = [TransferFoldersCard.patterns[role] for (role, paths) in ((source_role, source), (target_role, target))
                         if not paths and role != "upload"]
                if empty:
                    raise ValueError("Chưa tìm thấy " + " và ".join(empty) + ". Kiểm tra thư mục rồi bấm Quét lại.")
            matched_targets = match_locale_targets(source, target, source_role, target_role)
            if anchor_target:
                source[:] = match_locale_targets(target, source, target_role, source_role)
            else:
                target[:] = matched_targets
        except ValueError as exc:
            self.pair_error = str(exc)

    def _refresh_lists(self):
        source_role, target_role = self._roles()
        self._match_paths()
        if self.folder_only:
            self.invalidate()
            return
        for role, buttons in ((source_role, (self.source_choose_button, self.source_extra_button)),
                              (target_role, (self.target_choose_button, self.target_extra_button))):
            for button in buttons:
                button.setEnabled(not self.folders[role])
                if self.folders[role]:
                    button.setToolTip(f"Danh sách lấy từ thư mục {self.folders[role]}")
                else:
                    button.setToolTip("")
        self.output_button.setEnabled(not self.folders["upload"])
        self.output_edit.setReadOnly(bool(self.folders["upload"]))
        self.prefix_edit.setVisible(not self.folders["upload"])
        self.generate_button.setVisible(not self.folders["upload"])
        self._selection_sync = True
        try:
            self.source_list.set_paths(self.csv_paths if self.importing() else self.asset_paths)
            self.target_list.set_paths(self.asset_paths if self.importing() else self.export_paths,
                                       allow_new=not self.importing())
        finally:
            self._selection_sync = False
        self._update_labels()
        self.invalidate()

    def _lists_changed(self):
        if self.importing():
            self.csv_paths, self.asset_paths = self.source_list.paths(), self.target_list.paths()
        else:
            self.asset_paths, self.export_paths = self.source_list.paths(), self.target_list.paths()
        self._match_paths(anchor_target=self.sender() is self.target_list)
        aligned = self.asset_paths if self.importing() else self.export_paths
        source = self.csv_paths if self.importing() else self.asset_paths
        if self.source_list.paths() != source:
            self.source_list.set_paths(source)
        if self.target_list.paths() != aligned:
            self.target_list.set_paths(aligned, allow_new=not self.importing())
        self.settings.unity_asset_files = [str(p) for p in self.asset_paths]
        self._update_labels()
        self.invalidate()
        self.details.setPlainText("Thứ tự file đã thay đổi. Bấm Xem trước để kiểm tra các cặp mới trước khi ghi.")

    def _update_labels(self):
        left, right = self.source_list.count(), self.target_list.count()
        self.source_title.setText(f"NGUỒN · {'CSV đã dịch' if self.importing() else 'Unity locale'} · {left} file")
        self.target_title.setText(f"NHẬN VÀO · {'Unity locale' if self.importing() else 'CSV'} · {right} file")
        height = max(36, max(left, right) * FileOrderList.ROW_HEIGHT + 4)
        for view in (self.source_list, self.target_list):
            view.setFixedHeight(height)
        while self.arrow_layout.count():
            self.arrow_layout.takeAt(0).widget().deleteLater()
        for row in range(max(left, right)):
            arrow = QLabel("→" if not self.pair_error and row < min(left, right) else "·")
            arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
            arrow.setFixedHeight(FileOrderList.ROW_HEIGHT)
            self.arrow_layout.addWidget(arrow)
        self.pair_scroll.setFixedHeight(max(65, min(200, height + 4)))
        self._update_toolbar()

    def _activate_list(self, view):
        if self._selection_sync:
            return
        self._selection_sync = True
        try:
            self._active_list = view
            other = self.target_list if view is self.source_list else self.source_list
            other.clearSelection()
        finally:
            self._selection_sync = False
        self._update_toolbar()

    def _selection_changed(self, view):
        if self._selection_sync:
            return
        if view.selectedItems():
            self._activate_list(view)
        else:
            self._update_toolbar()

    def _update_toolbar(self):
        view = self._active_list
        rows = sorted(view.row(item) for item in view.selectedItems())
        side = "Nguồn" if view is self.source_list else "Nhận vào"
        self.selection_label.setText(f"Bên {side} · chọn {len(rows)}/{view.count()} file")
        self.up_button.setEnabled(bool(rows) and rows[0] > 0)
        self.down_button.setEnabled(bool(rows) and rows[-1] < view.count() - 1)
        source_role, target_role = self._roles()
        role = source_role if view is self.source_list else target_role
        self.remove_button.setEnabled(bool(rows) and not self.folders[role])
        self.clear_button.setEnabled(view.count() > 0 and not self.folders[role])
        if self.pair_error:
            self.pair_status.setText(self.pair_error)
        elif len(rows) == 1:
            row = rows[0]
            source = self.source_list.paths()
            target = self.target_list.paths()
            self.pair_status.setText(f"Hàng {row + 1:02d}: "
                                     + (source[row].name if row < len(source) else "Chưa chọn nguồn")
                                     + "  →  " + (target[row].name if row < len(target) else "Chưa chọn file nhận"))
        else:
            left, right = self.source_list.count(), self.target_list.count()
            if left == right and left:
                self.pair_status.setText(f"{left} cặp theo mã ngôn ngữ · bên trái → bên phải.")
            else:
                self.pair_status.setText(f"{left} nguồn / {right} đích.")

    @staticmethod
    def _append_unique(existing, added):
        return list(dict.fromkeys(Path(p).resolve() for p in [*existing, *added]))

    def choose_source(self):
        self.choose_csv() if self.importing() else self.choose_assets()

    def choose_target(self):
        self.choose_assets() if self.importing() else self.choose_export_csv()

    def choose_target_extra(self):
        if self.importing():
            self.choose_folder()
        elif self.target_extra_button.menu() is None:
            self.choose_new_csv()

    def choose_assets(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn I2 LanguageSourceAsset", self.settings.unity_locale_dir,
                                               "Unity locale (locale*.asset);;Unity asset (*.asset)")
        if paths:
            self.set_assets(self._append_unique(self.asset_paths, paths))

    def set_assets(self, paths: list[Path]):
        self.asset_paths = list(paths)
        self.settings.unity_asset_files = [str(p) for p in self.asset_paths]
        if paths:
            self.settings.unity_locale_dir = str(paths[0].parent)
        self._refresh_lists()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Thư mục chứa locale_*.asset", self.settings.unity_locale_dir)
        if folder:
            paths = sorted(Path(folder).glob("locale*.asset"))
            self.settings.unity_locale_dir = folder
            self.set_assets(self._append_unique(self.asset_paths, paths))
            if not paths:
                self.details.setPlainText("Không có locale*.asset trong thư mục này. Chọn Assets/AssetBundle/Localization của Dicegeon.")
                self.preview_status.setText("Không tìm thấy locale*.asset trong thư mục đã chọn.")
                self.details_button.setChecked(True)

    def choose_csv(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn CSV đã dịch", self.settings.unity_csv_dir or self.settings.last_export_dir,
                                               "CSV UTF-8 (*.csv)")
        if paths:
            self.csv_paths = self._append_unique(self.csv_paths, paths)
            self.settings.unity_csv_dir = str(Path(paths[0]).parent)
            self._refresh_lists()

    def choose_export_csv(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn CSV nhận dữ liệu (ghi đè)", self.output_edit.text(), "CSV (*.csv)")
        if paths:
            self.export_paths = self._append_unique(self.export_paths, paths)
            self._refresh_lists()

    def set_upload_paths(self, paths):
        self.upload_paths = list(paths)
        menu_available = bool(self.upload_paths) and not self.importing()
        self.use_uploads_action.setText(f"Dùng danh sách CSV upload ({len(paths)} tệp)")
        self.target_extra_button.setMenu(self.export_target_menu if menu_available else None)
        self.target_extra_button.setText("Thư mục…" if self.importing() else
                                        "CSV upload / CSV mới…" if menu_available else "Thêm CSV mới…")

    def use_upload_targets(self):
        self.export_paths = list(self.upload_paths)
        self._refresh_lists()

    def choose_new_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Thêm đường dẫn CSV nhận dữ liệu", self.output_edit.text(), "CSV (*.csv)")
        if path:
            if not path.lower().endswith(".csv"):
                path += ".csv"
            self.export_paths = self._append_unique(self.export_paths, [path])
            self._refresh_lists()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Thư mục tạo CSV mới", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def generate_destinations(self):
        self.invalidate()
        if not self.output_edit.text().strip():
            self.details.setPlainText("Chọn thư mục tạo CSV trước.")
            self.preview_status.setText("Chọn thư mục tạo CSV trước.")
            self.output_edit.setFocus()
            return
        assets, folder, prefix = list(self.asset_paths), Path(self.output_edit.text()), self.prefix_edit.text()
        self.details.setPlainText("Đang tạo danh sách đường dẫn CSV đích…")
        self._run(lambda: upload_destinations(assets, [], folder, prefix), False, generating=True)

    def _run(self, task: Callable, applying: bool, *, generating: bool = False, reports_progress: bool = False):
        if self.worker:
            return
        self.progress.show()
        self.preview_status.setText("Đang sao lưu và ghi dữ liệu…" if applying else "Đang tạo danh sách file…" if generating else "Đang kiểm tra dữ liệu…")
        self.controls.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.log_emitted.emit("INFO", f"{self.windowTitle()} · {self.preview_status.text()}")
        self._applying, self._generating = applying, generating
        self.worker = LocaleWorker(task, self, reports_progress=reports_progress)
        if applying:
            if self.loading_dialog:
                self.loading_dialog.deleteLater()
            operation = "Replace Import" if self.importing() else "Replace Export"
            self.loading_dialog = LocaleProgressDialog(operation, len(self.plan.changes) if self.plan else 0, self)
            self.loading_dialog.show()
            self.worker.progress_changed.connect(self._apply_progress)
        self.worker.finished.connect(self._finished)
        start_feature_worker(self)

    @Slot(int, int, str)
    def _apply_progress(self, completed, total, message):
        self.log_emitted.emit("INFO", message)
        if self.loading_dialog:
            self.loading_dialog.update_progress(completed, total, message)
        self.progress.setRange(0, total)
        self.progress.setValue(completed)

    def preview(self):
        self.invalidate()
        if self.folder_only:
            source, target = ((list(self.csv_paths), list(self.asset_paths)) if self.importing()
                              else (list(self.asset_paths), list(self.export_paths)))
        else:
            source, target = self.source_list.paths(), self.target_list.paths()
        delimiter = self.delimiter_combo.currentData()
        if self.pair_error:
            self.details.setPlainText("LỖI: " + self.pair_error)
            self.details_button.setChecked(True)
            return
        folders = []
        for role, paths in zip(self._roles(), (source, target)):
            if self.folders[role]:
                expected = self.upload_paths if role == "upload" else paths
                folders.append((role, Path(self.folders[role]), tuple(expected)))
        self.details.setPlainText("Đang kiểm tra ngôn ngữ trong từng cặp file…")
        if self.importing():
            task = lambda: prepare_import_pairs(source, target, delimiter, match_languages=True, folders=tuple(folders))
        else:
            annotations = self.desc_annotations.snapshot()
            task = lambda: prepare_export_pairs(source, target, "," if delimiter == "auto" else delimiter,
                                                annotations=annotations, match_languages=True, folders=tuple(folders))
        self._run(task, False)

    def apply(self):
        if self.plan:
            plan = self.plan
            self.details.appendPlainText("Đang sao lưu và ghi các cặp file đã xem trước…")
            self._run(lambda report: apply_plan(plan, USER_CONFIG_DIR / "unity_backups", progress=report),
                      True, reports_progress=True)

    @Slot()
    def _finished(self):
        worker = self.worker
        worker.wait()
        self.worker = None
        self.controls.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.progress.setRange(0, 1)
        audit_kind, self.audit_kind = self.audit_kind, None
        if worker.error:
            self.changes.hide()
            self.progress.setValue(0)
            self.plan = None
            self.details.appendPlainText("LỖI: " + worker.error)
            self.log_emitted.emit("FAIL", worker.error)
            self.preview_status.setText("Không thể hoàn tất. " + worker.error.splitlines()[0])
            self.details_button.show()
            self.details_button.setChecked(True)
            self.apply_button.setEnabled(False)
            if self.folder_only:
                self.safety_label.hide()
        elif audit_kind:
            self.progress.hide()
            review_sources(audit_kind, self, self.settings, worker.result, self.desc_annotations)
            self.invalidate()
        elif self._generating:
            self.export_paths = worker.result
            self._refresh_lists()
            self.details.setPlainText("Đã tạo danh sách CSV đích theo mã ngôn ngữ, chưa ghi file. Bấm Xem trước để kiểm tra.\n"
                                      "Đổi thư mục/tên bảng tính chỉ áp dụng khi bấm Tạo danh sách CSV đích lại.")
        elif self._applying:
            self.plan = None
            self.backup_path = worker.result
            self.backup_button.show()
            self.backup_button.setEnabled(True)
            self.progress.setValue(1)
            target = "asset Unity" if self.importing() else "file CSV upload"
            next_step = ("Quay lại Unity và Refresh (Ctrl+R) để nạp bản dịch." if self.importing()
                         else "Mở CSV ↔ Sheet để tải các file này lên bảng tính.")
            self.preview_status.setText(f"Đã ghi {self.table.rowCount()} {target}. {next_step}")
            self.log_emitted.emit("SUCCESS", f"{self.preview_status.text()} {self.backup_path}")
            if self.folder_only:
                self.safety_label.hide()
            for row in range(self.table.rowCount()):
                self.table.item(row, 9).setText("Đã ghi")
            self.details.appendPlainText(f"Hoàn tất. Bản sao lưu: {self.backup_path}\n{next_step}")
        else:
            self.plan = worker.result
            self.safety_label.show()
            if self.folder_only:
                self.changes.show_changes([(c.source_path.name, c.path.name, c.stats, c.summary) for c in self.plan.changes])
            else:
                self.table.show()
            self.details_button.show()
            self.table.setRowCount(len(self.plan.changes))
            stats = [change.stats for change in self.plan.changes]
            source_total = sum(stat.source_count for stat in stats)
            before_total = "chưa xác định" if any(stat.before_count is None for stat in stats) else str(sum(stat.before_count for stat in stats))
            after_total = sum(stat.after_count for stat in stats)
            self.source_metric.setText(f"NGUỒN · <b>{source_total}</b> {stats[0].source_unit}")
            self.before_metric.setText(f"ĐÍCH TRƯỚC · <b>{before_total}</b> {stats[0].target_unit}")
            self.after_metric.setText(f"ĐÍCH SAU · <b>{after_total}</b> {stats[0].target_unit}")
            self.table.horizontalHeaderItem(2).setToolTip(f"Số {stats[0].source_unit} từ file nguồn, trước khi gộp key trùng.")
            for column in (3, 4):
                self.table.horizontalHeaderItem(column).setToolTip(f"Số {stats[0].target_unit} trong file đích trước / sau khi ghi.")
            duplicates = sum(stat.duplicate_before for stat in stats)
            self.stats_note.setText("Thêm / Xóa / Sửa / Giữ tính theo key; Sửa = khác nội dung, loại hoặc mô tả."
                                    + (f" Đích hiện có {duplicates} bản ghi trùng key" + (", sẽ được gộp khi nhập." if self.importing() else ".") if duplicates else "")
                                    + " Dấu — = chưa so sánh được dữ liệu cũ.")
            details = ["Kiểm tra thành công. Dữ liệu sẽ chuyển theo các cặp đã hiển thị; file cũ được sao lưu trước khi ghi."]
            for row, change in enumerate(self.plan.changes):
                stat = change.stats
                source = change.source_path
                values = (f"{row + 1:02d}. {source.name}", change.path.name, stat.source_count,
                          stat.before_count, stat.after_count, stat.added, stat.removed, stat.updated, stat.unchanged,
                          "Ghi đè" if change.before is not None else "Tạo mới")
                colors = {0: ("#e7f1ff", "#174b8a"), 1: ("#eeeaff", "#5531a0"),
                          2: ("#e7f1ff", "#174b8a"), 3: ("#f0f2f5", "#39475a"),
                          4: ("#eeeaff", "#5531a0"), 5: ("#dcf5e7", "#14633c"),
                          6: ("#ffe5e5", "#a1232b"), 7: ("#fff0ce", "#865500"),
                          8: ("#f0f2f5", "#39475a")}
                for col, value in enumerate(values):
                    item = QTableWidgetItem("—" if value is None else str(value))
                    item.setToolTip(str(source) if col == 0 else str(change.path) if col == 1 else change.summary)
                    if col in colors:
                        background, foreground = colors[col]
                        item.setBackground(QColor(background))
                        item.setForeground(QColor(foreground))
                    if 2 <= col <= 8:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    self.table.setItem(row, col, item)
                details.append(f"Hàng {row + 1}: {source}\n→ {change.path}\n{change.summary}")
                for warning in change.warnings:
                    self.log_emitted.emit("WARNING", f"{change.path.name} · {warning}")
                details.extend("  • " + warning for warning in change.warnings)
            self.table.setMinimumHeight(min(280, self.table.horizontalHeader().height() + self.table.verticalHeader().length() + 6))
            self.details.setPlainText("\n\n".join(details))
            warnings = sum(len(change.warnings) for change in self.plan.changes)
            self.preview_status.setText(f"{len(self.plan.changes)} cặp sẵn sàng · chưa ghi dữ liệu"
                                        + (f" · {warnings} cảnh báo cần xem" if warnings else ""))
            self.log_emitted.emit("SUCCESS", self.preview_status.text())
            self.details_button.setChecked(bool(warnings))
            self.apply_button.setEnabled(True)
            self.progress.setValue(1)
        self.progress.hide()
        if self.folder_only:
            self.duplicates_button.setEnabled(bool(self.asset_paths))
        self._update_action_emphasis()
        if self._applying and self.loading_dialog:
            self.loading_dialog.finish(worker.error, worker.result if not worker.error else None)
        worker.deleteLater()

    def open_backup(self):
        if self.backup_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backup_path)))

    def reject(self):
        if self.worker:
            return
        self.settings.unity_export_dir = self.output_edit.text()
        self.settings.unity_export_prefix = self.prefix_edit.text()
        self.settings.unity_asset_files = [str(p) for p in self.asset_paths]
        self.settings.unity_import_csv_files = [str(p) for p in self.csv_paths]
        self.settings.unity_export_csv_files = [str(p) for p in self.export_paths]
        self.settings.unity_mode = "import" if self.importing() else "export"
        super().reject()

    def closeEvent(self, event: QCloseEvent):
        if self.worker:
            event.ignore()
        else:
            self.reject()
            event.accept()
