from __future__ import annotations

import re


class FillSelectionError(ValueError):
    pass


def column_letters_to_number(letters: str) -> int:
    """Convert a Google Sheets column name to a 1-based column number."""
    normalized = str(letters or "").strip().upper()
    if not re.fullmatch(r"[A-Z]+", normalized):
        raise FillSelectionError(
            f"Tên cột không hợp lệ: '{letters}'. Ví dụ hợp lệ: A, D, AA."
        )

    value = 0
    for character in normalized:
        value = value * 26 + (ord(character) - 64)
    return value


def column_number_to_letters(column_number: int) -> str:
    """Convert a 1-based column number to Google Sheets letters."""
    number = int(column_number)
    if number < 1:
        raise FillSelectionError(f"Số cột không hợp lệ: {column_number}")

    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def parse_column_selection(value: str) -> tuple[int, ...]:
    """Parse selections such as ``D:I`` or ``D,F,H:J`` into column numbers."""
    normalized = re.sub(r"\s*:\s*", ":", str(value or "").strip().upper())
    if not normalized:
        raise FillSelectionError("Bạn chưa nhập cột cần fill.")

    selected: set[int] = set()
    for token in re.split(r"[\s,;]+", normalized):
        if not token:
            continue
        match = re.fullmatch(r"([A-Z]+)(?::([A-Z]+))?", token)
        if not match:
            raise FillSelectionError(
                f"Cú pháp cột không hợp lệ: '{token}'. "
                "Ví dụ hợp lệ: D:I hoặc D,F,H:J."
            )
        start_column = column_letters_to_number(match.group(1))
        end_column = column_letters_to_number(match.group(2) or match.group(1))
        if start_column > end_column:
            start_column, end_column = end_column, start_column
        selected.update(range(start_column, end_column + 1))

    if not selected:
        raise FillSelectionError("Không xác định được cột cần fill.")
    return tuple(sorted(selected))


def group_consecutive_columns(
    columns: tuple[int, ...],
) -> tuple[tuple[int, int], ...]:
    if not columns:
        return ()
    groups: list[tuple[int, int]] = []
    start = previous = columns[0]
    for column in columns[1:]:
        if column == previous + 1:
            previous = column
            continue
        groups.append((start, previous))
        start = previous = column
    groups.append((start, previous))
    return tuple(groups)


def normalize_column_selection(value: str) -> str:
    """Return a compact normalized representation of a column selection."""
    columns = parse_column_selection(value)
    return ",".join(
        column_number_to_letters(start)
        if start == end
        else f"{column_number_to_letters(start)}:{column_number_to_letters(end)}"
        for start, end in group_consecutive_columns(columns)
    )


def build_fill_copy_requests(
    sheet_id: int,
    source_row: int,
    last_row: int,
    selected_columns: tuple[int, ...],
) -> list[dict[str, object]]:
    """Build copyPaste requests for one or more contiguous column groups."""
    requests: list[dict[str, object]] = []
    for start_column, end_column in group_consecutive_columns(selected_columns):
        requests.append(
            {
                "copyPaste": {
                    "source": {
                        "sheetId": int(sheet_id),
                        "startRowIndex": int(source_row) - 1,
                        "endRowIndex": int(source_row),
                        "startColumnIndex": int(start_column) - 1,
                        "endColumnIndex": int(end_column),
                    },
                    "destination": {
                        "sheetId": int(sheet_id),
                        "startRowIndex": int(source_row),
                        "endRowIndex": int(last_row),
                        "startColumnIndex": int(start_column) - 1,
                        "endColumnIndex": int(end_column),
                    },
                    "pasteType": "PASTE_NORMAL",
                    "pasteOrientation": "NORMAL",
                }
            }
        )
    return requests
