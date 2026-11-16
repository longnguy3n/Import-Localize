from __future__ import annotations

import traceback
import time
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from import_localize.models.import_job import ImportJob
from import_localize.services.csv_service import (
    CsvImportError,
    inspect_csv,
    load_csv_bundle,
)
from import_localize.services.google_service import (
    GoogleServiceError,
    connect_to_spreadsheet,
    transfer_tabs,
    sanitize_export_filename_part,
    validate_upload_headers,
    upload_bundles_fast,
)

from import_localize.services.transfer_files import (
    TransferFileError, parse_csv_filename, parse_tab_code, scan_folder, validate_csv_header,
)


class ImportWorker(QThread):
    progress_changed = Signal(int, str)
    log_emitted = Signal(str, str)
    completed = Signal(bool, str)

    def __init__(self, job: ImportJob, parent=None, *, annotations=None):
        super().__init__(parent)
        self.annotations = annotations
        self.job = job
        self._cancel_event = Event()

    def request_stop(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set() or self.isInterruptionRequested()

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log_emitted.emit(level, message)

    def _run_upload(self, connection) -> tuple[int, list[str]]:
        single = self.job.target_mode == "single"
        paths = self.job.file_paths[:1] if single else self.job.file_paths
        if not paths:
            raise CsvImportError("Chưa chọn file CSV upload.")
        infos = []
        seen = {}
        existing_targets = []
        tabs = transfer_tabs(connection, "upload")
        for path in paths:
            info = inspect_csv(path)
            prefix, code = parse_csv_filename(info.path, "upload")
            if prefix and prefix.casefold() != sanitize_export_filename_part(connection.spreadsheet_name).casefold():
                raise CsvImportError(f"{info.path.name}: tên bảng tính không khớp '{connection.spreadsheet_name}'.")
            if code in seen:
                raise CsvImportError(f"Hai file upload cùng mã {code}: {seen[code]} và {info.path.name}.")
            seen[code] = info.path.name
            # Preserve the spelling of the destination when creating a tab.
            desired = self.job.sheet_name if single else info.path.stem.rsplit(" - ", 1)[-1]
            if parse_tab_code(desired, "upload") != code:
                raise CsvImportError(f"{info.path.name}: mã {code} không khớp tab nhận {desired}.")
            matches = tabs.get(code, [])
            if len(matches) > 1:
                raise CsvImportError(f"Nhiều tab upload cùng mã {code}: " + ", ".join(t.title for t in matches))
            target = matches[0].title if matches else desired
            if matches:
                existing_targets.append(target)
            infos.append(replace(info, target_sheet_name=target))
        total_files = len(infos)
        imported_tabs = [info.target_sheet_name for info in infos]
        upload_plans = []

        for file_index, info in enumerate(infos, start=1):
            if self._is_cancelled():
                raise CancelledError()

            read_start = 18 + round((file_index - 1) / total_files * 34)
            read_end = 18 + round(file_index / total_files * 34)
            read_width = max(1, read_end - read_start)
            self._log(
                f"Đọc file {file_index}/{total_files}: {info.path.name} "
                f"→ tab '{info.target_sheet_name}'."
            )
            self.progress_changed.emit(read_start, f"Đang đọc {info.path.name}")

            file_job = replace(
                self.job,
                file_paths=(str(info.path),),
                sheet_name=info.target_sheet_name,
                import_mode="overwrite",
                first_row_is_header=True,
                strict_headers=True,
                add_source_column=False,
            )
            bundle = load_csv_bundle(
                file_job,
                progress_callback=lambda value, text, start=read_start, width=read_width: self.progress_changed.emit(
                    start + round(value / 100 * width), text
                ),
                log_callback=lambda message: self._log(message),
                cancel_callback=self._is_cancelled,
                annotations=self.annotations,
                info_lookup={str(info.path): info},
            )
            validate_csv_header(bundle.header, parse_tab_code(file_job.sheet_name, "upload"), info.path.name)
            upload_plans.append((bundle, file_job))

        self.progress_changed.emit(53, "Đang ghi nhanh nhiều tab lên Google Sheets")
        validate_upload_headers(connection, existing_targets, cancel_callback=self._is_cancelled)
        if self.job.upload_folder:
            scan = scan_folder(self.job.upload_folder, "upload")
            if scan.issues:
                raise CsvImportError("\n".join(scan.issues))
            expected_paths = {Path(p) for p in paths}
            scanned_paths = set(scan.paths)
            if single:
                scanned_paths = {p for p in scanned_paths if parse_csv_filename(p, "upload")[1] in seen}
            if scanned_paths != expected_paths:
                raise CsvImportError("Thư mục upload đã thay đổi. Quét lại danh sách trước khi ghi.")
        total_rows = upload_bundles_fast(
            connection,
            upload_plans,
            progress_callback=lambda value, text: self.progress_changed.emit(
                min(98, 53 + round(value * 0.45)), text
            ),
            log_callback=lambda message: self._log(message),
            cancel_callback=self._is_cancelled,
        )
        return total_rows, imported_tabs

    def run(self) -> None:
        started_at = time.perf_counter()
        try:
            self.progress_changed.emit(2, "Đang kiểm tra Google Sheet")
            connection = connect_to_spreadsheet(
                self.job.spreadsheet_url,
                progress_callback=lambda value, text: self.progress_changed.emit(
                    max(2, min(18, round(value * 0.16) + 2)), text
                ),
                log_callback=lambda message: self._log(message),
                cancel_callback=self._is_cancelled,
            )

            total_rows, imported_tabs = self._run_upload(connection)

            self.progress_changed.emit(100, "Hoàn tất")
            tab_preview = ", ".join(imported_tabs[:8])
            if len(imported_tabs) > 8:
                tab_preview += f", … (+{len(imported_tabs) - 8})"
            elapsed = time.perf_counter() - started_at
            self._log(f"Tổng thời gian Import: {elapsed:.2f} giây.", "SUCCESS")
            self.completed.emit(
                True,
                f"Import hoàn tất trong {elapsed:.2f} giây: {total_rows} dòng vào "
                f"{len(imported_tabs)} tab ({tab_preview}).",
            )
        except CancelledError:
            self.completed.emit(False, "Đã dừng thao tác theo yêu cầu.")
        except (GoogleServiceError, CsvImportError, TransferFileError) as exc:
            self._log(str(exc), "FAIL")
            self.completed.emit(False, f"Import thất bại: {exc}")
        except Exception as exc:
            self._log(traceback.format_exc(), "FAIL")
            self.completed.emit(False, f"Lỗi không mong đợi: {exc}")
