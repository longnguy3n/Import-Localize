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
