from __future__ import annotations

import traceback
from concurrent.futures import CancelledError
from threading import Event

from PySide6.QtCore import QThread, Signal

from import_localize.services.google_service import (
    GoogleServiceError,
    connect_to_spreadsheet,
    fill_translate_data_columns,
)


class TranslateFillWorker(QThread):
    """Run the Translate_Data fill action independently from CSV import."""

    progress_changed = Signal(int, str)
    log_emitted = Signal(str, str)
    completed = Signal(bool, str)

    def __init__(self, spreadsheet_url: str, parent=None):
        super().__init__(parent)
        self.spreadsheet_url = spreadsheet_url
        self._cancel_event = Event()

    def request_stop(self) -> None:
        self._cancel_event.set()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log_emitted.emit(level, message)

    def run(self) -> None:
        try:
            self.progress_changed.emit(4, "Đang kết nối Google Sheet")
            connection = connect_to_spreadsheet(
                self.spreadsheet_url,
                progress_callback=lambda value, text: self.progress_changed.emit(
                    max(4, min(38, 4 + round(value * 0.34))), text
                ),
                log_callback=lambda message: self._log(message),
                cancel_callback=self._is_cancelled,
            )

            self.progress_changed.emit(42, "Đang kiểm tra tab Translate_Data")
            applied, message, last_row = fill_translate_data_columns(
                connection,
                progress_callback=lambda value, text: self.progress_changed.emit(
                    min(99, 42 + round(value * 0.57)), text
                ),
                cancel_callback=self._is_cancelled,
            )

            if applied:
                self._log(message, "SUCCESS")
                self.progress_changed.emit(100, "Đã fill xong Translate_Data")
                self.completed.emit(True, message)
                return

            # A missing tab, empty D2:I2, or no rows below row 2 is a completed
            # validation result rather than a failed network operation.
            self._log(message, "WARNING")
            self.progress_changed.emit(100, "Không có dữ liệu cần fill")
            suffix = f" Hàng dữ liệu cuối: {last_row}." if last_row else ""
            self.completed.emit(True, message + suffix)
        except CancelledError:
            self.completed.emit(False, "Đã dừng Fill Translate_Data theo yêu cầu.")
        except GoogleServiceError as exc:
            self._log(str(exc), "FAIL")
            self.completed.emit(False, f"Fill Translate_Data thất bại: {exc}")
        except Exception as exc:
            self._log(traceback.format_exc(), "FAIL")
            self.completed.emit(False, f"Lỗi không mong đợi khi fill Translate_Data: {exc}")
