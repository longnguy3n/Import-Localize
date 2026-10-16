"""Persist selections across actual settings reloads and Qt window lifetimes."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui.main_window import MainWindow
from import_localize.ui.unity_locale_dialog import UnityLocaleDialog
from import_localize.ui.locale_duplicate_dialog import LocaleDuplicateDialog
from test_unity_locale_ui import app


def test_unity_remembers_order_mode_and_new_export_targets(app, tmp_path):
    repository = SettingsRepository(tmp_path / "settings.json")
    settings = AppSettings()
    csvs = [tmp_path / "first.csv", tmp_path / "second.csv"]
    assets = [tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"]
    outputs = [tmp_path / "new_en.csv", tmp_path / "new_vi.csv"]
    dialog = UnityLocaleDialog(settings, csvs)
    dialog.set_assets(assets)
    dialog.source_list.setCurrentRow(1)
    dialog.source_list.move_selected(-1)
    dialog.mode_combo.setCurrentIndex(1)
    dialog.export_paths = outputs
    dialog._refresh_lists()
    dialog.reject()
    repository.save(settings)
    restored = UnityLocaleDialog(repository.load(), [tmp_path / "unrelated.csv"])
    assert not restored.importing()
    assert restored.source_list.paths() == assets
    assert restored.target_list.paths() == outputs  # These files need not exist yet.
    assert "Thiếu file" not in restored.target_list.item(0).text()
    restored.mode_combo.setCurrentIndex(0)
    assert restored.source_list.paths() == list(reversed(csvs))
    assert restored.target_list.paths() == assets
    assert restored.plan is None and not restored.apply_button.isEnabled()
    restored.reject()


def test_unity_keeps_missing_pair_positions_and_remembers_clear(app, tmp_path):
    repository = SettingsRepository(tmp_path / "settings.json")
    csvs = [tmp_path / "missing.csv", tmp_path / "exists.csv"]
    csvs[1].write_text("Key,English\na,b\n")
    assets = [tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"]
    settings = AppSettings(unity_import_csv_files=list(map(str, csvs)), unity_asset_files=list(map(str, assets)))
    dialog = UnityLocaleDialog(settings)
    assert dialog.source_list.paths() == csvs
    assert dialog.target_list.paths() == assets
    assert "Thiếu file" in dialog.source_list.item(0).text()
    assert "Thiếu file" not in dialog.source_list.item(1).text()
    dialog.source_list.clear_files()
    dialog.target_list.clear_files()
    dialog.reject()
    repository.save(settings)
    reopened = UnityLocaleDialog(repository.load(), csvs)
    assert reopened.csv_paths == [] and reopened.asset_paths == []
    reopened.reject()


def test_main_csv_order_removal_and_clear_survive_restart(app, tmp_path, monkeypatch):
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr("import_localize.ui.main_window.SettingsRepository", lambda: repository)
    paths = [tmp_path / f"file_{i}.csv" for i in range(3)]
    for path in paths:
        path.write_text("Key,English\na,b\n")
    first = MainWindow()
    first.add_csv_files(list(map(str, paths)))
    first.file_table.selectRow(2)
    first.move_selected_files(-1)
    first.file_table.clearSelection()
    first.file_table.selectRow(0)
    first.remove_selected_files()
    first.close()
    second = MainWindow()
    assert [Path(second.file_table.item(i, 0).data(Qt.ItemDataRole.UserRole))
            for i in range(second.file_table.rowCount())] == [paths[2], paths[1]]
    second.clear_files()
    second.close()
    third = MainWindow()
    assert third.file_table.rowCount() == 0
    third.close()


def test_missing_main_csv_does_not_interrupt_startup(app, tmp_path, monkeypatch):
    repository = SettingsRepository(tmp_path / "settings.json")
    path = tmp_path / "valid.csv"
    path.write_text("Key,English\na,b\n")
    repository.save(AppSettings(auto_check_updates=False,
        selected_csv_files=[str(tmp_path / "missing.csv"), str(path)]))
    monkeypatch.setattr("import_localize.ui.main_window.SettingsRepository", lambda: repository)
    def unexpected_popup(*args):
        raise AssertionError("Restoration must report missing files in the log")
    monkeypatch.setattr("import_localize.ui.main_window.QMessageBox.warning", unexpected_popup)
    window = MainWindow()
    assert window.file_table.rowCount() == 1
    assert any("missing.csv" in label.text() for label in window.log_edit.findChildren(QLabel))
    window.close()


def test_duplicate_remembers_exact_subset_instead_of_whole_folder(app, tmp_path):
    repository = SettingsRepository(tmp_path / "settings.json")
    paths = [tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"]
    for path in paths:
        path.touch()
    settings = AppSettings(unity_locale_dir=str(tmp_path))
    first = LocaleDuplicateDialog([paths[1]], settings=settings)
    first.reject()
    repository.save(settings)
    second = LocaleDuplicateDialog([], settings=repository.load())
    assert second.paths == [paths[1]]
    second.reject()


def test_old_settings_and_invalid_path_lists(tmp_path):
    repository = SettingsRepository(tmp_path / "settings.json")
    repository.path.write_text('{"unity_locale_dir": "old-folder"}')
    assert repository.load().unity_import_csv_files is None
    repository.path.write_text('{"selected_csv_files": [null, 4, "", "a.csv", "a.csv"], '
                               '"unity_asset_files": null, "unity_import_csv_files": "bad"}')
    settings = repository.load()
    assert settings.selected_csv_files == ["a.csv"]
    assert settings.unity_asset_files == []
    assert settings.unity_import_csv_files == []
