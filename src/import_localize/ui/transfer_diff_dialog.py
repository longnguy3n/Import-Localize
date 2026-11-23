"""Inspect the per-key snapshot used by the transfer preview."""
from html import escape
from itertools import zip_longest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout,
)

from .line_diff import field_diff
from .uu_theme import color


LABELS = {"added": "Thêm", "removed": "Xóa", "changed": "Sửa", "unchanged": "Giữ"}


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
            parts.append(field_diff(before, after, full))
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
