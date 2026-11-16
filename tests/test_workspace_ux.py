"""Workspace navigation and preference regression checks, with no network."""
from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui import main_window
from test_unity_locale_ui import app


def test_inline_target_tools_log_and_preferences(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / 'config.json')
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, 'SettingsRepository', lambda: repo)
    window = main_window.MainWindow()
    window.show()
    app.processEvents()
    try:
        assert window.log_placeholder.isHidden()
        assert window.file_table.isVisible()
        window.show_unity_locale()
        tool = window.workspace.pages[-1]
        assert tool.isVisible() and tool.window() is window
        assert not window.file_table.isVisible()
        assert not window.start_button.isVisible() and window.log_card.isVisible()
        assert window.action_title_label.text() == "Replace Import · CSV → Unity"
        assert window.action_card.isAncestorOf(tool.preview_status)
        assert window.action_card.isAncestorOf(tool.apply_button)
        assert tool.preview_status.isVisible() and not tool.progress.isVisible()
        tool.mode_combo.setCurrentIndex(1)
        assert window.action_title_label.text() == "Replace Export · Unity → CSV"
        tool.duplicates_button.click()
        duplicate = window.workspace.pages[-1]
        assert window.action_title_label.text() == duplicate.windowTitle()
        assert duplicate.scan_button.isVisible() and not tool.preview_status.isVisible()
        duplicate.close_button.click()
        assert window.workspace.pages[-1] is tool and tool.preview_status.isVisible()
        assert window.action_title_label.text() == "Replace Export · Unity → CSV"
        window.files_launcher.click()
        assert window.file_table.isVisible() and not window.workspace.pages
        assert window.start_button.isVisible() and window.target_summary.isVisible()
        assert window.action_pages.count() == 1
        assert window.file_table.isColumnHidden(3)
        assert not window.start_button.isEnabled()
        window.quick_sheet_url_edit.setText('https://docs.google.com/spreadsheets/d/example/edit')
        assert window.sheet_url_edit.text() == window.quick_sheet_url_edit.text()
        window.sheet_url_edit.setText('https://docs.google.com/spreadsheets/d/other/edit')
        assert window.quick_sheet_url_edit.text() == window.sheet_url_edit.text()
        window.direct_download_button.click()
        tool = window.workspace.pages[-1]
        assert tool.window() is window and tool.direction == "download"
        assert window.action_title_label.text() == "Google Sheets → Unity"
        assert tool.apply_button.isVisible() and not tool.stop_button.isVisible()
        assert not window.download_export_tabs_button.isVisible()
        window.quick_sheet_url_edit.setText('https://drive.google.com/open?id=another')
        assert tool.url == window.quick_sheet_url_edit.text()
        window.direct_upload_button.click()
        assert window.workspace.pages[-1].direction == "upload"
        assert window.action_title_label.text() == "Unity → Google Sheets"
        window.files_launcher.click()
        window.sheet_url_edit.setText('https://docs.google.com/spreadsheets/d/other/edit')
        first, second = tmp_path / 'en.csv', tmp_path / 'vi.csv'
        for path in (first, second):
            path.write_text('Key,English\na,Hello\n')
        window.add_csv_files([str(first), str(second)])
        window.file_table.selectAll()
        assert window.compare_action.isEnabled() and window.language_action.isEnabled()
        calls = []
        window.compare_files_button.clicked.disconnect()
        window.compare_files_button.clicked.connect(lambda: calls.append('compare'))
        window.compare_action.trigger()
        assert calls == ['compare']
        window.set_running(True)
        assert not window.quick_sheet_url_edit.isEnabled()
        assert not window.csv_tools_button.isEnabled()
        window.set_running(False)
        assert window.quick_sheet_url_edit.isEnabled()
        # A completion signal can arrive while QThread still reports running.
        class FinishingWorker:
            def isRunning(self):
                return True
        window.worker = FinishingWorker()
        window.set_running(False)
        assert not window.start_button.isEnabled()
        window.on_worker_finished()
        assert window.start_button.isEnabled()
        assert window.compare_action.isEnabled()
        window.technical_columns_action.setChecked(True)
        window.append_log('FAIL', 'Example failure for UI test')
        assert window.log_toggle.isChecked()
        assert window.log_placeholder.isVisible()
    finally:
        window.close()
    reopened = main_window.MainWindow()
    try:
        assert reopened.log_toggle.isChecked()
        assert not reopened.file_table.isColumnHidden(3)
        assert reopened.quick_sheet_url_edit.text().endswith('/other/edit')
    finally:
        reopened.close()


def test_audit_actions_follow_active_view(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "config.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    window = main_window.MainWindow()
    window.show()
    try:
        window.check_mapping()
        mapping = window.workspace.pages[-1]
        assert window.action_title_label.text() == mapping.windowTitle()
        assert mapping.scan_button.isVisible() and window.action_card.isAncestorOf(mapping.scan_button)
        mapping.focus_button.click()
        assert not window.action_card.isVisible() and mapping.mark_button.isVisible()
        mapping.focus_button.click()
        assert mapping.scan_button.isVisible()
        mapping.close_button.click()

        window.check_csv_languages()
        language = window.workspace.pages[-1]
        assert window.action_title_label.text() == language.windowTitle()
        assert window.action_card.isAncestorOf(language.scan_button)
        assert language.scan_button.isVisible() and not language.progress.isVisible()
        language.close_button.click()

        paths = [tmp_path / name for name in ("old.csv", "new.csv")]
        for path in paths:
            path.write_text("Key,English\nhello,Hello\n", encoding="utf-8")
        window.add_csv_files([str(path) for path in paths])
        window.file_table.selectAll()
        window.compare_action.trigger()
        compare = window.workspace.pages[-1]
        assert compare.worker.wait(5000)
        app.processEvents()
        assert window.action_title_label.text() == compare.windowTitle()
        assert window.action_card.isAncestorOf(compare.summary_label)
        assert compare.swap_button.isVisible() and compare.swap_button.isEnabled()
        compare.swap_button.click()
        assert compare.worker.wait(5000)
        app.processEvents()
        assert compare.paths == (str(paths[1]), str(paths[0]))
        window.files_launcher.click()
        assert window.start_button.isVisible() and window.action_pages.count() == 1
    finally:
        window.close()
