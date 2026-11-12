from __future__ import annotations

from concurrent.futures import CancelledError
from copy import deepcopy
from types import SimpleNamespace

import pytest

from import_localize.services import mapping_sheet_service as service
from import_localize.services.google_service import GoogleServiceError


class Response:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Session:
    def __init__(self, rows, formulas=None):
        self.rows = deepcopy(rows)
        self.formulas = formulas or [[r[2]] if len(r) > 2 else [] for r in rows]
        self.calls = []
        self.before_read = None
        self.reads = 0
        self.writes = 0

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "GET":
            self.reads += 1
            if self.before_read:
                self.before_read(self)
            params = kwargs["params"]
            values = self.formulas if params["valueRenderOption"] == "FORMULA" else self.rows
            return Response({"valueRanges": [{"values": deepcopy(values)}]})
        assert method == "POST" and url.endswith("/values:batchUpdate")
        self.writes += 1
        payload = kwargs["json"]
        assert payload["valueInputOption"] == "RAW"
        for item in payload["data"]:
            assert item["range"].startswith("'Translate_Data'!C")
            number = int(item["range"].split("!C")[1])
            row = self.rows[number - 1]
            row.extend([""] * max(0, 3 - len(row)))
            row[2] = item["values"][0][0]
        return Response({"totalUpdatedCells": len(payload["data"])})


def connection(rows, **kwargs):
    return SimpleNamespace(spreadsheet_id="test-id", authorized_session=Session(rows, **kwargs))


HEADERS = ["Tag", "Key", "Custom(modified)"]


def test_updates_only_matching_c_cells_and_reports_duplicates_and_missing():
    rows = [HEADERS, ["Base", "a", "new"], ["Tag", "other", "keep"],
            ["", "a", ""], ["", "b", "Wrong mapping"]]
    conn = connection(rows)
    result = service.mark_wrong_mapping(conn, {"a", "b", "missing"})
    assert result.updated_rows == 2
    assert result.already_marked_rows == 1
    assert result.matched_keys == ("a", "b")
    assert result.missing_keys == ("missing",)
    assert conn.authorized_session.rows == [HEADERS, ["Base", "a", "Wrong mapping"],
        ["Tag", "other", "keep"], ["", "a", "Wrong mapping"], ["", "b", "Wrong mapping"]]
    assert rows[1][2] == "new"


def test_key_matching_preserves_case_whitespace_and_leading_zeroes():
    conn = connection([HEADERS, ["", "0", ""], ["", "001", ""],
                       ["", "a", ""], ["", "A", ""], ["", "a ", ""]])
    result = service.mark_wrong_mapping(conn, {"001", "a "})
    assert result.updated_rows == 2
    assert [r[2] for r in conn.authorized_session.rows[1:]] == ["", "Wrong mapping", "", "", "Wrong mapping"]


@pytest.mark.parametrize("headers", [["Tag", "Key", "English"], ["Tag", "English", "Custom(modified)"],
                                     ["Key", "Term", "Custom(modified)"]])
def test_bad_schema_never_writes(headers):
    conn = connection([headers, ["", "a", ""]])
    with pytest.raises(GoogleServiceError):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 0


def test_missing_or_already_marked_keys_do_not_write():
    conn = connection([HEADERS, ["", "a", "Wrong mapping"]])
    result = service.mark_wrong_mapping(conn, {"a", "missing"})
    assert result.updated_rows == 0 and result.already_marked_rows == 1
    assert conn.authorized_session.writes == 0


@pytest.mark.parametrize("formulas", [[["Custom(modified)"], ['=IF(1,"new","")']],
                                     [["Custom(modified)"], [""], ["=ARRAYFORMULA(A:A)"]]])
def test_formula_backed_status_is_not_overwritten(formulas):
    conn = connection([HEADERS, ["", "a", "new"]], formulas=formulas)
    with pytest.raises(GoogleServiceError, match="công thức|ARRAYFORMULA"):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 0


@pytest.mark.parametrize("column,replacement", [(1, "another-key"), (2, "changed-status")])
def test_live_row_or_status_change_aborts_before_write(column, replacement):
    conn = connection([HEADERS, ["", "a", "new"]])
    def change_on_preflight(session):
        if session.reads == 3:
            session.rows[1][column] = replacement
    conn.authorized_session.before_read = change_on_preflight
    with pytest.raises(GoogleServiceError, match="đã thay đổi"):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 0


@pytest.mark.parametrize("new_formula", ['=IF(TRUE,"new","")', '=ARRAYFORMULA(IF(B2:B="a","new",""))'])
def test_new_formula_with_same_displayed_value_is_rechecked_before_write(new_formula):
    conn = connection([HEADERS, ["", "a", "new"]])
    def insert_formula_after_initial_check(session):
        if session.reads == 3:
            # Keep the rendered status identical so only FORMULA rendering
            # reveals this concurrent edit.
            session.formulas[1][0] = new_formula
    conn.authorized_session.before_read = insert_formula_after_initial_check
    with pytest.raises(GoogleServiceError, match="công thức|ARRAYFORMULA"):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 0
    assert conn.authorized_session.rows[1][2] == "new"


def test_formula_inserted_between_batches_stops_remaining_writes(monkeypatch):
    monkeypatch.setattr(service, "WRITE_BATCH_SIZE", 1)
    conn = connection([HEADERS, ["", "a", "new"], ["", "b", "new"]])
    def insert_formula_after_first_write(session):
        if session.writes == 1:
            session.formulas[2][0] = '=IF(TRUE,"new","")'
    conn.authorized_session.before_read = insert_formula_after_first_write
    with pytest.raises(GoogleServiceError, match="Đã xác nhận cập nhật 1 ô"):
        service.mark_wrong_mapping(conn, {"a", "b"})
    assert conn.authorized_session.writes == 1
    assert conn.authorized_session.rows[1][2] == "Wrong mapping"
    assert conn.authorized_session.rows[2][2] == "new"


def test_cancel_before_start_has_no_network_calls():
    conn = connection([HEADERS])
    with pytest.raises(CancelledError):
        service.mark_wrong_mapping(conn, {"a"}, cancel_callback=lambda: True)
    assert not conn.authorized_session.calls


def test_cancellation_after_write_explains_possible_partial_changes(monkeypatch):
    monkeypatch.setattr(service, "WRITE_BATCH_SIZE", 1)
    conn = connection([HEADERS, ["", "a", ""], ["", "b", ""]])
    with pytest.raises(GoogleServiceError, match="Yêu cầu cuối đã gửi"):
        service.mark_wrong_mapping(conn, {"a", "b"},
                                   cancel_callback=lambda: conn.authorized_session.writes > 0)
    assert conn.authorized_session.rows[1][2] == "Wrong mapping"
    assert conn.authorized_session.rows[2][2] == ""


def test_batches_report_real_progress(monkeypatch):
    monkeypatch.setattr(service, "WRITE_BATCH_SIZE", 1)
    conn = connection([HEADERS, ["", "a", ""], ["", "b", ""]])
    progress = []
    result = service.mark_wrong_mapping(conn, {"a", "b"}, progress_callback=lambda n, text: progress.append(n))
    assert result.updated_rows == 2
    assert conn.authorized_session.writes == 2
    assert progress[0] == 5 and progress[-1] == 100 and progress == sorted(progress)


def test_uncertain_write_is_not_retried_and_is_reported():
    from requests.exceptions import ReadTimeout
    conn = connection([HEADERS, ["", "a", ""]])
    original = conn.authorized_session.request
    def lose_response(method, url, **kwargs):
        result = original(method, url, **kwargs)
        if method == "POST":
            raise ReadTimeout("response lost after server accepted write")
        return result
    conn.authorized_session.request = lose_response
    with pytest.raises(GoogleServiceError, match="có thể đã ghi"):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 1
    assert conn.authorized_session.rows[1][2] == "Wrong mapping"
