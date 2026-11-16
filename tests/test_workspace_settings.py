from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui import main_window
from test_unity_locale_ui import app
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


def test_settings_edit_keeps_active_tool_and_shared_state(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    monkeypatch.setattr(main_window, "preview_sheet_title", lambda _: "Test")
    edits = []

    def edit_settings(dialog):
        assert dialog.settings is window.settings
        edits.append(dialog)
        dialog.update_repository_edit.setText("example/localize")
        dialog.accept()

    monkeypatch.setattr(main_window.SettingsDialog, "exec", edit_settings)
    window = main_window.MainWindow()
    window.resize(660, 620)
    window.show()
    app.processEvents()

    def check_settings_visible():
        for button in (window.settings_button, window.target_settings_button):
            assert button.isVisible() and button.isEnabled()
            assert window.rect().contains(button.mapTo(window, button.rect().center()))
    try:
        window.show_unity_locale()
        unity = window.workspace.pages[-1]
        unity.mode_combo.setCurrentIndex(1)
        window.sheet_url_edit.setText("https://drive.google.com/open?id=first")
        marks = window.desc_annotations
        marks.set_mark("vi", "hello", "Wrong mapping")
        assert unity.desc_annotations is marks
        unity.plan = object()
        window.sheet_url_edit.setText("https://drive.google.com/open?id=second")
        assert unity.plan is None
        assert unity.desc_annotations is window.desc_annotations
        assert not unity.desc_annotations.has("vi", "hello", "Wrong mapping")
        check_settings_visible()
        window.settings_button.click()
        assert window.workspace.pages[-1] is unity
        assert unity.settings is window.settings
        window.check_mapping()
        from import_localize.ui.mapping_dialog import MappingDialog
        mapping = window.findChild(MappingDialog)
        assert mapping.isWindow() and mapping.settings is window.settings
        mapping.reject()
        window.target_settings_button.click()
        assert window.workspace.pages == [unity]
        window.sheet_url_edit.setText("https://drive.google.com/open?id=first")
        assert unity.desc_annotations is marks
        window.show_direct_transfer()
        direct = window.workspace.pages[-1]
        check_settings_visible()
        assert direct.annotations is marks
        plan = direct.plan = object()
        window.settings_button.click()
        assert window.workspace.pages[-1] is direct and len(edits) == 3
        assert direct.plan is plan
        def change_input_mode(dialog):
            window.value_input_combo.setCurrentIndex(1)
            dialog.accept()
        monkeypatch.setattr(main_window.SettingsDialog, "exec", change_input_mode)
        window.target_settings_button.click()
        assert direct.plan is None and not direct.apply_button.isEnabled()
        asset = tmp_path / "locale_en.asset"
        asset.touch()
        window.set_transfer_folder("unity", str(tmp_path))
        window.show_files()
        assert repo.load().unity_asset_files == [str(asset)]
        assert repo.load().update_repository == "example/localize"
    finally:
        window.close()


def test_settings_unlock_after_embedded_worker(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    window = main_window.MainWindow()
    window.show()
    window.activateWindow()
    app.processEvents()
    try:
        for name in ("upload_en.csv", "export_en.csv"):
            (tmp_path / name).write_text("Key,English\nhello,Hello\n", encoding="utf-8")
        window.set_transfer_folder("upload", str(tmp_path))
        window.set_transfer_folder("export", str(tmp_path))
        window.compare_selected_files()
        compare = app.activeModalWidget()
        assert compare.window() is compare and window.workspace.pages == []
        for attempt in range(2):
            if attempt:
                compare.swap_button.click()
            assert compare.worker.wait(5000)
            app.processEvents()
            assert compare.swap_button.isEnabled()
        compare.reject()
        assert window.settings_button.isEnabled() and window.folder_card.isEnabled()
    finally:
        window.close()


def test_popup_marks_remain_scoped_to_sheet(app, tmp_path, monkeypatch):
    from test_mapping_ui import report

    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    monkeypatch.setattr(main_window, "preview_sheet_title", lambda _: "Test")
    window = main_window.MainWindow()
    try:
        window.sheet_url_edit.setText("https://drive.google.com/open?id=first")
        window.check_mapping()
        from import_localize.ui.mapping_dialog import MappingDialog
        mapping = window.findChild(MappingDialog)
        mapping.report = report([tmp_path / "upload_vi.csv"])
        mapping.render_report()
        mapping.issues_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        mapping.mark()
        assert mapping.issues_table.item(0, 3).text() == "vi"
        assert "1 dấu Desc" in window.csv_tools_button.text()
        mapping.reject()
        window.sheet_url_edit.setText("https://drive.google.com/open?id=second")
        assert window.csv_tools_button.text() == "Kiểm tra dữ liệu"
        window.sheet_url_edit.setText("https://drive.google.com/open?id=first")
        assert window.desc_annotations.has("vi", mapping.visible_keys[0], "Wrong mapping")
    finally:
        window.close()


def test_shared_unity_mapping_reads_assets_and_keeps_active_workflow(app, tmp_path, monkeypatch):
    from pathlib import Path
    from import_localize.ui.mapping_dialog import MappingDialog
    from test_unity_locale import ASSET
    from test_unity_locale_ui import drain

    mapping_path = Path(__file__).parent / "fixtures" / "mapping_v2.json"
    assets = [tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"]
    for path, code, name, value in zip(assets, ("en", "vi"), ("English", "Vietnamese"), ("DMG", "wrong")):
        path.write_text(ASSET.replace("Code: en", "Code: " + code).replace("Name: English", "Name: " + name)
                        .replace("Term: 001", "Term: cf_damage_title").replace("- yes", "- " + value), encoding="utf-8")
    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(AppSettings(auto_check_updates=False, unity_folder=str(tmp_path), mapping_path=str(mapping_path)))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    window = main_window.MainWindow()
    try:
        window.show_direct_transfer()
        page = window.workspace.pages[-1]
        page.direction_combo.setCurrentIndex(page.direction_combo.findData("upload"))
        page.plan = object()
        window.csv_tools_button.menu().aboutToShow.emit()
        action = window.audit_source_actions["mapping", "unity"]
        assert action.isEnabled() and "2 tệp" in action.text()
        assert not window.audit_source_actions["mapping", "export"].isEnabled()
        action.trigger()
        popup = window.findChild(MappingDialog)
        assert popup.paths == assets and page.audit_button.isHidden()
        popup.scan()
        drain(app, popup)
        assert popup.report.files == assets and "cf_damage_title" in popup.report.wrong_keys
        popup.select_visible()
        popup.mark()
        assert window.desc_annotations.has("vi", "cf_damage_title", "Wrong mapping")
        popup.reject()
        assert window.workspace.pages == [page] and page.plan is None
        assert not list(tmp_path.glob("*.csv"))
    finally:
        window.close()
