"""Persist selections across actual settings reloads and Qt window lifetimes."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui.main_window import MainWindow
from import_localize.ui.unity_locale_dialog import UnityLocaleDialog
from import_localize.ui.locale_duplicate_dialog import LocaleDuplicateDialog


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


def test_saved_folder_is_rescanned_and_legacy_selection_is_ignored(app, tmp_path, monkeypatch):
    repository = SettingsRepository(tmp_path / "settings.json")
    old = tmp_path / "old.csv"
    old.write_text("Key,English\na,b\n")
    repository.save(AppSettings(auto_check_updates=False, selected_csv_files=[str(old)],
                                unity_asset_files=[str(tmp_path / "stale.asset")]))
    monkeypatch.setattr("import_localize.ui.main_window.SettingsRepository", lambda: repository)
    first = MainWindow()
    assert not first.file_infos and not first.start_button.isEnabled()
    first.show_direct_transfer()
    assert not first.workspace.pages[-1].paths
    first.set_transfer_folder("upload", str(tmp_path))
    first.close()
    new = tmp_path / "upload_en.csv"
    new.write_bytes(old.read_bytes())
    second = MainWindow()
    assert tuple(second.file_infos) == (str(new),)
    second.set_transfer_folder("upload", "")
    assert not second.file_infos
    second.close()


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
