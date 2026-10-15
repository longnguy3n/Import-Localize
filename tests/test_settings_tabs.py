"""Regression: starting work in Settings must not navigate to the target tab."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.services.update_service import UpdateRelease
from import_localize.ui import dialogs


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    if Path("C:/Windows/Fonts/segoeui.ttf").exists():
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        instance.setFont(QFont("Segoe UI", 10))
    return instance


@pytest.fixture
def dialog(app, tmp_path, monkeypatch):
    repository = SettingsRepository(tmp_path / "config.json")
    repository.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(dialogs, "SettingsRepository", lambda: repository)
    monkeypatch.setattr(dialogs, "oauth_configuration_status", lambda: {
        "client_path": "test-client.json", "client_ready": True, "token_exists": False,
    })
    monkeypatch.setattr(dialogs, "can_install_updates", lambda: True)
    # Construct real workers and wire their signals, but never start network work.
    for worker in (dialogs.OAuthWorker, dialogs.UpdateCheckWorker, dialogs.UpdateDownloadWorker):
        monkeypatch.setattr(worker, "start", lambda self: None)
    instance = dialogs.SettingsDialog(initial_tab="update", target_form=QWidget())
    instance.show()
    app.processEvents()
    yield instance
    instance.close()
    instance.deleteLater()
    app.processEvents()


def release():
    return UpdateRelease("longnguy3n/Import-Localize", "99.0.0", "v99.0.0", "Test", "Notes",
                         "https://github.com/longnguy3n/Import-Localize/releases/tag/v99.0.0",
                         "Import_Localize_v99.0.0.zip", "https://example.invalid/file.zip",
                         "https://example.invalid/file.zip.sha256.txt", 100)


@pytest.mark.parametrize("action,index", [("check", 1), ("download", 1), ("login", 0)])
def test_start_and_finish_keep_current_tab(dialog, app, action, index):
    dialog.settings_tabs.setCurrentIndex(index)
    changes = []
    dialog.settings_tabs.currentChanged.connect(changes.append)
    dialog.latest_release = release()
    dialog.install_update_button.setEnabled(True)
    button = {"check": dialog.check_update_button, "download": dialog.install_update_button,
              "login": dialog.login_button}[action]
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert dialog.settings_tabs.currentIndex() == index
    assert dialog.settings_tabs.isTabEnabled(index)
    assert all(not dialog.settings_tabs.isTabEnabled(i) for i in range(3) if i != index)
    assert not changes
    if action == "check":
        dialog.update_check_worker.completed.emit(True, release(), "OK")
    elif action == "download":
        dialog.update_download_worker.completed.emit(False, None, "Đã dừng tải")
    else:
        dialog.oauth_worker.completed.emit(True, "OK")
    app.processEvents()
    assert dialog.settings_tabs.currentIndex() == index
    assert all(dialog.settings_tabs.isTabEnabled(i) for i in range(3))
    assert not changes


def test_update_inputs_and_switching_tabs_remain_available(dialog, app):
    QTest.mouseClick(dialog.update_repository_edit, Qt.MouseButton.LeftButton)
    dialog.update_repository_edit.selectAll()
    QTest.keyClicks(dialog.update_repository_edit, "longnguy3n/Import-Localize")
    QTest.mouseClick(dialog.auto_check_updates_checkbox, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert dialog.settings_tabs.currentIndex() == 1
    bar = dialog.settings_tabs.tabBar()
    for index in (0, 2, 1):
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(index).center())
        assert dialog.settings_tabs.currentIndex() == index
