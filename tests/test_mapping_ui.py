"""Mapping review UI and write guards; no live Google calls."""
from pathlib import Path
from types import SimpleNamespace
import time

from import_localize.services.desc_annotations import DescAnnotations, WRONG_MAPPING

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui.mapping_dialog import MappingDialog, MappingWorker, snapshots


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
        dialog.mark()
        assert dialog.source_panel.isHidden()
        assert dialog.annotations.has("vi", "cf_hp_title", WRONG_MAPPING)
        dialog.set_busy(True)
        assert not dialog.progress.isHidden() and not dialog.stop_button.isHidden()
        dialog.set_busy(False)
        assert dialog.progress.isHidden() and dialog.stop_button.isHidden()
    finally:
        dialog.reject()


def test_annotate_snapshot_then_reopen_without_touching_files(app, tmp_path):
    mapping = Path(__file__).parent / "fixtures" / "mapping_v2.json"
    sources = {Path("upload_en.csv"): b"Key,English\ncf_damage_title,DMG\n",
               Path("upload_vi.csv"): b"Key,Vietnamese\ncf_damage_title,wrong\n"}
    annotations = DescAnnotations()
    settings = AppSettings(mapping_path=str(mapping), mapping_csv_files=["remembered.csv"])
    dialog = MappingDialog(settings, sources=sources, annotations=annotations)
    try:
        dialog.scan()
        drain(app, dialog)
        assert dialog.report.wrong_keys == {"cf_damage_title"}
        dialog.select_visible()
        dialog.mark()
        assert annotations.has("vi", "cf_damage_title", WRONG_MAPPING)
        assert not annotations.has("en", "cf_damage_title", WRONG_MAPPING)
        assert not dialog.selected_keys
    finally:
        dialog.reject()
    assert settings.mapping_csv_files == ["remembered.csv"]
    reopened = MappingDialog(settings, sources=sources, annotations=annotations)
    try:
        reopened.scan()
        drain(app, reopened)
        assert reopened.issues_table.item(0, 3).text() == "vi"
        reopened.select_visible()
        reopened.unmark()
        assert not annotations
    finally:
        reopened.reject()


def test_themed_resize_handles_and_focused_table_restore(app, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    paths = [tmp_path / f"DG_Localization - upload_{code}.csv" for code in ("en", "vi", "pt-BR")]
    dialog = MappingDialog(AppSettings(), paths)
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
        dialog.focus_button.click()
        app.processEvents()
        assert dialog.mark_button.isVisible() and dialog.mark_button.isEnabled()
        dialog.mark_button.click()
        assert dialog.annotations.has("vi", "cf_story_desc", WRONG_MAPPING)
        assert not dialog.annotations.has("vi", "cf_hp_title", WRONG_MAPPING)
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
        assert dialog.detail.isHidden()
        assert dialog.results.reset_button.isVisible()
        dialog.files_table.selectRow(0)
        dialog.results.reset_button.click()
        assert dialog.issues_table.isVisible() and dialog.issues_table.rowCount() == 2
        assert not dialog.search.text() and not dialog.files_table.selectedItems()
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


def test_changed_source_blocks_staging_old_result(app, tmp_path):
    mapping, path = inputs(tmp_path)
    dialog = MappingDialog(AppSettings(mapping_path=str(mapping)), [path])
    try:
        dialog.report = report([path])
        dialog.render_report()
        dialog.snapshot = snapshots([mapping, path])
        path.write_text("changed", encoding="utf-8")
        dialog.select_visible()
        dialog.mark()
        assert "đã thay đổi" in dialog.status.text()
        assert not dialog.annotations
    finally:
        dialog.reject()


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
