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
        mapping = window.workspace.pages[-1]
        check_settings_visible()
        window.target_settings_button.click()
        assert window.workspace.pages[-1] is mapping
        assert mapping.settings is window.settings
        window.sheet_url_edit.setText("https://drive.google.com/open?id=first")
        assert mapping.annotations is marks
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
        direct.add_paths([asset])
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
        paths = [tmp_path / name for name in ("old.csv", "new.csv")]
        for path in paths:
            path.write_text("Key,English\nhello,Hello\n", encoding="utf-8")
        window.add_csv_files([str(path) for path in paths])
        window.file_table.selectAll()
        window.compare_selected_files()
        compare = window.workspace.pages[-1]
        for attempt in range(2):
            if attempt:
                compare.swap_button.click()
            assert not window.settings_button.isEnabled()
            assert not window.shared_files_button.isEnabled()
            QTest.keyClick(window, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
            assert not window.quick_sheet_url_edit.hasFocus()
            assert compare.worker.wait(5000)
            app.processEvents()
            assert window.settings_button.isEnabled()
            assert window.shared_files_button.isEnabled()
            assert window.workspace.pages[-1] is compare
            QTest.keyClick(window, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
            assert window.quick_sheet_url_edit.hasFocus()
    finally:
        window.close()


def test_mapping_marks_follow_link_and_global_clear(app, tmp_path, monkeypatch):
    from test_mapping_ui import report

    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    monkeypatch.setattr(main_window, "preview_sheet_title", lambda _: "Test")
    window = main_window.MainWindow()
    try:
        window.sheet_url_edit.setText("https://drive.google.com/open?id=first")
        window.check_mapping()
        mapping = window.workspace.pages[-1]
        mapping.report = report([tmp_path / "upload_vi.csv"])
        mapping.render_report()
        mapping.issues_table.selectRow(0)
        mapping.mark()
        assert mapping.issues_table.item(0, 3).text() == "vi"
        assert window.clear_desc_action.isEnabled()
        window.sheet_url_edit.setText("https://drive.google.com/open?id=second")
        assert mapping.issues_table.item(0, 3).text() == "—"
        assert not window.clear_desc_action.isEnabled()
        window.sheet_url_edit.setText("https://drive.google.com/open?id=first")
        assert mapping.issues_table.item(0, 3).text() == "vi"
        window.clear_desc_action.trigger()
        assert mapping.issues_table.item(0, 3).text() == "—"
        assert not window.clear_desc_action.isEnabled()
    finally:
        window.close()
