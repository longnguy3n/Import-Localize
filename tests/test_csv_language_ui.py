import time
from pathlib import Path

from PySide6.QtCore import QTimer

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui.csv_language_dialog import CsvLanguageDialog
from import_localize.ui.main_window import MainWindow
from import_localize.ui.unity_locale_dialog import UnityLocaleDialog
from test_csv_language import write_csv
from test_unity_locale_ui import app


def wait(app, dialog):
    deadline = time.monotonic() + 45
    while dialog.worker and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert dialog.worker is None


def test_dialog_results_filters_content_and_offline_worker(app, tmp_path):
    path = write_csv(tmp_path / "input.csv", [["Key", "Vietnamese"],
        ["wrong", "<color=red>Increase damage against enemies</color>"],
        ["right", "Tăng sát thương lên kẻ địch"], ["name", "Asmodeus"]])
    before = path.read_bytes()
    dialog = CsvLanguageDialog([path])
    dialog.show()
    ticks = []
    timer = QTimer()
    timer.setInterval(0)  # Cached model can finish this tiny fixture in <10 ms.
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    wait(app, dialog)
    timer.stop()
    assert ticks
    assert dialog.summary.rowCount() == 1
    assert dialog.summary.item(0, 5).text() == "1"
    assert dialog.model.rowCount() == 1
    dialog.table.selectRow(0)
    app.processEvents()
    assert "<color=red>" in dialog.content.toPlainText()
    assert "Tiếng Anh" in dialog.content.toPlainText()
    dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("all"))
    assert dialog.model.rowCount() == 3
    dialog.search.setText("name")
    assert dialog.model.rowCount() == 1
    dialog.search.clear()
    dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("unresolved"))
    assert dialog.model.rowCount() == 1
    assert dialog.progress.value() == dialog.progress.maximum()
    dialog.reject()
    assert path.read_bytes() == before


def test_close_while_scanning_cancels_and_joins_worker(app, tmp_path):
    path = write_csv(tmp_path / "input.csv", [["Key", "English"]] +
        [[str(i), "Increase damage against enemies"] for i in range(500)])
    dialog = CsvLanguageDialog([path])
    dialog.reject()
    wait(app, dialog)
    assert dialog._closing and not dialog.isVisible()


def test_entrypoints_pass_selected_files_and_unity_csvs(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "settings.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr("import_localize.ui.main_window.SettingsRepository", lambda: repo)
    visits = []
    def fake_exec(dialog):
        visits.append(dialog.paths)
        dialog.reject()
        wait(app, dialog)
        return 0
    monkeypatch.setattr(CsvLanguageDialog, "exec", fake_exec)
    paths = [write_csv(tmp_path / f"{i}.csv", [["Key", "English"], ["a", "OK"]]) for i in range(2)]
    main = MainWindow()
    main.add_csv_files(list(map(str, paths)))
    main.file_table.selectRow(1)
    main.language_check_button.click()
    assert visits[-1] == [paths[1]]
    main.file_table.clearSelection()
    main.language_check_button.click()
    assert visits[-1] == paths
    unity = UnityLocaleDialog(main.settings, paths)
    unity.language_check_button.click()
    assert visits[-1] == paths
    unity.reject()
    main.close()
