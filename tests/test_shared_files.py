from PySide6.QtWidgets import QDialog

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui import main_window
from import_localize.ui.shared_files_dialog import SharedFilesDialog
from test_unity_locale_ui import app


def test_shared_file_changes_follow_workflows_and_survive_restart(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    upload = tmp_path / "DG - upload_en.csv"
    upload.write_text("Key,English\na,Hello\n")
    asset = tmp_path / "locale_en.asset"
    asset.touch()
    other_asset = tmp_path / "locale_vi.asset"
    other_asset.touch()
    window = main_window.MainWindow()

    try:
        window.show_direct_transfer()
        direct = window.workspace.pages[-1]
        direct.plan = object()
        window.set_transfer_folder("unity", str(tmp_path))
        window.set_transfer_folder("upload", str(tmp_path))
        assert direct.paths == [asset, other_asset] and direct.plan is None
        assert direct.add_button.isHidden() and direct.folder_button.isHidden() and direct.table.isHidden()
        window.show_unity_locale()
        unity = window.workspace.pages[-1]
        unity.mode_combo.setCurrentIndex(1)
        assert unity.asset_paths == [asset, other_asset]
        assert unity.export_paths == [upload, tmp_path / "DG - upload_vi.csv"]
        assert unity.pair_scroll.isHidden() and unity.table.isHidden()
    finally:
        window.close()
    assert repo.load().unity_asset_files == [str(asset), str(other_asset)]
    assert repo.load().selected_csv_files == [str(upload)]


def test_shared_file_order_and_clear_are_scoped_to_current_list(app, tmp_path):
    csvs = [tmp_path / (name + ".csv") for name in ("one", "two")]
    assets = [tmp_path / "locale_en.asset"]
    for csv in csvs:
        csv.write_text("Key,English\na,Hello\n")
    dialog = SharedFilesDialog(csvs, assets, AppSettings())
    dialog.csv_list.setCurrentRow(1)
    dialog.up_button.click()
    assert dialog.csv_list.paths() == list(reversed(csvs))
    dialog.tabs.setCurrentIndex(1)
    dialog.clear_button.click()
    dialog.accept()
    assert [info.path for info in dialog.csv_infos] == list(reversed(csvs))
    assert dialog.asset_list.paths() == []
