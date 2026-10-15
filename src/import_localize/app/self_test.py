"""Frozen application startup check, isolated from user settings and Google."""
from __future__ import annotations

import json
import os
import tempfile
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
            from import_localize.services.unity_locale_service import (
                prepare_export, prepare_import, apply_plan, read_asset,
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
            imports = prepare_import([locale], [exports.changes[0].path])
            apply_plan(imports, backup_root)
            assert read_asset(locale).terms[0]["Languages"] == ["Hello"]
            unity_dialog = UnityLocaleDialog(window.settings, parent=window)
            unity_dialog.ensurePolished()
            assert not unity_dialog.grab().isNull(), "Unity Locale could not render"
            unity_dialog.close()
            report = {
                "status": "ok", "qt_version": qVersion(),
                "platform": app.platformName(), "main_window_rendered": True,
                "csv_comparison": True,
                "unity_locale": True,
            }
            window.close()
            app.processEvents()
    except Exception:
        report["error"] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "ok" else 1
