from PySide6.QtWidgets import QFileDialog
from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui import main_window
from import_localize.ui.transfer_folders_card import TransferFoldersCard
from test_unity_locale import ASSET
from test_unity_locale_ui import app, drain


def test_folder_card_distinguishes_unset_empty_and_invalid_folders(app, tmp_path, monkeypatch):
    settings = AppSettings(upload_folder=str(tmp_path), export_folder=str(tmp_path))
    card = TransferFoldersCard(settings)
    changes = []
    card.changed.connect(lambda role, folder: changes.append((role, folder)))
    try:
        card.show()
        upload_field, upload_count, upload_action = card.rows["upload"]
        assert upload_field.text() == str(tmp_path)
        assert upload_count.text() == "0 tệp"
        assert "upload_<mã>.csv" in upload_count.menu().actions()[0].text()
        assert card.rows["unity"][1].isHidden()
        assert card.rows["unity"][2].menu() is None
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(tmp_path / "other"))
        upload_action.click()
        upload_action.menu().actions()[0].trigger()
        assert changes == [("upload", str(tmp_path / "other")), ("upload", "")]
        card.toggle.setChecked(False)
        issue = "Hai tệp upload trùng mã en."
        card.set_result("upload", (), (issue,))
        assert card.toggle.isChecked()
        assert card.issue_labels["upload"].isVisible() and card.issue_labels["upload"].text() == issue
        card.toggle.setChecked(False)
        card.set_result("upload", (), (issue,))
        assert not card.toggle.isChecked() and "1 lỗi" in card.summary.text()
        card.set_result("upload", (tmp_path / "upload_en.csv",), ())
        assert card.issue_labels["upload"].isHidden()
        assert card.summary.text() == "Upload 1 · Export 0 · Unity —"
    finally:
        card.close()


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
        assert [page.changes.item(0, col).text() for col in range(7)] == [
            "export_en.csv", "locale_en.asset", "2 → 1", "0", "1", "1", "0"]
        assert page.source_metric.isHidden() and page.table.isHidden()
        page.mode_combo.setCurrentIndex(1)
        assert page.changes.isHidden() and not page.apply_button.isEnabled()
    finally:
        window.close()


def test_preview_count_colors_follow_theme_and_keep_filenames_readable(app):
    from import_localize.app.paths import THEMES_DIR
    from import_localize.services.unity_locale_service import ChangeStats
    from import_localize.ui.change_colors import STATUS_COLORS, STATUS_COLORS_DARK
    from import_localize.ui.transfer_preview import TransferPreview

    preview = TransferPreview()
    preview.resize(1100, 150)
    try:
        preview.show_changes([("export_en.csv", "locale_en.asset", ChangeStats(
            10, 9, 10, 2, 1, 3, 5, "CSV", "term"), "Chi tiết")])
        for theme, colors in (("light", STATUS_COLORS), ("dark", STATUS_COLORS_DARK)):
            preview.setStyleSheet((THEMES_DIR / f"{theme}.qss").read_text(encoding="utf-8"))
            app.processEvents()
            for column, status in enumerate(("added", "removed", "changed", "unchanged"), 3):
                cell = preview.visualItemRect(preview.item(0, column))
                image = preview.viewport().grab(cell).toImage()
                # Check the painted badge: global QSS can override ordinary item backgrounds.
                background = colors[status][0]
                assert any(image.pixelColor(x, image.height() // 2).name() == background
                           for x in range(image.width()))
        preview.resize(320, 150)
        app.processEvents()
        assert preview.columnWidth(0) >= preview.fontMetrics().horizontalAdvance("locale_pt-BR.asset")
        assert preview.columnWidth(1) >= preview.fontMetrics().horizontalAdvance("locale_pt-BR.asset")
        assert preview.horizontalScrollBar().maximum() > 0
    finally:
        preview.close()
