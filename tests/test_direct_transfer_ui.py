import csv
import io
from pathlib import Path
from threading import Event

from import_localize.config.settings import AppSettings
from import_localize.services.desc_annotations import DescAnnotations, WRONG_MAPPING
from import_localize.services.direct_transfer import TransferPlan, TransferPair
from import_localize.ui import direct_sheet_dialog, unity_locale_dialog
from import_localize.services.unity_locale_service import ChangeStats
from test_unity_locale import ASSET
from test_unity_locale_ui import app, drain


def test_direct_preview_explains_missing_inputs_and_folder_scan_errors(app, tmp_path):
    dialog = direct_sheet_dialog.DirectSheetDialog(AppSettings(), "upload", folder_only=True)
    try:
        assert "Google Sheets" in dialog.status.text() and "Unity locale" in dialog.status.text()
        assert not dialog.preview_button.isEnabled()
        dialog.set_sheet_context("https://docs.google.com/spreadsheets/d/example", dialog.annotations)
        dialog.set_folder_files([], tmp_path)
        assert "locale_<mã>.asset" in dialog.status.text()
        dialog.set_folder_files([], tmp_path, ["Trùng mã vi"])
        assert "Trùng mã vi" in dialog.status.text()
        assert "Trùng mã vi" in dialog.preview_button.toolTip()
        dialog.set_folder_files([tmp_path / "locale_vi.asset"], tmp_path)
        assert dialog.preview_button.isEnabled() and "Trùng mã" not in dialog.status.text()
    finally:
        dialog.close()


def test_direct_review_preview_snapshot_and_submit(app, tmp_path, monkeypatch):
    path = tmp_path / "different-filename.asset"
    path.write_text(ASSET)
    settings = AppSettings(sheet_url="https://docs.google.com/spreadsheets/d/test",
                           unity_asset_files=[str(path)])
    marks = DescAnnotations()
    submitted = []
    gate = Event()

    def audit(kind, parent, received_settings, sources, received_marks):
        assert kind == "mapping" and received_settings is settings
        rows = list(csv.reader(io.StringIO(sources[Path("upload_en.csv")].decode("utf-8-sig"))))
        assert rows[1] == ["001", "Text", "old description", "yes"]
        assert received_marks is marks
        received_marks.set_mark("en", "001", WRONG_MAPPING)

    def prepare(direction, url, paths, **kwargs):
        assert direction == "upload" and url == settings.sheet_url and paths == [path]
        assert kwargs["annotations"].has("en", "001", WRONG_MAPPING)
        assert kwargs["annotations"] is not marks
        assert gate.wait(5)
        kwargs["progress_callback"](100, "Đã đọc")
        return TransferPlan(direction, url, "My Spreadsheet",
                            [TransferPair(path, "upload_en", 2, "Ghi đè tab", 7, ChangeStats(2, 1, 2, 1, 0, 0, 1, "term", "dòng Sheet"))])

    def submit(plan, backup_root, **kwargs):
        submitted.append(plan)
        kwargs["progress_callback"](100, "Đã ghi")

    monkeypatch.setattr(direct_sheet_dialog, "review_sources", audit)
    monkeypatch.setattr(direct_sheet_dialog, "prepare_transfer", prepare)
    monkeypatch.setattr(direct_sheet_dialog, "apply_transfer", submit)
    dialog = direct_sheet_dialog.DirectSheetDialog(settings, "upload", annotations=marks)
    try:
        dialog.show()
        dialog.check_mapping()
        drain(app, dialog)
        assert dialog.plan is None and not dialog.apply_button.isEnabled()
        dialog.preview_button.click()
        assert not dialog.folder_button.isEnabled() and not dialog.close_button.isEnabled()
        assert not dialog.direction_combo.isEnabled()
        dialog.direction_combo.setCurrentIndex(1)
        assert dialog.direction_combo.currentData() == dialog.direction == "upload"
        dialog.reject()
        assert dialog.isVisible()
        gate.set()
        drain(app, dialog)
        assert dialog.table.item(0, 1).text() == "upload_en"
        assert dialog.sheet.text() == "My Spreadsheet"
        assert "My Spreadsheet" in dialog.status.text() and "thay nội dung 1 tab" in dialog.status.text()
        assert "1 tab" in dialog.apply_button.toolTip()
        snapshot = dialog.plan
        dialog.apply_button.click()
        drain(app, dialog)
        assert submitted == [snapshot]
        assert dialog.plan is None and not dialog.apply_button.isEnabled()
        dialog.preview_button.click()
        drain(app, dialog)
        assert dialog.apply_button.isEnabled()
        dialog.direction_combo.setCurrentIndex(1)
        assert dialog.plan is None and not dialog.apply_button.isEnabled()
        assert dialog.paths == [path] and settings.direct_direction == "download"
        assert dialog.table.item(0, 1).text() == path.name
        assert not dialog.mapping_action.isVisible()
    finally:
        gate.set()
        drain(app, dialog)
        dialog.close()


def test_offline_asset_audit_marks_follow_csv_export(app, tmp_path, monkeypatch):
    asset = tmp_path / "locale_en.asset"
    asset.write_text(ASSET)
    dest = tmp_path / "DG - upload_en.csv"
    marks = DescAnnotations()
    def review(kind, parent, settings, sources, annotations):
        assert not dest.exists()
        assert kind == "mapping" and list(sources) == [Path("upload_en.csv")]
        annotations.set_mark("en", "001", WRONG_MAPPING)
    monkeypatch.setattr(unity_locale_dialog, "review_sources", review)
    monkeypatch.setattr(unity_locale_dialog, "USER_CONFIG_DIR", tmp_path / "config")
    settings = AppSettings(unity_asset_files=[str(asset)], unity_export_csv_files=[str(dest)], unity_mode="export")
    dialog = unity_locale_dialog.UnityLocaleDialog(settings, annotations=marks)
    try:
        dialog.preview()
        drain(app, dialog)
        assert dialog.apply_button.isEnabled()
        dialog.review_mapping()
        drain(app, dialog)
        assert dialog.plan is None and not dialog.apply_button.isEnabled()
        dialog.preview()
        drain(app, dialog)
        dialog.apply()
        drain(app, dialog)
        with dest.open(encoding="utf-8-sig", newline="") as stream:
            assert list(csv.reader(stream))[1][2] == "old description\nWrong mapping"
        assert asset.read_text() == ASSET
    finally:
        dialog.close()

def test_embedded_sheet_write_logs_while_collapsed_and_expands_on_failure(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel
    from import_localize.config.settings import SettingsRepository
    from import_localize.ui import main_window

    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    window = main_window.MainWindow()
    window.show_direct_transfer()
    page = window.workspace.pages[-1]
    window.log_toggle.setChecked(False)

    def submit(plan, backup_root, **kwargs):
        kwargs["progress_callback"](50, "Ghi upload_vi")
        if plan == "error":
            raise ValueError("Tab <upload_vi> đã thay đổi")

    monkeypatch.setattr(direct_sheet_dialog, "apply_transfer", submit)
    try:
        for plan in ("ok", "error"):
            page.plan = plan
            page.apply()
            drain(app, page)
            assert window.log_toggle.isChecked() == (plan == "error")
        messages = [(label.property("level"), label.text())
                    for label in window.log_edit.findChildren(QLabel, "logMessage")]
        assert ("INFO", "Ghi upload_vi") in messages
        assert any(level == "SUCCESS" and "Đã ghi" in text for level, text in messages)
        assert ("FAIL", "Tab <upload_vi> đã thay đổi") in messages
    finally:
        window.close()
