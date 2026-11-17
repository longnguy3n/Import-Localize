"""Translate the UU brand's semantic colors and state layers into native Qt styles."""
import json
import re
from functools import cache

from PySide6.QtGui import QColor

from import_localize.app.paths import THEMES_DIR


@cache
def _colors() -> dict[str, str]:
    return json.loads((THEMES_DIR / "uu" / "colors.json").read_text(encoding="utf-8"))


def color(role: str) -> str:
    return _colors()[role]


def _state_color(base_role: str, object_role: str, percentage: str) -> str:
    # QSS has no overlay pseudo-element. Compose the foreground over its base,
    # retaining alpha on ghost controls so the underlying panel still shows.
    base = QColor(color(base_role))
    foreground = QColor(color(object_role))
    amount = int(percentage) / 100
    base_weight = base.alphaF() * (1 - amount)
    alpha = amount + base_weight
    rgb = [round((front * amount + back * base_weight) / alpha)
           for front, back in zip(foreground.getRgb()[:3], base.getRgb()[:3])]
    return QColor(*rgb, round(alpha * 255)).name(QColor.NameFormat.HexArgb)


@cache
def stylesheet() -> str:
    template = (THEMES_DIR / "uu.qss").read_text(encoding="utf-8")
    assets = THEMES_DIR / "uu"
    for placeholder, filename in (
        ("__ICON_CHEVRON_DOWN__", "chevron-down.svg"),
        ("__ICON_UU_CHECK__", "check.svg"),
        ("__ICON_UU_ACTIVE_TAB__", "tab-indicator.svg"),
    ):
        template = template.replace(placeholder, (assets / filename).as_posix())

    def substitute(match):
        expression = match.group(1)
        if expression.startswith("state:"):
            _, base, foreground, strength = expression.split(":")
            return _state_color(base, foreground, strength)
        return color(expression)

    return re.sub(r"\{\{([\w:-]+)\}\}", substitute, template)
