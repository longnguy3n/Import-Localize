from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, QUrl, Slot, Signal, QSize, Qt, QSignalBlocker, QRect
from PySide6.QtGui import QCloseEvent, QDesktopServices, QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)

from import_localize.app.paths import USER_CONFIG_DIR
from import_localize.config.settings import AppSettings
from import_localize.services.unity_locale_service import (
    LocalePlan, apply_plan, prepare_export, prepare_export_pairs, prepare_import_pairs,
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

    def set_paths(self, paths: list[Path]):
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
    """Visible source/destination row pairs, independent of Google settings."""

    def __init__(self, settings: AppSettings, csv_paths: list[Path] | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.asset_paths: list[Path] = []
        self.csv_paths = list(csv_paths or [])
        self.export_paths: list[Path] = []
        self.plan: LocalePlan | None = None
        self.worker: LocaleWorker | None = None
        self._applying = False
        self._generating = False
        self.backup_path: Path | None = None
        self.setWindowTitle("Unity Locale — Replace Import / Export")
        self.resize(1120, 850)
        layout = QVBoxLayout(self)
        intro = QLabel("Mỗi hàng: file bên trái → file bên phải. Kéo thả trong từng bên để đổi cặp nguồn–đích.\n"
                       "Import thay toàn bộ term trong asset. Lưu asset và thoát Play Mode trong Unity trước khi ghi.")
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

        self.export_controls = QWidget()
        export_layout = QHBoxLayout(self.export_controls)
        export_layout.setContentsMargins(0, 0, 0, 0)
        self.output_edit = QLineEdit(settings.unity_export_dir)
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
        headers = QHBoxLayout()
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
        controls.addLayout(headers)
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
        toolbar.addWidget(self.selection_label, 1)
        self.up_button = QPushButton("↑ Lên")
        self.down_button = QPushButton("↓ Xuống")
        self.remove_button = QPushButton("Bỏ chọn")
        self.clear_button = QPushButton("Xóa hết")
        self.clear_button.setToolTip("Xóa toàn bộ file khỏi danh sách bên đang thao tác; không xóa file trên máy.")
        for button in (self.up_button, self.down_button, self.remove_button, self.clear_button):
            toolbar.addWidget(button)
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
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Kết quả xem trước, cảnh báo và đường dẫn sao lưu.")
        self.details.setMinimumHeight(65)
        self.details.setMaximumHeight(110)
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
        self.apply_button = QPushButton()
        self.close_button = QPushButton("Đóng")
        actions.addWidget(self.backup_button)
        actions.addStretch()
        for button in (self.preview_button, self.apply_button, self.close_button):
            actions.addWidget(button)
        layout.addLayout(actions)

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
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.delimiter_combo.currentIndexChanged.connect(self.invalidate)
        self.output_edit.textChanged.connect(self.invalidate)
        self.prefix_edit.textChanged.connect(self.invalidate)
        self.preview_button.clicked.connect(self.preview)
        self.apply_button.clicked.connect(self.apply)
        self.close_button.clicked.connect(self.reject)
        self.backup_button.clicked.connect(self.open_backup)
        self._mode_changed()

    def importing(self):
        return self.mode_combo.currentIndex() == 0

    def _mode_changed(self):
        importing = self.importing()
        self.export_controls.setVisible(not importing)
        self.source_choose_button.setText("Thêm CSV đã dịch…" if importing else "Thêm locale*.asset…")
        self.source_extra_button.setText("Thư mục locale…")
        self.source_extra_button.setVisible(not importing)
        self.target_choose_button.setText("Thêm locale*.asset…" if importing else "Chọn CSV nhận…")
        self.target_extra_button.setText("Thư mục locale…" if importing else "Thêm CSV mới…")
        self.apply_button.setText("2. Thực hiện Replace " + ("Import" if importing else "Export"))
        self._refresh_lists()

    def invalidate(self):
        self.plan = None
        self.apply_button.setEnabled(False)
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.source_metric.setText("NGUỒN · chưa xem trước")
        self.before_metric.setText("ĐÍCH TRƯỚC · chưa xem trước")
        self.after_metric.setText("ĐÍCH SAU · chưa xem trước")
        self.stats_note.setText("Thêm / Xóa / Sửa / Giữ được tính theo key; Sửa là khác bản dịch, loại hoặc mô tả.")

    def _refresh_lists(self):
        self._selection_sync = True
        try:
            self.source_list.set_paths(self.csv_paths if self.importing() else self.asset_paths)
            self.target_list.set_paths(self.asset_paths if self.importing() else self.export_paths)
        finally:
            self._selection_sync = False
        self._update_labels()
        self.invalidate()

    def _lists_changed(self):
        if self.importing():
            self.csv_paths, self.asset_paths = self.source_list.paths(), self.target_list.paths()
        else:
            self.asset_paths, self.export_paths = self.source_list.paths(), self.target_list.paths()
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
            arrow = QLabel("→" if row < min(left, right) else "·")
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
        self.selection_label.setText(f"Bên {side} · chọn {len(rows)}/{view.count()} file · Ctrl/Shift để chọn nhiều")
        self.up_button.setEnabled(bool(rows) and rows[0] > 0)
        self.down_button.setEnabled(bool(rows) and rows[-1] < view.count() - 1)
        self.remove_button.setEnabled(bool(rows))
        self.clear_button.setEnabled(view.count() > 0)
        if len(rows) == 1:
            row = rows[0]
            source = self.source_list.paths()
            target = self.target_list.paths()
            self.pair_status.setText(f"Hàng {row + 1:02d}: "
                                     + (source[row].name if row < len(source) else "Chưa chọn nguồn")
                                     + "  →  " + (target[row].name if row < len(target) else "Chưa chọn file nhận"))
        else:
            left, right = self.source_list.count(), self.target_list.count()
            if left == right and left:
                self.pair_status.setText(f"{left} cặp theo hàng · bên trái → bên phải. Đổi thứ tự một bên sẽ đổi file nhận dữ liệu.")
            else:
                self.pair_status.setText(f"Chưa đủ cặp: {left} nguồn / {right} đích. Hai bên phải có cùng số file để thực hiện.")

    @staticmethod
    def _append_unique(existing, added):
        return list(dict.fromkeys(Path(p).resolve() for p in [*existing, *added]))

    def choose_source(self):
        self.choose_csv() if self.importing() else self.choose_assets()

    def choose_target(self):
        self.choose_assets() if self.importing() else self.choose_export_csv()

    def choose_target_extra(self):
        self.choose_folder() if self.importing() else self.choose_new_csv()

    def choose_assets(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn I2 LanguageSourceAsset", self.settings.unity_locale_dir,
                                               "Unity locale (locale*.asset);;Unity asset (*.asset)")
        if paths:
            self.set_assets(self._append_unique(self.asset_paths, paths))

    def set_assets(self, paths: list[Path]):
        self.asset_paths = list(paths)
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
            return
        assets, folder, prefix = list(self.asset_paths), Path(self.output_edit.text()), self.prefix_edit.text()
        self.details.setPlainText("Đang tạo danh sách đường dẫn CSV đích…")
        self._run(lambda: [c.path for c in prepare_export(assets, folder, prefix).changes], False, generating=True)

    def _run(self, task: Callable, applying: bool, *, generating: bool = False):
        if self.worker:
            return
        self.controls.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self._applying, self._generating = applying, generating
        self.worker = LocaleWorker(task, self)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def preview(self):
        self.invalidate()
        source, target = self.source_list.paths(), self.target_list.paths()
        delimiter = self.delimiter_combo.currentData()
        self.details.setPlainText("Đang kiểm tra từng cặp file theo thứ tự hàng…")
        if self.importing():
            task = lambda: prepare_import_pairs(source, target, delimiter)
        else:
            task = lambda: prepare_export_pairs(source, target, "," if delimiter == "auto" else delimiter)
        self._run(task, False)

    def apply(self):
        if self.plan:
            plan = self.plan
            self.details.appendPlainText("Đang sao lưu và ghi các cặp file đã xem trước…")
            self._run(lambda: apply_plan(plan, USER_CONFIG_DIR / "unity_backups"), True)

    @Slot()
    def _finished(self):
        worker = self.worker
        worker.wait()
        self.worker = None
        self.controls.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.progress.setRange(0, 1)
        if worker.error:
            self.plan = None
            self.details.appendPlainText("LỖI: " + worker.error)
            self.apply_button.setEnabled(False)
        elif self._generating:
            self.export_paths = worker.result
            self._refresh_lists()
            self.details.setPlainText("Đã tạo danh sách CSV đích, chưa ghi file. Kéo thả để chỉnh cặp nếu cần, rồi bấm Xem trước.\n"
                                      "Đổi thư mục/tên bảng tính chỉ áp dụng khi bấm Tạo danh sách CSV đích lại.")
        elif self._applying:
            self.plan = None
            self.backup_path = worker.result
            self.backup_button.setEnabled(True)
            self.progress.setValue(1)
            for row in range(self.table.rowCount()):
                self.table.item(row, 9).setText("Đã ghi")
            self.details.appendPlainText(f"Hoàn tất. Bản sao lưu: {self.backup_path}\n"
                                         "Import: quay lại Unity và Refresh (Ctrl+R) nếu asset chưa cập nhật.\n"
                                         "Export: thêm CSV upload_* vào luồng upload Google Sheets của ứng dụng.")
        else:
            self.plan = worker.result
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
