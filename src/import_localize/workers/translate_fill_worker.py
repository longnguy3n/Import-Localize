from __future__ import annotations

import traceback
import time
from concurrent.futures import CancelledError
from threading import Event

from PySide6.QtCore import QThread, Signal

from import_localize.models.import_job import FillOptions
from import_localize.services.google_service import (
    GoogleServiceError,
    connect_to_spreadsheet,
    fill_translate_data_columns,
)


class TranslateFillWorker(QThread):
    """Run a configurable Google Sheets fill action independently from CSV import."""

    progress_changed = Signal(int, str)
    log_emitted = Signal(str, str)
    completed = Signal(bool, str)

    def __init__(
        self,
        spreadsheet_url: str,
        options: FillOptions,
        parent=None,
    ):
        super().__init__(parent)
        self.spreadsheet_url = spreadsheet_url
        self.options = options
        self._cancel_event = Event()

    def request_stop(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set() or self.isInterruptionRequested()

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log_emitted.emit(level, message)

    def run(self) -> None:
        started_at = time.perf_counter()
        try:
            options = self.options
            self.progress_changed.emit(4, "Đang kết nối Google Sheet")
            connection = connect_to_spreadsheet(
                self.spreadsheet_url,
                progress_callback=lambda value, text: self.progress_changed.emit(
                    max(4, min(38, 4 + round(value * 0.34))), text
                ),
                log_callback=lambda message: self._log(message),
                cancel_callback=self._is_cancelled,
            )

            self.progress_changed.emit(
                42,
                f"Đang kiểm tra tab {options.sheet_name}",
            )
            applied, message, last_row = fill_translate_data_columns(
                connection,
                sheet_name=options.sheet_name,
                source_row=options.source_row,
                columns=options.columns,
                progress_callback=lambda value, text: self.progress_changed.emit(
                    min(99, 42 + round(value * 0.57)), text
                ),
                log_callback=lambda message: self._log(message),
                cancel_callback=self._is_cancelled,
            )

            if applied:
                self._log(message, "SUCCESS")
                self.progress_changed.emit(
                    100,
                    f"Đã fill xong tab {options.sheet_name}",
                )
                elapsed = time.perf_counter() - started_at
                self._log(f"Tổng thời gian Fill: {elapsed:.2f} giây.", "SUCCESS")
                self.completed.emit(True, f"{message} Thời gian: {elapsed:.2f} giây.")
                return

            self._log(message, "WARNING")
            self.progress_changed.emit(100, "Không có dữ liệu cần fill")
            suffix = f" Hàng dữ liệu cuối: {last_row}." if last_row else ""
            elapsed = time.perf_counter() - started_at
            self.completed.emit(True, message + suffix + f" Thời gian: {elapsed:.2f} giây.")
        except CancelledError:
            self.completed.emit(False, "Đã dừng thao tác Fill theo yêu cầu.")
        except GoogleServiceError as exc:
            self._log(str(exc), "FAIL")
            self.completed.emit(False, f"Fill dữ liệu thất bại: {exc}")
        except Exception as exc:
            self._log(traceback.format_exc(), "FAIL")
            self.completed.emit(False, f"Lỗi không mong đợi khi fill dữ liệu: {exc}")
