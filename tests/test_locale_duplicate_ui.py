from PySide6.QtWidgets import QTextBrowser
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

from import_localize.ui import locale_duplicate_dialog
from import_localize.ui.locale_duplicate_dialog import LocaleDuplicateDialog
from import_localize.services.locale_duplicate_service import scan_duplicates
from test_locale_duplicates import duplicate_asset
from test_unity_locale_ui import app, drain
from import_localize.config.settings import AppSettings
from import_localize.config.settings import SettingsRepository
from import_localize.ui.main_window import MainWindow
from import_localize.ui.unity_locale_dialog import UnityLocaleDialog


def test_check_choose_then_cleanup(app, tmp_path, monkeypatch):
    monkeypatch.setattr(locale_duplicate_dialog, "USER_CONFIG_DIR", tmp_path / "config")
    path = tmp_path / "locale_en.asset"
    original, _, _ = duplicate_asset(path, conflict=True)
    dialog = LocaleDuplicateDialog([path])
    dialog.show()
    dialog.scan()
    drain(app, dialog)
    assert dialog.groups.rowCount() == 1
    assert not dialog.apply_button.isEnabled()
    assert dialog.keep_combo.currentData() is None
    texts = [dialog.variants.widget(i).findChild(QTextBrowser).toPlainText()
             for i in range(dialog.variants.count())]
    assert len(texts) == 2 and "other" in texts[1]
    assert "English (en)" in texts[0] and "Có khác biệt" in texts[0]
    assert '"Term"' not in texts[0] and '"Languages"' not in texts[0]
    assert "Flags" not in texts[0] and "Languages_Touch" not in texts[0]
    assert path.read_bytes() == original
    dialog.keep_combo.setCurrentIndex(2)
    assert dialog.apply_button.isEnabled()
    dialog.keep_combo.setCurrentIndex(0)
    assert not dialog.apply_button.isEnabled()
    dialog.keep_combo.setCurrentIndex(2)
    dialog.apply_button.click()
    drain(app, dialog)
    assert dialog.wrote_files and dialog.backup_path.is_dir()
    assert not scan_duplicates([path]).groups
    assert not dialog.apply_button.isEnabled()
    assert "Đã xóa 1" in dialog.summary.text()
    dialog.scan()
    drain(app, dialog)
    assert "Không có duplicate" in dialog.status.text()
    dialog.reject()


def test_identical_needs_no_choice_cancel_does_not_write(app, tmp_path):
    path = tmp_path / "locale_en.asset"
    original, _, _ = duplicate_asset(path)
    dialog = LocaleDuplicateDialog([path])
    dialog.scan()
    drain(app, dialog)
    assert dialog.apply_button.isEnabled()
    assert not dialog.keep_combo.isEnabled()
    dialog.reject()
    assert path.read_bytes() == original


def test_stale_file_requires_rescan(app, tmp_path):
    path = tmp_path / "locale_en.asset"
    duplicate_asset(path)
    dialog = LocaleDuplicateDialog([path])
    dialog.scan()
    drain(app, dialog)
    changed = path.read_bytes() + b"\n"
    path.write_bytes(changed)
    dialog.apply_button.click()
    drain(app, dialog)
    assert "LỖI" in dialog.status.text() and "đã thay đổi" in dialog.status.text()
    assert not dialog.wrote_files and not dialog.apply_button.isEnabled()
    assert path.read_bytes() == changed
    dialog.reject()


def test_entry_invalidates_import_preview_after_cleanup(app, tmp_path, monkeypatch):
    monkeypatch.setattr(locale_duplicate_dialog, "USER_CONFIG_DIR", tmp_path / "config")
    path = tmp_path / "locale_en.asset"
    duplicate_asset(path)
    csv = tmp_path / "translated.csv"
    csv.write_text("Key,English\n001,new\n")
    parent = UnityLocaleDialog(AppSettings(), [csv])
    parent.set_assets([path])
    parent.preview()
    drain(app, parent)
    assert parent.plan is not None
    def use_dialog(dialog):
        drain(app, dialog)
        assert dialog.apply_button.isEnabled()
        dialog.cleanup()
        drain(app, dialog)
        return 0
    monkeypatch.setattr(LocaleDuplicateDialog, "exec", use_dialog)
    parent.duplicates_button.click()
    assert parent.plan is None and not parent.apply_button.isEnabled()
    assert parent.backup_path.is_dir() and parent.backup_button.isEnabled()
    parent.reject()


def test_all_conflicts_must_be_chosen_before_any_write(app, tmp_path):
    paths = [tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"]
    originals = [duplicate_asset(path, conflict=True)[0] for path in paths]
    dialog = LocaleDuplicateDialog(paths)
    dialog.scan()
    drain(app, dialog)
    dialog.keep_combo.setCurrentIndex(1)
    assert not dialog.apply_button.isEnabled()
    # A decision automatically advances to the next unresolved group.
    assert dialog.groups.currentRow() == 1
    dialog.keep_combo.setCurrentIndex(2)
    assert dialog.apply_button.isEnabled()
    dialog.groups.selectRow(0)
    assert dialog.keep_combo.currentData() == 0
    dialog.reject()


def test_click_advances_once_and_can_revisit_previous_choice(app, tmp_path):
    paths = [tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"]
    originals = [duplicate_asset(path, conflict=True)[0] for path in paths]
    dialog = LocaleDuplicateDialog(paths)
    dialog.show()
    dialog.scan()
    drain(app, dialog)
    QTest.mouseClick(dialog.variants.widget(1).content.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert dialog.groups.currentRow() == 1
    assert dialog.choices == {(paths[0], "001"): 1}
    assert dialog.keep_combo.currentData() is None
    assert not dialog.apply_button.isEnabled()
    QTest.mouseClick(dialog.variants.widget(0).title, Qt.MouseButton.LeftButton)
    assert dialog.groups.currentRow() == 1  # last conflict stays visible
    assert dialog.apply_button.isEnabled()
    assert dialog.choices[(paths[1], "001")] == 0
    dialog.groups.selectRow(0)
    assert dialog.keep_combo.currentData() == 1
    assert dialog.variants.widget(1).property("selected")
    assert [path.read_bytes() for path in paths] == originals
    dialog.reject()
    assert [path.read_bytes() for path in paths] == originals


def test_click_content_or_heading_selects_and_highlights_variant(app, tmp_path):
    path = tmp_path / "locale_en.asset"
    original, _, _ = duplicate_asset(path, conflict=True)
    dialog = LocaleDuplicateDialog([path])
    dialog.show()
    dialog.scan()
    drain(app, dialog)
    first, second = dialog.variants.widget(0), dialog.variants.widget(1)
    assert not first.property("selected") and not second.property("selected")
    QTest.mouseClick(second.content.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert dialog.keep_combo.currentData() == 1 and dialog.apply_button.isEnabled()
    assert second.property("selected") and "GIỮ BẢN NÀY" in second.title.text()
    QTest.mouseClick(first.title, Qt.MouseButton.LeftButton)
    assert dialog.keep_combo.currentData() == 0
    assert first.property("selected") and not second.property("selected")
    dialog.keep_combo.setCurrentIndex(2)
    assert second.property("selected") and not first.property("selected")
    dialog.show_group()
    assert dialog.keep_combo.currentData() == 1
    first, second = dialog.variants.widget(0), dialog.variants.widget(1)
    assert second.property("selected")
    dialog.keep_combo.setCurrentIndex(0)
    assert not first.property("selected") and not second.property("selected")
    assert not dialog.apply_button.isEnabled()
    assert path.read_bytes() == original
    dialog.reject()


def test_duplicate_folder_saved_and_automatically_reused_after_restart(app, tmp_path, monkeypatch):
    folder = tmp_path / "Localization"
    folder.mkdir()
    assets = [folder / "locale_en.asset", folder / "locale_vi.asset"]
    for asset in assets:
        duplicate_asset(asset)
    (folder / "not_locale.asset").write_text("ignore")
    (folder / "locale_directory.asset").mkdir()
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr("import_localize.ui.main_window.SettingsRepository", lambda: repository)
    monkeypatch.setattr(locale_duplicate_dialog.QFileDialog, "getExistingDirectory", lambda *_: str(folder))
    visits = []
    def duplicate_exec(dialog):
        if not visits:
            dialog.choose_folder()
        drain(app, dialog)
        assert dialog.paths == assets
        assert str(folder) in dialog.folder_label.text()
        assert dialog.scan_result is not None
        visits.append(True)
        dialog.reject()
        return 0
    def unity_exec(dialog):
        assert not dialog.asset_paths
        dialog.check_duplicates()
        dialog.reject()
        return 0
    monkeypatch.setattr(LocaleDuplicateDialog, "exec", duplicate_exec)
    monkeypatch.setattr(UnityLocaleDialog, "exec", unity_exec)
    window = MainWindow()
    window.show_unity_locale()
    window.close()
    assert repository.load().unity_locale_dir == str(folder)
    def unexpected_picker(*_):
        raise AssertionError("Should reuse the saved folder without asking")
    monkeypatch.setattr(locale_duplicate_dialog.QFileDialog, "getExistingDirectory", unexpected_picker)
    monkeypatch.setattr(locale_duplicate_dialog.QFileDialog, "getOpenFileNames", unexpected_picker)
    reopened = MainWindow()
    reopened.show_unity_locale()
    reopened.close()
    assert len(visits) == 2


def test_duplicate_file_picker_remembers_folder_and_cancel_keeps_it(app, tmp_path, monkeypatch):
    asset = tmp_path / "locale_en.asset"
    duplicate_asset(asset)
    settings = AppSettings(unity_locale_dir=str(tmp_path / "old"))
    dialog = LocaleDuplicateDialog([], settings=settings)
    directories = []
    def picker(*args):
        directories.append(args[2])
        return ([str(asset)], "") if len(directories) == 1 else ([], "")
    monkeypatch.setattr(locale_duplicate_dialog.QFileDialog, "getOpenFileNames", picker)
    dialog.choose_files()
    drain(app, dialog)
    assert settings.unity_locale_dir == str(tmp_path)
    dialog.choose_files()
    assert dialog.paths == [asset] and settings.unity_locale_dir == str(tmp_path)
    assert directories == [str(tmp_path / "old"), str(tmp_path)]
    dialog.reject()


def test_saved_missing_or_empty_folder_and_explicit_selection(app, tmp_path):
    settings = AppSettings(unity_locale_dir=str(tmp_path / "missing"))
    missing = LocaleDuplicateDialog([], settings=settings)
    assert not missing.paths and "không còn tồn tại" in missing.status.text()
    missing.reject()
    settings.unity_locale_dir = str(tmp_path)
    empty = LocaleDuplicateDialog([], settings=settings)
    assert not empty.paths and "không có locale" in empty.status.text()
    empty.reject()
    first, second = tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"
    duplicate_asset(first)
    duplicate_asset(second)
    explicit = LocaleDuplicateDialog([second], settings=settings)
    assert explicit.paths == [second]  # explicit selection takes priority over saved folder
    explicit.reject()
