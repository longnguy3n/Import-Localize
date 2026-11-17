"""Semantic colors shared by comparison and transfer results (background, text)."""
from functools import cache

from PySide6.QtGui import QPalette

from .uu_theme import color, uses_uu

STATUS_COLORS = {
    "added": ("#dcfce7", "#166534"),
    "removed": ("#ffe4e6", "#9f1239"),
    "changed": ("#fef3c7", "#92400e"),
    "unchanged": ("#e2e8f0", "#475569"),
}
STATUS_COLORS_DARK = {
    "added": ("#173e2b", "#86efac"),
    "removed": ("#482330", "#fda4af"),
    "changed": ("#46361d", "#fcd34d"),
    "unchanged": ("#26352f", "#b9c8c1"),
}


@cache
def _uu_status_colors():
    return {
        "added": (color("background-positive-muted"), color("object-primary")),
        "removed": (color("background-negative-muted"), color("object-primary")),
        "changed": (color("background-warning-muted"), color("object-on-warning")),
        "unchanged": (color("background-subtle"), color("object-secondary")),
    }


def status_colors(widget):
    if uses_uu(widget):
        return _uu_status_colors()
    dark = widget is not None and widget.palette().color(QPalette.ColorRole.Base).lightness() < 128
    return STATUS_COLORS_DARK if dark else STATUS_COLORS
