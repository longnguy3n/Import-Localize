from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap

from import_localize.app.paths import APP_LOGO_PNG, APP_LOGO_SVG, ICONS_DIR


def icon(name: str) -> QIcon:
    """Return an SVG icon from the application assets directory."""
    return QIcon(str(ICONS_DIR / f"{name}.svg"))


def load_logo(width: int) -> QPixmap:
    """Load the PNG logo first and fall back to SVG."""
    logo_path = APP_LOGO_PNG if APP_LOGO_PNG.is_file() else APP_LOGO_SVG
    pixmap = QPixmap(str(logo_path))
    if pixmap.isNull():
        return QPixmap()
    return pixmap.scaledToWidth(
        width,
        Qt.TransformationMode.SmoothTransformation,
    )


def set_button_icon(button, name: str, size: int = 16) -> None:
    button.setIcon(icon(name))
    button.setIconSize(QSize(size, size))
