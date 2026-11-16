from __future__ import annotations

from pathlib import Path
from threading import Thread
from queue import Empty, SimpleQueue

from PySide6.QtCore import QEvent, QFileSystemWatcher, QTimer, QUrl, Qt, QSize
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QKeySequence,
    QShortcut,
    QDesktopServices,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QGraphicsDropShadowEffect,
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
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)
from import_localize.app.paths import FORMS_DIR, ICONS_DIR, IMAGES_DIR, THEMES_DIR
from import_localize.config.settings import SettingsRepository
from import_localize.models.import_job import CsvFileInfo, ImportJob
from import_localize.services.csv_service import (
    CsvImportError,
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
from .transfer_folders_card import TransferFoldersCard
from import_localize.services.transfer_files import scan_folder


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
        self._size_key = None
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._refresh_minimum_height)
        self._density_mode: str | None = None
        self._screen_signal_connected = False

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setWindowIcon(QIcon(str(IMAGES_DIR / "import_localize_logo.svg")))

        self.root = load_ui(FORMS_DIR / "main_window.ui", self)
        self.window_scroll = QScrollArea()
        self.window_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.window_scroll.setWidgetResizable(True)
        self.window_scroll.setWidget(self.root)
        self.setCentralWidget(self.window_scroll)
        self._bind_widgets()
        self._configure_widgets()
        self._connect_signals()
        self._restore_settings()
        self.apply_theme(self.settings.theme)
        self._set_initial_geometry()
        self.refresh_transfer_folders()

        self.append_log(
            "INFO",
            "Sẵn sàng. Chọn thư mục truyền dữ liệu và chiều chuyển.",
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

        self.target_card = require_object(target, "targetCard", QFrame)
        self.action_card = require_object(root, "actionCard", QFrame)
        self.log_card = require_object(root, "logCard", QFrame)

        self.target_card_layout = require_object(target, "targetCardLayout", QVBoxLayout)
        self.action_card_layout = require_object(root, "actionCardLayout", QVBoxLayout)
        self.log_card_layout = require_object(root, "logCardLayout", QVBoxLayout)

        self.target_icon_label = require_object(target, "targetIconLabel", QLabel)
        self.action_icon_label = require_object(root, "actionIconLabel", QLabel)
        self.log_icon_label = require_object(root, "logIconLabel", QLabel)

        self.target_header_layout = require_object(target, "targetHeaderLayout", QHBoxLayout)
        self.action_header_layout = require_object(root, "actionHeaderLayout", QHBoxLayout)
        self.log_header_layout = require_object(root, "logHeaderLayout", QHBoxLayout)
        self.target_title_layout = require_object(target, "targetTitleLayout", QVBoxLayout)
        self.action_title_layout = require_object(root, "actionTitleLayout", QVBoxLayout)
        self.log_title_layout = require_object(root, "logTitleLayout", QVBoxLayout)
        self.target_subtitle_label = require_object(target, "targetSubtitleLabel", QLabel)
        self.action_subtitle_label = require_object(root, "actionSubtitleLabel", QLabel)
        self.log_subtitle_label = require_object(root, "logSubtitleLabel", QLabel)

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
        self.target_icon_label.setPixmap(icon("sheet").pixmap(QSize(18, 18)))
        self.action_icon_label.setPixmap(icon("rocket").pixmap(QSize(18, 18)))
        self.log_icon_label.setPixmap(icon("terminal").pixmap(QSize(18, 18)))

        set_button_icon(self.settings_button, "settings", 18)
        set_button_icon(self.help_button, "help", 18)
        set_button_icon(self.theme_button, "moon", 18)
        set_button_icon(self.open_sheet_button, "external-link", 14)
        set_button_icon(self.clear_log_button, "trash", 15)
        set_button_icon(self.download_export_tabs_button, "download", 16)
        set_button_icon(self.start_button, "upload", 17)
        set_button_icon(self.stop_button, "stop", 15)

        for card in (
            self.target_card,
            self.action_card,
            self.log_card,
        ):
            card.setGraphicsEffect(None)

        self._configure_card_headers()

        self.log_edit = BottomAlignedLogView(self.log_placeholder)
        self.log_placeholder_layout.addWidget(self.log_edit)

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stop_button.setVisible(False)

        for card in (self.action_card, self.log_card):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._configure_workspace()
        self.workspace = FeatureWorkspace(self)
        self.workflow_frame = require_object(self.root, "workflowFrame", QFrame)
        workflow_layout = QVBoxLayout(self.workflow_frame)
        workflow_layout.setContentsMargins(1, 1, 1, 1)
        workflow_layout.setSpacing(0)
        workflow_layout.addWidget(self.action_card)
        self.action_card_layout.insertWidget(1, self.workspace, 1)
        self.csv_page = require_object(self.action_pages, "csvActions", QWidget)
        self._sync_feature_controls()
        self.log_card_layout.setStretch(1, 1)
        self.action_card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.log_container = QWidget()
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        if not self.log_toggle.isChecked():
            log_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_splitter.replaceWidget(1, self.log_container)
        log_layout.addWidget(self.log_card)
        self.csv_page.installEventFilter(self)
        self.action_card.installEventFilter(self)
        self.folder_card.installEventFilter(self)
        self.cards_splitter.setChildrenCollapsible(False)
        self.cards_splitter.setStretchFactor(0, 4)
        self.cards_splitter.setStretchFactor(1, 1)
        self.cards_splitter.splitterMoved.connect(self._save_card_sizes)

    def _configure_workspace(self) -> None:
        """Keep tools separate from the CSV-to-Sheets task and expose its target."""
        self.app_subtitle_label.setText("CSV · Unity Locale · Google Sheets")
        self.action_title_label = require_object(self.root, "actionTitleLabel", QLabel)
        require_object(self.root, "logTitleLabel", QLabel).setText("Nhật ký xử lý")
        self.action_subtitle_label.hide()
        self.log_subtitle_label.hide()
        self.start_button.setText("Upload CSV lên Sheet")
        self.start_button.setProperty("primaryAction", True)
        self.stop_button.setProperty("dangerAction", True)
        self.download_export_tabs_button.setText("Tải CSV export từ Sheet")

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
        self.unity_locale_button.setToolTip("Truyền toàn bộ CSV và asset cùng mã ngôn ngữ trong các thư mục chung.")
        self.direct_transfer_button = QPushButton("Sheet ↔ Unity")
        self.direct_transfer_button.setToolTip("Truyền trực tiếp giữa locale*.asset và các tab upload_* hoặc export_*.")
        self.direct_transfer_button.clicked.connect(self.show_direct_transfer)
        self.files_launcher = QPushButton("CSV ↔ Sheet")
        self.files_launcher.clicked.connect(self.show_files)
        self.workflow_buttons = (self.files_launcher, self.unity_locale_button, self.direct_transfer_button)
        for button in self.workflow_buttons:
            button.setCheckable(True)
            button.setProperty("workflowTab", True)
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.csv_tools_button = QToolButton(tools)
        self.csv_tools_button.setText("Kiểm tra dữ liệu")
        self.csv_tools_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.csv_tools_button)
        self.audit_source_actions = {}
        for kind, label, callback in (("mapping", "Kiểm tra mapping", self.check_mapping),
                                      ("language", "Nhận diện ngôn ngữ", self.check_csv_languages)):
            submenu = menu.addMenu(label)
            for role, title in TransferFoldersCard.roles.items():
                action = submenu.addAction(title)
                action.triggered.connect(lambda checked=False, r=role, check=callback: check(r))
                self.audit_source_actions[kind, role] = action
        self.duplicate_action = menu.addAction("Kiểm tra key trùng trong asset…", self.check_asset_duplicates)
        self.compare_action = menu.addAction("So sánh hai CSV…", self.compare_selected_files)
        menu.aboutToShow.connect(self._update_audit_sources)
        self.csv_tools_button.setMenu(menu)
        toolbar.addWidget(self.csv_tools_button)
        self.root.layout().insertWidget(1, tools)
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
        stack.insertLayout(0, target_row)
        self.sheet_title_label = QLabel()
        self.sheet_title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.sheet_title_label.setWordWrap(True)
        stack.insertWidget(1, self.sheet_title_label)
        self.folder_card = TransferFoldersCard(self.settings)
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
        self._update_target_summary()
        self.progress_label.hide()

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
        self.csv_tools_button.setText(f"Kiểm tra dữ liệu · {count} dấu Desc" if count else "Kiểm tra dữ liệu")

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

    def _update_target_summary(self, *_args) -> None:
        count = len(self.file_infos)
        self.target_summary.setText(f"{count} CSV upload → tab upload_*   ·   Tab export_* → thư mục CSV export")

    def _toggle_log(self, expanded: bool) -> None:
        self.settings.ui_log_expanded = expanded
        self.log_toggle.setText("Thu gọn nhật ký" if expanded else "Hiện nhật ký")
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.log_placeholder.setVisible(expanded)
        self.clear_log_button.setVisible(expanded)
        self.log_card.setMaximumHeight(16777215 if expanded else 64)
        if hasattr(self, "log_container"):
            self.log_container.layout().setAlignment(Qt.AlignmentFlag(0) if expanded else Qt.AlignmentFlag.AlignTop)
        self.log_card.setMinimumHeight(140 if expanded else 64)
        if expanded:
            sizes = self.cards_splitter.sizes()
            if len(sizes) == 2:
                self.cards_splitter.setSizes([max(220, sum(sizes) - 160), 160])
        QTimer.singleShot(0, self._refresh_minimum_height)

    def _configure_card_headers(self) -> None:
        """Cho phép phần mô tả dưới tiêu đề card co giãn theo bề ngang cửa sổ."""
        for subtitle in (
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
        self.target_header_layout.setStretch(1, 1)
        self.action_header_layout.setStretch(1, 1)
        self.log_header_layout.setStretch(1, 1)

    def _connect_signals(self) -> None:
        self.unity_locale_button.clicked.connect(self.show_unity_locale)
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
        self._add_files_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        self._add_files_shortcut.activated.connect(self.show_transfer_folders)
        self._target_shortcut = QShortcut(QKeySequence("Ctrl+L"), self.quick_sheet_url_edit)
        self._target_shortcut.activated.connect(self.quick_sheet_url_edit.setFocus)
        self._help_shortcut = QShortcut(QKeySequence("F1"), self)
        self._help_shortcut.activated.connect(self.show_help)
        self._update_transfer_buttons()

    def _restore_settings(self) -> None:
        self.sheet_url_edit.setText(self.settings.sheet_url)
        self.target_mode_combo.setCurrentIndex(0)
        self.target_mode_combo.hide()
        self.target_form.findChild(QLabel, "targetModeLabel").hide()
        self.single_sheet_name_edit.setText(self.settings.sheet_name)
        self.value_input_combo.setCurrentIndex(
            1 if self.settings.value_input_option == "USER_ENTERED" else 0
        )
        self.single_sheet_name_label.hide()
        self.single_sheet_name_edit.hide()

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
        self._card_sizes_restored = True
        self._refresh_minimum_height()

    def _save_card_sizes(self, *_args) -> None:
        if self._card_sizes_restored and self._size_key:
            self.settings.workflow_card_sizes[self._size_key] = self.cards_splitter.sizes()
            self.save_settings()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.LayoutRequest:
            self._layout_timer.start()
        return super().eventFilter(obj, event)

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
            self.target_card_layout,
            self.action_card_layout,
            self.log_card_layout,
        ):
            layout.setContentsMargins(*margin)
            layout.setSpacing(spacing)

        icon_map = (
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
        page = self.workspace.pages[-1] if self.workspace.pages else None
        content_height = 0
        if page is not None:
            page_layout = page.layout()
            width = max(1, self.workspace.width() - 4)
            content_height = max(page_layout.minimumSize().height(), page_layout.minimumHeightForWidth(width)) + 4
        self.workspace.setMinimumHeight(content_height)
        cards = (self.action_card, self.log_card)
        for card, floor in zip(cards, (0, 140)):
            if card is self.log_card and not self.log_toggle.isChecked():
                card.setMinimumHeight(64)
                continue
            card.setMinimumHeight(max(
                floor, card.layout().minimumSize().height(),
                card.layout().minimumHeightForWidth(card.width()),
            ))
        self.workflow_frame.setMinimumHeight(self.action_card.minimumHeight() + 2)
        if self._card_sizes_restored:
            if isinstance(page, UnityLocaleDialog):
                key = "unity-import" if page.importing() else "unity-export"
            elif page is None:
                key = "csv-sheet"
            else:
                key = "direct-" + page.direction
            if key != self._size_key:
                self._size_key = key
                sizes = self.settings.workflow_card_sizes.get(key)
                if sizes is None and page is None:
                    sizes = self.settings.workflow_card_sizes.get(f"csv-{self.settings.csv_sheet_direction}")
                if not (isinstance(sizes, list) and len(sizes) == 2 and
                        all(type(n) is int and 0 < n < 100000 for n in sizes)):
                    preferred = self.workflow_frame.minimumHeight()
                    sizes = [preferred, max(64, self.cards_splitter.height() - preferred - self.cards_splitter.handleWidth())]
                self.cards_splitter.setSizes(sizes)
        self.root.setMinimumHeight(layout.minimumSize().height())

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
        self._layout_timer.start()
        pages = self.workspace.pages
        if not pages:
            title = "CSV ↔ Google Sheets"
        elif isinstance(pages[-1], UnityLocaleDialog):
            title = "CSV ↔ Unity"
        else:
            title = "Google Sheets ↔ Unity"
        self.action_title_label.setText(title)

    def _sync_shared_controls(self, starting=False):
        editable = not starting and self.worker is None and all(page.worker is None for page in self.workspace.pages)
        for widget in (self.quick_sheet_url_edit, self.target_settings_button, self.settings_button,
                       self.csv_tools_button, self.folder_card):
            widget.setEnabled(editable)
        if editable and self.folder_refresh_pending:
            self.folder_timer.start()

    def _sync_feature_controls(self):
        self._sync_action_title()
        self._sync_shared_controls()
        base = self.workspace.pages[0] if self.workspace.pages else None
        self.workspace.setVisible(base is not None)
        if hasattr(base, "direction"):
            active = self.direct_transfer_button
        elif isinstance(base, UnityLocaleDialog):
            active = self.unity_locale_button
        else:
            active = self.files_launcher
        for button in self.workflow_buttons:
            button.setChecked(button is active)
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
        dialog = DirectSheetDialog(self.settings, direction, self, annotations=self.desc_annotations, folder_only=True)
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
        dialog = UnityLocaleDialog(self.settings, parent=self, annotations=self.desc_annotations, folder_only=True)
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

    def show_transfer_folders(self):
        self.folder_card.toggle.setChecked(True)
        self.folder_card.toggle.setFocus()

    def set_transfer_folder(self, role, folder):
        setattr(self.settings, role + "_folder", folder)
        if role == "export":
            self.settings.last_export_dir = folder
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
            try:
                infos = [inspect_csv(path) for path in selected]
            except (CsvImportError, OSError) as exc:
                issues += (str(exc),)
                infos, selected = [], []
            self.file_infos = {str(info.path): info for info in infos}
            self.settings.selected_csv_files = list(self.file_infos)
            self.settings.unity_export_csv_files = list(self.settings.selected_csv_files)
            self.settings.unity_export_dir = folder
        elif role == "unity":
            self.settings.unity_asset_files = [str(p) for p in selected]
        else:
            self.settings.unity_import_csv_files = [str(p) for p in selected]
        self.folder_card.set_result(role, paths, issues)
        self._update_transfer_buttons()
        self._update_target_summary()
        if force or previous != (paths, issues):
            for page in self.workspace.pages:
                if isinstance(page, UnityLocaleDialog):
                    page.set_folder_files(role, selected, folder, issues)
                elif role == "unity" and hasattr(page, "direction"):
                    page.set_folder_files(selected, folder)
            return True
        return False

    def _update_transfer_buttons(self):
        self.start_button.setEnabled(self.worker is None and bool(self.file_infos))
        self.download_export_tabs_button.setEnabled(self.worker is None and bool(self.settings.export_folder) and not self.folder_card.results["export"][1])

    def _csv_audit_available(self):
        if self.worker is not None or any(page.worker is not None for page in self.workspace.pages):
            self.statusBar().showMessage("Đợi tác vụ hiện tại hoàn tất trước khi kiểm tra dữ liệu.", 4500)
            return False
        return True

    def open_audit_popup(self, dialog, after_close=None):
        # The active workflow stays mounted, including its preview and selection.
        for name in ("folder_button", "files_button", "choose_button"):
            button = getattr(dialog, name, None)
            if button is not None:
                button.hide()
        signal = getattr(dialog, "desc_marks_changed", None)
        if signal is not None:
            signal.connect(self._invalidate_export_previews)
            signal.connect(self._refresh_desc_count)
        if after_close:
            dialog.finished.connect(lambda _: after_close())
        dialog.finished.connect(lambda _: self.save_settings())
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    def _update_audit_sources(self):
        for (_, role), action in self.audit_source_actions.items():
            paths, issues = self.folder_card.results[role]
            detail = "Lỗi thư mục" if issues else f"{len(paths)} tệp"
            if not getattr(self.settings, role + "_folder"):
                detail = "Chưa chọn thư mục"
            action.setText(f"{TransferFoldersCard.roles[role]} · {detail}")
            action.setEnabled(bool(paths) and not issues)
        paths, issues = self.folder_card.results["unity"]
        self.duplicate_action.setEnabled(bool(paths) and not issues)

    def check_csv_languages(self, role="upload") -> None:
        if self._csv_audit_available():
            from .csv_language_dialog import CsvLanguageDialog
            paths, issues = self.folder_card.results[role]
            if not issues:
                dialog = CsvLanguageDialog(paths, self, annotations=self.desc_annotations, unity_assets=role == "unity")
                dialog.setWindowTitle("Nhận diện ngôn ngữ · " + TransferFoldersCard.roles[role])
                self.open_audit_popup(dialog)

    def check_mapping(self, role="upload") -> None:
        if self._csv_audit_available():
            from .mapping_dialog import MappingDialog
            paths, issues = self.folder_card.results[role]
            if not issues:
                dialog = MappingDialog(self.settings, paths, self, annotations=self.desc_annotations,
                                       unity_assets=role == "unity")
                dialog.setWindowTitle("Kiểm tra mapping · " + TransferFoldersCard.roles[role])
                self.open_audit_popup(dialog)

    def check_asset_duplicates(self) -> None:
        if not self._csv_audit_available():
            return
        from .locale_duplicate_dialog import LocaleDuplicateDialog
        paths, issues = self.folder_card.results["unity"]
        if not paths or issues:
            self.show_transfer_folders()
            return
        dialog = LocaleDuplicateDialog(list(paths), self, settings=self.settings)

        def after_review():
            if dialog.wrote_files:
                for page in self.workspace.pages:
                    page.invalidate()

        self.open_audit_popup(dialog, after_review)
        dialog.scan()

    def compare_selected_files(self) -> None:
        if self._csv_audit_available():
            choices = [str(path) for role in ("upload", "export") for path in self.folder_card.results[role][0]]
            self.open_audit_popup(CsvCompareDialog(parent=self, choices=choices))

    def open_sheet(self) -> None:
        url = self.sheet_url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Thiếu link", "Dán link vào ô Sheet đích trên màn hình chính.")
            return
        QDesktopServices.openUrl(QUrl(url))

    def build_job(self) -> ImportJob | None:
        if not self.settings.upload_folder:
            self.show_transfer_folders()
            self.statusBar().showMessage("Chọn thư mục CSV upload trong Thư mục truyền dữ liệu.", 4500)
            return None
        self._scan_transfer_folder("upload")
        issues = self.folder_card.results["upload"][1]
        if issues:
            QMessageBox.warning(self, "Kiểm tra thư mục upload", "\n".join(issues))
            return None
        if not self.file_infos:
            QMessageBox.warning(
                self,
                "Chưa chọn file",
                "Thư mục upload cần có ít nhất một file upload_<mã>.csv.",
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

        file_paths = tuple(self.file_infos)

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
            target_mode="multiple",
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
        self.progress_label.setText("Đang chuẩn bị upload CSV lên Sheet…")
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

    def start_download_export_tabs(self) -> None:
        if not self.show_files() or (self.worker and self.worker.isRunning()):
            return
        url = self._validate_sheet_action()
        if not url:
            return
        output_dir = self.settings.export_folder
        if not output_dir:
            self.show_transfer_folders()
            self.statusBar().showMessage("Chọn thư mục CSV export trong Thư mục truyền dữ liệu.", 4500)
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
        if running:
            self.progress_bar.setValue(0)
            self.progress_label.show()
        self.progress_bar.setVisible(running or self.progress_bar.value() > 0)
        self._sync_shared_controls(starting=running)
        if running:
            self.start_button.setEnabled(False)
            self.download_export_tabs_button.setEnabled(False)
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)
        self.unity_locale_button.setEnabled(not running)
        self.direct_transfer_button.setEnabled(not running)
        self.files_launcher.setEnabled(not running)
        if not running:
            self._update_transfer_buttons()
        self.target_mode_combo.setEnabled(not running)
        self.single_sheet_name_edit.setEnabled(not running)
        self.value_input_combo.setEnabled(not running)

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
        self._update_transfer_buttons()
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
        self.settings.target_mode = "multiple"
        self.settings.import_mode = "overwrite"
        self.settings.value_input_option = (
            "USER_ENTERED"
            if self.value_input_combo.currentIndex() == 1
            else "RAW"
        )
        self.settings.first_row_is_header = True
        self.settings.strict_headers = True
        self.settings.add_source_column = False
        if self._card_sizes_restored:
            self.settings.card_sizes = self.cards_splitter.sizes()
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        try:
            self.settings_repository.save(self.settings)
        except OSError as exc:
            self.append_log("FAIL", f"Không thể lưu cấu hình: {exc}")

    def closeEvent(self, event: QCloseEvent) -> None:
        popup = QApplication.activeModalWidget()
        if popup is not None and self.isAncestorOf(popup):
            popup.raise_()
            event.ignore()
            return
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
