from __future__ import annotations

from threading import Event

from PySide6.QtCore import QThread, Signal

from import_localize.services.update_service import (
    PreparedUpdate,
    UpdateCancelled,
    UpdateRelease,
    fetch_latest_release,
    prepare_update,
)


class UpdateCheckWorker(QThread):
    completed = Signal(bool, object, str)

    def __init__(self, repository: str, parent=None):
        super().__init__(parent)
        self.repository = repository
        self._stop_event = Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def _cancelled(self) -> bool:
        return self._stop_event.is_set()

    def run(self) -> None:
        try:
            release = fetch_latest_release(
                self.repository,
                cancel_callback=self._cancelled,
            )
            self.completed.emit(True, release, "Đã kiểm tra bản phát hành mới nhất.")
        except UpdateCancelled as exc:
            self.completed.emit(False, None, str(exc))
        except Exception as exc:
            self.completed.emit(False, None, str(exc))


class UpdateDownloadWorker(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(bool, object, str)

    def __init__(self, release: UpdateRelease, parent=None):
        super().__init__(parent)
        self.release = release
        self._stop_event = Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def _cancelled(self) -> bool:
        return self._stop_event.is_set()

    def run(self) -> None:
        try:
            prepared: PreparedUpdate = prepare_update(
                self.release,
                progress_callback=self.progress_changed.emit,
                cancel_callback=self._cancelled,
            )
            self.completed.emit(
                True,
                prepared,
                f"Bản v{self.release.version} đã tải xong và sẵn sàng cài đặt.",
            )
        except UpdateCancelled as exc:
            self.completed.emit(False, None, str(exc))
        except Exception as exc:
            self.completed.emit(False, None, str(exc))
