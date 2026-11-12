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


@dataclass(frozen=True)
class MappingMarkResult:
    updated_rows: int = 0
    already_marked_rows: int = 0
    matched_keys: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()


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


def _check_status_formulas(formulas: list[list], rows: Iterable[int]) -> None:
    for formula_row in formulas:
        formula = _cell(formula_row, 0)
        if formula.startswith("=") and "ARRAYFORMULA" in formula.upper():
            raise GoogleServiceError("Cột C có ARRAYFORMULA; không ghi đè kết quả công thức.")
    for number in rows:
        if number <= len(formulas) and _cell(formulas[number - 1], 0).startswith("="):
            raise GoogleServiceError(f"Ô C{number} đang là công thức; chưa ghi dữ liệu trong lô này.")


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
    Direct formulas and ARRAYFORMULA in C are rejected. This values API check
    does not detect every spill formula anchored outside C. Each batch re-reads
    formatted keys/statuses and formula cells immediately before writing;
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

    def read(range_name: str, render: str = "FORMATTED_VALUE") -> list[list]:
        response = _request_with_retry(
            connection.authorized_session, "GET", base + "/values:batchGet",
            action="Đọc Translate_Data", log_callback=log_callback, cancel_callback=cancel_callback,
            params={"ranges": f"'{SHEET_NAME}'!{range_name}", "valueRenderOption": render},
        )
        _raise_for_response(response, "Đọc Translate_Data")
        ranges = response.json().get("valueRanges", [])
        if len(ranges) != 1:
            raise GoogleServiceError("Google không trả về vùng Translate_Data được yêu cầu.")
        return ranges[0].get("values", [])

    _progress(progress_callback, 5, "Đang đọc key và cột C trong Translate_Data")
    original = read("A:C")
    key_index = _key_column(original)
    matches = [(number, _cell(row, key_index), _cell(row, 2))
               for number, row in enumerate(original[1:], start=2)
               if _cell(row, key_index) in requested]
    found = {key for _, key, _ in matches}
    missing = tuple(sorted(requested - found))
    already = sum(value == MARKER for _, _, value in matches)
    pending = [(row, key, value) for row, key, value in matches if value != MARKER]
    if missing:
        _log(log_callback, f"{len(missing)} key không có trong Translate_Data; các key này không được ghi.")
    if not pending:
        _progress(progress_callback, 100, "Không có ô cần thay đổi")
        return MappingMarkResult(0, already, tuple(sorted(found)), missing)

    _check_status_formulas(read("C:C", "FORMULA"), (number for number, _, _ in pending))

    updated = 0
    submitted = False
    try:
        for offset in range(0, len(pending), WRITE_BATCH_SIZE):
            _check_cancel(cancel_callback)
            chunk = pending[offset:offset + WRITE_BATCH_SIZE]
            # Resolve drift immediately before each write. Never reuse a row
            # number from a prior scan or from a local CSV.
            latest = read("A:C")
            if _key_column(latest) != key_index:
                raise GoogleServiceError("Cột key đã thay đổi trong lúc kiểm tra; hãy chạy lại.")
            for number, key, old_value in chunk:
                if (number > len(latest) or _cell(latest[number - 1], key_index) != key
                        or _cell(latest[number - 1], 2) != old_value):
                    raise GoogleServiceError(f"Hàng {number} đã thay đổi trong lúc kiểm tra; hãy chạy lại.")
            # A newly inserted formula can evaluate to the same formatted value
            # as the old literal; formatted-value checks alone cannot detect it.
            _check_status_formulas(read("C:C", "FORMULA"), (number for number, _, _ in chunk))
            _check_cancel(cancel_callback)
            submitted = True
            response = _request_with_retry(
                connection.authorized_session, "POST", base + "/values:batchUpdate",
                action="Đánh dấu Wrong mapping", log_callback=log_callback,
                cancel_callback=cancel_callback, max_attempts=1,
                json={"valueInputOption": "RAW", "data": [
                    {"range": f"'{SHEET_NAME}'!C{number}", "values": [[MARKER]]}
                    for number, _, _ in chunk]},
            )
            _raise_for_response(response, "Đánh dấu Wrong mapping")
            count = response.json().get("totalUpdatedCells")
            if count != len(chunk):
                raise GoogleServiceError("Google trả số ô cập nhật không khớp yêu cầu; cần kiểm tra lại tab.")
            updated += count
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
    _log(log_callback, f"Đã đánh dấu {updated} ô; {already} ô đã là Wrong mapping; {len(missing)} key không tìm thấy.")
    return MappingMarkResult(updated, already, tuple(sorted(found)), missing)
