from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QSize
from PySide6.QtGui import QColor, QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
)

from import_localize.app.constants import (
    APP_VERSION,
    DEFAULT_GITHUB_REPOSITORY,
)
from import_localize.app.paths import FORMS_DIR, USER_CONFIG_DIR
from import_localize.config.settings import SettingsRepository
from import_localize.services.google_service import (
    clear_saved_oauth_token,
    install_oauth_client,
    oauth_configuration_status,
)
from import_localize.services.update_service import (
    PreparedUpdate,
    UpdateRelease,
    can_install_updates,
    is_newer_version,
    launch_prepared_update,
    normalize_repository,
)
from import_localize.ui.assets import icon, set_button_icon
from import_localize.ui.ui_loader import load_ui, require_object
from import_localize.workers.oauth_worker import OAuthWorker
from import_localize.workers.update_worker import (
    UpdateCheckWorker,
    UpdateDownloadWorker,
)


class _DesignerDialog(QDialog):
    """Frameless theme-aware dialog matching the SK Export visual system."""

    def _configure_window(self, title: str) -> None:
        self.setObjectName("designerDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    @staticmethod
    def _apply_shadow(card: QFrame) -> None:
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 95))
        card.setGraphicsEffect(shadow)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            geometry = self.frameGeometry()
            geometry.moveCenter(parent.frameGeometry().center())
            self.move(geometry.topLeft())
            return
        screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = self.frameGeometry()
            geometry.moveCenter(screen.availableGeometry().center())
            self.move(geometry.topLeft())


class SettingsDialog(_DesignerDialog):
    def __init__(self, parent=None, *, initial_tab: str = "google"):
        super().__init__(parent)
        self._configure_window("Cài đặt — Import Localize")
        self.setMinimumWidth(570)
        self.setMaximumWidth(650)

        self.settings_repository = SettingsRepository()
        self.settings = self.settings_repository.load()
        self.oauth_worker: OAuthWorker | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self.latest_release: UpdateRelease | None = None
        self.prepared_update: PreparedUpdate | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.form = load_ui(FORMS_DIR / "settings_dialog.ui", self)
        layout.addWidget(self.form)

        self.dialog_card = require_object(self.form, "dialogCard", QFrame)
        self.dialog_icon_label = require_object(
            self.form, "dialogIconLabel", QLabel
        )
        self.close_button = require_object(self.form, "closeButton", QPushButton)
        self.close_icon_button = require_object(
            self.form, "closeIconButton", QPushButton
        )
        self.settings_tabs = require_object(self.form, "settingsTabs", QTabWidget)

        self.oauth_client_icon_label = require_object(
            self.form, "oauthClientIconLabel", QLabel
        )
        self.google_account_icon_label = require_object(
            self.form, "googleAccountIconLabel", QLabel
        )
        self.security_note_icon_label = require_object(
            self.form, "securityNoteIconLabel", QLabel
        )
        self.oauth_client_path_edit = require_object(
            self.form, "oauthClientPathEdit", QLineEdit
        )
        self.choose_oauth_button = require_object(
            self.form, "chooseOauthButton", QPushButton
        )
        self.open_config_button = require_object(
            self.form, "openConfigButton", QPushButton
        )
        self.oauth_status_label = require_object(
            self.form, "oauthStatusLabel", QLabel
        )
        self.login_button = require_object(
            self.form, "loginGoogleButton", QPushButton
        )
        self.logout_button = require_object(
            self.form, "logoutGoogleButton", QPushButton
        )
        self.oauth_log_edit = require_object(
            self.form, "oauthLogEdit", QPlainTextEdit
        )

        self.update_icon_label = require_object(
            self.form, "updateIconLabel", QLabel
        )
        self.update_repository_edit = require_object(
            self.form, "updateRepositoryEdit", QLineEdit
        )
        self.auto_check_updates_checkbox = require_object(
            self.form, "autoCheckUpdatesCheckBox", QCheckBox
        )
        self.current_version_value_label = require_object(
            self.form, "currentVersionValueLabel", QLabel
        )
        self.latest_version_value_label = require_object(
            self.form, "latestVersionValueLabel", QLabel
        )
        self.update_status_label = require_object(
            self.form, "updateStatusLabel", QLabel
        )
        self.update_progress_bar = require_object(
            self.form, "updateProgressBar", QProgressBar
        )
        self.release_notes_edit = require_object(
            self.form, "releaseNotesEdit", QPlainTextEdit
        )
        self.open_release_button = require_object(
            self.form, "openReleaseButton", QPushButton
        )
        self.check_update_button = require_object(
            self.form, "checkUpdateButton", QPushButton
        )
        self.install_update_button = require_object(
            self.form, "installUpdateButton", QPushButton
        )

        self._apply_shadow(self.dialog_card)
        self.dialog_icon_label.setPixmap(icon("settings").pixmap(QSize(22, 22)))
        self.oauth_client_icon_label.setPixmap(icon("oauth").pixmap(QSize(18, 18)))
        self.google_account_icon_label.setPixmap(icon("google").pixmap(QSize(18, 18)))
        self.security_note_icon_label.setPixmap(icon("info").pixmap(QSize(15, 15)))
        self.update_icon_label.setPixmap(icon("cloud-upload").pixmap(QSize(18, 18)))
        set_button_icon(self.close_icon_button, "close", 16)
        set_button_icon(self.choose_oauth_button, "folder", 15)
        set_button_icon(self.open_config_button, "folder", 15)
        set_button_icon(self.login_button, "login", 16)
        set_button_icon(self.logout_button, "logout", 15)
        set_button_icon(self.open_release_button, "external-link", 14)
        set_button_icon(self.check_update_button, "info", 15)
        set_button_icon(self.install_update_button, "cloud-upload", 16)

        self.choose_oauth_button.clicked.connect(self.choose_oauth_client)
        self.open_config_button.clicked.connect(self.open_config_directory)
        self.login_button.clicked.connect(self.toggle_google_login)
        self.logout_button.clicked.connect(self.logout_google)
        self.check_update_button.clicked.connect(self.toggle_update_check)
        self.install_update_button.clicked.connect(self.toggle_update_install)
        self.open_release_button.clicked.connect(self.open_release_page)
        self.close_button.clicked.connect(self.accept)
        self.close_icon_button.clicked.connect(self.accept)

        self.current_version_value_label.setText(f"v{APP_VERSION}")
        self.update_progress_bar.setRange(0, 100)
        self.update_progress_bar.setValue(0)
        self.update_repository_edit.setText(
            self.settings.update_repository or DEFAULT_GITHUB_REPOSITORY
        )
        self.auto_check_updates_checkbox.setChecked(
            self.settings.auto_check_updates
        )
        self.open_release_button.setEnabled(False)
        self.install_update_button.setEnabled(False)
        if not can_install_updates():
            self.install_update_button.setToolTip(
                "Chạy bản EXE đã build trên Windows để tự cài cập nhật."
            )

        self.refresh_status()
        self.settings_tabs.setCurrentIndex(1 if initial_tab == "update" else 0)

    def refresh_status(self) -> None:
        status = oauth_configuration_status()
        self.oauth_client_path_edit.setText(str(status["client_path"]))
        if status["token_exists"]:
            self.oauth_status_label.setText(
                "Đã có phiên đăng nhập Google trên máy này. "
                "Nhấn Đổi tài khoản để đăng nhập lại."
            )
            self.login_button.setText("Đổi tài khoản")
            self.logout_button.setEnabled(True)
        else:
            self.oauth_status_label.setText("Chưa đăng nhập Google.")
            self.login_button.setText("Đăng nhập Google")
            self.logout_button.setEnabled(False)
        self.login_button.setEnabled(bool(status["client_ready"]))

    def choose_oauth_client(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn OAuth Client JSON",
            str(Path.home()),
            "JSON (*.json);;Tất cả file (*.*)",
        )
        if not path:
            return
        try:
            installed = install_oauth_client(path)
        except Exception as exc:
            QMessageBox.critical(self, "OAuth Client không hợp lệ", str(exc))
            return
        self.oauth_log_edit.appendPlainText(f"Đã cài OAuth Client: {installed}")
        self.refresh_status()

    def open_config_directory(self) -> None:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(USER_CONFIG_DIR)))

    def toggle_google_login(self) -> None:
        if self.oauth_worker and self.oauth_worker.isRunning():
            self.oauth_worker.request_stop()
            self.login_button.setEnabled(False)
            self.login_button.setText("Đang dừng...")
            return

        status = oauth_configuration_status()
        if not status["client_ready"]:
            QMessageBox.warning(
                self,
                "Chưa có OAuth Client",
                "Hãy chọn oauth_client.json loại Desktop app trước.",
            )
            return

        if status["token_exists"] and self.login_button.text() == "Đổi tài khoản":
            clear_saved_oauth_token()

        self.oauth_log_edit.clear()
        self.oauth_status_label.setText("Đang chờ đăng nhập trên trình duyệt...")
        self.login_button.setText("Dừng đăng nhập")
        self.logout_button.setEnabled(False)
        self._set_close_enabled(False)

        worker = OAuthWorker(self)
        self.oauth_worker = worker
        worker.log_emitted.connect(self.oauth_log_edit.appendPlainText)
        worker.completed.connect(self.on_oauth_completed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def on_oauth_completed(self, success: bool, message: str) -> None:
        self.oauth_log_edit.appendPlainText(message)
        self.oauth_status_label.setText(message)
        self.oauth_worker = None
        self._set_close_enabled(True)
        self.refresh_status()
        if not success and "dừng" not in message.casefold():
            QMessageBox.warning(self, "Đăng nhập Google", message)

    def logout_google(self) -> None:
        success, message = clear_saved_oauth_token()
        if success:
            QMessageBox.information(self, "Đăng xuất Google", message)
        else:
            QMessageBox.warning(self, "Đăng xuất Google", message)
        self.refresh_status()

    def _repository(self) -> str | None:
        try:
            repository = normalize_repository(self.update_repository_edit.text())
        except Exception as exc:
            QMessageBox.warning(self, "Nguồn cập nhật không hợp lệ", str(exc))
            self.update_repository_edit.setFocus()
            return None
        self.update_repository_edit.setText(repository)
        return repository

    def toggle_update_check(self) -> None:
        if self.update_check_worker and self.update_check_worker.isRunning():
            self.update_check_worker.request_stop()
            self.check_update_button.setEnabled(False)
            self.check_update_button.setText("Đang dừng...")
            return
        repository = self._repository()
        if not repository:
            return
        self._save_update_settings()
        self.latest_release = None
        self.prepared_update = None
        self.install_update_button.setEnabled(False)
        self.open_release_button.setEnabled(False)
        self.latest_version_value_label.setText("Đang kiểm tra...")
        self.update_status_label.setText("Đang kết nối GitHub Releases...")
        self.update_progress_bar.setRange(0, 0)
        self.check_update_button.setText("Dừng kiểm tra")
        self.install_update_button.setText("Tải và cài đặt")
        self._set_close_enabled(False)

        worker = UpdateCheckWorker(repository, self)
        self.update_check_worker = worker
        worker.completed.connect(self.on_update_check_completed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def on_update_check_completed(
        self,
        success: bool,
        release_object: object,
        message: str,
    ) -> None:
        self.update_check_worker = None
        self.update_progress_bar.setRange(0, 100)
        self.update_progress_bar.setValue(0)
        self.check_update_button.setEnabled(True)
        self.check_update_button.setText("Kiểm tra cập nhật")
        self._set_close_enabled(True)

        if not success or not isinstance(release_object, UpdateRelease):
            self.latest_version_value_label.setText("Không xác định")
            self.update_status_label.setText(message)
            if "dừng" not in message.casefold():
                QMessageBox.warning(self, "Kiểm tra cập nhật", message)
            return

        release = release_object
        self.latest_release = release
        self.latest_version_value_label.setText(f"v{release.version}")
        self.release_notes_edit.setPlainText(
            release.notes or "Bản phát hành không có ghi chú."
        )
        self.open_release_button.setEnabled(bool(release.html_url))
        if is_newer_version(release.version, APP_VERSION):
            self.update_status_label.setText(
                f"Có bản cập nhật v{release.version}. File cài đặt đã được xác minh "
                "bằng SHA-256 trước khi thay thế ứng dụng."
            )
            self.install_update_button.setEnabled(can_install_updates())
            if not can_install_updates():
                self.update_status_label.setText(
                    f"Có bản cập nhật v{release.version}. Bản chạy source chỉ có thể "
                    "kiểm tra; hãy dùng Import_Localize.exe để tự cài đặt."
                )
        else:
            self.update_status_label.setText(
                f"Bạn đang dùng phiên bản mới nhất (v{APP_VERSION})."
            )
            self.install_update_button.setEnabled(False)

    def toggle_update_install(self) -> None:
        if self.update_download_worker and self.update_download_worker.isRunning():
            self.update_download_worker.request_stop()
            self.install_update_button.setEnabled(False)
            self.install_update_button.setText("Đang dừng...")
            return

        if self.prepared_update is not None:
            self._confirm_and_apply_update(self.prepared_update)
            return
        if self.latest_release is None:
            QMessageBox.information(
                self,
                "Chưa kiểm tra cập nhật",
                "Hãy nhấn Kiểm tra cập nhật trước.",
            )
            return
        if not can_install_updates():
            QMessageBox.information(
                self,
                "Không thể tự cài từ source",
                "Tính năng tự cài chỉ hoạt động trong bản Import_Localize.exe đã build.",
            )
            return

        self.update_progress_bar.setRange(0, 100)
        self.update_progress_bar.setValue(0)
        self.update_status_label.setText(
            f"Đang tải bản v{self.latest_release.version}..."
        )
        self.install_update_button.setText("Dừng tải")
        self.check_update_button.setEnabled(False)
        self._set_close_enabled(False)

        worker = UpdateDownloadWorker(self.latest_release, self)
        self.update_download_worker = worker
        worker.progress_changed.connect(self.on_update_progress)
        worker.completed.connect(self.on_update_download_completed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def on_update_progress(self, value: int, message: str) -> None:
        self.update_progress_bar.setValue(max(0, min(100, value)))
        self.update_status_label.setText(message)

    def on_update_download_completed(
        self,
        success: bool,
        prepared_object: object,
        message: str,
    ) -> None:
        self.update_download_worker = None
        self.check_update_button.setEnabled(True)
        self.install_update_button.setText("Tải và cài đặt")
        self._set_close_enabled(True)
        if not success or not isinstance(prepared_object, PreparedUpdate):
            self.install_update_button.setEnabled(self.latest_release is not None)
            self.update_status_label.setText(message)
            if "dừng" not in message.casefold():
                QMessageBox.warning(self, "Cập nhật ứng dụng", message)
            return
        self.prepared_update = prepared_object
        self.install_update_button.setText("Cài đặt và khởi động lại")
        self.install_update_button.setEnabled(True)
        self.update_progress_bar.setValue(100)
        self.update_status_label.setText(message)
        self._confirm_and_apply_update(prepared_object)

    def _confirm_and_apply_update(self, prepared: PreparedUpdate) -> None:
        answer = QMessageBox.question(
            self,
            "Cài đặt bản cập nhật",
            f"Ứng dụng sẽ đóng, cài bản v{prepared.release.version} rồi tự mở lại.\n\n"
            "Cấu hình và token Google trong AppData được giữ nguyên. Tiếp tục?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            launch_prepared_update(prepared)
        except Exception as exc:
            QMessageBox.critical(self, "Không thể chạy cập nhật", str(exc))
            return
        QApplication.instance().quit()

    def open_release_page(self) -> None:
        if self.latest_release and self.latest_release.html_url:
            QDesktopServices.openUrl(QUrl(self.latest_release.html_url))

    def _save_update_settings(self) -> None:
        self.settings.update_repository = self.update_repository_edit.text().strip()
        self.settings.auto_check_updates = self.auto_check_updates_checkbox.isChecked()
        self.settings_repository.save(self.settings)

    def _set_close_enabled(self, enabled: bool) -> None:
        self.close_button.setEnabled(enabled)
        self.close_icon_button.setEnabled(enabled)
        self.settings_tabs.setTabEnabled(0, enabled or self.oauth_worker is not None)
        self.settings_tabs.setTabEnabled(1, enabled or self.update_check_worker is not None or self.update_download_worker is not None)

    def _has_running_worker(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (
                self.oauth_worker,
                self.update_check_worker,
                self.update_download_worker,
            )
        )

    def reject(self) -> None:
        if self._has_running_worker():
            QMessageBox.information(
                self,
                "Tác vụ đang chạy",
                "Hãy dừng hoặc hoàn tất tác vụ trong Cài đặt trước khi đóng cửa sổ.",
            )
            return
        super().reject()

    def accept(self) -> None:
        if self._has_running_worker():
            self.reject()
            return
        try:
            self._save_update_settings()
        except OSError as exc:
            QMessageBox.warning(self, "Không thể lưu cài đặt", str(exc))
        super().accept()
class HelpDialog(_DesignerDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._configure_window("Hướng dẫn — Import Localize")
        self.setMinimumWidth(520)
        self.setMaximumWidth(600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.form = load_ui(FORMS_DIR / "help_dialog.ui", self)
        layout.addWidget(self.form)

        dialog_card = require_object(self.form, "dialogCard", QFrame)
        dialog_icon = require_object(self.form, "dialogIconLabel", QLabel)
        note_icon = require_object(self.form, "helpNoteIconLabel", QLabel)
        close_button = require_object(self.form, "closeButton", QPushButton)
        close_icon_button = require_object(
            self.form,
            "closeIconButton",
            QPushButton,
        )
        require_object(self.form, "helpTextBrowser", QTextBrowser)

        self._apply_shadow(dialog_card)
        dialog_icon.setPixmap(icon("help").pixmap(QSize(22, 22)))
        note_icon.setPixmap(icon("info").pixmap(QSize(15, 15)))
        set_button_icon(close_icon_button, "close", 16)
        close_button.clicked.connect(self.accept)
        close_icon_button.clicked.connect(self.accept)
