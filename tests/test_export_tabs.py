from __future__ import annotations

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

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, params, headers, timeout))
        gid = int(params["gid"])
        return _FakeResponse(self.payloads[gid])


def _connection(worksheets):
    return SheetConnection(
        credentials=object(),
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
        2: b"key,value\r\nhello,xin chao\r\n",
        3: b"key,value\r\nhello,hello\r\n",
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
    assert [call[1]["gid"] for call in fake_session.calls] == ["2", "3"]


def test_download_reports_when_no_export_tabs(tmp_path):
    connection = _connection([SimpleNamespace(title="import_vi", id=1)])
    with pytest.raises(GoogleServiceError, match="Không tìm thấy tab"):
        download_export_tabs_as_csv(connection, tmp_path)
