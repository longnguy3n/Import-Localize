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
    dialog.generate_destinations()
    drain(app, dialog)
    dialog.preview_button.click()
    drain(app, dialog)
    assert dialog.apply_button.isEnabled()
    dialog.prefix_edit.setText("Other Sheet")
    assert not dialog.apply_button.isEnabled()
    dialog.generate_destinations()
    drain(app, dialog)
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


def test_row_order_controls_import_destination_and_invalidates_preview(app, tmp_path, monkeypatch):
    monkeypatch.setattr(unity_locale_dialog, "USER_CONFIG_DIR", tmp_path / "config")
    assets = [tmp_path / f"locale_en_{i}.asset" for i in range(2)]
    csvs = [tmp_path / f"translated_{i}.csv" for i in range(2)]
    for i, (asset, csv) in enumerate(zip(assets, csvs)):
        asset.write_text(ASSET)
        csv.write_text(f"Key,English\nkey,translation {i}\n")
    dialog = UnityLocaleDialog(AppSettings(), csvs)
    dialog.set_assets(assets)
    dialog.show()
    assert csvs[0].name in dialog.source_list.item(0).text()
    assert str(assets[0]) == dialog.target_list.item(0).toolTip()
    dialog.preview()
    drain(app, dialog)
    assert dialog.plan and dialog.apply_button.isEnabled()
    # Qt's internal drag-and-drop moves rows through this same model operation.
    view = dialog.target_list
    assert view.model().moveRow(view.rootIndex(), 1, view.rootIndex(), 0)
    assert dialog.asset_paths == assets[::-1]
    assert dialog.source_list.paths() == csvs
    assert dialog.plan is None and not dialog.apply_button.isEnabled()
    assert view.item(0).text().startswith("01.")
    dialog.preview()
    drain(app, dialog)
    assert [c.path for c in dialog.plan.changes] == assets[::-1]
    dialog.apply()
    drain(app, dialog)
    assert read_asset(assets[1]).terms[0]["Languages"] == ["translation 0"]
    assert read_asset(assets[0]).terms[0]["Languages"] == ["translation 1"]
    dialog.reject()


def test_export_order_and_destinations_survive_source_moves_and_mode_switch(app, tmp_path, monkeypatch):
    monkeypatch.setattr(unity_locale_dialog, "USER_CONFIG_DIR", tmp_path / "config")
    assets = [tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"]
    assets[0].write_text(ASSET)
    assets[1].write_text(ASSET.replace("English", "Vietnamese").replace("Code: en", "Code: vi"))
    dialog = UnityLocaleDialog(AppSettings())
    dialog.set_assets(assets)
    dialog.mode_combo.setCurrentIndex(1)
    dialog.output_edit.setText(str(tmp_path))
    dialog.generate_destinations()
    drain(app, dialog)
    targets = dialog.target_list.paths()
    assert len(targets) == 2 and not any(p.exists() for p in targets)
    dialog.source_list.setCurrentRow(1)
    dialog.source_list.move_selected(-1)
    assert dialog.source_list.paths() == assets[::-1]
    assert dialog.target_list.paths() == targets  # no automatic rematching
    dialog.mode_combo.setCurrentIndex(0)
    dialog.mode_combo.setCurrentIndex(1)
    assert dialog.target_list.paths() == targets
    assert dialog.source_list.paths() == assets[::-1]
    dialog.preview()
    drain(app, dialog)
    dialog.apply()
    drain(app, dialog)
    assert "Vietnamese" in targets[0].read_text(encoding="utf-8-sig").splitlines()[0]
    assert "English" in targets[1].read_text(encoding="utf-8-sig").splitlines()[0]
    dialog.target_list.setCurrentRow(0)
    dialog.target_list.remove_selected()
    assert len(dialog.export_paths) == 1
    assert dialog.source_list.height() == dialog.target_list.height()
    dialog.preview()
    drain(app, dialog)
    assert dialog.plan is None and "cùng số file" in dialog.details.toPlainText()
    dialog.reject()
