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
        assert window.csv_page.isVisible()
        window.show_unity_locale()
        tool = window.workspace.pages[-1]
        assert tool.isVisible() and tool.window() is window
        assert not window.csv_page.isVisible()
        assert not window.start_button.isVisible() and window.log_card.isVisible()
        assert window.action_title_label.text() == "Replace Import · CSV → Unity"
        assert window.action_card.isAncestorOf(tool.preview_status)
        assert window.action_card.isAncestorOf(tool.apply_button)
        assert tool.preview_status.isVisible() and not tool.progress.isVisible()
        tool.mode_combo.setCurrentIndex(1)
        assert window.action_title_label.text() == "Replace Export · Unity → CSV"
        assert not tool.pair_scroll.isVisible() and not tool.changes.isVisible()
        assert not tool.duplicates_button.isEnabled()
        window.files_launcher.click()
        assert window.csv_page.isVisible() and not window.workspace.pages
        assert window.start_button.isVisible() and window.target_summary.isVisible()
        assert window.action_pages.count() == 1
        assert not window.start_button.isEnabled()
        window.quick_sheet_url_edit.setText('https://docs.google.com/spreadsheets/d/example/edit')
        assert window.sheet_url_edit.text() == window.quick_sheet_url_edit.text()
        window.sheet_url_edit.setText('https://docs.google.com/spreadsheets/d/other/edit')
        assert window.quick_sheet_url_edit.text() == window.sheet_url_edit.text()
        window.direct_transfer_button.click()
        tool = window.workspace.pages[-1]
        tool.direction_combo.setCurrentIndex(tool.direction_combo.findData("download"))
        assert tool.window() is window and tool.direction == "download"
        assert window.action_title_label.text() == "Google Sheets → Unity"
        assert tool.apply_button.isVisible() and not tool.stop_button.isVisible()
        assert not window.download_export_tabs_button.isVisible()
        window.quick_sheet_url_edit.setText('https://drive.google.com/open?id=another')
        assert tool.url == window.quick_sheet_url_edit.text()
        window.direct_transfer_button.click()
        assert window.workspace.pages[-1] is tool and tool.direction == "download"
        tool.direction_combo.setCurrentIndex(tool.direction_combo.findData("upload"))
        assert tool.direction == "upload"
        assert window.action_title_label.text() == "Unity → Google Sheets"
        window.files_launcher.click()
        window.sheet_url_edit.setText('https://docs.google.com/spreadsheets/d/other/edit')
        first = tmp_path / "upload_en.csv"
        first.write_text("Key,English\na,Hello\n")
        window.set_transfer_folder("upload", str(tmp_path))
        assert window.compare_action.isEnabled() and window.language_action.isEnabled()
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
        window.append_log('FAIL', 'Example failure for UI test')
        assert window.log_toggle.isChecked()
        assert window.log_placeholder.isVisible()
    finally:
        window.close()
    reopened = main_window.MainWindow()
    try:
        assert reopened.log_toggle.isChecked()
        assert reopened.folder_card.results["upload"][0] == (first,)
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
        mapping = app.activeModalWidget()
        assert mapping.isWindow() and mapping.scan_button.isVisible()
        assert mapping.files_button.isHidden() and mapping.folder_button.isHidden()
        mapping.focus_button.click()
        assert mapping.mark_button.isVisible()
        mapping.focus_button.click()
        mapping.close_button.click()
        window.direct_transfer_button.click()
        direct = window.workspace.pages[-1]
        window.language_action.trigger()
        language = app.activeModalWidget()
        assert language.paths == [] and language.choose_button.isHidden()
        assert window.workspace.pages == [direct]
        language.reject()
        window.compare_action.trigger()
        compare = app.activeModalWidget()
        assert compare.isWindow() and compare.worker is None and not compare.swap_button.isEnabled()
        assert "hai CSV" in compare.summary_label.text()
        compare.reject()
        assert window.workspace.pages == [direct]
    finally:
        window.close()
