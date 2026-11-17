from unittest.mock import patch
from PySide6.QtWidgets import QFileDialog

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui import main_window
from test_unity_locale_ui import app


def test_export_uses_visible_destination_and_survives_navigation(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "config.json")
    repo.save(AppSettings(auto_check_updates=False, csv_sheet_direction="download", card_sizes=[300, 160, 120]))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    window = main_window.MainWindow()
    window.show()
    try:
        assert window.start_button.isVisible() and window.download_export_tabs_button.isVisible()
        assert not window.start_button.isEnabled()
        assert not window.download_export_tabs_button.isEnabled()
        with patch.object(QFileDialog, "getExistingDirectory", return_value=str(tmp_path)):
            window.folder_card.choose("export")
        assert window.folder_card.rows["export"][0].text() == str(tmp_path)
        assert repo.load().last_export_dir == str(tmp_path)
        assert not window.download_export_tabs_button.isEnabled() and window.target_summary.isVisible()
        window.sheet_url_edit.setText("https://drive.google.com/open?id=test-sheet")
        assert window.target_summary.isHidden()
        assert window.download_export_tabs_button.isEnabled() and not window.start_button.isEnabled()
        window.direct_transfer_button.click()
        window.files_launcher.click()
        assert window.action_title_label.text() == "CSV ↔ Google Sheets"
        assert window.workspace.isHidden() and window.csv_page.isVisible()
        assert window.folder_card.rows["export"][0].isVisible() and window.folder_card.rows["export"][0].text() == str(tmp_path)
        with (patch.object(window, "_validate_sheet_action", return_value="test-sheet"),
              patch.object(main_window, "ExportTabsWorker") as worker):
            window.download_export_tabs_button.click()
            assert worker.call_args.args[:2] == ("test-sheet", str(tmp_path))
            worker.return_value.start.assert_called_once()
            assert not window.folder_card.isEnabled()
            assert window.stop_button.isVisible() and window.progress_bar.isVisible()
            assert window.start_button.isVisible() and window.download_export_tabs_button.isVisible()
            assert not window.start_button.isEnabled() and not window.download_export_tabs_button.isEnabled()
            window.set_running(False)
            window.on_worker_finished()
        assert window.download_export_tabs_button.isEnabled() and not window.stop_button.isVisible()
        csv = tmp_path / "upload_en.csv"
        csv.write_text("Key,English\na,Hello\n")
        window.set_transfer_folder("upload", str(tmp_path))
        window.set_transfer_folder("export", "")
        assert window.start_button.isEnabled() and not window.download_export_tabs_button.isEnabled()
        with patch.object(window, "build_job") as job, patch.object(main_window, "ImportWorker") as worker:
            window.progress_bar.setValue(100)
            window.start_button.click()
            assert worker.call_args.args[0] is job.return_value
            assert window.stop_button.isVisible() and window.progress_bar.value() == 0
            window.stop_button.click()
            worker.return_value.request_stop.assert_called_once()
            window.set_running(False)
            window.on_worker_finished()
        window.sheet_url_edit.setText("invalid-url")
        assert not window.start_button.isEnabled() and window.target_summary.isVisible()
        window.sheet_url_edit.clear()
        assert not window.start_button.isEnabled()
    finally:
        window.close()
