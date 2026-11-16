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
        assert window.file_table.isColumnHidden(3)
        assert not window.start_button.isEnabled()
        window.quick_sheet_url_edit.setText('https://docs.google.com/spreadsheets/d/example/edit')
        assert window.sheet_url_edit.text() == window.quick_sheet_url_edit.text()
        window.sheet_url_edit.setText('https://docs.google.com/spreadsheets/d/other/edit')
        assert window.quick_sheet_url_edit.text() == window.sheet_url_edit.text()
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
