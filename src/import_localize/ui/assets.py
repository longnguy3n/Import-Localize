from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QAbstractButton, QLabel

from import_localize.app.paths import APP_LOGO_PNG, APP_LOGO_SVG, ICONS_DIR
from import_localize.ui.uu_theme import color


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


@lru_cache(maxsize=96)
def _tinted_icon(name: str, size: int, foreground: str, disabled: str) -> QIcon:
    """Render the original SVG silhouette at the native and high-DPI sizes."""
    source = QIcon(str(ICONS_DIR / f"{name}.svg"))
    result = QIcon()
    for scale in (1, 2, 3):
        side = size * scale
        original = source.pixmap(QSize(side, side))
        if original.isNull():
            continue
        for mode, value in ((QIcon.Mode.Normal, foreground), (QIcon.Mode.Disabled, disabled)):
            pixmap = original.copy()
            with QPainter(pixmap) as painter:
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor(value))
            result.addPixmap(pixmap, mode)
            if mode == QIcon.Mode.Normal:
                result.addPixmap(pixmap, QIcon.Mode.Active)
    return result


def set_button_icon(button: QAbstractButton, name: str, size: int = 16) -> None:
    button.ensurePolished()
    palette = button.palette()
    normal = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText).name()
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText).name()
    button.setIcon(_tinted_icon(name, size, normal, disabled))
    button.setIconSize(QSize(size, size))


def set_label_icon(label: QLabel, name: str, size: int) -> None:
    asset = _tinted_icon(name, size, color("object-secondary"), color("object-disabled"))
    label.setPixmap(asset.pixmap(QSize(size, size), label.devicePixelRatioF()))
