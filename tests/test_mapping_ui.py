"""Mapping review UI and write guards; no live Google calls."""
from pathlib import Path
from types import SimpleNamespace
import time

from PySide6.QtWidgets import QMessageBox

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui.mapping_dialog import MappingDialog, MappingWorker, snapshots
from test_unity_locale_ui import app


def test_mapping_source_and_detail_panels_open_when_needed(app, tmp_path):
    _, csv = inputs(tmp_path)
    dialog = MappingDialog(AppSettings(), [csv])
    try:
        assert not dialog.source_panel.isHidden()
        assert dialog.detail.isHidden() and dialog.progress.isHidden()
        dialog.report = report([csv])
        dialog.render_report()
        assert dialog.source_panel.isHidden()
        dialog.issues_table.selectRow(0)
        assert not dialog.detail.isHidden()
        dialog.mark()  # A missing Sheet URL must reveal the field to fix it.
        assert not dialog.source_panel.isHidden()
        assert "Nhập link Google Sheet" in dialog.status.text()
        dialog.set_busy(True)
        assert not dialog.progress.isHidden() and not dialog.stop_button.isHidden()
        dialog.set_busy(False)
        assert dialog.progress.isHidden() and dialog.stop_button.isHidden()
    finally:
        dialog.reject()


def test_mark_history_survives_reopen_is_scoped_to_sheet_and_unchecks_only_completed(app, tmp_path):
    from import_localize.config.mapping_history import MappingHistoryRepository
    from import_localize.services.mapping_sheet_service import MappingKeyResult, MappingMarkResult
    mapping, csv = inputs(tmp_path)
    repo = MappingHistoryRepository(tmp_path / "history.json")
    settings = AppSettings(mapping_path=str(mapping), sheet_url="https://docs.google.com/spreadsheets/d/sheet-one/edit")
    dialog = MappingDialog(settings, [csv], history_repository=repo)
    try:
        dialog.report = report([csv])
        dialog.render_report()
        dialog.select_visible()
        dialog.on_mark_result(settings.sheet_url, MappingMarkResult(key_results=(
            MappingKeyResult("cf_hp_title", "written", 2, 2, 2),
            MappingKeyResult("cf_story_desc", "uncertain", 0, 1, 0, 1))))
        assert dialog.selected_keys == {"cf_story_desc"}
        assert "Đã ghi" in dialog.issues_table.item(0, 3).text()
        assert "2/2 hàng" in dialog.issues_table.item(0, 3).text()
        assert "Chưa rõ kết quả" in dialog.issues_table.item(1, 3).text()
        dialog.search.setText("cf_hp_title")
        assert "Đã ghi" in dialog.issues_table.item(0, 3).text()
        dialog.sheet_edit.setText("https://docs.google.com/spreadsheets/d/sheet-two/edit")
        assert dialog.issues_table.item(0, 3).text() == "Chưa kiểm tra"
        dialog.sheet_edit.setText(settings.sheet_url + "#gid=42")
        assert "Đã ghi" in dialog.issues_table.item(0, 3).text()
    finally:
        dialog.reject()
    reopened = MappingDialog(settings, [csv], history_repository=MappingHistoryRepository(repo.path))
    try:
        reopened.report = report([csv])
        reopened.render_report()
        assert "Đã ghi" in reopened.issues_table.item(0, 3).text()
        assert "Chưa rõ kết quả" in reopened.issues_table.item(1, 3).text()
        # Live feedback supersedes an old success if the Sheet was edited.
        reopened.on_mark_result(settings.sheet_url, MappingMarkResult(key_results=(
            MappingKeyResult("cf_hp_title", "pending", 0, 2),)))
        assert "Chưa ghi" in reopened.issues_table.item(0, 3).text()
    finally:
        reopened.reject()


def test_history_save_error_does_not_lose_live_status(app, tmp_path, monkeypatch):
    from import_localize.config.mapping_history import MappingHistoryRepository
    from import_localize.services.mapping_sheet_service import MappingKeyResult, MappingMarkResult
    _, csv = inputs(tmp_path)
    repo = MappingHistoryRepository(tmp_path / "history.json")
    dialog = MappingDialog(AppSettings(sheet_url="https://docs.google.com/spreadsheets/d/sheet-one"), [csv], history_repository=repo)
    def fail_save(data):
        raise OSError("disk unavailable")
    monkeypatch.setattr(repo, "save", fail_save)
    try:
        dialog.report = report([csv])
        dialog.render_report()
        dialog.on_mark_result(dialog.sheet_edit.text(), MappingMarkResult(key_results=(
            MappingKeyResult("cf_hp_title", "already", 1, 1),)))
        assert "Đã có sẵn" in dialog.issues_table.item(0, 3).text()
        assert "Không lưu được lịch sử" in dialog.history_error
    finally:
        dialog.reject()


def test_worker_partial_error_keeps_per_key_feedback_on_gui(app, tmp_path, monkeypatch):
    from import_localize.config.mapping_history import MappingHistoryRepository
    from import_localize.services import google_service, mapping_sheet_service
    from import_localize.services.mapping_sheet_service import MappingKeyResult, MappingMarkResult
    mapping, csv = inputs(tmp_path)
    settings = AppSettings(mapping_path=str(mapping), sheet_url="https://docs.google.com/spreadsheets/d/test-target")
    dialog = MappingDialog(settings, [csv], history_repository=MappingHistoryRepository(tmp_path / "history.json"))
    monkeypatch.setattr(google_service, "connect_to_spreadsheet", lambda *a, **kw: object())
    def mark(*args, result_callback, **kwargs):
        result_callback(MappingMarkResult(updated_rows=1, key_results=(
            MappingKeyResult("cf_hp_title", "written", 1, 1, 1),
            MappingKeyResult("cf_story_desc", "uncertain", 0, 1, 0, 1))))
        raise google_service.GoogleServiceError("Mất phản hồi ở lô cuối")
    monkeypatch.setattr(mapping_sheet_service, "mark_wrong_mapping", mark)
    try:
        dialog.report = report([csv])
        dialog.snapshot = snapshots([mapping, csv])
        dialog.render_report()
        dialog.select_visible()
        dialog.launch(MappingWorker(mapping, [csv], keys=set(dialog.selected_keys),
                      sheet_url=settings.sheet_url, snapshot=dialog.snapshot, parent=dialog))
        drain(app, dialog)
        assert "Mất phản hồi" in dialog.status.text()
        assert "Đã ghi" in dialog.issues_table.item(0, 3).text()
        assert "Chưa rõ kết quả" in dialog.issues_table.item(1, 3).text()
        assert dialog.selected_keys == {"cf_story_desc"}
        assert "written" == dialog.history_repository.load()["test-target"]["cf_hp_title"]["status"]
    finally:
        dialog.reject()


def test_themed_resize_handles_and_focused_table_restore(app, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    paths = [tmp_path / f"DG_Localization - upload_{code}.csv" for code in ("en", "vi", "pt-BR")]
    dialog = MappingDialog(AppSettings(), paths)
    dialog.setStyleSheet((Path(__file__).parents[1] / "src/themes/light.qss").read_text(encoding="utf-8"))
    try:
        dialog.report = report(paths)
        dialog.render_report()
        dialog.set_busy(False)
        dialog.resize(740, 720)
        dialog.show()
        QTest.qWait(120)
        for table in (dialog.files_table, dialog.issues_table):
            header = table.horizontalHeader()
            before = table.columnWidth(0)
            edge = header.sectionViewportPosition(0) + before - 1
            QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(edge, 18))
            QTest.mouseMove(header.viewport(), QPoint(edge + 45, 18))
            QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(edge + 45, 18))
            assert table.columnWidth(0) > before
        dialog.fit_button.click()
        QTest.qWait(120)
        for column in range(dialog.files_table.columnCount()):
            text = dialog.files_table.horizontalHeaderItem(column).text()
            assert dialog.files_table.columnWidth(column) >= dialog.files_table.horizontalHeader().fontMetrics().horizontalAdvance(text) + 24
        dialog.issues_table.setColumnWidth(2, 333)
        dialog.issues_table.selectRow(0)
        old_size = dialog.size()
        dialog.focus_button.click()
        app.processEvents()
        assert dialog.isFullScreen() and dialog.focus_mode
        assert dialog.setup_panel.isHidden() and dialog.files_table.isHidden()
        assert dialog.issues_table.isVisible() and dialog.search.isVisible()
        assert dialog.focus_button.isVisible()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        QTest.qWait(120)
        assert not dialog.isFullScreen() and not dialog.focus_mode
        assert dialog.setup_panel.isVisible() and dialog.files_table.isVisible()
        assert dialog.size() == old_size
        assert dialog.issues_table.columnWidth(2) == 333
        assert dialog.issues_table.currentRow() == 0
    finally:
        if dialog.focus_mode:
            dialog.toggle_focus_mode()
        dialog.reject()


def inputs(tmp_path):
    mapping = tmp_path / "mapping.json"
    mapping.write_text("{}", encoding="utf-8")
    csv = tmp_path / "export_vi.csv"
    csv.write_text("Key,Vietnamese\nwrong,HP\n", encoding="utf-8")
    return mapping, csv


def test_ctrl_shift_checkboxes_filter_selection_and_fullscreen_mark(app, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    mapping, csv = inputs(tmp_path)
    dialog = MappingDialog(AppSettings(mapping_path=str(mapping), sheet_url="https://example.invalid"), [csv])
    dialog.report = report([csv])
    dialog.snapshot = snapshots([mapping, csv])
    dialog.render_report()
    dialog.set_busy(False)
    dialog.resize(1180, 1000)
    dialog.show()
    QTest.qWait(150)
    table = dialog.issues_table
    def click(row, column=2, modifier=Qt.KeyboardModifier.NoModifier):
        table.scrollToItem(table.item(row, column))
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, modifier,
                         table.visualItemRect(table.item(row, column)).center())
    try:
        click(0)
        click(1, modifier=Qt.KeyboardModifier.ControlModifier)
        assert dialog.selected_keys == {"cf_hp_title", "cf_story_desc"}
        click(0, 0)
        assert dialog.selected_keys == {"cf_story_desc"}
        click(0, 0)
        assert len(dialog.selected_keys) == 2
        dialog.clear_selection_button.click()
        click(0)
        click(1, modifier=Qt.KeyboardModifier.ShiftModifier)
        assert len(dialog.selected_keys) == 2
        dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("review"))
        assert dialog.selected_keys == {"cf_hp_title", "cf_story_desc"}
        assert "1 đang ẩn" in dialog.selection_label.text()
        dialog.clear_selection_button.click()
        dialog.select_visible_button.click()
        assert dialog.selected_keys == {"cf_story_desc"}
        launched, confirmations = [], []
        def confirm(*args):
            confirmations.append(args[-1])
            return QMessageBox.StandardButton.Yes
        monkeypatch.setattr(QMessageBox, "question", confirm)
        monkeypatch.setattr(dialog, "launch", launched.append)
        dialog.focus_button.click()
        app.processEvents()
        assert dialog.mark_button.isVisible() and dialog.mark_button.isEnabled()
        dialog.mark_button.click()
        assert len(launched) == 1 and launched[0].keys == {"cf_story_desc"}
        assert "1 key thuộc nhóm Cần xem ngữ cảnh" in confirmations[0]
        launched[0].deleteLater()
    finally:
        if dialog.focus_mode:
            dialog.toggle_focus_mode()
        dialog.reject()


def test_table_outer_edge_fills_viewport_and_shift_wheel_is_horizontal(app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from import_localize.ui.mapping_dialog import MappingTable
    from PySide6.QtWidgets import QTableWidgetItem
    table = MappingTable(4)
    table.setHorizontalHeaderLabels(["A", "B", "C", "D"])
    table.setRowCount(30)
    for row in range(30):
        table.setItem(row, 0, QTableWidgetItem("text"))
    table.resize(800, 350)
    table.show()
    QTest.qWait(120)
    try:
        for column in range(4):
            table.setColumnWidth(column, 100)
        app.processEvents()
        assert abs(table.horizontalHeader().length() - table.viewport().width()) <= 2
        for column in range(4):
            table.setColumnWidth(column, 400)
        app.processEvents()
        y = table.verticalScrollBar().value()
        event = QWheelEvent(QPointF(30, 30), QPointF(30, 30), QPoint(), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ShiftModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        app.sendEvent(table.viewport(), event)
        assert table.horizontalScrollBar().value() > 0
        assert table.verticalScrollBar().value() == y
    finally:
        QTest.keyRelease(table, Qt.Key.Key_Shift)
        table.close()


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
        assert not dialog.mark_button.isEnabled()
        dialog.files_table.selectRow(1)
        assert dialog.issues_table.rowCount() == 1
        assert dialog.issues_table.columnCount() == 7
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


def test_one_key_row_has_one_column_per_file_including_same_language(app, tmp_path):
    from import_localize.services.mapping_audit_service import MappingIssue, MappingRecord, MappingReport
    en, vi, pt = [tmp_path / f"export_{code}.csv" for code in ("en", "vi", "pt-BR")]
    other = tmp_path / "upload_vi.csv"
    result = MappingReport(tmp_path / "mapping.json", files=[en, vi, pt, other],
        records=[MappingRecord(p, 2, "same_key", {code: value}, ()) for p, code, value in (
            (en, "en", "Damage"), (vi, "vi", "Wrong\ntranslation"),
            (pt, "pt-BR", "DNO"), (other, "vi", "Another version"))],
        issues=[MappingIssue(vi, 2, "same_key", "vi", "Damage", "Wrong\ntranslation", "ST", "Wrong label", "wrong"),
                MappingIssue(other, 2, "same_key", "vi", "Damage", "Another version", "ST", "Wrong label", "wrong")])
    dialog = MappingDialog(AppSettings(), [en, vi, pt])
    try:
        dialog.report = result
        dialog.render_report()
        assert dialog.issues_table.rowCount() == 1
        assert dialog.issues_table.columnCount() == 9
        assert dialog.issues_table.item(0, 4).text() == "Damage"
        assert dialog.issues_table.item(0, 6).text() == "DNO"
        text = dialog.issues_table.item(0, 5).text()
        assert dialog.issues_table.horizontalHeaderItem(5).text() == "export_vi.csv"
        assert dialog.issues_table.horizontalHeaderItem(7).text() == "upload_vi.csv"
        assert text == "Wrong\ntranslation"
        assert dialog.issues_table.item(0, 7).text() == "Another version"
        dialog.files_table.selectRow(1)
        assert dialog.issues_table.rowCount() == 1
        assert dialog.issues_table.item(0, 4).text() == "Damage"
        assert dialog.issues_table.item(0, 6).text() == "DNO"
        dialog.issues_table.selectRow(0)
        assert str(pt) in dialog.detail.toPlainText()
        dialog.show()
        for column in range(dialog.issues_table.columnCount()):
            dialog.issues_table.setColumnWidth(column, 300)
        app.processEvents()
        assert dialog.issues_table.horizontalScrollBar().maximum() > 0
        dialog.search.setText("same_key")
        assert dialog.issues_table.columnWidth(3) == 300
    finally:
        dialog.reject()


def test_mark_uses_only_selected_review_key(app, tmp_path, monkeypatch):
    mapping, csv = inputs(tmp_path)
    settings = AppSettings(mapping_path=str(mapping), sheet_url="https://docs.google.com/spreadsheets/d/example")
    dialog = MappingDialog(settings, [csv])
    try:
        dialog.report = report([csv])
        dialog.snapshot = snapshots([mapping, csv])
        dialog.render_report()
        dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("review"))
        dialog.issues_table.selectRow(0)
        launched = []
        confirmations = []
        monkeypatch.setattr(QMessageBox, "question", lambda *args: confirmations.append(args[2]) or QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(dialog, "launch", launched.append)
        dialog.mark()
        assert "Công thức riêng tại các ô C" in confirmations[0]
        assert "giá trị cố định Wrong mapping" in confirmations[0]
        assert len(launched) == 1
        worker = launched[0]
        assert worker.keys == {"cf_story_desc"}
        assert "cf_hp_title" not in worker.keys
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
        dialog.render_report()
        dialog.issues_table.selectRow(0)
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
