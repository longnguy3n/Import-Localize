from __future__ import annotations

import traceback
import time
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from import_localize.services.google_service import (
    GoogleServiceError,
    connect_to_spreadsheet,
    download_export_tabs_as_csv,
)


class ExportTabsWorker(QThread):
    """Download every ``export_*`` worksheet as Google's raw CSV bytes."""

    progress_changed = Signal(int, str)
    log_emitted = Signal(str, str)
    completed = Signal(bool, str)

    def __init__(self, spreadsheet_url: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.spreadsheet_url = spreadsheet_url
        self.output_dir = output_dir
        self._cancel_event = Event()

    def request_stop(self) -> None:
        self._cancel_event.set()

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log_emitted.emit(level, message)

    def run(self) -> None:
        started_at = time.perf_counter()
        try:
            self.progress_changed.emit(2, "Đang kết nối Google Sheet")
            connection = connect_to_spreadsheet(
                self.spreadsheet_url,
                progress_callback=lambda value, text: self.progress_changed.emit(
                    max(2, min(24, 2 + round(value * 0.22))), text
                ),
                log_callback=lambda message: self._log(message),
                cancel_callback=self._is_cancelled,
            )

            self.progress_changed.emit(25, "Đang quét các tab export_*")
            created_files = download_export_tabs_as_csv(
                connection,
                self.output_dir,
                progress_callback=lambda value, text: self.progress_changed.emit(
                    min(100, 25 + round(value * 0.75)), text
                ),
                log_callback=lambda message: self._log(message),
                cancel_callback=self._is_cancelled,
            )

            folder = Path(self.output_dir).expanduser().resolve()
            self.progress_changed.emit(100, "Đã tải xong CSV")
            self.completed.emit(
                True,
                f"Đã tải {len(created_files)} file CSV vào:\n{folder}",
            )
        except CancelledError:
            self.completed.emit(False, "Đã dừng tải các tab export_* theo yêu cầu.")
        except GoogleServiceError as exc:
            self._log(str(exc), "FAIL")
            self.completed.emit(False, f"Tải CSV thất bại: {exc}")
        except Exception as exc:
            self._log(traceback.format_exc(), "FAIL")
            self.completed.emit(False, f"Lỗi không mong đợi khi tải CSV: {exc}")
