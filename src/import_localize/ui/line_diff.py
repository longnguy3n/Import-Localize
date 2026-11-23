"""Render numbered, unified diffs of plain localization text in Qt."""
from difflib import SequenceMatcher
from html import escape
import re

from .change_colors import status_colors
from .uu_theme import color


def _marked_values(before, after):
    """Keep both strings complete and highlight edited words, punctuation and tags."""
    tokenize = re.compile(r"<[^<>\n]+>|\w+|\s+|[^\w\s]").findall
    old, new = tokenize(before), tokenize(after)
    left, right = [], []
    for op, i, j, k, l in SequenceMatcher(None, old, new).get_opcodes():
        for parts, tokens, status in ((left, old[i:j], "removed"), (right, new[k:l], "added")):
            value = escape("".join(tokens))
            if op != "equal" and value:
                role = "positive" if status == "added" else "negative"
                style = f'background-color:{color("background-" + role)};color:{color("object-on-" + role)}'
                value = f'<span style="{style}"><b>{value}</b></span>'
            parts.append(value)
    return "".join(left), "".join(right)


def _diff_row(old_number, new_number, sign, html):
    background = {"−": "removed", "+": "added"}.get(sign)
    style = f' bgcolor="{status_colors()[background][0]}"' if background else ""
    cells = "".join(f'<td align="right"{style}>{number or ""}</td>' for number in (old_number, new_number))
    html = html.replace("\r", "␍")
    return (f'<tr>{cells}<td{style}><b>{sign}</b></td><td{style}>'
            f'<span style="white-space:pre-wrap">{html or "&nbsp;"}</span></td></tr>')


def field_diff(before, after, full=False, *, before_only=False):
    if before is None and after is None:
        return "<p><i>Cả hai bản đều thiếu ô này.</i></p>"
    # Keep a final empty line so an added/removed trailing newline is visible.
    old = before.split("\n") if before is not None else []
    new = after.split("\n") if after is not None else []
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    groups = ([matcher.get_opcodes()] if full or old == new else matcher.get_grouped_opcodes(2))
    rows = ['<table width="100%" cellspacing="0" cellpadding="3">'
            '<tr><th width="42">Trước</th><th width="36">Sau</th><th width="14"></th><th align="left">Nội dung</th></tr>']
    last_old = 0

    def fold(count):
        if count:
            rows.append(f'<tr><td colspan="4"><i>⋯ {count} dòng không đổi</i></td></tr>')

    for group in groups:
        fold(group[0][1] - last_old)
        for op, i, j, k, l in group:
            if op == "equal":
                rows.extend(_diff_row(n + 1, k + n - i + 1, "", escape(old[n])) for n in range(i, j))
            else:
                for offset in range(max(j - i, l - k)):
                    a, b = i + offset, k + offset
                    if a < j and b < l:
                        left, right = _marked_values(old[a], new[b])
                    else:
                        left = escape(old[a]) if a < j else ""
                        right = escape(new[b]) if b < l else ""
                    if a < j:
                        rows.append(_diff_row(a + 1, None, "−", left))
                    if b < l and not before_only:
                        rows.append(_diff_row(None, b + 1, "+", right))
        last_old = group[-1][2]
    fold(len(old) - last_old)
    return "".join(rows) + "</table>"
