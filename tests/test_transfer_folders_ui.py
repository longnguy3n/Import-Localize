from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui import main_window
from test_unity_locale import ASSET
from test_unity_locale_ui import app


def test_saved_folders_route_both_csv_roles_and_assets(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "config.json")
    repo.save(AppSettings(auto_check_updates=False, sheet_url="https://docs.google.com/spreadsheets/d/example/edit"))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    monkeypatch.setattr(main_window, "oauth_configuration_status", lambda: {"client_ready": True})
    monkeypatch.setattr(main_window, "preview_sheet_title", lambda *_: "DG")
    folder = tmp_path / "csv"
    folder.mkdir()
    assets = tmp_path / "assets"
    assets.mkdir()
    upload = folder / "DG - upload_en.csv"
    upload.write_text("Key,English\na,Hello\n")
    translated = folder / "DG - export_en.csv"
    translated.write_text("Key,English\na,Hello\n")
    (folder / "unrelated.csv").touch()
    asset = assets / "locale_en.asset"
    asset.write_text(ASSET)
    window = main_window.MainWindow()
    try:
        for role, path in (("upload", folder), ("export", folder), ("unity", assets)):
            monkeypatch.setattr(main_window.QFileDialog, "getExistingDirectory", lambda *_, p=path: str(p))
            window.folder_card.choose(role)
        assert window._ordered_file_paths() == (str(upload),)
        assert window.csv_page.folder.text() == str(folder)
        window.show_unity_locale()
        unity = window.workspace.pages[-1]
        assert unity.source_list.paths() == [translated] and unity.target_list.paths() == [asset]
        unity.mode_combo.setCurrentIndex(1)
        assert unity.source_list.paths() == [asset] and unity.target_list.paths() == [upload]
        window.show_direct_transfer()
        direct = window.workspace.pages[-1]
        assert direct.paths == [asset] and not direct.add_button.isEnabled()
        window.files_launcher.click()
        second = folder / "upload_vi.csv"
        second.write_text("Key,Vietnamese\na,Xin chào\n", encoding="utf-8")
        window.folder_card.rescan.click()
        window.target_mode_combo.setCurrentIndex(1)
        window.single_sheet_name_edit.setText("upload_vi")
        assert window.build_job().file_paths == (str(second),)
        assert window.file_table.item(1, 1).text() == "upload_vi"
    finally:
        window.close()
    reopened = main_window.MainWindow()
    try:
        assert reopened.folder_card.results["upload"][0] == (upload, second)
        assert reopened.folder_card.results["export"][0] == (translated,)
        assert reopened.folder_card.results["unity"][0] == (asset,)
        alias = folder / "Other - upload_vi.csv"
        alias.write_bytes(second.read_bytes())
        reopened.refresh_transfer_folders()
        assert reopened.folder_card.results["upload"][1] and not reopened._ordered_file_paths()
        assert not reopened.start_button.isEnabled()
        assert reopened.folder_card.results["export"][0] == (translated,)
        reopened.set_transfer_folder("upload", "")
        assert reopened.add_files_button.isEnabled() and alias.is_file()
    finally:
        reopened.close()
