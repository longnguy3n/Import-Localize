import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from shiboken6 import ownedByPython

from import_localize.app.bootstrap import create_application


@pytest.fixture(scope="session")
def _qt_application():
    application = QApplication.instance() or create_application([])
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
        application.setFont(QFont("Segoe UI", 10))
    return application


@pytest.fixture
def app(_qt_application):
    existing = set(_qt_application.topLevelWidgets())
    yield _qt_application
    # Closing a Qt window just hides it. Release test-owned windows while Qt's
    # event loop and stylesheet are available, including their child widgets.
    _qt_application.processEvents()
    for window in _qt_application.topLevelWidgets():
        if window not in existing and window.parent() is None and ownedByPython(window):
            window.deleteLater()
    _qt_application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
