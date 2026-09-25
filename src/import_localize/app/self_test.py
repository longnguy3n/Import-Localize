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
            report = {
                "status": "ok", "qt_version": qVersion(),
                "platform": app.platformName(), "main_window_rendered": True,
                "csv_comparison": True,
            }
            window.close()
            app.processEvents()
    except Exception:
        report["error"] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "ok" else 1
