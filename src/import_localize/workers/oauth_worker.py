from __future__ import annotations

from concurrent.futures import CancelledError
from threading import Event

from PySide6.QtCore import QThread, Signal

from import_localize.services.google_service import authenticate_google_account


class OAuthWorker(QThread):
    log_emitted = Signal(str)
    completed = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_event = Event()

    def request_stop(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            success, message = authenticate_google_account(
                log_callback=self.log_emitted.emit,
                cancel_callback=self._cancel_event.is_set,
            )
            self.completed.emit(success, message)
        except CancelledError:
            self.completed.emit(False, "Đã dừng đăng nhập Google.")
        except Exception as exc:
            self.completed.emit(False, f"Không thể đăng nhập Google: {exc}")
