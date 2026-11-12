from __future__ import annotations

from concurrent.futures import CancelledError
from copy import deepcopy
from types import SimpleNamespace
import re

import pytest

from import_localize.services import mapping_sheet_service as service
from import_localize.services.google_service import GoogleServiceError
from import_localize.services import google_service


@pytest.fixture(autouse=True)
def isolated_fake_http(monkeypatch):
    # Exercise the real cancellable background transport without any network.
    monkeypatch.setattr(google_service, "AuthorizedSession", lambda credentials: credentials)


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
        self.formulas = deepcopy(formulas) if formulas is not None else [[r[2]] if len(r) > 2 else [] for r in rows]
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
            result = []
            for area in params["ranges"]:
                match = re.fullmatch(r"'Translate_Data'!([A-C])(\d*):([A-C])(\d*)", area)
                assert match, area
                left, first, right, last = match.groups()
                first = int(first or 1)
                size = max(len(self.rows), len(self.formulas))
                last = int(last or size)
                values = []
                for number in range(first, last + 1):
                    row = self.rows[number - 1] if number <= len(self.rows) else []
                    selected = []
                    for col in range(ord(left) - 65, ord(right) - 65 + 1):
                        formula = self.formulas[number - 1] if number <= len(self.formulas) else []
                        if params["valueRenderOption"] == "FORMULA" and col == 2 and formula and str(formula[0]).startswith("="):
                            selected.append(formula[0])
                        else:
                            selected.append(row[col] if col < len(row) else "")
                    values.append(selected)
                while values and not any(values[-1]):
                    values.pop()
                result.append({"values": deepcopy(values)})
            return Response({"valueRanges": result})
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
            while len(self.formulas) < number:
                self.formulas.append([])
            self.formulas[number - 1] = [row[2]]
        return Response({"totalUpdatedCells": len(payload["data"])})

    def close(self):
        pass


def connection(rows, **kwargs):
    session = Session(rows, **kwargs)
    return SimpleNamespace(spreadsheet_id="test-id", authorized_session=session, credentials=session)


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


@pytest.mark.parametrize("formulas", [[["Custom(modified)"], ['=ARRAYFORMULA(A:A)']],
                                     [["Custom(modified)"], [""], ["=ARRAYFORMULA(A:A)"]]])
def test_shared_array_formula_is_not_overwritten(formulas):
    conn = connection([HEADERS, ["", "a", "new"]], formulas=formulas)
    with pytest.raises(GoogleServiceError, match="công thức|ARRAYFORMULA"):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 0


@pytest.mark.parametrize("column,replacement", [(1, "another-key"), (2, "changed-status")])
def test_live_row_or_status_change_aborts_before_write(column, replacement):
    conn = connection([HEADERS, ["", "a", "new"]])
    def change_on_preflight(session):
        if session.reads == 4:
            session.rows[1][column] = replacement
    conn.authorized_session.before_read = change_on_preflight
    with pytest.raises(GoogleServiceError, match="đã thay đổi"):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 0


@pytest.mark.parametrize("new_formula", ['=IF(TRUE,"new","")', '=ARRAYFORMULA(IF(B2:B="a","new",""))'])
def test_new_formula_with_same_displayed_value_is_rechecked_before_write(new_formula):
    conn = connection([HEADERS, ["", "a", "new"]])
    def insert_formula_after_initial_check(session):
        if session.reads == 4:
            # Keep the rendered status identical so only FORMULA rendering
            # reveals this concurrent edit.
            session.formulas[1][0] = new_formula
    conn.authorized_session.before_read = insert_formula_after_initial_check
    with pytest.raises(GoogleServiceError, match="đã thay đổi|ARRAYFORMULA"):
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


def test_slow_read_can_finish_after_old_six_second_limit_without_retry():
    import time
    from requests.exceptions import ReadTimeout
    conn = connection([HEADERS, ["", "a", "new"]])
    original = conn.authorized_session.request
    calls = []
    def slow_first_read(method, url, **kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            # Reproduce a server that needs seven seconds. The old cancellable
            # transport would abort this response at six seconds.
            budget = kwargs["timeout"][1]
            if budget < 7:
                raise ReadTimeout("response arrives after the client deadline")
            time.sleep(7)
        return original(method, url, **kwargs)
    conn.authorized_session.request = slow_first_read
    result = service.mark_wrong_mapping(conn, {"a"}, cancel_callback=lambda: False)
    assert result.updated_rows == 1
    assert conn.authorized_session.reads == 5
    assert len(calls) == 6  # Five reads, one write; no timeout/retry cycle.
    assert all(timeout == (5.0, 60.0) for timeout in calls)


def test_sparse_preflight_only_reads_key_spans_and_raw_statuses():
    rows = [HEADERS] + [["expensive tag formula", f"k{i}", ""] for i in range(3000)]
    conn = connection(rows)
    result = service.mark_wrong_mapping(conn, {"k0", "k2999"})
    assert result.updated_rows == 2
    reads = [kwargs["params"] for method, _, kwargs in conn.authorized_session.calls if method == "GET"]
    assert reads[3]["ranges"] == ["'Translate_Data'!A1:C1", "'Translate_Data'!B2:B2", "'Translate_Data'!B3001:B3001"]
    assert not any("'Translate_Data'!A:C" in p["ranges"] for p in reads)
    assert all(p["valueRenderOption"] == "FORMULA" for p in reads if "'Translate_Data'!C:C" in p["ranges"])
    assert conn.authorized_session.rows[1500][2] == ""


def test_sparse_batches_keep_blank_row_offsets_and_limit_request_ranges(monkeypatch):
    monkeypatch.setattr(service, "READ_BATCH_RANGES", 2)
    rows = [HEADERS] + [[] for _ in range(100)]
    for number in (2, 30, 60, 100):
        rows[number - 1] = ["", f"key{number}", ""]
    conn = connection(rows)
    result = service.mark_wrong_mapping(conn, {"key2", "key30", "key60", "key100"})
    assert result.updated_rows == 4
    assert [i for i, row in enumerate(conn.authorized_session.rows, 1) if len(row) > 2 and row[2] == service.MARKER] == [2, 30, 60, 100]
    assert all(len(kw["params"]["ranges"]) <= 3 for method, _, kw in conn.authorized_session.calls if method == "GET")


def test_key_in_column_a_and_header_drift_still_guarded():
    conn = connection([["Key", "Tag", "Custom(modified)"], ["001", "", "new"]])
    assert service.mark_wrong_mapping(conn, {"001"}).updated_rows == 1
    conn = connection([HEADERS, ["", "a", "new"]])
    def change_header(session):
        if session.reads == 4:
            session.rows[0] = ["Key", "Tag", "Custom(modified)"]
    conn.authorized_session.before_read = change_header
    with pytest.raises(GoogleServiceError, match="Cột key đã thay đổi"):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 0


def test_selected_c412_formula_is_replaced_without_touching_other_keys():
    rows = [HEADERS] + [["Base", f"key{i}", "new"] for i in range(1, 414)]
    formulas = [["Custom(modified)"]] + [['=IF(TRUE,"new","")'] for _ in rows[1:]]
    # Both occurrences of the selected key must be marked, including C412.
    rows[412][1] = rows[411][1]
    conn = connection(rows, formulas=formulas)
    result = service.mark_wrong_mapping(conn, {rows[411][1]})
    assert result.updated_rows == result.replaced_formula_rows == 2
    for number in (412, 413):
        assert conn.authorized_session.rows[number - 1][2] == service.MARKER
        assert conn.authorized_session.formulas[number - 1] == [service.MARKER]
    for number in (2, 411, 414):
        assert conn.authorized_session.rows[number - 1] == rows[number - 1]
        assert conn.authorized_session.formulas[number - 1] == formulas[number - 1]
    again = service.mark_wrong_mapping(conn, {rows[411][1]})
    assert again.updated_rows == again.replaced_formula_rows == 0
    assert again.already_marked_rows == 2
    assert conn.authorized_session.writes == 1


def test_formula_changed_to_same_displayed_result_stops_before_write():
    conn = connection([HEADERS, ["", "a", "new"]],
                      formulas=[["Custom(modified)"], ['=IF(TRUE,"new","")']])
    def change_formula(session):
        if session.reads == 4:
            session.formulas[1] = ['=IF(1=1,"new","")']
    conn.authorized_session.before_read = change_formula
    with pytest.raises(GoogleServiceError, match="đã thay đổi"):
        service.mark_wrong_mapping(conn, {"a"})
    assert conn.authorized_session.writes == 0


def test_key_results_distinguish_written_existing_missing_and_partial_duplicates(monkeypatch):
    monkeypatch.setattr(service, "WRITE_BATCH_SIZE", 1)
    conn = connection([HEADERS, ["", "a", "new"], ["", "a", "new"],
                       ["", "b", "Wrong mapping"]])
    events = []
    result = service.mark_wrong_mapping(conn, {"a", "b", "missing"}, result_callback=events.append)
    initial = {item.key: item for item in events[0].key_results}
    assert initial["a"].status == "pending" and initial["a"].total_rows == 2
    assert initial["b"].status == "already"
    assert initial["missing"].status == "missing"
    partials = [i for event in events for i in event.key_results if i.key == "a" and i.status == "partial"]
    assert partials and partials[0].confirmed_rows == 1 and partials[0].total_rows == 2
    final = {item.key: item for item in result.key_results}
    assert final["a"].status == "written" and final["a"].confirmed_rows == 2
    assert final["a"].updated_rows == 2
    assert final["b"].status == "already"


def test_partial_failure_preserves_finished_keys_and_marks_only_last_batch_uncertain(monkeypatch):
    from requests.exceptions import ReadTimeout
    monkeypatch.setattr(service, "WRITE_BATCH_SIZE", 1)
    conn = connection([HEADERS, ["", "a", ""], ["", "b", ""], ["", "c", ""]])
    events = []
    original = conn.authorized_session.request
    def lose_second_response(method, url, **kwargs):
        response = original(method, url, **kwargs)
        if method == "POST" and conn.authorized_session.writes == 2:
            raise ReadTimeout("accepted but response lost")
        return response
    conn.authorized_session.request = lose_second_response
    with pytest.raises(GoogleServiceError, match="Đã xác nhận cập nhật 1 ô"):
        service.mark_wrong_mapping(conn, {"a", "b", "c"}, result_callback=events.append)
    states = {item.key: item for item in events[-1].key_results}
    assert states["a"].status == "written"
    assert states["b"].status == "uncertain" and states["b"].confirmed_rows == 0
    assert states["b"].uncertain_rows == 1
    assert states["c"].status == "pending"
    assert conn.authorized_session.writes == 2
    conn.authorized_session.request = original
    result = service.mark_wrong_mapping(conn, {"a", "b", "c"})
    assert result.updated_rows == 1 and result.already_marked_rows == 2
    assert {i.key: i.status for i in result.key_results} == {"a": "already", "b": "already", "c": "written"}


def test_cancel_between_batches_keeps_first_key_confirmed(monkeypatch):
    monkeypatch.setattr(service, "WRITE_BATCH_SIZE", 1)
    conn = connection([HEADERS, ["", "a", ""], ["", "b", ""]])
    events = []
    cancelled = False
    def receive(result):
        nonlocal cancelled
        events.append(result)
        cancelled = result.updated_rows == 1
    with pytest.raises(GoogleServiceError, match="Đã xác nhận cập nhật 1 ô"):
        service.mark_wrong_mapping(conn, {"a", "b"}, result_callback=receive,
                                   cancel_callback=lambda: cancelled)
    assert {i.key: i.status for i in events[-1].key_results} == {"a": "written", "b": "pending"}
    assert conn.authorized_session.writes == 1
