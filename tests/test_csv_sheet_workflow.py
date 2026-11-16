from unittest.mock import patch

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui import main_window
from test_unity_locale_ui import app


def test_export_uses_visible_destination_and_survives_navigation(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "config.json")
    repo.save(AppSettings(auto_check_updates=False, card_sizes=[300, 160, 120]))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    window = main_window.MainWindow()
    window.show()
    try:
        page = window.csv_page
        page.direction.setCurrentIndex(1)
        assert not window.file_table.isVisible() and page.folder.isVisible()
        assert window.download_export_tabs_button.isVisible() and not window.start_button.isVisible()
        with patch.object(main_window.QFileDialog, "getExistingDirectory", return_value=str(tmp_path)):
            page.choose_folder.click()
        assert page.folder.text() == str(tmp_path)
        assert repo.load().last_export_dir == str(tmp_path)
        window.direct_transfer_button.click()
        window.files_launcher.click()
        assert window.action_title_label.text() == page.direction.currentText()
        assert page.folder.isVisible() and page.folder.text() == str(tmp_path)
        with (patch.object(window, "_validate_sheet_action", return_value="test-sheet"),
              patch.object(main_window, "ExportTabsWorker") as worker):
            window.download_export_tabs_button.click()
            assert worker.call_args.args[:2] == ("test-sheet", str(tmp_path))
            worker.return_value.start.assert_called_once()
            assert not page.direction.isEnabled() and not page.choose_folder.isEnabled()
            window.on_worker_finished()
            window.set_running(False)
        page.direction.setCurrentIndex(0)
        assert window.file_table.isVisible() and window.start_button.isVisible()
        assert not window.download_export_tabs_button.isVisible()
    finally:
        window.close()
