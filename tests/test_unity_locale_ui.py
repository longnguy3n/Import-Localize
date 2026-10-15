"""Offline integration: no Google account and no live Unity project writes."""
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.services.unity_locale_service import read_asset
from import_localize.ui import unity_locale_dialog
from import_localize.ui.main_window import MainWindow
from import_localize.ui.unity_locale_dialog import UnityLocaleDialog
from test_unity_locale import ASSET


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    if Path("C:/Windows/Fonts/segoeui.ttf").exists():
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        application.setFont(QFont("Segoe UI", 10))
    return application


def drain(app, dialog):
    deadline = time.monotonic() + 10
    while dialog.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert dialog.worker is None


def test_preview_apply_export_and_settings(app, tmp_path, monkeypatch):
    monkeypatch.setattr(unity_locale_dialog, "USER_CONFIG_DIR", tmp_path / "config")
    asset = tmp_path / "locale_en.asset"
    asset.write_text(ASSET)
    source = tmp_path / "input.csv"
    source.write_text("Key,Type,Desc,English\nhello,Text,,World\n", encoding="utf-8")
    settings = AppSettings(auto_check_updates=False)
    dialog = UnityLocaleDialog(settings, [source])
    dialog.show()
    dialog.set_assets([asset])
    assert not dialog.apply_button.isEnabled()
    dialog.preview_button.click()
    drain(app, dialog)
    assert dialog.apply_button.isEnabled()
    assert dialog.table.rowCount() == 1
    assert len(read_asset(asset).terms) == 2
    dialog.apply_button.click()
    drain(app, dialog)
    assert read_asset(asset).terms[0]["Languages"] == ["World"]
    assert dialog.table.item(0, 2).text() == "Đã ghi"
    assert dialog.backup_path.is_dir()
    assert not dialog.apply_button.isEnabled()
    dialog.mode_combo.setCurrentIndex(1)
    dialog.output_edit.setText(str(tmp_path))
    dialog.prefix_edit.setText("My Sheet")
    dialog.preview_button.click()
    drain(app, dialog)
    assert dialog.apply_button.isEnabled()
    dialog.prefix_edit.setText("Other Sheet")
    assert not dialog.apply_button.isEnabled()
    dialog.preview()
    drain(app, dialog)
    dialog.apply()
    drain(app, dialog)
    output = tmp_path / "Other Sheet - upload_en.csv"
    assert "hello,Text,,World" in output.read_text(encoding="utf-8-sig")
    dialog.reject()
    assert settings.unity_export_prefix == "Other Sheet"
    assert settings.unity_locale_dir == str(tmp_path)
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.save(settings)
    assert repository.load().unity_export_dir == str(tmp_path)


def test_error_and_close_during_work(app, tmp_path):
    dialog = UnityLocaleDialog(AppSettings())
    dialog.show()
    dialog.preview()
    drain(app, dialog)
    assert "LỖI:" in dialog.details.toPlainText()
    assert not dialog.apply_button.isEnabled()
    dialog._run(lambda: (time.sleep(0.1), tmp_path)[1], True)
    dialog.close()
    assert dialog.isVisible()
    drain(app, dialog)
    dialog.close()
    assert not dialog.isVisible()


def test_main_entry_and_busy_state(app, tmp_path, monkeypatch):
    repository = SettingsRepository(tmp_path / "config.json")
    repository.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr("import_localize.ui.main_window.SettingsRepository", lambda: repository)
    window = MainWindow()
    window.show()
    app.processEvents()
    assert window.unity_locale_button.isVisible()
    assert window.unity_locale_button.isEnabled()
    window.set_running(True)
    assert not window.unity_locale_button.isEnabled()
    window.set_running(False)
    assert window.unity_locale_button.isEnabled()
    window.close()
