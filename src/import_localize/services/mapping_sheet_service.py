"""Mark exact mapping-audit keys in Translate_Data without rewriting other cells."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from import_localize.services.google_service import (
    CancelCallback, GoogleServiceError, LogCallback, ProgressCallback, SheetConnection,
    _check_cancel, _log, _progress, _raise_for_response, _request_with_retry,
)

SHEET_NAME = "Translate_Data"
MARKER = "Wrong mapping"
WRITE_BATCH_SIZE = 500
REQUEST_TIMEOUT = (5.0, 60.0)
READ_BATCH_RANGES = 50


def _key_ranges(column: str, rows: Iterable[int]) -> list[tuple[int, int, str]]:
    """Coalesce nearby target rows; cap each span to avoid huge sparse reads."""
    spans = []
    for row in sorted(set(rows)):
        if spans and row - spans[-1][1] <= 16 and row - spans[-1][0] < 1000:
            spans[-1][1] = row
        else:
            spans.append([row, row])
    return [(start, end, f"{column}{start}:{column}{end}") for start, end in spans]


@dataclass(frozen=True)
class MappingMarkResult:
    updated_rows: int = 0
    already_marked_rows: int = 0
    matched_keys: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()
    replaced_formula_rows: int = 0


def _cell(row: list, index: int) -> str:
    return str(row[index]) if index < len(row) and row[index] is not None else ""


def _key_column(rows: list[list]) -> int:
    if not rows:
        raise GoogleServiceError("Tab Translate_Data đang trống.")
    headers = [_cell(rows[0], index).strip().casefold() for index in range(3)]
    if "".join(headers[2].split()) != "custom(modified)":
        raise GoogleServiceError("Cột C của Translate_Data phải có tiêu đề Custom(modified); chưa ghi dữ liệu.")
    key_columns = [index for index, value in enumerate(headers[:2]) if value in {"key", "term"}]
    if len(key_columns) != 1:
        raise GoogleServiceError("Translate_Data phải có đúng một cột Key (hoặc Term) trong A:B; chưa ghi dữ liệu.")
    return key_columns[0]


def _check_status_array_formulas(formulas: list[list]) -> None:
    for formula_row in formulas:
        formula = _cell(formula_row, 0)
        if formula.startswith("=") and "ARRAYFORMULA" in formula.upper():
            raise GoogleServiceError("Cột C có ARRAYFORMULA dùng chung nhiều hàng; không thể thay riêng ô bằng Wrong mapping. Chưa ghi dữ liệu trong lô này.")


def mark_wrong_mapping(
    connection: SheetConnection,
    keys: Iterable[str],
    *,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> MappingMarkResult:
    """Read live row positions and set only matching C cells to a RAW literal.

    All rows of a duplicated key are marked. Exact key matching preserves case,
    whitespace and leading zeroes. No live writes are performed for missing keys.
    The confirmed action replaces ordinary formulas in selected C cells with
    the marker, while ARRAYFORMULA in C is rejected. This values API check
    does not detect every spill formula anchored outside C. Each batch re-reads
    formatted keys and raw status/formula cells immediately before writing;
    users should not sort or edit the tab while this runs because
    Sheets values updates cannot provide an atomic compare-and-set operation.
    """
    requested = set(keys)
    if any(not isinstance(key, str) or not key for key in requested):
        raise GoogleServiceError("Danh sách key cần đánh dấu chứa key trống hoặc không phải chuỗi.")
    _check_cancel(cancel_callback)
    if not requested:
        return MappingMarkResult()
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{connection.spreadsheet_id}"

    def read_many(range_names: list[str], render: str = "FORMATTED_VALUE") -> list[list[list]]:
        action = f"Đọc Translate_Data ({render}, {len(range_names)} vùng)"
        response = _request_with_retry(
            connection.authorized_session, "GET", base + "/values:batchGet",
            action=action, log_callback=log_callback, cancel_callback=cancel_callback,
            background_credentials=connection.credentials, timeout=REQUEST_TIMEOUT, max_attempts=3,
            params={"ranges": [f"'{SHEET_NAME}'!{name}" for name in range_names],
                    "majorDimension": "ROWS", "valueRenderOption": render},
        )
        _raise_for_response(response, action)
        ranges = response.json().get("valueRanges", [])
        if len(ranges) != len(range_names):
            raise GoogleServiceError("Google không trả về vùng Translate_Data được yêu cầu.")
        return [entry.get("values", []) for entry in ranges]

    def read(range_name: str, render: str = "FORMATTED_VALUE") -> list[list]:
        return read_many([range_name], render)[0]

    _progress(progress_callback, 5, "Đang kiểm tra tiêu đề Translate_Data")
    key_index = _key_column(read("A1:C1"))
    key_column = "AB"[key_index]
    _progress(progress_callback, 7, f"Đang tìm key trong cột {key_column} của Translate_Data")
    key_rows = read(f"{key_column}2:{key_column}")
    matches = [(number, _cell(row, 0)) for number, row in enumerate(key_rows, start=2)
               if _cell(row, 0) in requested]
    _progress(progress_callback, 10, "Đang đọc trạng thái và kiểm tra công thức cột C")
    # FORMULA gives literals or formula text, avoiding a second full-column
    # formatted-status read. Scan all of C to detect ARRAYFORMULA anchors even
    # outside the selected rows; never fetch translation columns.
    statuses = read("C:C", "FORMULA") if matches else []
    def status_at(values: list[list], number: int) -> str:
        return _cell(values[number - 1], 0) if number <= len(values) else ""
    matches = [(number, key, status_at(statuses, number)) for number, key in matches]
    found = {key for _, key, _ in matches}
    missing = tuple(sorted(requested - found))
    already = sum(value == MARKER for _, _, value in matches)
    pending = [(row, key, value) for row, key, value in matches if value != MARKER]
    if missing:
        _log(log_callback, f"{len(missing)} key không có trong Translate_Data; các key này không được ghi.")
    if not pending:
        _progress(progress_callback, 100, "Không có ô cần thay đổi")
        return MappingMarkResult(0, already, tuple(sorted(found)), missing)

    _check_status_array_formulas(statuses)

    updated = 0
    replaced_formulas = 0
    submitted = False
    try:
        for offset in range(0, len(pending), WRITE_BATCH_SIZE):
            _check_cancel(cancel_callback)
            chunk = pending[offset:offset + WRITE_BATCH_SIZE]
            # Resolve drift immediately before each write. Never reuse a row
            # number from a prior scan or from a local CSV.
            _progress(progress_callback, 15 + round(85 * updated / len(pending)),
                      f"Đang kiểm tra lại {len(chunk)} hàng trước khi ghi; đã ghi {updated}/{len(pending)} ô")
            spans = _key_ranges(key_column, (number for number, _, _ in chunk))
            latest_keys = {}
            for start in range(0, len(spans), READ_BATCH_RANGES):
                group = spans[start:start + READ_BATCH_RANGES]
                names = [name for _, _, name in group]
                if start == 0:
                    names.insert(0, "A1:C1")
                values = read_many(names)
                if start == 0:
                    header = values.pop(0)
                    if _key_column(header) != key_index:
                        raise GoogleServiceError("Cột key đã thay đổi trong lúc kiểm tra; hãy chạy lại.")
                for (first, last, _), rows in zip(group, values):
                    for number in range(first, last + 1):
                        index = number - first
                        latest_keys[number] = _cell(rows[index], 0) if index < len(rows) else ""
            # Re-read raw statuses, including global ARRAYFORMULA anchors.
            # One read serves both drift and formula checks.
            latest_statuses = read("C:C", "FORMULA")
            _check_status_array_formulas(latest_statuses)
            for number, key, old_value in chunk:
                if (latest_keys.get(number) != key or status_at(latest_statuses, number) != old_value):
                    raise GoogleServiceError(f"Hàng {number} đã thay đổi trong lúc kiểm tra; hãy chạy lại.")
            _check_cancel(cancel_callback)
            submitted = True
            response = _request_with_retry(
                connection.authorized_session, "POST", base + "/values:batchUpdate",
                action="Đánh dấu Wrong mapping", log_callback=log_callback,
                cancel_callback=cancel_callback, max_attempts=1,
                background_credentials=connection.credentials, timeout=REQUEST_TIMEOUT,
                json={"valueInputOption": "RAW", "data": [
                    {"range": f"'{SHEET_NAME}'!C{number}", "values": [[MARKER]]}
                    for number, _, _ in chunk]},
            )
            _raise_for_response(response, "Đánh dấu Wrong mapping")
            count = response.json().get("totalUpdatedCells")
            if count != len(chunk):
                raise GoogleServiceError("Google trả số ô cập nhật không khớp yêu cầu; cần kiểm tra lại tab.")
            updated += count
            replaced_formulas += sum(old_value.startswith("=") for _, _, old_value in chunk)
            submitted = False
            _progress(progress_callback, 15 + round(85 * updated / len(pending)),
                      f"Đã đánh dấu {updated}/{len(pending)} ô Wrong mapping")
    except Exception as exc:
        if updated or submitted:
            uncertainty = " Yêu cầu cuối đã gửi; có thể đã ghi dù chưa nhận được xác nhận." if submitted else ""
            raise GoogleServiceError(
                f"Tác vụ chưa hoàn tất. Đã xác nhận cập nhật {updated} ô.{uncertainty} "
                f"Hãy kiểm tra Translate_Data trước khi chạy lại. Chi tiết: {exc}"
            ) from exc
        raise
    _log(log_callback, f"Đã đánh dấu {updated} ô (thay {replaced_formulas} công thức riêng); {already} ô đã là Wrong mapping; {len(missing)} key không tìm thấy.")
    return MappingMarkResult(updated, already, tuple(sorted(found)), missing, replaced_formulas)
