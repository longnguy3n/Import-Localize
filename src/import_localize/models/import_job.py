from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True, frozen=True)
class CsvFileInfo:
    path: Path
    size_bytes: int
    encoding: str
    delimiter: str
    source_spreadsheet_name: str = ""
    target_sheet_name: str = ""

    @property
    def display_delimiter(self) -> str:
        return {
            ",": "Dấu phẩy (,)",
            ";": "Dấu chấm phẩy (;)",
            "\t": "Tab",
            "|": "Dấu gạch đứng (|)",
        }.get(self.delimiter, repr(self.delimiter))


@dataclass(slots=True, frozen=True)
class ImportJob:
    file_paths: tuple[str, ...]
    spreadsheet_url: str
    # multiple: mỗi file vào một tab theo mẫu [Tên Google Sheet] - [Tên tab].csv.
    # single: chỉ file đầu tiên trong danh sách được nhập vào ``sheet_name``.
    target_mode: str = "multiple"
    sheet_name: str = ""
    import_mode: str = "overwrite"
    value_input_option: str = "RAW"
    first_row_is_header: bool = True
    strict_headers: bool = True
    add_source_column: bool = False


@dataclass(slots=True)
class CsvBundle:
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    encodings: dict[str, str] = field(default_factory=dict)
    delimiters: dict[str, str] = field(default_factory=dict)

    @property
    def column_count(self) -> int:
        candidates = [len(self.header)]
        candidates.extend(len(row) for row in self.rows[:1000])
        return max(candidates, default=0)

    @property
    def row_count(self) -> int:
        return len(self.rows)
