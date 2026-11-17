"""Native product icons follow a window's theme and its button state."""
from collections import Counter

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from import_localize.ui.assets import icon, refresh_theme_icons, set_button_icon, set_label_icon
from import_localize.ui.uu_theme import color, stylesheet
from test_unity_locale_ui import app


def glyph_color(pixmap):
    image = pixmap.toImage()
    opaque = Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() == 255:
                opaque[pixel.name()] += 1
    return opaque.most_common(1)[0][0]


def test_uu_icons_follow_foreground_disabled_and_theme_switch(app):
    window = QWidget()
    other_window = QWidget()
    try:
        primary = QPushButton(window)
        outline = QPushButton(window)
        label = QLabel(window)
        other_button = QPushButton(other_window)
        primary.setProperty("primaryAction", True)
        outline.setObjectName("downloadExportTabsButton")
        size = QSize(16, 16)
        set_button_icon(primary, "upload")
        set_button_icon(outline, "download")
        set_label_icon(label, "sheet", 16)
        set_button_icon(other_button, "download")
        original = glyph_color(icon("download").pixmap(size))
        window.setProperty("uiTheme", "uu")
        window.setStyleSheet(stylesheet())
        refresh_theme_icons(window)

        assert glyph_color(primary.icon().pixmap(size)) == color("object-on-interactive").lower()
        assert glyph_color(outline.icon().pixmap(size, 2.0)) == color("object-interactive").lower()
        assert glyph_color(outline.icon().pixmap(size, QIcon.Mode.Disabled)) == color("object-disabled").lower()
        assert glyph_color(label.pixmap()) == color("object-secondary").lower()
        assert glyph_color(other_button.icon().pixmap(size)) == original

        window.setProperty("uiTheme", "light")
        window.setStyleSheet("")
        refresh_theme_icons(window)
        assert glyph_color(outline.icon().pixmap(size)) == original
    finally:
        window.close()
        other_window.close()
