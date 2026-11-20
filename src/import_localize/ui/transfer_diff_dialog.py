"""Inspect the per-key snapshot used by the transfer preview."""
import re
from difflib import SequenceMatcher
from html import escape
from itertools import zip_longest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout,
)

from .change_colors import status_colors


LABELS = {"added": "Thêm", "removed": "Xóa", "changed": "Sửa", "unchanged": "Giữ"}


def marked_values(before, after):
    """Keep both strings complete and highlight edited words, punctuation and tags."""
    tokenize = re.compile(r"<[^<>\n]+>|\w+|\s+|[^\w\s]").findall
    old, new = tokenize(before), tokenize(after)
    left, right = [], []
    colors = status_colors()
    for op, i, j, k, l in SequenceMatcher(None, old, new).get_opcodes():
        for parts, tokens, status in ((left, old[i:j], "removed"), (right, new[k:l], "added")):
            value = escape("".join(tokens))
            if op != "equal" and value:
                value = f'<span style="background-color:{colors[status][0]}"><b>{value}</b></span>'
            parts.append(value)
    return "".join(left), "".join(right)


def render_change(change):
    parts = [f"<h3>{escape(change.key)}</h3>"]
    multiple = max(len(change.before), len(change.after)) > 1
    for index, (old, new) in enumerate(zip_longest(change.before, change.after), 1):
        if multiple:
            parts.append(f"<h4>Bản ghi {index}</h4>")
        old, new = old or {}, new or {}
        for field in dict.fromkeys((*old, *new)):
            before, after = old.get(field), new.get(field)
            if before == after and change.status == "changed":
                continue
            parts.append(f"<p><b>{escape(field)}</b></p>")
            left, right = marked_values(before or "", after or "")
            entries = []
            if before == after:
                entries.append(("Giữ", left))
            else:
                if field in old:
                    entries.append(("− Trước", left))
                if field in new:
                    entries.append(("+ Sau", right))
            for label, value in entries:
                parts.append(f'<p style="white-space:pre-wrap">{label}   {value or "<i>(trống)</i>"}</p>')
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
        layout.addWidget(pair)
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
            self.viewer.setHtml(render_change(self.details[item.data(Qt.ItemDataRole.UserRole)]))
