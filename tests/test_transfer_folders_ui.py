from PySide6.QtWidgets import QFileDialog
from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui import main_window
from test_unity_locale import ASSET
from test_unity_locale_ui import app, drain


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
            monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_, p=path: str(p))
            window.folder_card.choose(role)
        assert tuple(window.file_infos) == (str(upload),)
        assert window.folder_card.rows["export"][0].text() == str(folder)
        window.show_unity_locale()
        unity = window.workspace.pages[-1]
        assert unity.csv_paths == [translated] and unity.asset_paths == [asset]
        unity.mode_combo.setCurrentIndex(1)
        assert unity.asset_paths == [asset] and unity.export_paths == [upload]
        window.show_direct_transfer()
        direct = window.workspace.pages[-1]
        assert direct.paths == [asset] and not direct.add_button.isEnabled()
        window.files_launcher.click()
        second = folder / "upload_vi.csv"
        second.write_text("Key,Vietnamese\na,Xin chào\n", encoding="utf-8")
        window.folder_card.rescan.click()
        assert window.build_job().file_paths == (str(upload), str(second))
        assert window.target_mode_combo.isHidden()
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
        assert reopened.folder_card.results["upload"][1] and not tuple(reopened.file_infos)
        assert not reopened.start_button.isEnabled()
        assert reopened.folder_card.results["export"][0] == (translated,)
        reopened.set_transfer_folder("upload", "")
        assert not reopened.start_button.isEnabled() and alias.is_file()
    finally:
        reopened.close()

def test_folder_preview_appears_only_after_diff_and_resets_on_switch(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "config.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    (tmp_path / "locale_en.asset").write_text(ASSET, encoding="utf-8")
    (tmp_path / "export_en.csv").write_text("Key,Type,Desc,English\n001,Text,,Changed\n", encoding="utf-8")
    window = main_window.MainWindow()
    try:
        window.set_transfer_folder("unity", str(tmp_path))
        window.set_transfer_folder("export", str(tmp_path))
        window.show()
        window.show_unity_locale()
        page = window.workspace.pages[-1]
        assert page.changes.isHidden() and page.pair_scroll.isHidden() and page.table.isHidden()
        page.preview_button.click()
        drain(app, page)
        assert page.changes.isVisible() and page.apply_button.isEnabled()
        assert [page.changes.item(0, col).text() for col in range(6)] == [
            "export_en.csv → locale_en.asset", "2 → 1", "0", "1", "1", "0"]
        assert page.source_metric.isHidden() and page.table.isHidden()
        page.mode_combo.setCurrentIndex(1)
        assert page.changes.isHidden() and not page.apply_button.isEnabled()
    finally:
        window.close()
