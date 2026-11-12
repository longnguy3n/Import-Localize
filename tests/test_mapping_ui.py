"""Mapping review UI and write guards; no live Google calls."""
from pathlib import Path
from types import SimpleNamespace
import time

from PySide6.QtWidgets import QMessageBox

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui.mapping_dialog import MappingDialog, MappingWorker, snapshots
from test_unity_locale_ui import app


def inputs(tmp_path):
    mapping = tmp_path / "mapping.json"
    mapping.write_text("{}", encoding="utf-8")
    csv = tmp_path / "export_vi.csv"
    csv.write_text("Key,Vietnamese\nwrong,HP\n", encoding="utf-8")
    return mapping, csv


def report(paths):
    def issue(path, key, status, source, actual, expected):
        return SimpleNamespace(path=path, line=2, key=key, locale="vi", source=source,
                               actual=actual, expected=expected, reason="Đối chiếu thuật ngữ", status=status)
    return SimpleNamespace(files=paths, errors={}, checked_cells=4, unmapped_cells=1,
        wrong_keys={"cf_hp_title"}, issues=[
            issue(paths[0], "cf_hp_title", "wrong", "HP", "HP", "MÁU"),
            issue(paths[-1], "cf_story_desc", "review", "<b>Frostbite</b>", "Phỏng Lạnh", "Xét ngữ cảnh"),
        ])


def drain(app, dialog):
    deadline = time.monotonic() + 10
    while dialog.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert dialog.worker is None


def test_file_summary_filters_and_full_content(app, tmp_path):
    mapping, csv = inputs(tmp_path)
    second = tmp_path / "export_pt-BR.csv"
    dialog = MappingDialog(AppSettings(mapping_path=str(mapping)), [csv, second])
    try:
        dialog.report = report([csv, second])
        dialog.render_report()
        dialog.set_busy(False)
        dialog.show()
        app.processEvents()
        assert dialog.files_table.rowCount() == 2
        assert dialog.files_table.item(0, 1).text() == "1"
        assert dialog.files_table.item(1, 2).text() == "1"
        assert dialog.issues_table.rowCount() == 2
        assert "1 key sai mapping" in dialog.status.text()
        assert dialog.mark_button.isEnabled()
        dialog.files_table.selectRow(1)
        assert dialog.issues_table.rowCount() == 1
        dialog.issues_table.selectRow(0)
        assert "<b>Frostbite</b>" in dialog.detail.toPlainText()
        dialog.all_files_button.click()
        assert dialog.issues_table.rowCount() == 2
        dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("wrong"))
        assert dialog.issues_table.rowCount() == 1
        assert dialog.visible_issues[0].key == "cf_hp_title"
        dialog.search.setText("not_a_key")
        assert dialog.issues_table.rowCount() == 0
        dialog.search.clear()
        dialog.filter_combo.setCurrentIndex(0)
        dialog.issues_table.selectRow(0)
        assert not dialog.grab().isNull()
    finally:
        dialog.reject()


def test_mark_uses_all_definite_wrong_keys_not_visible_review_row(app, tmp_path, monkeypatch):
    mapping, csv = inputs(tmp_path)
    settings = AppSettings(mapping_path=str(mapping), sheet_url="https://docs.google.com/spreadsheets/d/example")
    dialog = MappingDialog(settings, [csv])
    try:
        dialog.report = report([csv])
        dialog.snapshot = snapshots([mapping, csv])
        dialog.render_report()
        dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("review"))
        launched = []
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(dialog, "launch", launched.append)
        dialog.mark()
        assert len(launched) == 1
        worker = launched[0]
        assert worker.keys == {"cf_hp_title"}
        assert "cf_story_desc" not in worker.keys
        assert worker.snapshot == dialog.snapshot
        assert worker.sheet_url == settings.sheet_url
        worker.deleteLater()
    finally:
        dialog.reject()


def test_declining_mark_never_launches_write(app, tmp_path, monkeypatch):
    mapping, csv = inputs(tmp_path)
    dialog = MappingDialog(AppSettings(mapping_path=str(mapping), sheet_url="https://example.invalid"), [csv])
    try:
        dialog.report = report([csv])
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        launched = []
        monkeypatch.setattr(dialog, "launch", launched.append)
        dialog.mark()
        assert not launched
    finally:
        dialog.reject()


def test_stale_csv_blocks_google_connection_and_write(tmp_path, monkeypatch):
    from import_localize.services import google_service, mapping_sheet_service
    mapping, csv = inputs(tmp_path)
    snapshot = snapshots([mapping, csv])
    csv.write_text("changed", encoding="utf-8")
    calls = []
    monkeypatch.setattr(google_service, "connect_to_spreadsheet", lambda *a, **kw: calls.append("connect"))
    monkeypatch.setattr(mapping_sheet_service, "mark_wrong_mapping", lambda *a, **kw: calls.append("write"))
    worker = MappingWorker(mapping, [csv], keys={"wrong"}, snapshot=snapshot)
    worker.run()
    assert "đã thay đổi" in worker.error
    assert not calls


def test_changes_during_authentication_block_write(tmp_path, monkeypatch):
    from import_localize.services import google_service, mapping_sheet_service
    mapping, csv = inputs(tmp_path)
    snapshot = snapshots([mapping, csv])
    def connect(*args, **kwargs):
        mapping.write_text('{"changed": true}', encoding="utf-8")
        return object()
    calls = []
    monkeypatch.setattr(google_service, "connect_to_spreadsheet", connect)
    monkeypatch.setattr(mapping_sheet_service, "mark_wrong_mapping", lambda *a, **kw: calls.append("write"))
    worker = MappingWorker(mapping, [csv], keys={"wrong"}, snapshot=snapshot)
    worker.run()
    assert "đã thay đổi" in worker.error
    assert not calls


def test_mapping_selection_is_remembered_and_change_invalidates_report(app, tmp_path):
    mapping, csv = inputs(tmp_path)
    settings = AppSettings()
    dialog = MappingDialog(settings, [csv])
    dialog.report = report([csv])
    dialog.snapshot = snapshots([mapping, csv])
    dialog.mapping_edit.setText(str(mapping))
    assert dialog.report is None and dialog.snapshot is None
    assert not dialog.mark_button.isEnabled()
    dialog.reject()
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.save(settings)
    restored = repository.load()
    assert restored.mapping_path == str(mapping)
    assert restored.mapping_csv_files == [str(csv)]
    reopened = MappingDialog(restored)
    assert reopened.paths == [csv]
    reopened.reject()


def test_close_during_work_requests_cancel_and_preserves_worker_until_finished(app, tmp_path, monkeypatch):
    mapping, csv = inputs(tmp_path)
    def waiting_run(worker):
        deadline = time.monotonic() + 5
        while not worker.isInterruptionRequested() and time.monotonic() < deadline:
            time.sleep(.002)
        worker.error = "Đã dừng kiểm tra."
    monkeypatch.setattr(MappingWorker, "run", waiting_run)
    dialog = MappingDialog(AppSettings(mapping_path=str(mapping)), [csv])
    dialog.show()
    worker = MappingWorker(mapping, [csv], parent=dialog)
    dialog.launch(worker)
    assert not dialog.scan_button.isEnabled()
    assert not dialog.mark_button.isEnabled()
    dialog.reject()
    assert dialog.worker is worker
    drain(app, dialog)
    assert "Đã dừng" in dialog.status.text()
    assert dialog.scan_button.isEnabled()
    dialog.reject()
