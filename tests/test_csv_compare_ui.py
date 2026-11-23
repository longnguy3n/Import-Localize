"""Offline Qt integration checks; settings are isolated from the real account."""
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel, QTimer, Qt
from PySide6.QtWidgets import QApplication

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.ui.csv_compare_dialog import CsvCompareDialog
from import_localize.ui.dialogs import SettingsDialog
from import_localize.ui.main_window import MainWindow


def drain_worker(app, dialog):
    deadline = time.monotonic() + 10
    while dialog.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert dialog.worker is None


@pytest.fixture
def csv_pair(tmp_path):
    old, new = tmp_path / "old.csv", tmp_path / "new.csv"
    old.write_text("key,en,vi\na,Hi,Chào\nb,Bye,Tạm biệt\n", encoding="utf-8")
    new.write_text("key,en,vi\nc,New,Mới\nb,Goodbye,Tạm biệt\na,Hi,Chào\n", encoding="utf-8")
    return str(old), str(new)


def test_compare_filter_details_swap_and_close(app, csv_pair):
    dialog = CsvCompareDialog(*csv_pair)
    dialog.show()
    drain_worker(app, dialog)
    assert dialog.result.count("added") == 1
    assert dialog.result.count("changed") == 1
    assert dialog.model.rowCount() == 3
    dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("added"))
    assert {diff.key for diff, _ in dialog.model.rows} == {"c"}
    assert "New" in dialog.diff_view.toPlainText() and "+" in dialog.diff_view.toPlainText()
    dialog.search_edit.setText("missing")
    assert dialog.model.rowCount() == 0
    dialog.search_edit.clear()
    dialog._swap()
    drain_worker(app, dialog)
    assert dialog.result.count("removed") == 1
    assert dialog.model.rowCount() == 0
    dialog.reject()
    assert not dialog.isVisible()


def test_close_during_load_and_read_error(app, csv_pair):
    dialog = CsvCompareDialog(*csv_pair)
    dialog.show()
    dialog.reject()
    drain_worker(app, dialog)
    assert not dialog.isVisible()
    dialog = CsvCompareDialog("missing.csv", csv_pair[1])
    drain_worker(app, dialog)
    assert dialog.result is None
    assert "Không tìm thấy" in dialog.summary_label.text()
    dialog.reject()


def test_main_selection_settings_persistence_and_layout(app, csv_pair, tmp_path):
    repository = SettingsRepository(tmp_path / "config.json")
    repository.save(AppSettings(auto_check_updates=False))
    with patch("import_localize.ui.main_window.SettingsRepository", return_value=repository), patch("import_localize.ui.dialogs.SettingsRepository", return_value=repository):
        window = MainWindow()
        window.show()
        for _ in range(10):
            app.processEvents()
        window.files_launcher.click()
        assert window.target_form.isHidden()
        assert window.cards_splitter.indexOf(window.target_card) == -1
        assert window.csv_tools_button.isVisible()
        assert [a.text() for a in window.csv_tools_button.menu().actions()] == [
            "Kiểm tra mapping", "Nhận diện ngôn ngữ", "Kiểm tra key trùng trong asset…", "So sánh hai CSV…"]
        for attempt in range(2):
            observed = []
            def edit_settings():
                dialog = QApplication.activeModalWidget()
                if not isinstance(dialog, SettingsDialog):
                    return
                observed.append(dialog.settings_tabs.count() == 2 and dialog.settings_tabs.currentWidget().isAncestorOf(window.target_form))
                window.sheet_url_edit.setText("https://docs.google.com/spreadsheets/d/example/edit")
                assert window.target_mode_combo.isHidden()
                dialog.update_repository_edit.setText("example/localize")
                dialog.accept()
            QTimer.singleShot(30, edit_settings)
            QTimer.singleShot(2000, lambda: QApplication.activeModalWidget() and QApplication.activeModalWidget().reject())
            window.show_settings()
            assert observed == [True]
            assert window.target_form.isHidden()
            assert window.target_form.parent() is window
            saved = repository.load()
            assert saved.target_mode == "multiple"
            assert saved.update_repository == "example/localize"
            assert saved.sheet_url.endswith("example/edit")
        window.close()


def test_card_resize_minimum_and_restore(app, tmp_path):
    repository = SettingsRepository(tmp_path / "config.json")
    repository.save(AppSettings(auto_check_updates=False))
    with patch("import_localize.ui.main_window.SettingsRepository", return_value=repository):
        window = MainWindow()
        window.show()
        for _ in range(10):
            app.processEvents()
        splitter = window.cards_splitter
        assert splitter.count() == 2
        assert splitter.widget(0).isAncestorOf(window.workspace)
        assert splitter.widget(0).isAncestorOf(window.action_card) and splitter.widget(1).isAncestorOf(window.log_card)
        splitter.moveSplitter(splitter.height(), 1)
        app.processEvents()
        assert window.log_card.height() >= window.log_card.minimumHeight()
        splitter.setSizes([445, 230])
        splitter.moveSplitter(splitter.sizes()[0] - 15, 1)
        app.processEvents()
        saved = repository.load().card_sizes
        assert saved == splitter.sizes()
        window.close()
        reopened = MainWindow()
        reopened.show()
        for _ in range(10):
            app.processEvents()
        assert all(abs(a - b) <= 2 for a, b in zip(saved, reopened.cards_splitter.sizes()))
        reopened.show_unity_locale()
        for _ in range(10):
            app.processEvents()
        floor = reopened.workflow_frame.minimumHeight()
        reopened.cards_splitter.moveSplitter(1, 1)
        assert reopened.workflow_frame.height() >= floor
        reopened.show_files()
        for _ in range(10):
            app.processEvents()
        assert all(abs(a - b) <= 2 for a, b in zip(saved, reopened.cards_splitter.sizes()))
        reopened.close()


def test_sort_all_columns_keeps_detail_mapping_and_status_colors(app, csv_pair):
    dialog = CsvCompareDialog(*csv_pair)
    dialog.show()
    drain_worker(app, dialog)
    dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("all"))
    for column in range(5):
        for order in (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder):
            dialog.table.sortByColumn(column, order)
            proxy = dialog.sort_model
            for row in range(proxy.rowCount()):
                index = proxy.index(row, 0)
                dialog.table.setCurrentIndex(index)
                source = proxy.mapToSource(index)
                diff, col = dialog.model.rows[source.row()]
                assert diff.key in dialog.detail_label.text()
                assert diff.after[col] in dialog.diff_view.toPlainText()
                assert dialog.model.data(source, Qt.ItemDataRole.BackgroundRole) is not None
            values = [proxy.index(row, column).data(Qt.ItemDataRole.UserRole + 1) for row in range(proxy.rowCount())]
            expected = sorted(values, key=lambda value: (value.casefold(), value) if isinstance(value, str) else (value,), reverse=order == Qt.SortOrder.DescendingOrder)
            assert values == expected
    dialog.search_edit.setText("b")
    assert dialog.sort_model.rowCount() == 1
    assert "Goodbye" in dialog.diff_view.toPlainText() and "Bye" in dialog.diff_view.toPlainText()
    dialog.reject()
