from __future__ import annotations

import csv
import os
import re
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Callable, Iterable

from import_localize.models.import_job import CsvBundle, CsvFileInfo, ImportJob

ProgressCallback = Callable[[int, str], None] | None
LogCallback = Callable[[str], None] | None
CancelCallback = Callable[[], bool] | None

SUPPORTED_DELIMITERS = ",;\t|"
ENCODING_CANDIDATES = (
    "utf-8-sig",
    "utf-8",
    "cp1258",
    "cp1252",
    "latin-1",
)


INVALID_WORKSHEET_CHARACTERS = re.compile(r"[:\\/?*\[\]]")
FILENAME_SEPARATOR = " - "


def parse_localization_filename(path: str | Path) -> tuple[str, str]:
    """Tách tên file dạng ``[Tên Google Sheet] - [Tên tab].csv``.

    Dùng ``rsplit`` để phần tên Google Sheet vẫn có thể chứa dấu gạch ngang.
    Tên tab được kiểm tra theo giới hạn của Google Sheets trước khi import.
    """
    csv_path = Path(path)
    stem = csv_path.stem.strip()
    if FILENAME_SEPARATOR not in stem:
        raise CsvImportError(
            f"Tên file '{csv_path.name}' không đúng định dạng. "
            "Hãy đặt tên: [Tên Google Sheet] - [Tên tab].csv"
        )

    spreadsheet_name, sheet_name = (
        part.strip() for part in stem.rsplit(FILENAME_SEPARATOR, 1)
    )
    if not spreadsheet_name or not sheet_name:
        raise CsvImportError(
            f"Tên file '{csv_path.name}' thiếu tên Google Sheet hoặc tên tab."
        )
    validate_worksheet_title(sheet_name, source_name=csv_path.name)
    return spreadsheet_name, sheet_name


def validate_worksheet_title(sheet_name: str, *, source_name: str = "") -> str:
    """Kiểm tra và trả về tên tab Google Sheets đã được trim."""
    cleaned = str(sheet_name or "").strip()
    origin = f" trong '{source_name}'" if source_name else ""
    if not cleaned:
        raise CsvImportError("Tên Sheet/tab không được để trống.")
    if len(cleaned) > 100:
        raise CsvImportError(f"Tên tab{origin} dài quá 100 ký tự.")
    if INVALID_WORKSHEET_CHARACTERS.search(cleaned):
        raise CsvImportError(
            f"Tên tab '{cleaned}'{origin} chứa ký tự không hợp lệ: : \\ / ? * [ ]"
        )
    if any(ord(character) < 32 for character in cleaned):
        raise CsvImportError(
            f"Tên tab '{cleaned}'{origin} chứa ký tự điều khiển không hợp lệ."
        )
    return cleaned


def normalize_spreadsheet_title(value: str) -> str:
    """Chuẩn hóa nhẹ để so tên file với tên Google Spreadsheet thực tế."""
    text = re.sub(r"[_\-]+", " ", str(value or ""))
    return " ".join(text.split()).casefold()


class CsvImportError(RuntimeError):
    pass


class HeaderMismatchError(CsvImportError):
    pass


def _check_cancel(cancel_callback: CancelCallback) -> None:
    if cancel_callback and cancel_callback():
        raise CancelledError("Người dùng đã dừng thao tác.")


def _log(callback: LogCallback, message: str) -> None:
    if callback:
        callback(message)


def _progress(callback: ProgressCallback, value: int, message: str) -> None:
    if callback:
        callback(max(0, min(100, int(value))), message)


def _decode_sample(raw: bytes) -> tuple[str, str]:
    for encoding in ENCODING_CANDIDATES:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8 (thay ký tự lỗi)"


def _detect_delimiter(sample: str) -> str:
    if not sample.strip():
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=SUPPORTED_DELIMITERS)
        return dialect.delimiter
    except csv.Error:
        counts = {item: sample.count(item) for item in SUPPORTED_DELIMITERS}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","


def inspect_csv(
    path: str | Path,
    *,
    require_localization_name: bool = False,
) -> CsvFileInfo:
    csv_path = Path(path).expanduser().resolve()
    if not csv_path.is_file():
        raise CsvImportError(f"Không tìm thấy file CSV: {csv_path}")
    if csv_path.suffix.casefold() != ".csv":
        raise CsvImportError(f"File không phải CSV: {csv_path.name}")

    with csv_path.open("rb") as handle:
        raw = handle.read(131072)
    sample, encoding = _decode_sample(raw)
    delimiter = _detect_delimiter(sample)
    try:
        source_spreadsheet_name, target_sheet_name = parse_localization_filename(csv_path)
    except CsvImportError:
        if require_localization_name:
            raise
        source_spreadsheet_name, target_sheet_name = "", ""
    return CsvFileInfo(
        path=csv_path,
        size_bytes=csv_path.stat().st_size,
        encoding=encoding,
        delimiter=delimiter,
        source_spreadsheet_name=source_spreadsheet_name,
        target_sheet_name=target_sheet_name,
    )


def _clean_row(row: Iterable[object]) -> list[str]:
    return ["" if value is None else str(value).strip() for value in row]


def _make_unique_header(header: list[str]) -> list[str]:
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(header, start=1):
        base = value.strip() or f"Cột {index}"
        key = base.casefold()
        count = seen.get(key, 0) + 1
        seen[key] = count
        result.append(base if count == 1 else f"{base} ({count})")
    return result


def _header_keys(header: list[str]) -> list[str]:
    return [" ".join(value.split()).casefold() for value in header]


def _read_csv_rows(
    info: CsvFileInfo,
    *,
    cancel_callback: CancelCallback = None,
) -> list[list[str]]:
    rows: list[list[str]] = []
    try:
        with info.path.open(
            "r",
            encoding=info.encoding.split(" ", 1)[0],
            newline="",
            errors="replace",
        ) as handle:
            reader = csv.reader(handle, delimiter=info.delimiter)
            for index, row in enumerate(reader):
                if index % 500 == 0:
                    _check_cancel(cancel_callback)
                cleaned = _clean_row(row)
                if cleaned and any(cell != "" for cell in cleaned):
                    rows.append(cleaned)
    except (OSError, csv.Error) as exc:
        raise CsvImportError(f"Không thể đọc {info.path.name}: {exc}") from exc
    return rows


def _pad_rows(rows: list[list[str]], width: int) -> None:
    for row in rows:
        if len(row) < width:
            row.extend([""] * (width - len(row)))


def load_csv_bundle(
    job: ImportJob,
    *,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> CsvBundle:
    if not job.file_paths:
        raise CsvImportError("Chưa chọn file CSV.")

    bundle = CsvBundle()
    canonical_header: list[str] = []
    canonical_keys: list[str] = []
    column_lookup: dict[str, int] = {}
    no_header_width = 0
    total_files = len(job.file_paths)

    for file_index, raw_path in enumerate(job.file_paths, start=1):
        _check_cancel(cancel_callback)
        info = inspect_csv(raw_path)
        bundle.source_files.append(str(info.path))
        bundle.encodings[info.path.name] = info.encoding
        bundle.delimiters[info.path.name] = info.delimiter
        _log(
            log_callback,
            f"Đang đọc {info.path.name} — {info.encoding}, "
            f"phân cách {info.display_delimiter}.",
        )
        rows = _read_csv_rows(info, cancel_callback=cancel_callback)
        if not rows:
            _log(log_callback, f"Bỏ qua {info.path.name}: file không có dữ liệu.")
            continue

        if job.first_row_is_header:
            file_header = _make_unique_header(rows[0])
            file_rows = rows[1:]
            file_keys = _header_keys(file_header)

            if not canonical_header:
                canonical_header = list(file_header)
                canonical_keys = list(file_keys)
                column_lookup = {key: index for index, key in enumerate(canonical_keys)}
            elif job.strict_headers:
                if len(set(file_keys)) != len(file_keys):
                    raise HeaderMismatchError(
                        f"Header trong {info.path.name} có cột trùng tên. "
                        "Hãy sửa CSV hoặc tắt chế độ kiểm tra header nghiêm ngặt."
                    )
                if set(file_keys) != set(canonical_keys):
                    missing = [canonical_header[i] for i, key in enumerate(canonical_keys) if key not in file_keys]
                    extra = [file_header[i] for i, key in enumerate(file_keys) if key not in canonical_keys]
                    detail: list[str] = []
                    if missing:
                        detail.append("thiếu: " + ", ".join(missing))
                    if extra:
                        detail.append("dư: " + ", ".join(extra))
                    raise HeaderMismatchError(
                        f"Header của {info.path.name} không khớp file đầu tiên"
                        + (" (" + "; ".join(detail) + ")" if detail else "")
                        + "."
                    )
            else:
                for header_value, key in zip(file_header, file_keys):
                    if key not in column_lookup:
                        column_lookup[key] = len(canonical_header)
                        canonical_header.append(header_value)
                        canonical_keys.append(key)
                        for previous_row in bundle.rows:
                            previous_row.append("")

            file_index_by_key = {key: index for index, key in enumerate(file_keys)}
            for row_number, row in enumerate(file_rows, start=2):
                _check_cancel(cancel_callback if row_number % 500 == 0 else None)
                if len(row) > len(file_header):
                    raise CsvImportError(
                        f"{info.path.name}, dòng {row_number} có {len(row)} cột "
                        f"nhưng header chỉ có {len(file_header)} cột."
                    )
                if len(row) < len(file_header):
                    row.extend([""] * (len(file_header) - len(row)))

                aligned = [""] * len(canonical_header)
                for key, source_index in file_index_by_key.items():
                    target_index = column_lookup.get(key)
                    if target_index is not None:
                        aligned[target_index] = row[source_index]
                if job.add_source_column:
                    aligned.insert(0, info.path.name)
                bundle.rows.append(aligned)
        else:
            file_rows = rows
            current_width = max((len(row) for row in file_rows), default=0)
            if current_width > no_header_width:
                no_header_width = current_width
                for previous_row in bundle.rows:
                    missing = no_header_width + (1 if job.add_source_column else 0) - len(previous_row)
                    if missing > 0:
                        previous_row.extend([""] * missing)
            for row_number, row in enumerate(file_rows, start=1):
                _check_cancel(cancel_callback if row_number % 500 == 0 else None)
                if len(row) < no_header_width:
                    row.extend([""] * (no_header_width - len(row)))
                if job.add_source_column:
                    row.insert(0, info.path.name)
                bundle.rows.append(row)

        _log(
            log_callback,
            f"Đã đọc {info.path.name}: {max(0, len(rows) - (1 if job.first_row_is_header else 0))} dòng dữ liệu.",
        )
        _progress(
            progress_callback,
            round(file_index / total_files * 100),
            f"Đã đọc {file_index}/{total_files} file CSV",
        )

    if job.first_row_is_header:
        bundle.header = list(canonical_header)
        if job.add_source_column and bundle.header:
            bundle.header.insert(0, "Nguồn file")
    else:
        bundle.header = []

    if not bundle.rows and not bundle.header:
        raise CsvImportError("Các file đã chọn không có dữ liệu để nhập.")

    width = max(
        len(bundle.header),
        max((len(row) for row in bundle.rows), default=0),
    )
    if bundle.header and len(bundle.header) < width:
        bundle.header.extend(
            f"Cột {index}" for index in range(len(bundle.header) + 1, width + 1)
        )
    _pad_rows(bundle.rows, width)

    _log(
        log_callback,
        f"Tổng hợp hoàn tất: {len(bundle.source_files)} file, "
        f"{bundle.row_count} dòng, {width} cột.",
    )
    return bundle


def format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"
