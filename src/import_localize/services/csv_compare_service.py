"""Compare localization CSVs by key and column name, preserving cell contents."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from import_localize.services.csv_service import (
    CSV_READ_ENCODING, CancelCallback, CsvImportError, _check_cancel, inspect_csv,
)


@dataclass(slots=True)
class KeyDifference:
    key: str
    status: str
    before: dict[str, str] | None
    after: dict[str, str] | None
    changed_columns: tuple[str, ...]


@dataclass(slots=True)
class CsvComparison:
    old_path: Path
    new_path: Path
    columns: dict[str, str]
    added_columns: tuple[str, ...]
    removed_columns: tuple[str, ...]
    differences: list[KeyDifference]

    def count(self, status: str) -> int:
        return sum(item.status == status for item in self.differences)


def _read_keyed_csv(path: str | Path, cancel: CancelCallback):
    _check_cancel(cancel)
    info = inspect_csv(path)
    records: dict[str, dict[str, str]] = {}
    try:
        with info.path.open(encoding=CSV_READ_ENCODING, newline="") as handle:
            reader = csv.reader(handle, delimiter=info.delimiter, strict=True)
            header = next((row for row in reader if any(cell.strip() for cell in row)), None)
            if not header:
                raise CsvImportError(f"{info.path.name}: CSV rỗng hoặc thiếu header.")
            names = [cell.strip() for cell in header]
            normalized = [name.casefold() for name in names]
            if "" in normalized or len(set(normalized)) != len(normalized):
                raise CsvImportError(f"{info.path.name}: tên cột rỗng hoặc trùng nhau.")
            if "key" not in normalized:
                raise CsvImportError(f"{info.path.name}: thiếu cột 'key' trong header.")
            key_index = normalized.index("key")
            first_lines: dict[str, int] = {}
            for row in reader:
                _check_cancel(cancel)
                if not row or not any(cell.strip() for cell in row):
                    continue
                line = reader.line_num
                if len(row) > len(header):
                    raise CsvImportError(f"{info.path.name}, dòng {line}: số cột vượt quá header.")
                row += [""] * (len(header) - len(row))
                key = row[key_index].strip()
                if not key:
                    raise CsvImportError(f"{info.path.name}, dòng {line}: key rỗng.")
                if key in records:
                    raise CsvImportError(
                        f"{info.path.name}: key '{key}' trùng ở dòng {first_lines[key]} và {line}. "
                        "Hãy sửa key trùng trước khi so sánh."
                    )
                first_lines[key] = line
                records[key] = {col: value for col, value in zip(normalized, row) if col != "key"}
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CsvImportError(f"Không thể đọc {info.path.name} dưới dạng CSV UTF-8: {exc}") from exc
    return info.path, {col: name for col, name in zip(normalized, names) if col != "key"}, records


def compare_csv_files(
    old_path: str | Path, new_path: str | Path, *, cancel_callback: CancelCallback = None,
) -> CsvComparison:
    old_path, old_columns, before = _read_keyed_csv(old_path, cancel_callback)
    new_path, new_columns, after = _read_keyed_csv(new_path, cancel_callback)
    columns = {**old_columns, **new_columns}
    differences = []
    # Stable display order follows the new file; old-only keys are appended.
    for key in dict.fromkeys((*after, *before)):
        _check_cancel(cancel_callback)
        old, new = before.get(key), after.get(key)
        changed = tuple(col for col in columns if (old or {}).get(col) != (new or {}).get(col))
        status = "added" if old is None else "removed" if new is None else "changed" if changed else "unchanged"
        differences.append(KeyDifference(key, status, old, new, changed))
    return CsvComparison(
        old_path, new_path, columns,
        tuple(col for col in new_columns if col not in old_columns),
        tuple(col for col in old_columns if col not in new_columns), differences,
    )
