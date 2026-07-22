from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from .constants import APP_NAME, ORGANIZATION_NAME
from .paths import APP_ICON_ICO, APP_LOGO_PNG, APP_LOGO_SVG


def _first_existing_path(*paths: Path) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Create QApplication with a valid system font and application icon."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(list(argv if argv is not None else sys.argv))
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)

    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    if font.pointSizeF() <= 0:
        font.setPointSizeF(10.0)
    app.setFont(font)

    icon_path = _first_existing_path(
        APP_ICON_ICO,
        APP_LOGO_PNG,
        APP_LOGO_SVG,
    )
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))

    return app
