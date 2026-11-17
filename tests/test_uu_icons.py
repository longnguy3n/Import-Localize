"""Native product icons use the application's UU colors on buttons and dialogs."""
from collections import Counter

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QWidget

from import_localize.ui.assets import set_button_icon, set_label_icon
from import_localize.ui.uu_theme import color


def glyph_color(pixmap):
    image = pixmap.toImage()
    opaque = Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() == 255:
                opaque[pixel.name()] += 1
    return opaque.most_common(1)[0][0]


def test_uu_icons_follow_button_state_and_dialog_palette(app):
    window = QWidget()
    dialog = QDialog(window)
    try:
        primary = QPushButton(window)
        outline = QPushButton(dialog)
        label = QLabel(dialog)
        primary.setProperty("primaryAction", True)
        outline.setObjectName("downloadExportTabsButton")
        size = QSize(16, 16)
        set_button_icon(primary, "upload")
        set_button_icon(outline, "download")
        set_label_icon(label, "sheet", 16)
        assert glyph_color(primary.icon().pixmap(size)) == color("object-on-interactive").lower()
        assert glyph_color(outline.icon().pixmap(size, 2.0)) == color("object-interactive").lower()
        assert glyph_color(outline.icon().pixmap(size, QIcon.Mode.Disabled)) == color("object-disabled").lower()
        assert glyph_color(label.pixmap()) == color("object-secondary").lower()
    finally:
        dialog.close()
        window.close()
