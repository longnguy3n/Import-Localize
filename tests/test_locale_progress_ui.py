from threading import Event

import pytest

from import_localize.config.settings import AppSettings
from import_localize.ui import unity_locale_dialog
from import_localize.ui.unity_locale_dialog import UnityLocaleDialog
from test_unity_locale import ASSET
from test_unity_locale_ui import app, drain


@pytest.mark.parametrize("exporting", [False, True])
def test_apply_popup_shows_real_steps_and_keeps_result_visible(app, tmp_path, monkeypatch, exporting):
    monkeypatch.setattr(unity_locale_dialog, "USER_CONFIG_DIR", tmp_path / "config")
    asset = tmp_path / "locale_en.asset"
    asset.write_text(ASSET)
    csv = tmp_path / "translated.csv"
    csv.write_text("Key,English\n001,Hello\n")
    dialog = UnityLocaleDialog(AppSettings(), [csv])
    dialog.set_assets([asset])
    if exporting:
        dialog.mode_combo.setCurrentIndex(1)
        dialog.export_paths = [tmp_path / "output.csv"]
        dialog._refresh_lists()
    dialog.show()
    dialog.preview()
    drain(app, dialog)
    original_apply = unity_locale_dialog.apply_plan
    blocked, release = Event(), Event()
    def controlled_apply(plan, backup_root, *, progress):
        def observe(completed, total, message):
            progress(completed, total, message)
            if completed == 1 and not blocked.is_set():
                blocked.set()
                assert release.wait(10), "Test did not release the worker"
        return original_apply(plan, backup_root, progress=observe)
    monkeypatch.setattr(unity_locale_dialog, "apply_plan", controlled_apply)
    dialog.apply_button.click()
    popup = dialog.loading_dialog
    try:
        assert popup.isVisible() and popup.busy
        assert blocked.wait(5)
        app.processEvents()
        assert popup.progress.value() == 1 < popup.progress.maximum()
        assert "kiểm tra" in popup.status.text().lower()
        assert not popup.close_button.isEnabled()
        popup.close()
        popup.reject()
        assert popup.isVisible()
    finally:
        release.set()
        drain(app, dialog)
    assert popup.isVisible() and not popup.busy
    assert "thành công" in popup.heading.text()
    assert popup.progress.value() == popup.progress.maximum()
    assert popup.close_button.isEnabled() and popup.backup_path.is_dir()
    assert popup.operation == ("Replace Export" if exporting else "Replace Import")
    popup.close_button.click()
    assert not popup.isVisible()
    dialog.reject()


def test_failed_apply_reports_error_without_success(app, tmp_path, monkeypatch):
    monkeypatch.setattr(unity_locale_dialog, "USER_CONFIG_DIR", tmp_path / "config")
    asset = tmp_path / "locale_en.asset"
    asset.write_text(ASSET)
    csv = tmp_path / "translated.csv"
    csv.write_text("Key,English\n001,Hello\n")
    dialog = UnityLocaleDialog(AppSettings(), [csv])
    dialog.set_assets([asset])
    dialog.preview()
    drain(app, dialog)
    asset.write_bytes(asset.read_bytes() + b"\n")
    dialog.apply()
    drain(app, dialog)
    popup = dialog.loading_dialog
    assert popup.isVisible() and not popup.busy
    assert "không hoàn tất" in popup.heading.text()
    assert "đã thay đổi" in popup.details.toPlainText()
    assert popup.progress.value() < popup.progress.maximum()
    assert not popup.backup_button.isVisible()
    assert popup.close_button.isEnabled()
    popup.accept()
    dialog.reject()
