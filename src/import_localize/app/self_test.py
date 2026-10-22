"""Frozen application startup check, isolated from user settings and Google."""
from __future__ import annotations

import json
import os
import tempfile
import time
import traceback
from pathlib import Path


def run_self_test(report_path: str) -> int:
    report = {"status": "failed"}
    try:
        with tempfile.TemporaryDirectory(prefix="import-localize-self-test-") as directory:
            os.environ["APPDATA"] = directory
            os.environ["XDG_CONFIG_HOME"] = directory
            from PySide6.QtCore import qVersion
            from import_localize.app.bootstrap import create_application
            from import_localize.ui.main_window import MainWindow
            from import_localize.ui.csv_compare_dialog import ComparisonModel
            from import_localize.services.csv_compare_service import compare_csv_files
            from import_localize.ui.unity_locale_dialog import UnityLocaleDialog
            from import_localize.ui.locale_duplicate_dialog import LocaleDuplicateDialog
            from import_localize.services.locale_duplicate_service import scan_duplicates
            from import_localize.services.unity_locale_service import (
                prepare_export, prepare_import_pairs, apply_plan, read_asset,
            )

            app = create_application(["Import_Localize self-test"])
            window = MainWindow()
            window.settings.auto_check_updates = False
            window.ensurePolished()
            app.processEvents()
            assert window.cards_splitter.count() == 3, "Missing main window cards"
            assert window.file_table.columnCount() == 5, "Missing CSV table"
            assert not window.grab().isNull(), "Main window could not render"
            before, after = Path(directory) / "old.csv", Path(directory) / "new.csv"
            before.write_text("key,en\na,Old\n", encoding="utf-8")
            after.write_text("key,en\na,New\nb,Added\n", encoding="utf-8")
            comparison = compare_csv_files(before, after)
            model = ComparisonModel()
            model.filter(comparison, "differences", "")
            assert comparison.count("added") == 1 and model.rowCount() == 2
            locale = Path(directory) / "locale_en.asset"
            locale.write_text(
                "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"
                "--- !u!114 &11400000\nMonoBehaviour:\n  mSource:\n"
                "    mTerms:\n    - Term: greeting\n      TermType: 0\n"
                "      Description: Test\n      Languages:\n      - Hello\n"
                "      Flags: 00\n      Languages_Touch: []\n"
                "    mLanguages:\n    - Name: English\n      Code: en\n      Flags: 0\n",
                encoding="utf-8",
            )
            exports = prepare_export([locale], Path(directory))
            backup_root = Path(directory) / "backups"
            apply_plan(exports, backup_root)
            imports = prepare_import_pairs([exports.changes[0].path], [locale])
            apply_plan(imports, backup_root)
            assert read_asset(locale).terms[0]["Languages"] == ["Hello"]
            unity_dialog = UnityLocaleDialog(window.settings, [exports.changes[0].path], parent=window)
            unity_dialog.set_assets([locale])
            assert unity_dialog.source_list.paths() == [exports.changes[0].path]
            assert unity_dialog.target_list.paths() == [locale]
            unity_dialog.ensurePolished()
            assert not unity_dialog.grab().isNull(), "Unity Locale could not render"
            unity_dialog.plan = prepare_import_pairs([exports.changes[0].path], [locale])
            unity_dialog.apply()
            deadline = time.monotonic() + 10
            while unity_dialog.worker and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            assert unity_dialog.worker is None, "Replace operation timed out"
            popup = unity_dialog.loading_dialog
            assert popup.isVisible() and not popup.busy and popup.backup_path
            assert popup.progress.value() == popup.progress.maximum()
            assert not popup.grab().isNull(), "Replace progress popup could not render"
            popup.accept()
            unity_dialog.close()
            loaded = read_asset(locale)
            start, end = loaded.spans["mTerms"]
            section = loaded.text[start:end]
            record = section[section.index("    - "):].replace("Flags: 00", "Flags: 01")
            locale.write_bytes((loaded.text[:end] + record + loaded.text[end:]).encode("utf-8"))
            duplicate_dialog = LocaleDuplicateDialog([locale], window)
            def wait_duplicate():
                deadline = time.monotonic() + 10
                while duplicate_dialog.worker and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.001)
                assert duplicate_dialog.worker is None, "Duplicate worker timed out"
            duplicate_dialog.scan()
            wait_duplicate()
            assert duplicate_dialog.groups.rowCount() == 1 and duplicate_dialog.apply_button.isEnabled(), duplicate_dialog.status.text()
            assert not duplicate_dialog.grab().isNull(), "Duplicate dialog could not render"
            duplicate_dialog.cleanup()
            wait_duplicate()
            assert duplicate_dialog.wrote_files and not scan_duplicates([locale]).groups
            duplicate_dialog.close()
            # Verify the packaged model without any network access, not just
            # an import of the Python wrapper around the native extension.
            from unittest.mock import patch
            from import_localize.ui.csv_language_dialog import CsvLanguageDialog
            language_csv = Path(directory) / "language.csv"
            language_csv.write_text("Key,Vietnamese\nwrong,Increase damage against enemies\n"
                                    "right,Tăng sát thương lên kẻ địch\n", encoding="utf-8")
            with patch("socket.socket.connect", side_effect=AssertionError("Language audit must be offline")):
                language_dialog = CsvLanguageDialog([language_csv], window)
                deadline = time.monotonic() + 45
                while language_dialog.worker and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.001)
                assert language_dialog.worker is None, "Language audit timed out"
                assert language_dialog.report and not language_dialog.report.errors, language_dialog.error_label.text()
                assert language_dialog.report.columns[0].counts["mismatch"] == 1
                assert language_dialog.report.columns[0].counts["match"] == 1
                assert not language_dialog.grab().isNull(), "Language results could not render"
                language_dialog.close()
            report = {
                "status": "ok", "qt_version": qVersion(),
                "platform": app.platformName(), "main_window_rendered": True,
                "csv_comparison": True,
                "unity_locale": True,
                "locale_duplicates": True,
                "replace_progress": True,
                "offline_language_detection": True,
            }
            window.close()
            app.processEvents()
    except Exception:
        report["error"] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "ok" else 1
