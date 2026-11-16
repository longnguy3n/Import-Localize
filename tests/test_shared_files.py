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

    def choose(dialog):
        dialog.csv_list.set_paths([upload])
        dialog.asset_list.set_paths([asset])
        dialog.accept()
        return dialog.result()

    try:
        window.show_direct_transfer()
        direct = window.workspace.pages[-1]
        direct.plan = object()
        monkeypatch.setattr(SharedFilesDialog, "exec", choose)
        window.shared_files_button.click()
        assert direct.paths == [asset] and direct.plan is None
        assert window._ordered_file_paths() == (str(upload),)
        assert repo.load().unity_asset_files == [str(asset)]
        window.show_unity_locale()
        unity = window.workspace.pages[-1]
        assert unity.asset_paths == [asset] and unity.csv_paths == []
        unity.mode_combo.setCurrentIndex(1)
        unity.use_uploads_action.trigger()
        assert unity.target_list.paths() == [upload]
        unity.set_assets([other_asset])

        def cancel(dialog):
            assert dialog.asset_list.paths() == [other_asset]
            dialog.asset_list.clear_files()
            dialog.csv_list.clear_files()
            dialog.reject()
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(SharedFilesDialog, "exec", cancel)
        window.shared_files_button.click()
        assert unity.asset_paths == [other_asset] and unity.target_list.paths() == [upload]
        assert window._ordered_file_paths() == (str(upload),)
    finally:
        window.close()
    assert repo.load().unity_asset_files == [str(other_asset)]
    assert repo.load().selected_csv_files == [str(upload)]
    assert repo.load().unity_export_csv_files == [str(upload)]


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
