from __future__ import annotations

from types import SimpleNamespace

from requests.exceptions import ReadTimeout
import pytest

pytest.importorskip("gspread")
pytest.importorskip("google_auth_oauthlib")
from import_localize.services import google_service


class _Response:
    def __init__(self, status_code: int = 200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._payload


class _FlakySession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def request(self, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_request_with_retry_recovers_from_read_timeout(monkeypatch):
    monkeypatch.setattr(google_service, "_sleep_with_cancel", lambda *_args: None)
    session = _FlakySession([ReadTimeout("slow"), _Response(200)])

    response = google_service._request_with_retry(
        session,
        "POST",
        "https://example.test",
        action="test",
        max_attempts=3,
    )

    assert response.status_code == 200
    assert session.calls == 2


def test_request_with_retry_recovers_from_transient_http(monkeypatch):
    monkeypatch.setattr(google_service, "_sleep_with_cancel", lambda *_args: None)
    session = _FlakySession([_Response(503), _Response(200)])

    response = google_service._request_with_retry(
        session,
        "POST",
        "https://example.test",
        action="test",
        max_attempts=3,
    )

    assert response.status_code == 200
    assert session.calls == 2


def test_structure_builder_does_not_add_existing_sheet_again():
    bundle = SimpleNamespace(header=["id"], column_count=1)
    job = SimpleNamespace(sheet_name="import_vi")
    values = [["id"], ["hello"]]
    properties = {
        "import_vi": {
            "sheetId": 7,
            "title": "import_vi",
            "gridProperties": {
                "rowCount": 100,
                "columnCount": 10,
                "frozenRowCount": 1,
            },
        }
    }

    requests, clear_ranges = google_service._build_structure_requests(
        [(bundle, job, values)],
        properties,
    )

    assert requests == []
    assert clear_ranges == ["'import_vi'"]
