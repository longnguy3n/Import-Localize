from __future__ import annotations

import traceback
from concurrent.futures import CancelledError
from dataclasses import replace
from threading import Event

from PySide6.QtCore import QThread, Signal

from import_localize.models.import_job import CsvFileInfo, ImportJob
from import_localize.services.csv_service import (
    CsvImportError,
    inspect_csv,
    load_csv_bundle,
    normalize_spreadsheet_title,
)
from import_localize.services.google_service import (
    GoogleServiceError,
    connect_to_spreadsheet,
    upload_bundles_fast,
)


class ImportWorker(QThread):
    progress_changed = Signal(int, str)
    log_emitted = Signal(str, str)
    completed = Signal(bool, str)

    def __init__(self, job: ImportJob, parent=None):
        super().__init__(parent)
        self.job = job
        self._cancel_event = Event()

    def request_stop(self) -> None:
        self._cancel_event.set()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log_emitted.emit(level, message)

    def _inspect_multiple_targets(self, spreadsheet_name: str) -> list[CsvFileInfo]:
        infos = [
            inspect_csv(path, require_localization_name=True)
            for path in self.job.file_paths
        ]
        expected = normalize_spreadsheet_title(spreadsheet_name)
        mismatched = [
            info.path.name
            for info in infos
            if normalize_spreadsheet_title(info.source_spreadsheet_name) != expected
        ]
        if mismatched:
            preview = "\n- ".join(mismatched[:10])
            raise CsvImportError(
                "Tên Google Sheet ở đầu tên file không khớp bảng tính đang mở "
                f"('{spreadsheet_name}'). File không khớp:\n- {preview}"
            )

        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for info in infos:
            key = info.target_sheet_name.casefold()
            if key in seen:
                duplicates.append(
                    f"'{info.target_sheet_name}': {seen[key]} và {info.path.name}"
                )
            else:
                seen[key] = info.path.name
        if duplicates:
            raise CsvImportError(
                "Có nhiều file cùng trỏ tới một tab đích. Mỗi tab chỉ được có "
                "một file trong một lượt import:\n- " + "\n- ".join(duplicates)
            )
        return infos

    def _run_single(self, connection) -> tuple[int, list[str]]:
        if not self.job.file_paths:
            raise CsvImportError("Chưa chọn file CSV.")

        first_path = self.job.file_paths[0]
        info = inspect_csv(first_path, require_localization_name=False)
        self._log(
            f"Chế độ một sheet: dùng file đầu tiên '{info.path.name}' "
            f"→ tab '{self.job.sheet_name}'."
        )

        file_job = replace(
            self.job,
            file_paths=(str(info.path),),
            target_mode="single",
            import_mode="overwrite",
            first_row_is_header=True,
            strict_headers=True,
            add_source_column=False,
        )
        bundle = load_csv_bundle(
            file_job,
            progress_callback=lambda value, text: self.progress_changed.emit(
                18 + round(value * 0.32), text
            ),
            log_callback=lambda message: self._log(message),
            cancel_callback=self._is_cancelled,
        )
        rows_written = upload_bundles_fast(
            connection,
            [(bundle, file_job)],
            progress_callback=lambda value, text: self.progress_changed.emit(
                min(98, 50 + round(value * 0.48)), text
            ),
            log_callback=lambda message: self._log(message),
            cancel_callback=self._is_cancelled,
        )
        return rows_written, [self.job.sheet_name]

    def _run_multiple(self, connection) -> tuple[int, list[str]]:
        infos = self._inspect_multiple_targets(connection.spreadsheet_name)
        total_files = len(infos)
        imported_tabs = [info.target_sheet_name for info in infos]
        upload_plans = []

        self._log(
            f"Chế độ nhiều sheet: đã xác định {total_files} tab đích từ tên file. "
            "Ứng dụng sẽ đọc toàn bộ CSV trước rồi ghi các tab theo lô để giảm "
            "số lần gọi Google Sheets API."
        )

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
                target_mode="multiple",
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
            )
            upload_plans.append((bundle, file_job))

        self.progress_changed.emit(53, "Đang ghi nhanh nhiều tab lên Google Sheets")
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

            if self.job.target_mode == "single":
                total_rows, imported_tabs = self._run_single(connection)
            else:
                total_rows, imported_tabs = self._run_multiple(connection)

            self.progress_changed.emit(100, "Hoàn tất")
            tab_preview = ", ".join(imported_tabs[:8])
            if len(imported_tabs) > 8:
                tab_preview += f", … (+{len(imported_tabs) - 8})"
            self.completed.emit(
                True,
                f"Import hoàn tất: {total_rows} dòng vào {len(imported_tabs)} tab "
                f"({tab_preview}).",
            )
        except CancelledError:
            self.completed.emit(False, "Đã dừng thao tác theo yêu cầu.")
        except (GoogleServiceError, CsvImportError) as exc:
            self._log(str(exc), "FAIL")
            self.completed.emit(False, f"Import thất bại: {exc}")
        except Exception as exc:
            self._log(traceback.format_exc(), "FAIL")
            self.completed.emit(False, f"Lỗi không mong đợi: {exc}")
