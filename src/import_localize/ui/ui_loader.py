from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from PySide6.QtCore import QFile, QIODevice, QObject
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget

T = TypeVar("T", bound=QObject)


class UiLoadError(RuntimeError):
    pass


def load_ui(path: str | Path, parent: QWidget | None = None) -> QWidget:
    ui_path = Path(path).resolve()
    if not ui_path.is_file():
        raise UiLoadError(f"Không tìm thấy file UI: {ui_path}")

    handle = QFile(str(ui_path))
    if not handle.open(QIODevice.OpenModeFlag.ReadOnly):
        raise UiLoadError(f"Không thể mở file UI: {ui_path}")

    try:
        loader = QUiLoader()
        widget = loader.load(handle, parent)
        if widget is None:
            raise UiLoadError(loader.errorString() or f"Không thể nạp {ui_path.name}")
        return widget
    finally:
        handle.close()


def require_object(root: QObject, name: str, expected_type: type[T]) -> T:
    obj = root.findChild(expected_type, name)
    if obj is None:
        raise UiLoadError(
            f"File UI thiếu objectName '{name}' ({expected_type.__name__})."
        )
    return obj
