from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("gspread")
pytest.importorskip("google.auth")
pytest.importorskip("google_auth_oauthlib")

from import_localize.services import google_service
from import_localize.services.google_service import (
    GoogleServiceError,
    SheetConnection,
    build_csv_export_filename,
    download_export_tabs_as_csv,
    sanitize_export_filename_part,
)


class _FakeSpreadsheet:
    def __init__(self, worksheets):
        self._worksheets = worksheets

    def worksheets(self):
        return list(self._worksheets)


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": "text/csv;charset=UTF-8"}
        self.text = content.decode("utf-8", errors="replace")

    def json(self):
        raise ValueError("not json")


class _FakeSession:
    def __init__(self, credentials, payloads):
        self.credentials = credentials
        self.payloads = payloads
        self.calls = []

    def request(self, method, url, *, params, headers, timeout):
        assert method == "GET"
        self.calls.append((url, params, headers, timeout))
        gid = int(params["gid"])
        return _FakeResponse(self.payloads[gid])


def _connection(worksheets):
    return SheetConnection(
        credentials=object(),
        authorized_session=object(),
        client=object(),
        spreadsheet=_FakeSpreadsheet(worksheets),
        spreadsheet_id="spreadsheet-id",
        spreadsheet_name="DG_Localization",
    )


def test_build_csv_export_filename_matches_expected_pattern():
    assert (
        build_csv_export_filename("DG/Localization", "export_en")
        == "DG_Localization - export_en.csv"
    )
    assert sanitize_export_filename_part("  Name...  ") == "Name"


def test_download_only_export_prefix_and_preserve_raw_bytes(tmp_path, monkeypatch):
    worksheets = [
        SimpleNamespace(title="import_vi", id=1),
        SimpleNamespace(title="export_vi", id=2),
        SimpleNamespace(title="export_en", id=3),
    ]
    payloads = {
        2: b"key,Vietnamese\r\nhello,xin chao\r\n",
        3: b"key,English\r\nhello,hello\r\n",
    }
    fake_session = _FakeSession(object(), payloads)
    monkeypatch.setattr(
        google_service,
        "AuthorizedSession",
        lambda credentials: fake_session,
    )

    created = download_export_tabs_as_csv(_connection(worksheets), tmp_path)

    assert [item.name for item in created] == [
        "DG_Localization - export_vi.csv",
        "DG_Localization - export_en.csv",
    ]
    assert created[0].read_bytes() == payloads[2]
    assert created[1].read_bytes() == payloads[3]
    assert sorted(call[1]["gid"] for call in fake_session.calls) == ["2", "3"]


def test_download_reports_when_no_export_tabs(tmp_path):
    connection = _connection([SimpleNamespace(title="import_vi", id=1)])
    with pytest.raises(GoogleServiceError, match="Không tìm thấy tab"):
        download_export_tabs_as_csv(connection, tmp_path)


def test_reuse_bare_file_and_reject_wrong_header_before_replacing_any(tmp_path, monkeypatch):
    first = tmp_path / "export_vi.csv"
    first.write_bytes(b"Key,Vietnamese\nk,old\n")
    payloads = {1: b"Key,Vietnamese\nk,new\n", 2: b"Key,Vietnamese\nk,wrong\n"}
    targets = [SimpleNamespace(title="export_vi", id=1), SimpleNamespace(title="export_en", id=2)]
    connection = _connection(targets)
    monkeypatch.setattr(google_service, "read_worksheet_csv", lambda _, tab, **kw: payloads[tab.id])
    with pytest.raises(GoogleServiceError, match="export_en"):
        download_export_tabs_as_csv(connection, tmp_path)
    assert first.read_bytes() == b"Key,Vietnamese\nk,old\n" and list(tmp_path.iterdir()) == [first]
    payloads[2] = b"Key,English\nk,hi\n"
    created = download_export_tabs_as_csv(connection, tmp_path)
    assert created == [first, tmp_path / "DG_Localization - export_en.csv"]
    assert first.read_bytes() == payloads[1]
    (tmp_path / "DG_Localization - export_vi.csv").write_bytes(payloads[1])
    with pytest.raises(GoogleServiceError, match="cùng mã"):
        download_export_tabs_as_csv(connection, tmp_path)


def test_failed_second_replace_restores_existing_csv(tmp_path, monkeypatch):
    worksheets = [SimpleNamespace(title="export_en", id=1), SimpleNamespace(title="export_vi", id=2)]
    originals = {1: b"Key,English\na,old\n", 2: b"Key,Vietnamese\na,old\n"}
    for tab in worksheets:
        (tmp_path / (tab.title + ".csv")).write_bytes(originals[tab.id])
    monkeypatch.setattr(google_service, "read_worksheet_csv",
                        lambda _, tab, **kw: originals[tab.id].replace(b"old", b"new"))
    real_replace = Path.replace

    def replace(path, target):
        if path.name == "1.csv" and target.name == "export_vi.csv":
            raise PermissionError("locked")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(PermissionError, match="locked"):
        download_export_tabs_as_csv(_connection(worksheets), tmp_path)
    assert (tmp_path / "export_en.csv").read_bytes() == originals[1]
    assert (tmp_path / "export_vi.csv").read_bytes() == originals[2]
