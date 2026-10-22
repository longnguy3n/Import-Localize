"""JSON IPC for an isolated offline model process (also used by frozen EXEs)."""
import json
from concurrent.futures import CancelledError
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from .csv_language_service import LanguageReport, LanguageColumn, LanguageCell, Prediction, audit_csv_languages


def read_report(payload):
    report = LanguageReport(errors=payload["errors"])
    for value in payload["columns"]:
        column = LanguageColumn(Path(value["path"]), value["column"], value["expected"])
        for raw in value["cells"]:
            cell = dict(raw)
            cell["path"] = Path(cell["path"])
            cell["prediction"] = Prediction(**cell["prediction"])
            column.cells.append(LanguageCell(**cell))
        report.columns.append(column)
    return report


def run_audit_process(directory):
    folder = Path(directory)
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    try:
        with (folder / "progress.jsonl").open("w", encoding="utf-8") as stream:
            def progress(done, total, message):
                stream.write(json.dumps([done, total, message]) + "\n")
                stream.flush()
            with patch("socket.socket.connect", side_effect=RuntimeError("Offline audit cannot access the network")), \
                 patch("socket.socket.connect_ex", side_effect=RuntimeError("Offline audit cannot access the network")):
                report = audit_csv_languages(request["paths"], progress=progress,
                    cancel_callback=lambda: (folder / "cancel").exists())
            response = {"report": asdict(report)}
    except CancelledError:
        response = {"cancelled": True}
    except Exception as exc:
        response = {"error": str(exc)}
    temporary = folder / "result.tmp"
    temporary.write_text(json.dumps(response, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(folder / "result.json")
    return 0
