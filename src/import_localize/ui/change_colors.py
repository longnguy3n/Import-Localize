"""Semantic colors shared by comparison and transfer results (background, text)."""
from functools import cache

from .uu_theme import color


@cache
def status_colors():
    return {
        "added": (color("background-positive-muted"), color("object-primary")),
        "removed": (color("background-negative-muted"), color("object-primary")),
        "changed": (color("background-warning-muted"), color("object-on-warning")),
        "unchanged": (color("background-subtle"), color("object-secondary")),
    }
