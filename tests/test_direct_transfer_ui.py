import csv
import io
from pathlib import Path
from threading import Event

from import_localize.config.settings import AppSettings
from import_localize.services.desc_annotations import DescAnnotations, WRONG_MAPPING
from import_localize.services.direct_transfer import TransferPlan, TransferPair
from import_localize.ui import direct_sheet_dialog, unity_locale_dialog
from test_unity_locale import ASSET
from test_unity_locale_ui import app, drain


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
                            [TransferPair(path, "upload_en", 2, "Ghi đè tab", 7)])

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
