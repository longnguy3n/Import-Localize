"""Inspect the per-key snapshot used by the transfer preview."""
import re
from difflib import SequenceMatcher
from html import escape
from itertools import zip_longest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout,
)

from .change_colors import status_colors
from .uu_theme import color


LABELS = {"added": "Thêm", "removed": "Xóa", "changed": "Sửa", "unchanged": "Giữ"}


def marked_values(before, after, *, strong=False):
    """Keep both strings complete and highlight edited words, punctuation and tags."""
    tokenize = re.compile(r"<[^<>\n]+>|\w+|\s+|[^\w\s]").findall
    old, new = tokenize(before), tokenize(after)
    left, right = [], []
    colors = status_colors()
    for op, i, j, k, l in SequenceMatcher(None, old, new).get_opcodes():
        for parts, tokens, status in ((left, old[i:j], "removed"), (right, new[k:l], "added")):
            value = escape("".join(tokens))
            if op != "equal" and value:
                role = "positive" if status == "added" else "negative"
                style = (f'background-color:{color("background-" + role)};color:{color("object-on-" + role)}'
                         if strong else f'background-color:{colors[status][0]}')
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


def _field_diff(before, after, full):
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
                        left, right = marked_values(old[a], new[b], strong=True)
                    else:
                        left = escape(old[a]) if a < j else ""
                        right = escape(new[b]) if b < l else ""
                    if a < j:
                        rows.append(_diff_row(a + 1, None, "−", left))
                    if b < l:
                        rows.append(_diff_row(None, b + 1, "+", right))
        last_old = group[-1][2]
    fold(len(old) - last_old)
    return "".join(rows) + "</table>"


def render_change(change, full=False):
    parts = [f"<h3>{escape(change.key)}</h3>"]
    multiple = max(len(change.before), len(change.after)) > 1
    for index, (old, new) in enumerate(zip_longest(change.before, change.after), 1):
        if multiple:
            parts.append(f"<h4>Bản ghi {index}</h4>")
        old, new = old or {}, new or {}
        for field in dict.fromkeys((*old, *new)):
            before, after = old.get(field), new.get(field)
            if before == after and change.status == "changed" and not full:
                continue
            parts.append(f"<p><b>{escape(field)}</b></p>")
            parts.append(_field_diff(before, after, full))
    return "".join(parts)


class TransferDiffDialog(QDialog):
    def __init__(self, source, target, stats, status, parent):
        super().__init__(parent)
        self.setWindowTitle("Chi tiết thay đổi")
        self.resize(900, 540)
        self.setSizeGripEnabled(True)
        self.details = stats.details
        self.available = stats.before_count is not None
        layout = QVBoxLayout(self)
        pair = QLabel(f"{source} → {target}")
        pair.setTextFormat(Qt.TextFormat.PlainText)
        heading = QHBoxLayout()
        heading.addWidget(pair, 1)
        heading.addWidget(QLabel(f'<b style="color:{color("object-negative")}">− Đích hiện tại</b>'
                                 f' &nbsp; <b style="color:{color("object-positive")}">+ Sau khi ghi</b>'))
        layout.addLayout(heading)
        filters = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem("Các thay đổi", "")
        for code, count in zip(LABELS, (stats.added, stats.removed, stats.updated, stats.unchanged)):
            self.filter.addItem(f"{LABELS[code]} ({count if count is not None else '—'})", code)
        self.filter.setCurrentIndex(max(0, self.filter.findData(status)))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm key…")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.filter)
        filters.addWidget(self.search)
        self.full = QCheckBox("Hiện toàn văn")
        filters.addWidget(self.full)
        layout.addLayout(filters)
        panes = QSplitter()
        self.keys = QListWidget()
        self.viewer = QTextBrowser()
        panes.addWidget(self.keys)
        panes.addWidget(self.viewer)
        panes.setSizes([300, 600])
        layout.addWidget(panes, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.keys.currentItemChanged.connect(self._show_key)
        self.full.toggled.connect(lambda: self._show_key(self.keys.currentItem()))
        self.filter.currentIndexChanged.connect(self._refresh)
        self.search.textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        status = self.filter.currentData()
        query = self.search.text().strip().casefold()
        self.keys.clear()
        for i, change in enumerate(self.details):
            matches = change.status == status if status else change.status != "unchanged"
            if matches and query in change.key.casefold():
                item = QListWidgetItem(f"{LABELS[change.status]}   {change.key}")
                item.setData(Qt.ItemDataRole.UserRole, i)
                self.keys.addItem(item)
        if self.keys.count():
            self.keys.setCurrentRow(0)
        else:
            self.viewer.setPlainText("Không có key phù hợp với bộ lọc." if self.available
                                     else "Chưa đọc được nội dung đích để so sánh.")

    def _show_key(self, item):
        if item is not None:
            self.viewer.setHtml(render_change(self.details[item.data(Qt.ItemDataRole.UserRole)], self.full.isChecked()))
