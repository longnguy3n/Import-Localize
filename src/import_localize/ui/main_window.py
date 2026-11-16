from __future__ import annotations

from pathlib import Path
from threading import Thread
from queue import Empty, SimpleQueue

from PySide6.QtCore import QFileSystemWatcher, QItemSelectionModel, QTimer, QUrl, Qt, QSize
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
    QDialog,
    QFrame,
    QHBoxLayout,
    QGraphicsDropShadowEffect,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
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
from import_localize.app.paths import FORMS_DIR, ICONS_DIR, IMAGES_DIR, THEMES_DIR
from import_localize.config.settings import SettingsRepository
from import_localize.models.import_job import CsvFileInfo, ImportJob
from import_localize.services.csv_service import (
    CsvImportError,
    format_size,
    inspect_csv,
)
from import_localize.services.google_service import oauth_configuration_status, preview_sheet_title
from import_localize.services.update_service import UpdateRelease, is_newer_version
from import_localize.ui.assets import icon, load_logo, set_button_icon
from import_localize.ui.csv_compare_dialog import CsvCompareDialog
from import_localize.ui.unity_locale_dialog import UnityLocaleDialog
from import_localize.ui.dialogs import HelpDialog, SettingsDialog
from import_localize.ui.ui_loader import load_ui, require_object
from import_localize.ui.widgets import BottomAlignedLogView
from import_localize.workers.export_tabs_worker import ExportTabsWorker
from import_localize.workers.import_worker import ImportWorker
from import_localize.services.desc_annotations import DescAnnotations
from import_localize.services.sheet_link import sheet_id_from_link
from import_localize.workers.update_worker import UpdateCheckWorker


from .feature_workspace import FeatureWorkspace
from .csv_sheet_page import CsvSheetPage
from .transfer_folders_card import TransferFoldersCard
from import_localize.services.transfer_files import TransferFileError, parse_csv_filename, parse_tab_code, scan_folder


class MainWindow(QMainWindow):
    """Main Import Localize window using the same visual system as SK Export."""

    COMPACT_BREAKPOINT = 690

    def __init__(self):
        super().__init__()
        self.settings_repository = SettingsRepository()
        self.settings = self.settings_repository.load()
        self.worker: ImportWorker | ExportTabsWorker | None = None
        self._active_operation = ""
        self.update_check_worker: UpdateCheckWorker | None = None
        self._sheet_annotations: dict[str, DescAnnotations] = {}
        self.file_infos: dict[str, CsvFileInfo] = {}
        self._close_when_finished = False
        self._card_sizes_restored = False
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
        if self.settings.selected_csv_files and not self.settings.upload_folder:
            self.add_csv_files(self.settings.selected_csv_files, restoring=True)
        self.refresh_transfer_folders()

        self.append_log(
            "INFO",
            "Sẵn sàng. Thêm CSV để kiểm tra, mở Unity Locale hoặc nhập lên Google Sheets.",
        )
        QTimer.singleShot(1800, self._auto_check_updates)

    def _bind_widgets(self) -> None:
        root = self.root
        target = self.target_form = load_ui(FORMS_DIR / "target_settings.ui", self)
        target.hide()

        self.top_bar = require_object(root, "topBar", QFrame)
        self.logo_label = require_object(root, "logoLabel", QLabel)
        self.app_subtitle_label = require_object(root, "appSubtitleLabel", QLabel)
        self.version_label = require_object(root, "versionLabel", QLabel)
        self.version_label.setText(f"v{APP_VERSION}")
        self.help_button = require_object(root, "helpButton", QPushButton)
        self.settings_button = require_object(root, "settingsButton", QPushButton)
        self.theme_button = require_object(root, "themeButton", QPushButton)

        self.cards_splitter = require_object(root, "cardsSplitter", QSplitter)

        self.files_card = require_object(root, "filesCard", QFrame)
        self.target_card = require_object(target, "targetCard", QFrame)
        self.action_card = require_object(root, "actionCard", QFrame)
        self.log_card = require_object(root, "logCard", QFrame)

        self.files_card_layout = require_object(root, "filesCardLayout", QVBoxLayout)
        self.target_card_layout = require_object(target, "targetCardLayout", QVBoxLayout)
        self.action_card_layout = require_object(root, "actionCardLayout", QVBoxLayout)
        self.log_card_layout = require_object(root, "logCardLayout", QVBoxLayout)

        self.files_icon_label = require_object(root, "filesIconLabel", QLabel)
        self.target_icon_label = require_object(target, "targetIconLabel", QLabel)
        self.action_icon_label = require_object(root, "actionIconLabel", QLabel)
        self.log_icon_label = require_object(root, "logIconLabel", QLabel)

        self.files_header_layout = require_object(root, "filesHeaderLayout", QHBoxLayout)
        self.target_header_layout = require_object(target, "targetHeaderLayout", QHBoxLayout)
        self.action_header_layout = require_object(root, "actionHeaderLayout", QHBoxLayout)
        self.log_header_layout = require_object(root, "logHeaderLayout", QHBoxLayout)
        self.files_title_layout = require_object(root, "filesTitleLayout", QVBoxLayout)
        self.target_title_layout = require_object(target, "targetTitleLayout", QVBoxLayout)
        self.action_title_layout = require_object(root, "actionTitleLayout", QVBoxLayout)
        self.log_title_layout = require_object(root, "logTitleLayout", QVBoxLayout)
        self.files_subtitle_label = require_object(root, "filesSubtitleLabel", QLabel)
        self.target_subtitle_label = require_object(target, "targetSubtitleLabel", QLabel)
        self.action_subtitle_label = require_object(root, "actionSubtitleLabel", QLabel)
        self.log_subtitle_label = require_object(root, "logSubtitleLabel", QLabel)

        self.compare_files_button = require_object(root, "compareFilesButton", QPushButton)
        self.file_table = require_object(root, "fileTable", QTableWidget)
        self.add_files_button = require_object(root, "addFilesButton", QPushButton)
        self.move_up_button = require_object(root, "moveUpButton", QPushButton)
        self.move_down_button = require_object(root, "moveDownButton", QPushButton)
        self.remove_files_button = require_object(
            root, "removeFilesButton", QPushButton
        )
        self.clear_files_button = require_object(root, "clearFilesButton", QPushButton)
        self.file_summary_label = require_object(root, "fileSummaryLabel", QLabel)

        self.sheet_url_edit = require_object(target, "sheetUrlEdit", QLineEdit)
        self.open_sheet_button = require_object(target, "openSheetButton", QPushButton)
        self.target_mode_combo = require_object(target, "targetModeCombo", QComboBox)
        self.single_sheet_name_label = require_object(
            target, "singleSheetNameLabel", QLabel
        )
        self.single_sheet_name_edit = require_object(
            target, "singleSheetNameEdit", QLineEdit
        )
        self.value_input_combo = require_object(target, "valueInputCombo", QComboBox)
        self.download_export_tabs_button = require_object(
            root, "downloadExportTabsButton", QPushButton
        )
        self.unity_locale_button = require_object(root, "unityLocaleButton", QPushButton)

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
        set_button_icon(self.download_export_tabs_button, "download", 16)
        set_button_icon(self.start_button, "upload", 17)
        set_button_icon(self.stop_button, "stop", 15)

        for card in (
            self.files_card,
            self.target_card,
            self.action_card,
            self.log_card,
        ):
            card.setGraphicsEffect(None)

        self._configure_card_headers()

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

        for card in (self.files_card, self.action_card, self.log_card):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.file_table.setMinimumHeight(100)
        self.file_table.setMaximumHeight(16777215)
        self.language_check_button = QPushButton("Nhận diện ngôn ngữ CSV…")
        self.language_check_button.setToolTip("Kiểm tra offline các file được chọn; nếu không chọn hàng, kiểm tra toàn bộ danh sách.")
        self.mapping_check_button = QPushButton("Kiểm tra mapping…")
        self.mapping_check_button.setToolTip("Đối chiếu CSV với mapping.json; xem file sai và đánh dấu Wrong mapping trong Desc khi xuất.")
        self._configure_workspace()
        self.workspace = FeatureWorkspace(self)
        self.workflow_frame = QFrame()
        self.workflow_frame.setObjectName("workflowFrame")
        workflow_layout = QVBoxLayout(self.workflow_frame)
        workflow_layout.setContentsMargins(1, 1, 1, 1)
        workflow_layout.setSpacing(0)
        self.cards_splitter.replaceWidget(0, self.workflow_frame)
        workflow_layout.addWidget(self.workspace, 1)
        workflow_layout.addWidget(self.action_card)
        self.action_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.csv_page = CsvSheetPage(self.files_card, self.settings.last_export_dir)
        self.csv_page.direction.setCurrentIndex(1 if self.settings.csv_sheet_direction == "download" else 0)
        csv_scroll = QScrollArea()
        csv_scroll.setFrameShape(QFrame.Shape.NoFrame)
        csv_scroll.setWidgetResizable(True)
        csv_scroll.setWidget(self.csv_page)
        self.workspace.addWidget(csv_scroll)
        self.csv_page.choose_folder.clicked.connect(self._choose_export_folder)
        self.csv_page.direction.currentIndexChanged.connect(self._csv_direction_changed)
        self._csv_direction_changed()
        self._sync_feature_controls()
        self.workspace.setMinimumHeight(72)
        self.files_card_layout.setStretch(1, 1)
        self.log_card_layout.setStretch(1, 1)
        self.action_card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_splitter.setChildrenCollapsible(False)
        self.cards_splitter.setStretchFactor(0, 4)
        self.cards_splitter.setStretchFactor(1, 1)
        self.cards_splitter.splitterMoved.connect(self._save_card_sizes)

    def _configure_workspace(self) -> None:
        """Keep tools separate from the CSV-to-Sheets task and expose its target."""
        self.app_subtitle_label.setText("CSV · Unity Locale · Google Sheets")
        self.files_subtitle_label.setText("Kéo thả CSV hoặc thêm tệp. Giữ Ctrl/Shift để chọn nhiều.")
        require_object(self.root, "filesTitleLabel", QLabel).setText("Tệp CSV")
        self.action_title_label = require_object(self.root, "actionTitleLabel", QLabel)
        require_object(self.root, "logTitleLabel", QLabel).setText("Nhật ký xử lý")
        self.action_subtitle_label.hide()
        self.log_subtitle_label.hide()
        self.add_files_button.setText("Thêm CSV…")
        self.start_button.setText("Nhập CSV lên Sheet")
        self.start_button.setProperty("primaryAction", True)
        self.stop_button.setProperty("dangerAction", True)
        self.download_export_tabs_button.setText("Tải CSV export_*…")
        self.download_export_tabs_button.setProperty("primaryAction", True)

        tools = QWidget(self.root)
        self.workspace_toolbar = tools
        tools.setObjectName("workspaceTools")
        stack = QVBoxLayout(tools)
        stack.setContentsMargins(12, 0, 12, 0)
        toolbar = QHBoxLayout()
        stack.addLayout(toolbar)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.unity_locale_button.setText("CSV ↔ Unity")
        self.unity_locale_button.setToolTip("Import / export locale.asset, ghép cặp file và xử lý key trùng.")
        self.direct_transfer_button = QPushButton("Sheet ↔ Unity")
        self.direct_transfer_button.setToolTip("Truyền trực tiếp giữa locale*.asset và các tab upload_* hoặc export_*.")
        self.direct_transfer_button.clicked.connect(self.show_direct_transfer)
        self.files_launcher = QPushButton("CSV ↔ Sheet")
        self.files_launcher.clicked.connect(self.show_files)
        self.workflow_buttons = (self.files_launcher, self.unity_locale_button, self.direct_transfer_button)
        for button in self.workflow_buttons:
            button.setCheckable(True)
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.mapping_check_button.setParent(self)
        self.mapping_check_button.hide()
        self.csv_tools_button = QToolButton(tools)
        self.csv_tools_button.setText("Kiểm tra CSV")
        self.csv_tools_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.csv_tools_button)
        menu.addAction("Kiểm tra mapping…", self.mapping_check_button.click)
        self.compare_action = menu.addAction("So sánh hai CSV…", self.compare_selected_files)
        self.language_action = menu.addAction("Nhận diện ngôn ngữ…", self.check_csv_languages)
        menu.addSeparator()
        self.clear_desc_action = menu.addAction("Bỏ tất cả dấu Desc của bản xuất", self.clear_desc_annotations)
        self.technical_columns_action = menu.addAction("Hiện cột mã hóa và phân cách")
        self.technical_columns_action.setCheckable(True)
        self.technical_columns_action.toggled.connect(self._toggle_technical_columns)
        self.csv_tools_button.setMenu(menu)
        toolbar.addWidget(self.csv_tools_button)
        self.root.layout().insertWidget(1, tools)
        # Existing buttons remain the single signal entry points for actions.
        self.compare_files_button.hide()
        self.language_check_button.setParent(self)
        self.language_check_button.hide()
        self.technical_columns_action.setChecked(bool(self.settings.ui_show_technical_columns))
        self._toggle_technical_columns(bool(self.settings.ui_show_technical_columns))

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Bảng tính"))
        self.quick_sheet_url_edit = self.sheet_url_edit
        self.target_form.findChild(QLabel, "sheetUrlLabel").hide()
        self.sheet_url_edit.setPlaceholderText("Dán link chia sẻ bảng tính từ Drive hoặc Google Sheets")
        self.sheet_url_edit.setClearButtonEnabled(True)
        self.sheet_url_edit.setAccessibleName("Link Google Sheet đích")
        target_row.addWidget(self.sheet_url_edit, 1)
        target_row.addWidget(self.open_sheet_button)
        self.target_settings_button = QPushButton("Thiết lập đích…")
        self.target_settings_button.clicked.connect(lambda: self.show_settings(initial_tab="target"))
        target_row.addWidget(self.target_settings_button)
        self.shared_files_button = QPushButton("Tệp dùng chung…")
        self.shared_files_button.setToolTip("Chọn trước các CSV upload và asset Unity cho các luồng nhập, xuất.")
        self.shared_files_button.clicked.connect(self.show_shared_files)
        stack.insertLayout(0, target_row)
        self.sheet_title_label = QLabel()
        self.sheet_title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.sheet_title_label.setWordWrap(True)
        stack.insertWidget(1, self.sheet_title_label)
        self.folder_card = TransferFoldersCard(self.settings, self.shared_files_button)
        stack.insertWidget(2, self.folder_card)
        self.folder_card.changed.connect(self.set_transfer_folder)
        self.folder_card.refresh_requested.connect(self.refresh_transfer_folders)
        self.folder_watcher = QFileSystemWatcher(self)
        self.folder_timer = QTimer(self)
        self.folder_timer.setSingleShot(True)
        self.folder_timer.setInterval(300)
        self.folder_timer.timeout.connect(self.refresh_transfer_folders)
        self.folder_watcher.directoryChanged.connect(lambda _: self.folder_timer.start())
        self.folder_refresh_pending = False
        self._title_results = SimpleQueue()
        self._lookup_running = False
        self._lookup_generation = 0
        self._title_timer = QTimer(self)
        self._title_timer.setSingleShot(True)
        self._title_timer.timeout.connect(self._lookup_title)
        self.sheet_url_edit.textChanged.connect(self._schedule_title)
        self.sheet_url_edit.returnPressed.connect(self._schedule_title)
        self._schedule_title()
        self.target_summary = QLabel()
        self.target_summary.setProperty("muted", True)
        self.target_summary.setWordWrap(True)
        self.action_pages = require_object(self.root, "actionPages", QStackedWidget)
        self.action_pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        csv_layout = require_object(self.root, "csvActionsLayout", QVBoxLayout)
        csv_layout.insertWidget(0, self.target_summary)
        self.target_mode_combo.currentIndexChanged.connect(self._update_target_summary)
        self.single_sheet_name_edit.textChanged.connect(self._update_target_summary)
        self.value_input_combo.currentIndexChanged.connect(self._update_target_summary)
        self._update_target_summary()

        self.log_toggle = QToolButton(self.log_card)
        self.log_toggle.setText("Hiện nhật ký")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.log_toggle.toggled.connect(self._toggle_log)
        self.log_header_layout.addWidget(self.log_toggle)
        self.log_toggle.setChecked(bool(self.settings.ui_log_expanded))
        self._toggle_log(self.log_toggle.isChecked())
        self.progress_bar.hide()

    @property
    def desc_annotations(self) -> DescAnnotations:
        """Keep review decisions separate for each spreadsheet during this session."""
        key = sheet_id_from_link(self.sheet_url_edit.text()) or ""
        if key not in self._sheet_annotations:
            if key and set(self._sheet_annotations) == {""}:
                # Bind an offline review to its first chosen destination.
                self._sheet_annotations[key] = self._sheet_annotations.pop("")
            else:
                self._sheet_annotations[key] = DescAnnotations()
        return self._sheet_annotations[key]

    def _refresh_desc_count(self):
        key = sheet_id_from_link(self.sheet_url_edit.text()) or ""
        marks = self._sheet_annotations.get(key)
        if marks is None and set(self._sheet_annotations) == {""}:
            marks = self._sheet_annotations[""]
        count = len(marks) if marks else 0
        self.clear_desc_action.setEnabled(bool(count))
        self.csv_tools_button.setText(f"Kiểm tra · {count} dấu Desc" if count else "Kiểm tra CSV")
        self.clear_desc_action.setToolTip(f"{count} cặp key/ngôn ngữ đã đánh dấu để xuất")

    def clear_desc_annotations(self):
        self.desc_annotations.clear()
        self._invalidate_export_previews()
        for page in self.workspace.pages:
            refresh = getattr(page, "refresh_desc_marks", None)
            if refresh:
                refresh()
        self._refresh_desc_count()

    def _invalidate_export_previews(self):
        for page in self.workspace.pages:
            if getattr(page, "plan", None) is not None and (
                getattr(page, "direction", None) == "upload" or
                (isinstance(page, UnityLocaleDialog) and not page.importing())
            ):
                page.invalidate()

    def _schedule_title(self, *_args):
        self._lookup_generation += 1
        if hasattr(self, "workspace"):
            url = self.sheet_url_edit.text().strip()
            self.settings.sheet_url = url
            for page in self.workspace.pages:
                update_context = getattr(page, "set_sheet_context", None)
                if update_context:
                    update_context(url, self.desc_annotations)
        self._refresh_desc_count()
        spreadsheet_id = sheet_id_from_link(self.sheet_url_edit.text())
        valid = spreadsheet_id is not None
        self.open_sheet_button.setEnabled(valid)
        self.sheet_title_label.setText("Đang đọc tên bảng tính…" if valid else "Link Google Sheet chưa hợp lệ.")
        self.sheet_title_label.setVisible(bool(self.sheet_url_edit.text().strip()))
        self.sheet_title_label.setToolTip("")
        self._title_timer.start(350)

    def _lookup_title(self):
        if self._lookup_running:
            try:
                generation, title, error = self._title_results.get_nowait()
            except Empty:
                self._title_timer.start(100)
                return
            self._lookup_running = False
            if generation == self._lookup_generation:
                self.sheet_title_label.setToolTip(error)
                self.sheet_title_label.setText("Tên bảng tính: " + title if title else "Chưa đọc được tên bảng tính. Kiểm tra đăng nhập, quyền truy cập và kết nối.")
                return
        if not self.open_sheet_button.isEnabled():
            return
        generation = self._lookup_generation
        url = self.sheet_url_edit.text().strip()
        results = self._title_results

        def lookup():
            try:
                title = preview_sheet_title(url)
            except Exception as exc:
                results.put((generation, "", str(exc)))
            else:
                results.put((generation, title, ""))

        self._lookup_running = True
        Thread(target=lookup, daemon=True).start()
        self._title_timer.start(100)

    def _toggle_technical_columns(self, visible: bool) -> None:
        self.settings.ui_show_technical_columns = visible
        for column in (3, 4):
            self.file_table.setColumnHidden(column, not visible)

    def _update_target_summary(self, *_args) -> None:
        if hasattr(self, "csv_page") and self.csv_page.direction.currentData() == "download":
            self.target_summary.setText("Mỗi tab export_* được lưu thành một file CSV.")
            return
        mode = (f"Một tab: {self.single_sheet_name_edit.text().strip() or 'chưa đặt tên'}"
                if self._is_single_mode() else "Mỗi CSV → một tab theo tên file")
        self.target_summary.setText(mode + " · Ghi đè nội dung tab đích")

    def _toggle_log(self, expanded: bool) -> None:
        self.settings.ui_log_expanded = expanded
        self.log_toggle.setText("Thu gọn nhật ký" if expanded else "Hiện nhật ký")
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.log_placeholder.setVisible(expanded)
        self.clear_log_button.setVisible(expanded)
        self.log_card.setMaximumHeight(16777215 if expanded else 64)
        self.log_card.setMinimumHeight(140 if expanded else 64)
        if expanded:
            sizes = self.cards_splitter.sizes()
            if len(sizes) == 2:
                self.cards_splitter.setSizes([max(220, sum(sizes) - 160), 160])
        QTimer.singleShot(0, self._refresh_minimum_height)

    def _configure_card_headers(self) -> None:
        """Cho phép phần mô tả dưới tiêu đề card co giãn theo bề ngang cửa sổ."""
        for subtitle in (
            self.files_subtitle_label,
            self.target_subtitle_label,
            self.action_subtitle_label,
            self.log_subtitle_label,
        ):
            subtitle.setWordWrap(True)
            subtitle.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )

        # Kéo rộng phần title/subtitle thay vì giữ kích thước theo sizeHint.
        self.files_header_layout.setStretch(1, 1)
        self.files_header_layout.setStretch(2, 1)
        self.target_header_layout.setStretch(1, 1)
        self.action_header_layout.setStretch(1, 1)
        self.log_header_layout.setStretch(1, 1)

        self.file_summary_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )

    def _connect_signals(self) -> None:
        self.language_check_button.clicked.connect(self.check_csv_languages)
        self.mapping_check_button.clicked.connect(self.check_mapping)
        self.compare_files_button.clicked.connect(self.compare_selected_files)
        self.unity_locale_button.clicked.connect(self.show_unity_locale)
        self.add_files_button.clicked.connect(self.choose_csv_files)
        self.move_up_button.clicked.connect(lambda: self.move_selected_files(-1))
        self.move_down_button.clicked.connect(lambda: self.move_selected_files(1))
        self.remove_files_button.clicked.connect(self.remove_selected_files)
        self.clear_files_button.clicked.connect(self.clear_files)
        self.open_sheet_button.clicked.connect(self.open_sheet)
        self.start_button.clicked.connect(self.start_import)
        self.download_export_tabs_button.clicked.connect(
            self.start_download_export_tabs
        )
        self.stop_button.clicked.connect(self.stop_current_action)
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
        self._move_up_shortcut = QShortcut(QKeySequence("Alt+Up"), self.files_card)
        self._move_up_shortcut.activated.connect(
            lambda: self.move_selected_files(-1)
        )
        self._move_down_shortcut = QShortcut(QKeySequence("Alt+Down"), self.files_card)
        self._move_down_shortcut.activated.connect(
            lambda: self.move_selected_files(1)
        )
        self._add_files_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        self._add_files_shortcut.activated.connect(self.add_files_from_main)
        self.add_files_button.setToolTip("Thêm file CSV (Ctrl+O); cũng có thể kéo thả file vào cửa sổ.")
        self._target_shortcut = QShortcut(QKeySequence("Ctrl+L"), self.quick_sheet_url_edit)
        self._target_shortcut.activated.connect(self.quick_sheet_url_edit.setFocus)
        self._help_shortcut = QShortcut(QKeySequence("F1"), self)
        self._help_shortcut.activated.connect(self.show_help)
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

        QTimer.singleShot(0, lambda: self._apply_density(force=True))
        QTimer.singleShot(10, self._refresh_minimum_height)

    def _restore_card_sizes(self) -> None:
        if self._card_sizes_restored:
            return
        self._refresh_minimum_height()
        sizes = self.settings.card_sizes
        if not (isinstance(sizes, list) and len(sizes) in (2, 3)
                and all(type(value) is int and 0 < value < 100000 for value in sizes)):
            sizes = [610, 240]
        elif len(sizes) == 3:
            content, actions, log = sizes
            sizes = [(450 if content <= 40 else content) + actions, log]
        self.cards_splitter.setSizes(sizes)
        self._card_sizes_restored = True

    def _save_card_sizes(self, *_args) -> None:
        if self._card_sizes_restored:
            self.save_settings()

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
        cards = (self.action_card, self.log_card)
        for card, floor in zip(cards, (0, 140)):
            if card is self.log_card and not self.log_toggle.isChecked():
                card.setMinimumHeight(64)
                continue
            card.setMinimumHeight(max(
                floor, card.layout().minimumSize().height(),
                card.layout().minimumHeightForWidth(card.width()),
            ))
        desired = (self.top_bar.height() + self.workspace.minimumHeight() + sum(card.minimumHeight() for card in cards)
                   + 2 * self.cards_splitter.handleWidth() + 24)
        self.setMinimumHeight(max(620, desired))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "cards_splitter"):
            self._apply_density()
            QTimer.singleShot(0, self._refresh_minimum_height)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._screen_signal_connected and self.windowHandle() is not None:
            self.windowHandle().screenChanged.connect(self._on_screen_changed)
            self._screen_signal_connected = True
        QTimer.singleShot(0, self._restore_card_sizes)

    def _on_screen_changed(self, _screen) -> None:
        self._apply_density(force=True)
        self._refresh_minimum_height()

    def apply_theme(self, name: str) -> None:
        theme = "dark" if name == "dark" else "light"
        path = THEMES_DIR / f"{theme}.qss"
        try:
            stylesheet = path.read_text(encoding="utf-8")
            combo_arrow = (ICONS_DIR / "chevron-down.svg").resolve().as_posix()
            stylesheet = stylesheet.replace("__ICON_CHEVRON_DOWN__", combo_arrow)
            self.setStyleSheet(stylesheet)
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
        initial_tab: str = "target",
    ) -> None:
        if not self.settings_button.isEnabled():
            return
        self.save_settings()
        previous_input_option = self.settings.value_input_option
        dialog = SettingsDialog(self, initial_tab=initial_tab, target_form=self.target_form,
                                settings=self.settings, repository=self.settings_repository)
        dialog.setStyleSheet(self.styleSheet())
        try:
            dialog.exec()
        finally:
            self.target_form.hide()
            self.target_form.setParent(self)
        self.save_settings()
        for page in self.workspace.pages:
            direction = getattr(page, "direction", None)
            if direction in ("upload", "download") and page.plan is not None:
                if dialog.google_session_changed or (
                    direction == "upload" and previous_input_option != self.settings.value_input_option
                ):
                    page.invalidate()
        dialog.deleteLater()
        self._schedule_title()

    def show_files(self):
        left = self.workspace.leave_features()
        self._sync_feature_controls()
        return left

    def _sync_action_title(self):
        pages = self.workspace.pages
        self.action_title_label.setText(pages[-1].windowTitle() if pages else self.csv_page.direction.currentText())

    def _csv_direction_changed(self):
        self.settings.csv_sheet_direction = self.csv_page.direction.currentData()
        downloading = self.settings.csv_sheet_direction == "download"
        self.download_export_tabs_button.setVisible(downloading)
        self.start_button.setVisible(not downloading)
        self.progress_label.setText("Sẵn sàng")
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        self._update_target_summary()
        self._sync_action_title()

    def _sync_shared_controls(self, starting=False):
        editable = not starting and self.worker is None and all(page.worker is None for page in self.workspace.pages)
        for widget in (self.quick_sheet_url_edit, self.target_settings_button, self.settings_button,
                       self.shared_files_button, self.csv_tools_button, self.folder_card):
            widget.setEnabled(editable)
        if editable and self.folder_refresh_pending:
            self.folder_timer.start()

    def _sync_feature_controls(self):
        self._sync_action_title()
        self._sync_shared_controls()
        base = self.workspace.pages[0] if self.workspace.pages else None
        if hasattr(base, "direction"):
            active = self.direct_transfer_button
        elif isinstance(base, UnityLocaleDialog):
            active = self.unity_locale_button
        else:
            active = self.files_launcher
        for button in self.workflow_buttons:
            button.setChecked(button is active)
            button.setProperty("primaryAction", button is active)
            button.style().unpolish(button)
            button.style().polish(button)
        self._refresh_desc_count()

    def show_direct_transfer(self):
        if self.workspace.pages and hasattr(self.workspace.pages[0], "direction"):
            self.workspace.leave_features(keep=1)
            self._sync_feature_controls()
            return
        if not self.show_files():
            return
        from .direct_sheet_dialog import DirectSheetDialog
        self.save_settings()
        direction = "download" if self.settings.direct_direction == "download" else "upload"
        dialog = DirectSheetDialog(self.settings, direction, self, annotations=self.desc_annotations)
        dialog.sheet.hide()
        dialog.close_button.hide()
        self.workspace.add_feature(dialog)

    def show_unity_locale(self) -> None:
        if self.workspace.pages and isinstance(self.workspace.pages[0], UnityLocaleDialog):
            self.workspace.leave_features(keep=1)
            self._sync_feature_controls()
            return
        if not self.show_files():
            return
        self.save_settings()
        dialog = UnityLocaleDialog(self.settings, parent=self, annotations=self.desc_annotations)
        for role, (paths, issues) in self.folder_card.results.items():
            folder = getattr(self.settings, role + "_folder")
            if folder:
                dialog.set_folder_files(role, paths if not issues else (), folder, issues)
        dialog.direct_button.hide()
        dialog.close_button.hide()
        self.workspace.add_feature(dialog)

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

    def add_files_from_main(self):
        if self.files_card.isVisible() and not self.settings.upload_folder:
            self.add_files_button.click()
        else:
            self.shared_files_button.click()

    def show_shared_files(self) -> None:
        from .shared_files_dialog import SharedFilesDialog

        if self.worker or any(getattr(page, "worker", None) for page in self.workspace.pages):
            self.statusBar().showMessage("Chờ tác vụ hoàn tất để đổi các tệp dùng chung.", 4500)
            return
        dialog = SharedFilesDialog(self._ordered_file_paths(), self.settings.unity_asset_files, self.settings, self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            if dialog.csv_infos is not None and not self.settings.upload_folder:
                self.file_table.setRowCount(0)
                self.file_infos = {str(info.path): info for info in dialog.csv_infos}
                for info in dialog.csv_infos:
                    self._append_file_row(info)
                self.update_file_summary()
                self._update_reorder_buttons()
            self.settings.last_csv_dir = dialog.csv_dir
            self.settings.unity_locale_dir = dialog.asset_dir
            assets = [Path(p) for p in self.settings.unity_asset_files] if self.settings.unity_folder else dialog.asset_list.paths()
            if not self.settings.unity_folder:
                self.settings.unity_asset_files = [str(p) for p in assets]
            for page in self.workspace.pages:
                if isinstance(page, UnityLocaleDialog):
                    if not self.settings.upload_folder:
                        page.set_upload_paths(dialog.csv_list.paths())
                    if not self.settings.unity_folder and page.asset_paths != assets:
                        page.set_assets(assets)
                elif getattr(page, "direction", None) in ("upload", "download") and page.paths != assets:
                    page.paths = list(assets)
                    page.invalidate()
            self.save_settings()
        finally:
            dialog.deleteLater()

    def set_transfer_folder(self, role, folder):
        setattr(self.settings, role + "_folder", folder)
        if role == "export":
            self.settings.last_export_dir = folder
            self.csv_page.folder.setText(folder)
        self._scan_transfer_folder(role, force=True)
        self._watch_transfer_folders()
        self.save_settings()

    def _watch_transfer_folders(self):
        wanted = {Path(folder).resolve().as_posix() for role in self.folder_card.roles
                  if (folder := getattr(self.settings, role + "_folder")) and Path(folder).is_dir()}
        watched = set(self.folder_watcher.directories())
        if watched - wanted:
            self.folder_watcher.removePaths(list(watched - wanted))
        if wanted - watched:
            self.folder_watcher.addPaths(list(wanted - watched))

    def refresh_transfer_folders(self):
        if not self.folder_card.isEnabled():
            self.folder_refresh_pending = True
            return
        self.folder_refresh_pending = False
        changed = False
        for role in self.folder_card.roles:
            if getattr(self.settings, role + "_folder"):
                changed |= self._scan_transfer_folder(role)
        self._watch_transfer_folders()
        if changed:
            self.save_settings()

    def _scan_transfer_folder(self, role, force=False):
        folder = getattr(self.settings, role + "_folder")
        paths, issues = (), ()
        if folder:
            result = scan_folder(folder, role)
            paths, issues = tuple(result.paths), tuple(result.issues)
        previous = self.folder_card.results[role]
        selected = [] if issues else list(paths)
        if role == "upload":
            if len(selected) > MAX_CSV_FILES:
                issues += (f"Chọn thư mục có tối đa {MAX_CSV_FILES} file upload.",)
                selected = []
            try:
                infos = [inspect_csv(path) for path in selected]
            except (CsvImportError, OSError) as exc:
                issues += (str(exc),)
                infos, selected = [], []
            if force or list(self.file_infos.values()) != infos:
                self.file_table.setRowCount(0)
                self.file_infos = {str(info.path): info for info in infos}
                for info in infos:
                    self._append_file_row(info)
                self.update_file_summary()
            self.settings.selected_csv_files = [str(p) for p in selected]
            self.settings.unity_export_csv_files = list(self.settings.selected_csv_files)
            self.settings.unity_export_dir = folder
            self._update_reorder_buttons()
        elif role == "unity":
            self.settings.unity_asset_files = [str(p) for p in selected]
        else:
            self.settings.unity_import_csv_files = [str(p) for p in selected]
            self.csv_page.folder.setText(folder)
        self.folder_card.set_result(role, paths, issues)
        if force or previous != (paths, issues):
            for page in self.workspace.pages:
                if isinstance(page, UnityLocaleDialog):
                    page.set_folder_files(role, selected, folder, issues)
                elif role == "unity" and hasattr(page, "direction"):
                    page.set_folder_files(selected, folder)
            return True
        return False

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

    def add_csv_files(self, paths: list[str], *, restoring: bool = False) -> None:
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
            except (CsvImportError, OSError) as exc:
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
            if restoring:
                self.append_log("FAIL", "Không thể khôi phục một số CSV đã chọn:\n" + "\n".join(errors[:10]))
            else:
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
            "Nhập file upload có cùng mã ngôn ngữ với tab bên dưới"
            if single
            else "Mỗi file được nhập vào tab suy ra từ tên file"
        )
        self._refresh_file_targets()
        self.update_file_summary()
        self.target_card.updateGeometry()
        QTimer.singleShot(0, self._refresh_minimum_height)

    def _update_target_cell(self, row: int, info: CsvFileInfo) -> None:
        item = self.file_table.item(row, 1)
        if item is None:
            item = QTableWidgetItem("")
            self.file_table.setItem(row, 1, item)

        try:
            prefix, code = parse_csv_filename(info.path, "upload")
            tab = info.path.stem.rsplit(" - ", 1)[-1]
            if self._is_single_mode():
                tab = self.single_sheet_name_edit.text().strip()
                if code != parse_tab_code(tab, "upload"):
                    tab = "Không nhập"
            item.setText(tab)
            item.setToolTip(f"{prefix or 'Bảng tính đã chọn'} · {tab}")
        except TransferFileError as exc:
            item.setText("Kiểm tra tên")
            item.setToolTip(str(exc))

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
        if self.settings.upload_folder or (self.worker and self.worker.isRunning()):
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
            "Đã thay đổi thứ tự file.",
        )

    def _update_reorder_buttons(self) -> None:
        rows = sorted(
            {index.row() for index in self.file_table.selectionModel().selectedRows()}
        )
        running = bool(self.worker and self.worker.isRunning())
        managed = bool(self.settings.upload_folder)
        self.files_subtitle_label.setText(
            "Tự chọn theo mã ngôn ngữ trong thư mục CSV upload." if managed else
            "Kéo thả CSV hoặc thêm tệp. Giữ Ctrl/Shift để chọn nhiều."
        )
        for widget in (self.add_files_button, self.remove_files_button, self.clear_files_button,
                       self.move_up_button, self.move_down_button):
            widget.setVisible(not managed)
        self.language_check_button.setEnabled(bool(self.file_infos) and not running)
        self.compare_files_button.setEnabled(len(rows) == 2 and not running)
        self.remove_files_button.setEnabled(bool(rows) and not running)
        self.clear_files_button.setEnabled(bool(self.file_infos) and not running)
        if managed:
            for widget in (self.add_files_button, self.remove_files_button, self.clear_files_button):
                widget.setEnabled(False)
        else:
            self.add_files_button.setEnabled(not running)
        self.start_button.setEnabled(bool(self.file_infos) and not running)
        self.move_up_button.setEnabled(
            bool(rows) and rows[0] > 0 and not running
        )
        self.move_down_button.setEnabled(
            bool(rows)
            and rows[-1] < self.file_table.rowCount() - 1
            and not running
        )

    def _csv_audit_available(self):
        if self.worker is not None or any(page.worker is not None for page in self.workspace.pages):
            self.statusBar().showMessage("Đợi tác vụ hiện tại hoàn tất trước khi mở kiểm tra CSV.", 4500)
            return False
        return True

    def _leave_previous_audit(self):
        pages = self.workspace.pages
        keep_workflow = bool(pages) and (isinstance(pages[0], UnityLocaleDialog) or hasattr(pages[0], "direction"))
        return self.workspace.leave_features(keep=1 if keep_workflow else 0)

    def check_csv_languages(self) -> None:
        if not self._csv_audit_available() or not self._leave_previous_audit():
            return
        from .csv_language_dialog import CsvLanguageDialog
        rows = sorted(index.row() for index in self.file_table.selectionModel().selectedRows())
        paths = [self.file_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                 for row in (rows or range(self.file_table.rowCount()))]
        dialog = CsvLanguageDialog(paths, self, annotations=self.desc_annotations)
        dialog.desc_marks_changed.connect(self._invalidate_export_previews)
        self.workspace.add_feature(dialog)

    def check_mapping(self) -> None:
        if not self._csv_audit_available() or not self._leave_previous_audit():
            return
        from .mapping_dialog import MappingDialog
        self.save_settings()
        paths = [self.file_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                 for row in range(self.file_table.rowCount())]
        dialog = MappingDialog(self.settings, paths, self, annotations=self.desc_annotations)
        dialog.desc_marks_changed.connect(self._invalidate_export_previews)
        self.workspace.add_feature(dialog)

    def compare_selected_files(self) -> None:
        if not self._csv_audit_available():
            return
        rows = sorted(index.row() for index in self.file_table.selectionModel().selectedRows())
        if len(rows) == 2 or self.file_table.rowCount() == 2:
            selected = rows if len(rows) == 2 else range(2)
            paths = [str(self.file_table.item(row, 0).data(Qt.ItemDataRole.UserRole)) for row in selected]
        else:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Chọn hai tệp CSV để so sánh", self.settings.last_csv_dir, "CSV (*.csv)"
            )
            if not paths:
                return
            if len(paths) != 2:
                self.statusBar().showMessage("Cần chọn đúng hai tệp CSV để so sánh.", 4500)
                return
        if not self._leave_previous_audit():
            return
        dialog = CsvCompareDialog(*paths, self)
        self.workspace.add_feature(dialog)

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
            detail = f" • {format_size(total_size)} • ghép theo mã tab"
        else:
            valid_tabs = {self.file_table.item(row, 1).text().casefold() for row in range(self.file_table.rowCount())
                          if self.file_table.item(row, 1).text() != "Kiểm tra tên"}
            detail = f" • {format_size(total_size)} • {len(valid_tabs)} tab"
        self.file_summary_label.setText(f"{count} file{detail}")
        self.files_launcher.setToolTip(f"{count} file CSV đã chọn")

    def open_sheet(self) -> None:
        url = self.sheet_url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Thiếu link", "Dán link vào ô Sheet đích trên màn hình chính.")
            return
        QDesktopServices.openUrl(QUrl(url))

    def build_job(self) -> ImportJob | None:
        if self.settings.upload_folder:
            self._scan_transfer_folder("upload")
            issues = self.folder_card.results["upload"][1]
            if issues:
                QMessageBox.warning(self, "Kiểm tra thư mục upload", "\n".join(issues))
                return None
        if not self.file_infos:
            QMessageBox.warning(
                self,
                "Chưa chọn file",
                "Hãy chọn ít nhất một file CSV.",
            )
            return None
        url = self.sheet_url_edit.text().strip()
        if not sheet_id_from_link(url):
            QMessageBox.warning(
                self,
                "Link không hợp lệ",
                "Dán link Google Sheet hợp lệ vào ô Sheet đích trên màn hình chính.",
            )
            return None

        single_mode = self._is_single_mode()
        sheet_name = self.single_sheet_name_edit.text().strip() if single_mode else ""
        try:
            wanted = parse_tab_code(sheet_name, "upload") if single_mode else None
            by_code = {}
            for path in self._ordered_file_paths():
                _, code = parse_csv_filename(path, "upload")
                if wanted and code != wanted:
                    continue
                if code in by_code:
                    raise TransferFileError(f"Hai file cùng mã {code}: {Path(by_code[code]).name}, {Path(path).name}")
                by_code[code] = path
            if not by_code:
                raise TransferFileError(f"Không có file upload khớp với tab {sheet_name}.")
            file_paths = tuple(by_code.values())
        except TransferFileError as exc:
            QMessageBox.warning(self, "Kiểm tra nguồn và tab đích", str(exc))
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
            upload_folder=self.settings.upload_folder,
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
        if not self.show_files():
            return
        if self.worker and self.worker.isRunning():
            return
        job = self.build_job()
        if job is None:
            return

        self.save_settings()
        self._begin_log_section("IMPORT CSV")
        if job.target_mode == "single":
            self.append_log(
                "INFO",
                f"Nhập {Path(job.file_paths[0]).name} vào tab '{job.sheet_name}'.",
            )
        else:
            self.append_log(
                "INFO",
                f"Bắt đầu import {len(job.file_paths)} file CSV vào nhiều tab.",
            )
        self._active_operation = "import"
        self.set_running(True)

        worker = ImportWorker(job, self, annotations=self.desc_annotations.snapshot())
        self.worker = worker
        worker.progress_changed.connect(self.on_progress)
        worker.log_emitted.connect(self.append_log)
        worker.completed.connect(self.on_completed)
        worker.finished.connect(self.on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _validate_sheet_action(self) -> str | None:
        url = self.sheet_url_edit.text().strip()
        if not sheet_id_from_link(url):
            QMessageBox.warning(
                self,
                "Link không hợp lệ",
                "Dán link Google Sheet hợp lệ vào ô Sheet đích trên màn hình chính.",
            )
            self.sheet_url_edit.setFocus()
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
        return url

    def _choose_export_folder(self) -> str:
        initial_dir = self.settings.last_export_dir or str(Path.home())
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục lưu các tab export_*",
            initial_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if output_dir:
            self.set_transfer_folder("export", output_dir)
        return output_dir

    def start_download_export_tabs(self) -> None:
        if not self.show_files() or (self.worker and self.worker.isRunning()):
            return
        url = self._validate_sheet_action()
        if not url:
            return
        output_dir = self.csv_page.folder.text()
        if not self.settings.export_folder and (not output_dir or not Path(output_dir).is_dir()):
            output_dir = self._choose_export_folder()
        if not output_dir:
            return
        if self.settings.export_folder:
            self._scan_transfer_folder("export")
            issues = self.folder_card.results["export"][1]
            if issues:
                QMessageBox.warning(self, "Kiểm tra thư mục export", "\n".join(issues))
                return
        self.save_settings()
        self._begin_log_section("TẢI TAB EXPORT_*")
        self.append_log(
            "INFO",
            "Bắt đầu tải toàn bộ tab có tên bắt đầu bằng 'export_' dưới dạng "
            "CSV trực tiếp từ bộ máy export của Google Sheets.",
        )
        self.append_log("INFO", f"Thư mục lưu: {output_dir}")
        self._active_operation = "download"
        self.set_running(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Đang chuẩn bị tải các tab export_*")

        worker = ExportTabsWorker(url, output_dir, self, annotations=self.desc_annotations.snapshot())
        self.worker = worker
        worker.progress_changed.connect(self.on_progress)
        worker.log_emitted.connect(self.append_log)
        worker.completed.connect(self.on_completed)
        worker.finished.connect(self.on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def stop_current_action(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.stop_button.setEnabled(False)
            self.progress_label.setText("Đang dừng... (tối đa vài giây nếu Google đang trả dữ liệu)")
            self.append_log("INFO", "Đã yêu cầu dừng ngay. Nếu đang có request Google trên mạng, app sẽ cắt ở timeout ngắn gần nhất.")

    def set_running(self, running: bool) -> None:
        self.progress_bar.setVisible(running or self.progress_bar.value() > 0)
        self._sync_shared_controls(starting=running)
        self.csv_page.direction.setEnabled(not running)
        self.csv_page.choose_folder.setEnabled(not running)
        downloading = self.csv_page.direction.currentData() == "download"
        for button, active in ((self.start_button, not downloading), (self.download_export_tabs_button, downloading)):
            button.setEnabled(not running)
            button.setVisible(not running and active)
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)
        self.unity_locale_button.setEnabled(not running)
        self.direct_transfer_button.setEnabled(not running)
        self.mapping_check_button.setEnabled(not running)
        self.files_launcher.setEnabled(not running)
        self.add_files_button.setEnabled(not running)
        self.remove_files_button.setEnabled(not running)
        self.clear_files_button.setEnabled(not running)
        if running:
            self.language_check_button.setEnabled(False)
            self.compare_files_button.setEnabled(False)
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
        else:
            self._update_reorder_buttons()
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
        operation = self._active_operation
        self.set_running(False)
        self.append_log("SUCCESS" if success else "FAIL", message)
        self.progress_label.setText(
            "Hoàn tất" if success else "Đã dừng / thất bại"
        )
        if success:
            self.progress_bar.setValue(100)
            if operation == "download":
                title = "Tải CSV hoàn tất"
            else:
                title = "Import hoàn tất"
            QMessageBox.information(self, title, message)
        elif "dừng" not in message.casefold():
            if operation == "download":
                title = "Tải CSV thất bại"
            else:
                title = "Import thất bại"
            QMessageBox.warning(self, title, message)
        self._active_operation = ""

    def on_worker_finished(self) -> None:
        self.worker = None
        self._sync_shared_controls()
        self._update_reorder_buttons()
        if self._close_when_finished:
            self._close_when_finished = False
            self.close()

    def _begin_log_section(self, title: str) -> None:
        """Phân tách các tác vụ mà không xóa lịch sử log trong phiên hiện tại."""
        self.append_log("INFO", f"──────── {title} ────────")

    def append_log(self, level: str, message: str) -> None:
        self.log_edit.append_entry(level, message)
        if level.upper() in {"FAIL", "ERROR"}:
            self.log_toggle.setChecked(True)

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
        self.settings.selected_csv_files = [
            str(self.file_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(self.file_table.rowCount())]
        if self._card_sizes_restored:
            self.settings.card_sizes = self.cards_splitter.sizes()
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        try:
            self.settings_repository.save(self.settings)
        except OSError as exc:
            self.append_log("FAIL", f"Không thể lưu cấu hình: {exc}")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if not self.settings.upload_folder and self.shared_files_button.isEnabled() and any(
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
        if paths and self.shared_files_button.isEnabled() and not self.settings.upload_folder:
            count = len(self.file_infos)
            self.add_csv_files(paths)
            added = len(self.file_infos) - count
            if added:
                for page in self.workspace.pages:
                    if isinstance(page, UnityLocaleDialog):
                        page.set_upload_paths([Path(p) for p in self._ordered_file_paths()])
                self.save_settings()
                self.statusBar().showMessage(f"Đã thêm {added} file vào danh sách CSV upload dùng chung.", 4500)
            event.acceptProposedAction()
        else:
            event.ignore()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.show_files():
            event.ignore()
            return
        self.save_settings()
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Tác vụ đang chạy",
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
        self.folder_timer.stop()
        watched = self.folder_watcher.directories()
        if watched:
            self.folder_watcher.removePaths(watched)
        event.accept()
