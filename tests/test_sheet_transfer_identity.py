from types import SimpleNamespace

import pytest

from import_localize.models.import_job import ImportJob
from import_localize.services.csv_service import CsvImportError
from import_localize.services import google_service as sheets
from import_localize.services.transfer_files import TransferFileError
from import_localize.workers import import_worker


def test_uploader_resolves_actual_tab_and_checks_old_and_new_headers(tmp_path, monkeypatch):
    path = tmp_path / "upload_pt-BR.csv"
    path.write_text("Key,Portuguese (Brazil)\nt,abc\n", encoding="utf-8")
    tab = SimpleNamespace(title="upload_pt_BR", id=3)
    session = SimpleNamespace(request=lambda **kwargs: response)
    connection = sheets.SheetConnection(None, None, SimpleNamespace(worksheets=lambda: [tab]), "id", "Book", session)
    values = [{"values": [["Key", "English"]]}]
    response = SimpleNamespace(status_code=200, json=lambda: {"valueRanges": values})
    writes = []
    monkeypatch.setattr(import_worker, "upload_bundles_fast", lambda connection, plans, **kw: writes.extend(plans))
    worker = import_worker.ImportWorker(ImportJob((str(path),), "url"))
    with pytest.raises(TransferFileError, match="English"):
        worker._run_upload(connection)
    assert not writes
    values[0] = {"values": [["Key", "Portuguese (Brazil)"]]}
    worker._run_upload(connection)
    assert writes[0][1].sheet_name == tab.title


@pytest.mark.parametrize(("name", "target", "language"), [
    ("export_vi.csv", "upload_vi", "Vietnamese"),
    ("upload_vi.csv", "upload_en", "Vietnamese"),
    ("Other - upload_vi.csv", "upload_vi", "Vietnamese"),
    ("upload_vi.csv", "upload_vi", "English"),
])
def test_single_sheet_cannot_bypass_filename_or_language(tmp_path, monkeypatch, name, target, language):
    path = tmp_path / name
    path.write_text(f"Key,{language}\nx,abc\n", encoding="utf-8")
    job = ImportJob((str(path),), "url", target_mode="single", sheet_name=target)
    worker = import_worker.ImportWorker(job)
    monkeypatch.setattr(import_worker, "transfer_tabs", lambda *_: {})
    monkeypatch.setattr(import_worker, "upload_bundles_fast", lambda *a, **kw: pytest.fail("unexpected write"))
    with pytest.raises((CsvImportError, TransferFileError)):
        worker._run_upload(SimpleNamespace(spreadsheet_name="Book"))

def test_upload_rechecks_old_mapping_desc_against_current_sibling_csvs(tmp_path, monkeypatch):
    from pathlib import Path
    from import_localize.services.desc_annotations import DescAnnotations, WRONG_MAPPING
    import csv

    paths = []
    for code, lang, values in (("en", "English", ("Deal DMG", "Deal DMG")),
                               ("vi", "Vietnamese", ("Gây ST", "Gây sát thương"))):
        path = tmp_path / f"upload_{code}.csv"
        paths.append(str(path))
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Key", "Desc", lang])
            writer.writerow(["fixed", "note\nWrong mapping\nWrong languague", values[0]])
            writer.writerow(["pending", "Wrong mapping", values[1]])
    notes = DescAnnotations()
    notes.set_mark("vi", "fixed", WRONG_MAPPING)
    worker = import_worker.ImportWorker(ImportJob(tuple(paths), "url"), annotations=notes,
        mapping_path=Path(__file__).parent / "fixtures/mapping_v2.json")
    monkeypatch.setattr(import_worker, "transfer_tabs", lambda *_: {})
    monkeypatch.setattr(import_worker, "validate_upload_headers", lambda *a, **kw: None)
    writes = []
    monkeypatch.setattr(import_worker, "upload_bundles_fast", lambda _, plans, **kw: writes.extend(plans))
    worker._run_upload(SimpleNamespace(spreadsheet_name="Book"))
    assert writes[1][0].rows == [["fixed", "note\nWrong languague", "Gây ST"],
                                ["pending", "Wrong mapping", "Gây sát thương"]]
