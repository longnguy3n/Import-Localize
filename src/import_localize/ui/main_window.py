from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QTimer, QUrl, Qt, QSize
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QKeySequence,
    QShortcut,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from import_localize.app.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_GITHUB_REPOSITORY,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MAX_CSV_FILES,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)
from import_localize.app.paths import FORMS_DIR, IMAGES_DIR, THEMES_DIR
from import_localize.config.settings import SettingsRepository
from import_localize.models.import_job import CsvFileInfo, ImportJob
from import_localize.services.csv_service import (
    CsvImportError,
    format_size,
    inspect_csv,
    validate_worksheet_title,
)
from import_localize.services.google_service import oauth_configuration_status
from import_localize.services.update_service import UpdateRelease, is_newer_version
from import_localize.ui.assets import icon, load_logo, set_button_icon
from import_localize.ui.dialogs import HelpDialog, SettingsDialog
from import_localize.ui.ui_loader import load_ui, require_object
from import_localize.ui.widgets import BottomAlignedLogView
from import_localize.workers.import_worker import ImportWorker
from import_localize.workers.update_worker import UpdateCheckWorker


class MainWindow(QMainWindow):
    """Main Import Localize window using the same visual system as SK Export."""

    WIDE_BREAKPOINT = 1040  # Giữ để tương thích; card đích luôn nằm trên cùng.
    COMPACT_BREAKPOINT = 690

    def __init__(self):
        super().__init__()
        self.settings_repository = SettingsRepository()
        self.settings = self.settings_repository.load()
        self.worker: ImportWorker | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.file_infos: dict[str, CsvFileInfo] = {}
        self._close_when_finished = False
        self._wide_layout: bool | None = None
        self._density_mode: str | None = None
        self._screen_signal_connected = False

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setWindowIcon(QIcon(str(IMAGES_DIR / "import_localize_logo.svg")))
        self.setAcceptDrops(True)

        self.root = load_ui(FORMS_DIR / "main_window.ui", self)
        self.setCentralWidget(self.root)
        self._bind_widgets()
        self._configure_widgets()
        self._connect_signals()
        self._restore_settings()
        self.apply_theme(self.settings.theme)
        self._set_initial_geometry()

        self.append_log(
            "INFO",
            "Ứng dụng đã sẵn sàng. Chọn chế độ một sheet hoặc nhiều sheet rồi thêm file CSV.",
        )
        QTimer.singleShot(1800, self._auto_check_updates)

    def _bind_widgets(self) -> None:
        root = self.root

        self.top_bar = require_object(root, "topBar", QFrame)
        self.logo_label = require_object(root, "logoLabel", QLabel)
        self.app_subtitle_label = require_object(root, "appSubtitleLabel", QLabel)
        self.version_label = require_object(root, "versionLabel", QLabel)
        self.version_label.setText(f"v{APP_VERSION}")
        self.help_button = require_object(root, "helpButton", QPushButton)
        self.settings_button = require_object(root, "settingsButton", QPushButton)
        self.theme_button = require_object(root, "themeButton", QPushButton)

        self.upper_content = require_object(root, "upperContent", QWidget)
        self.top_container = require_object(root, "topContainer", QWidget)
        self.top_grid = require_object(root, "topGrid", QGridLayout)

        self.files_card = require_object(root, "filesCard", QFrame)
        self.target_card = require_object(root, "targetCard", QFrame)
        self.action_card = require_object(root, "actionCard", QFrame)
        self.log_card = require_object(root, "logCard", QFrame)

        self.files_card_layout = require_object(root, "filesCardLayout", QVBoxLayout)
        self.target_card_layout = require_object(root, "targetCardLayout", QVBoxLayout)
        self.action_card_layout = require_object(root, "actionCardLayout", QVBoxLayout)
        self.log_card_layout = require_object(root, "logCardLayout", QVBoxLayout)

        self.files_icon_label = require_object(root, "filesIconLabel", QLabel)
        self.target_icon_label = require_object(root, "targetIconLabel", QLabel)
        self.action_icon_label = require_object(root, "actionIconLabel", QLabel)
        self.log_icon_label = require_object(root, "logIconLabel", QLabel)

        self.file_table = require_object(root, "fileTable", QTableWidget)
        self.add_files_button = require_object(root, "addFilesButton", QPushButton)
        self.move_up_button = require_object(root, "moveUpButton", QPushButton)
        self.move_down_button = require_object(root, "moveDownButton", QPushButton)
        self.remove_files_button = require_object(
            root, "removeFilesButton", QPushButton
        )
        self.clear_files_button = require_object(root, "clearFilesButton", QPushButton)
        self.file_summary_label = require_object(root, "fileSummaryLabel", QLabel)

        self.sheet_url_edit = require_object(root, "sheetUrlEdit", QLineEdit)
        self.open_sheet_button = require_object(root, "openSheetButton", QPushButton)
        self.target_mode_combo = require_object(root, "targetModeCombo", QComboBox)
        self.single_sheet_name_label = require_object(
            root, "singleSheetNameLabel", QLabel
        )
        self.single_sheet_name_edit = require_object(
            root, "singleSheetNameEdit", QLineEdit
        )
        self.value_input_combo = require_object(root, "valueInputCombo", QComboBox)
        self.target_subtitle_label = require_object(
            root, "targetSubtitleLabel", QLabel
        )

        self.start_button = require_object(root, "startButton", QPushButton)
        self.stop_button = require_object(root, "stopButton", QPushButton)
        self.progress_bar = require_object(root, "progressBar", QProgressBar)
        self.progress_label = require_object(root, "progressLabel", QLabel)
        self.clear_log_button = require_object(root, "clearLogButton", QPushButton)
        self.log_placeholder = require_object(root, "logPlaceholder", QWidget)
        self.log_placeholder_layout = require_object(
            root, "logPlaceholderLayout", QVBoxLayout
        )

    @staticmethod
    def _apply_card_shadow(card: QFrame) -> None:
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 25))
        card.setGraphicsEffect(shadow)

    def _configure_widgets(self) -> None:
        self.logo_label.setPixmap(load_logo(40))
        self.files_icon_label.setPixmap(icon("files").pixmap(QSize(18, 18)))
        self.target_icon_label.setPixmap(icon("sheet").pixmap(QSize(18, 18)))
        self.action_icon_label.setPixmap(icon("rocket").pixmap(QSize(18, 18)))
        self.log_icon_label.setPixmap(icon("terminal").pixmap(QSize(18, 18)))

        set_button_icon(self.settings_button, "settings", 18)
        set_button_icon(self.help_button, "help", 18)
        set_button_icon(self.theme_button, "moon", 18)
        set_button_icon(self.open_sheet_button, "external-link", 14)
        set_button_icon(self.add_files_button, "folder-plus", 16)
        set_button_icon(self.move_up_button, "chevron-up", 15)
        set_button_icon(self.move_down_button, "chevron-down", 15)
        set_button_icon(self.remove_files_button, "remove", 15)
        set_button_icon(self.clear_files_button, "trash", 15)
        set_button_icon(self.clear_log_button, "trash", 15)
        set_button_icon(self.start_button, "upload", 17)
        set_button_icon(self.stop_button, "stop", 15)

        for card in (
            self.files_card,
            self.target_card,
            self.action_card,
            self.log_card,
        ):
            self._apply_card_shadow(card)

        self.file_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.file_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.file_table.setSortingEnabled(False)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.verticalHeader().setDefaultSectionSize(29)
        header = self.file_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        self.log_edit = BottomAlignedLogView(self.log_placeholder)
        self.log_placeholder_layout.addWidget(self.log_edit)

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stop_button.setVisible(False)

        self.files_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.target_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.action_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.log_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def _connect_signals(self) -> None:
        self.add_files_button.clicked.connect(self.choose_csv_files)
        self.move_up_button.clicked.connect(lambda: self.move_selected_files(-1))
        self.move_down_button.clicked.connect(lambda: self.move_selected_files(1))
        self.remove_files_button.clicked.connect(self.remove_selected_files)
        self.clear_files_button.clicked.connect(self.clear_files)
        self.open_sheet_button.clicked.connect(self.open_sheet)
        self.start_button.clicked.connect(self.start_import)
        self.stop_button.clicked.connect(self.stop_import)
        self.clear_log_button.clicked.connect(self.log_edit.clear)
        self.settings_button.clicked.connect(self.show_settings)
        self.help_button.clicked.connect(self.show_help)
        self.theme_button.clicked.connect(self.toggle_theme)
        self.target_mode_combo.currentIndexChanged.connect(
            self._on_target_mode_changed
        )
        self.single_sheet_name_edit.textChanged.connect(
            self._refresh_file_targets
        )
        self.file_table.itemSelectionChanged.connect(
            self._update_reorder_buttons
        )
        self._move_up_shortcut = QShortcut(QKeySequence("Alt+Up"), self)
        self._move_up_shortcut.activated.connect(
            lambda: self.move_selected_files(-1)
        )
        self._move_down_shortcut = QShortcut(QKeySequence("Alt+Down"), self)
        self._move_down_shortcut.activated.connect(
            lambda: self.move_selected_files(1)
        )
        self._update_reorder_buttons()

    def _restore_settings(self) -> None:
        self.sheet_url_edit.setText(self.settings.sheet_url)
        self.target_mode_combo.setCurrentIndex(
            1 if self.settings.target_mode == "single" else 0
        )
        self.single_sheet_name_edit.setText(self.settings.sheet_name)
        self.value_input_combo.setCurrentIndex(
            1 if self.settings.value_input_option == "USER_ENTERED" else 0
        )
        self._on_target_mode_changed()

    def _current_available_geometry(self):
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _set_initial_geometry(self) -> None:
        available = self._current_available_geometry()
        if available is None:
            self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
            self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
            return

        safe_width = max(560, available.width() - 24)
        safe_height = max(620, available.height() - 24)

        target_width = min(
            max(MIN_WINDOW_WIDTH, self.settings.window_width or DEFAULT_WINDOW_WIDTH),
            safe_width,
        )
        target_height = min(
            max(MIN_WINDOW_HEIGHT, self.settings.window_height or DEFAULT_WINDOW_HEIGHT),
            safe_height,
        )

        self.setMinimumWidth(min(MIN_WINDOW_WIDTH, safe_width))
        self.setMinimumHeight(min(MIN_WINDOW_HEIGHT, safe_height))
        self.resize(target_width, target_height)

        geometry = self.frameGeometry()
        geometry.moveCenter(available.center())
        self.move(geometry.topLeft())

        QTimer.singleShot(0, lambda: self._update_responsive_layout(force=True))
        QTimer.singleShot(0, lambda: self._apply_density(force=True))
        QTimer.singleShot(10, self._refresh_minimum_height)

    def _update_responsive_layout(self, force: bool = False) -> None:
        """Giữ Google Sheet đích ở trên, danh sách CSV ở ngay bên dưới.

        Bố cục này cố định ở mọi chiều rộng để thứ tự thao tác luôn rõ ràng:
        chọn bảng tính trước, sau đó chọn các file có tên quyết định tab đích.
        """
        compact = self.width() < self.COMPACT_BREAKPOINT
        if not force and self._wide_layout == compact:
            return
        self._wide_layout = compact
        self.top_grid.removeWidget(self.target_card)
        self.top_grid.removeWidget(self.files_card)

        self.target_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.files_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.top_grid.addWidget(self.target_card, 0, 0, 1, 2)
        self.top_grid.addWidget(self.files_card, 1, 0, 1, 2)
        self.top_grid.setColumnStretch(0, 1)
        self.top_grid.setColumnStretch(1, 0)

        if compact:
            self.file_table.setMinimumHeight(145)
            self.file_table.setMaximumHeight(180)
        else:
            self.file_table.setMinimumHeight(165)
            self.file_table.setMaximumHeight(220)

        self.top_container.updateGeometry()
        self.upper_content.updateGeometry()
        self.root.updateGeometry()
        QTimer.singleShot(0, self._refresh_minimum_height)

    def _apply_density(self, force: bool = False) -> None:
        available = self._current_available_geometry()
        screen_height = available.height() if available else self.height()

        if self.width() < self.COMPACT_BREAKPOINT or screen_height < 780:
            mode = "compact"
        elif self.width() >= 1250 and screen_height >= 950:
            mode = "spacious"
        else:
            mode = "regular"

        if not force and mode == self._density_mode:
            return
        self._density_mode = mode

        if mode == "compact":
            margin = (11, 8, 11, 9)
            spacing = 6
            icon_box = 31
            icon_pixmap = 16
            header_height = 60
            logo_size = 44
            header_button = 34
            self.app_subtitle_label.setVisible(self.width() >= 625)
        elif mode == "spacious":
            margin = (16, 12, 16, 14)
            spacing = 8
            icon_box = 38
            icon_pixmap = 20
            header_height = 68
            logo_size = 50
            header_button = 38
            self.app_subtitle_label.setVisible(True)
        else:
            margin = (14, 10, 14, 12)
            spacing = 7
            icon_box = 34
            icon_pixmap = 18
            header_height = 64
            logo_size = 48
            header_button = 36
            self.app_subtitle_label.setVisible(True)

        self.top_bar.setFixedHeight(header_height)
        self.logo_label.setFixedSize(logo_size, logo_size)
        self.logo_label.setPixmap(load_logo(max(36, logo_size - 8)))

        for button in (
            self.settings_button,
            self.help_button,
            self.theme_button,
        ):
            button.setFixedSize(header_button, header_button)
            button.setIconSize(QSize(max(16, header_button // 2), max(16, header_button // 2)))

        for layout in (
            self.files_card_layout,
            self.target_card_layout,
            self.action_card_layout,
            self.log_card_layout,
        ):
            layout.setContentsMargins(*margin)
            layout.setSpacing(spacing)

        icon_map = (
            (self.files_icon_label, "files"),
            (self.target_icon_label, "sheet"),
            (self.action_icon_label, "rocket"),
            (self.log_icon_label, "terminal"),
        )
        for label, icon_name in icon_map:
            label.setFixedSize(icon_box, icon_box)
            label.setPixmap(icon(icon_name).pixmap(QSize(icon_pixmap, icon_pixmap)))

        self.root.updateGeometry()
        QTimer.singleShot(0, self._refresh_minimum_height)

    def _refresh_minimum_height(self) -> None:
        available = self._current_available_geometry()
        if available is None:
            return

        layout = self.root.layout()
        if layout is not None:
            layout.activate()
        self.upper_content.updateGeometry()

        # Keep all fixed cards visible and reserve a two-line log viewport.
        body_margins = 20
        desired = (
            self.top_bar.height()
            + self.upper_content.sizeHint().height()
            + self.log_card.minimumHeight()
            + body_margins
            + 20
        )
        maximum_safe = max(620, available.height() - 16)
        self.setMinimumHeight(min(max(MIN_WINDOW_HEIGHT, desired), maximum_safe))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "top_grid"):
            self._update_responsive_layout()
            self._apply_density()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._screen_signal_connected and self.windowHandle() is not None:
            self.windowHandle().screenChanged.connect(self._on_screen_changed)
            self._screen_signal_connected = True
        QTimer.singleShot(0, self._refresh_minimum_height)

    def _on_screen_changed(self, _screen) -> None:
        self._apply_density(force=True)
        self._update_responsive_layout(force=True)
        self._refresh_minimum_height()

    def apply_theme(self, name: str) -> None:
        theme = "dark" if name == "dark" else "light"
        path = THEMES_DIR / f"{theme}.qss"
        try:
            self.setStyleSheet(path.read_text(encoding="utf-8"))
        except OSError:
            self.setStyleSheet("")
        self.settings.theme = theme
        set_button_icon(
            self.theme_button,
            "sun" if theme == "dark" else "moon",
            18,
        )
        self.theme_button.setToolTip(
            "Chuyển sang chế độ sáng"
            if theme == "dark"
            else "Chuyển sang chế độ tối"
        )

    def toggle_theme(self) -> None:
        self.apply_theme("light" if self.settings.theme == "dark" else "dark")
        self.save_settings()

    def show_settings(
        self,
        _checked: bool = False,
        *,
        initial_tab: str = "google",
    ) -> None:
        dialog = SettingsDialog(self, initial_tab=initial_tab)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()
        self.settings = self.settings_repository.load()

    def _auto_check_updates(self) -> None:
        if not self.settings.auto_check_updates:
            return
        repository = (
            self.settings.update_repository.strip()
            or DEFAULT_GITHUB_REPOSITORY.strip()
        )
        if not repository or self.update_check_worker is not None:
            return
        worker = UpdateCheckWorker(repository, self)
        self.update_check_worker = worker
        worker.completed.connect(self._on_auto_update_checked)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_auto_update_checked(
        self,
        success: bool,
        release_object: object,
        message: str,
    ) -> None:
        self.update_check_worker = None
        if not success or not isinstance(release_object, UpdateRelease):
            return
        if not is_newer_version(release_object.version, APP_VERSION):
            return
        self.append_log(
            "WARNING",
            f"Có bản cập nhật v{release_object.version}. "
            "Mở Cài đặt → Cập nhật để tải và cài đặt.",
        )
        self.settings_button.setToolTip(
            f"Có bản cập nhật v{release_object.version}"
        )

    def show_help(self) -> None:
        dialog = HelpDialog(self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()

    def choose_csv_files(self) -> None:
        start_dir = self.settings.last_csv_dir or str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn file CSV",
            start_dir,
            "CSV (*.csv);;Tất cả file (*.*)",
        )
        if paths:
            self.settings.last_csv_dir = str(Path(paths[0]).parent)
            self.add_csv_files(paths)

    def add_csv_files(self, paths: list[str]) -> None:
        remaining = MAX_CSV_FILES - len(self.file_infos)
        if remaining <= 0:
            QMessageBox.warning(
                self,
                "Quá nhiều file",
                f"Tối đa {MAX_CSV_FILES} file mỗi lần import.",
            )
            return

        errors: list[str] = []
        added = 0
        for raw_path in paths[:remaining]:
            path = str(Path(raw_path).expanduser().resolve())
            if path in self.file_infos:
                continue
            try:
                info = inspect_csv(path, require_localization_name=False)
            except CsvImportError as exc:
                errors.append(str(exc))
                continue
            self.file_infos[path] = info
            self._append_file_row(info)
            added += 1

        self.update_file_summary()
        self._update_reorder_buttons()
        if added:
            self.append_log("INFO", f"Đã thêm {added} file CSV.")
        if errors:
            QMessageBox.warning(
                self,
                "Một số file không hợp lệ",
                "\n".join(errors[:10]),
            )

    def _append_file_row(self, info: CsvFileInfo) -> None:
        row = self.file_table.rowCount()
        self.file_table.insertRow(row)
        name_item = QTableWidgetItem(info.path.name)
        name_item.setToolTip(str(info.path))
        name_item.setData(Qt.ItemDataRole.UserRole, str(info.path))
        self.file_table.setItem(row, 0, name_item)

        target_item = QTableWidgetItem("")
        self.file_table.setItem(row, 1, target_item)
        self._update_target_cell(row, info)
        self.file_table.setItem(
            row,
            2,
            QTableWidgetItem(format_size(info.size_bytes)),
        )
        self.file_table.setItem(row, 3, QTableWidgetItem(info.encoding))
        self.file_table.setItem(
            row,
            4,
            QTableWidgetItem(info.display_delimiter),
        )

    def _is_single_mode(self) -> bool:
        return self.target_mode_combo.currentIndex() == 1

    def _on_target_mode_changed(self, _index: int | None = None) -> None:
        single = self._is_single_mode()
        self.single_sheet_name_label.setVisible(single)
        self.single_sheet_name_edit.setVisible(single)
        self.target_subtitle_label.setText(
            "Chỉ file đầu tiên được nhập vào tab đã nhập bên dưới"
            if single
            else "Mỗi file được nhập vào tab suy ra từ tên file"
        )
        self._refresh_file_targets()
        self.update_file_summary()
        self.target_card.updateGeometry()
        self.upper_content.updateGeometry()
        QTimer.singleShot(0, self._refresh_minimum_height)

    def _update_target_cell(self, row: int, info: CsvFileInfo) -> None:
        item = self.file_table.item(row, 1)
        if item is None:
            item = QTableWidgetItem("")
            self.file_table.setItem(row, 1, item)

        if self._is_single_mode():
            if row == 0:
                target = self.single_sheet_name_edit.text().strip() or "(Nhập tên Sheet)"
                item.setText(target)
                item.setToolTip(f"File đầu tiên sẽ được nhập vào tab: {target}")
            else:
                item.setText("Không nhập")
                item.setToolTip(
                    "Chế độ một sheet chỉ sử dụng file nằm trên cùng trong danh sách."
                )
        else:
            target = info.target_sheet_name or "Tên file không đúng mẫu"
            item.setText(target)
            if info.target_sheet_name:
                item.setToolTip(
                    f"Google Sheet: {info.source_spreadsheet_name}\n"
                    f"Tab đích: {info.target_sheet_name}"
                )
            else:
                item.setToolTip(
                    "Chế độ nhiều sheet yêu cầu tên file dạng: "
                    "[Tên Google Sheet] - [Tên tab].csv"
                )

    def _refresh_file_targets(self, _text: str | None = None) -> None:
        for row in range(self.file_table.rowCount()):
            name_item = self.file_table.item(row, 0)
            path = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
            info = self.file_infos.get(str(path)) if path else None
            if info is not None:
                self._update_target_cell(row, info)

    def _ordered_file_paths(self) -> tuple[str, ...]:
        """Return file paths in the exact order currently shown in the table."""
        ordered: list[str] = []
        for row in range(self.file_table.rowCount()):
            item = self.file_table.item(row, 0)
            path = item.data(Qt.ItemDataRole.UserRole) if item else None
            if path and str(path) in self.file_infos:
                ordered.append(str(path))
        return tuple(ordered)

    def _swap_table_rows(self, first: int, second: int) -> None:
        if first == second:
            return
        column_count = self.file_table.columnCount()
        first_items = [self.file_table.takeItem(first, col) for col in range(column_count)]
        second_items = [self.file_table.takeItem(second, col) for col in range(column_count)]
        for column, item in enumerate(second_items):
            self.file_table.setItem(first, column, item)
        for column, item in enumerate(first_items):
            self.file_table.setItem(second, column, item)

    def move_selected_files(self, direction: int) -> None:
        """Move selected rows up/down while preserving their relative order."""
        if self.worker and self.worker.isRunning():
            return
        rows = sorted(
            {index.row() for index in self.file_table.selectionModel().selectedRows()}
        )
        if not rows or direction not in (-1, 1):
            return

        row_count = self.file_table.rowCount()
        if direction < 0:
            if rows[0] == 0:
                return
            for row in rows:
                self._swap_table_rows(row, row - 1)
            selected_rows = [row - 1 for row in rows]
        else:
            if rows[-1] >= row_count - 1:
                return
            for row in reversed(rows):
                self._swap_table_rows(row, row + 1)
            selected_rows = [row + 1 for row in rows]

        self.file_table.clearSelection()
        selection_model = self.file_table.selectionModel()
        for row in selected_rows:
            index = self.file_table.model().index(row, 0)
            selection_model.select(
                index,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        if selected_rows:
            self.file_table.setCurrentCell(selected_rows[0], 0)
        self._refresh_file_targets()
        self._update_reorder_buttons()
        self.append_log(
            "INFO",
            "Đã thay đổi thứ tự file. Chế độ một sheet luôn dùng file ở hàng đầu tiên.",
        )

    def _update_reorder_buttons(self) -> None:
        rows = sorted(
            {index.row() for index in self.file_table.selectionModel().selectedRows()}
        )
        running = bool(self.worker and self.worker.isRunning())
        self.move_up_button.setEnabled(
            bool(rows) and rows[0] > 0 and not running
        )
        self.move_down_button.setEnabled(
            bool(rows)
            and rows[-1] < self.file_table.rowCount() - 1
            and not running
        )

    def remove_selected_files(self) -> None:
        rows = sorted(
            {
                index.row()
                for index in self.file_table.selectionModel().selectedRows()
            },
            reverse=True,
        )
        for row in rows:
            item = self.file_table.item(row, 0)
            path = item.data(Qt.ItemDataRole.UserRole) if item else None
            if path:
                self.file_infos.pop(str(path), None)
            self.file_table.removeRow(row)
        self._refresh_file_targets()
        self.update_file_summary()
        self._update_reorder_buttons()

    def clear_files(self) -> None:
        self.file_infos.clear()
        self.file_table.setRowCount(0)
        self.update_file_summary()
        self._update_reorder_buttons()

    def update_file_summary(self) -> None:
        count = len(self.file_infos)
        total_size = sum(info.size_bytes for info in self.file_infos.values())
        if not count:
            detail = ""
        elif self._is_single_mode():
            detail = f" • {format_size(total_size)} • dùng file đầu tiên"
        else:
            valid_tabs = {
                info.target_sheet_name.casefold()
                for info in self.file_infos.values()
                if info.target_sheet_name
            }
            detail = f" • {format_size(total_size)} • {len(valid_tabs)} tab"
        self.file_summary_label.setText(f"{count} file{detail}")

    def open_sheet(self) -> None:
        url = self.sheet_url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Thiếu link", "Hãy nhập Link Google Sheet.")
            return
        QDesktopServices.openUrl(QUrl(url))

    def build_job(self) -> ImportJob | None:
        if not self.file_infos:
            QMessageBox.warning(
                self,
                "Chưa chọn file",
                "Hãy chọn ít nhất một file CSV.",
            )
            return None
        url = self.sheet_url_edit.text().strip()
        if "/spreadsheets/d/" not in url:
            QMessageBox.warning(
                self,
                "Link không hợp lệ",
                "Hãy nhập đúng link Google Sheet.",
            )
            return None

        single_mode = self._is_single_mode()
        if single_mode:
            try:
                sheet_name = validate_worksheet_title(
                    self.single_sheet_name_edit.text()
                )
            except CsvImportError as exc:
                QMessageBox.warning(self, "Tên Sheet không hợp lệ", str(exc))
                self.single_sheet_name_edit.setFocus()
                return None
            ordered_paths = self._ordered_file_paths()
            if not ordered_paths:
                QMessageBox.warning(self, "Chưa chọn file", "Danh sách file đang trống.")
                return None
            file_paths = (ordered_paths[0],)
        else:
            sheet_name = ""
            file_paths = self._ordered_file_paths()
            target_keys: dict[str, str] = {}
            duplicates: list[str] = []
            invalid_names: list[str] = []
            for path in file_paths:
                try:
                    info = inspect_csv(path, require_localization_name=True)
                except CsvImportError as exc:
                    invalid_names.append(str(exc))
                    continue
                key = info.target_sheet_name.casefold()
                if key in target_keys:
                    duplicates.append(
                        f"{target_keys[key]} và {info.path.name} → {info.target_sheet_name}"
                    )
                else:
                    target_keys[key] = info.path.name
            if invalid_names:
                QMessageBox.warning(
                    self,
                    "Tên file không hợp lệ",
                    "Chế độ nhiều sheet yêu cầu tên file theo mẫu "
                    "[Tên Google Sheet] - [Tên tab].csv:\n\n"
                    + "\n".join(invalid_names[:10]),
                )
                return None
            if duplicates:
                QMessageBox.warning(
                    self,
                    "Trùng tab đích",
                    "Mỗi tab chỉ được có một file trong một lượt import:\n"
                    + "\n".join(duplicates),
                )
                return None

        oauth_status = oauth_configuration_status()
        if not oauth_status["client_ready"]:
            QMessageBox.warning(
                self,
                "Chưa cấu hình Google OAuth",
                "Mở Cài đặt, chọn oauth_client.json và đăng nhập Google trước.",
            )
            self.show_settings()
            return None

        return ImportJob(
            file_paths=file_paths,
            spreadsheet_url=url,
            target_mode="single" if single_mode else "multiple",
            sheet_name=sheet_name,
            import_mode="overwrite",
            value_input_option=(
                "USER_ENTERED"
                if self.value_input_combo.currentIndex() == 1
                else "RAW"
            ),
            first_row_is_header=True,
            strict_headers=True,
            add_source_column=False,
        )

    def start_import(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        job = self.build_job()
        if job is None:
            return

        self.save_settings()
        self.log_edit.clear()
        if job.target_mode == "single":
            self.append_log(
                "INFO",
                f"Bắt đầu import file đầu tiên vào tab '{job.sheet_name}'.",
            )
        else:
            self.append_log(
                "INFO",
                f"Bắt đầu import {len(job.file_paths)} file CSV vào nhiều tab.",
            )
        self.set_running(True)

        worker = ImportWorker(job, self)
        self.worker = worker
        worker.progress_changed.connect(self.on_progress)
        worker.log_emitted.connect(self.append_log)
        worker.completed.connect(self.on_completed)
        worker.finished.connect(self.on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def stop_import(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.stop_button.setEnabled(False)
            self.progress_label.setText("Đang dừng an toàn...")
            self.append_log("INFO", "Đã yêu cầu dừng thao tác.")

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)
        self.settings_button.setEnabled(not running)
        self.add_files_button.setEnabled(not running)
        self.remove_files_button.setEnabled(not running)
        self.clear_files_button.setEnabled(not running)
        if running:
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
        else:
            self._update_reorder_buttons()
        self.sheet_url_edit.setEnabled(not running)
        self.target_mode_combo.setEnabled(not running)
        self.single_sheet_name_edit.setEnabled(not running)
        self.value_input_combo.setEnabled(not running)
        if not running:
            self.stop_button.setVisible(False)

    def on_progress(self, value: int, text: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, value)))
        self.progress_label.setText(text)

    def on_completed(self, success: bool, message: str) -> None:
        self.set_running(False)
        self.append_log("SUCCESS" if success else "FAIL", message)
        self.progress_label.setText(
            "Hoàn tất" if success else "Đã dừng / thất bại"
        )
        if success:
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "Import hoàn tất", message)
        elif "dừng" not in message.casefold():
            QMessageBox.warning(self, "Import thất bại", message)

    def on_worker_finished(self) -> None:
        self.worker = None
        if self._close_when_finished:
            self._close_when_finished = False
            self.close()

    def append_log(self, level: str, message: str) -> None:
        self.log_edit.append_entry(level, message)

    def save_settings(self) -> None:
        self.settings.sheet_url = self.sheet_url_edit.text().strip()
        self.settings.sheet_name = self.single_sheet_name_edit.text().strip()
        self.settings.target_mode = "single" if self._is_single_mode() else "multiple"
        self.settings.import_mode = "overwrite"
        self.settings.value_input_option = (
            "USER_ENTERED"
            if self.value_input_combo.currentIndex() == 1
            else "RAW"
        )
        self.settings.first_row_is_header = True
        self.settings.strict_headers = True
        self.settings.add_source_column = False
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        try:
            self.settings_repository.save(self.settings)
        except OSError as exc:
            self.append_log("FAIL", f"Không thể lưu cấu hình: {exc}")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(
            url.isLocalFile()
            and url.toLocalFile().casefold().endswith(".csv")
            for url in urls
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
            and url.toLocalFile().casefold().endswith(".csv")
        ]
        if paths:
            self.add_csv_files(paths)
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_settings()
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Đang import dữ liệu",
                "Tác vụ vẫn đang chạy. Dừng an toàn rồi đóng ứng dụng?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._close_when_finished = True
                self.worker.request_stop()
            event.ignore()
            return
        if self.update_check_worker and self.update_check_worker.isRunning():
            self.update_check_worker.request_stop()
            self.update_check_worker.wait(1200)
        event.accept()
