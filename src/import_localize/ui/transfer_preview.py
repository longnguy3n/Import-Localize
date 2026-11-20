"""Compact, read-only preview shared by folder-based transfers."""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
)

from .change_colors import status_colors
from .transfer_diff_dialog import TransferDiffDialog


class ChangeCountDelegate(QStyledItemDelegate):
    statuses = ("added", "removed", "changed", "unchanged")

    def paint(self, painter, option, index):
        text = index.data()
        if text == "—":
            super().paint(painter, option, index)
            return
        colors = status_colors()
        background, foreground = colors[self.statuses[index.column() - 3]]
        width = min(option.rect.width() - 4, max(30, option.fontMetrics.horizontalAdvance(text) + 16))
        height = min(option.rect.height() - 4, option.fontMetrics.height() + 4)
        badge = QRect(0, 0, width, height)
        badge.moveCenter(option.rect.center())
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setFont(option.font)
        painter.setPen(QColor(foreground))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class TransferPreview(QTableWidget):
    def __init__(self):
        super().__init__(0, 7)
        self.setAccessibleName("Thay đổi theo key")
        self.setHorizontalHeaderLabels(["Nguồn · xem chi tiết", "Đích", "Trước → Sau", "Thêm", "Xóa", "Sửa", "Giữ"])
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.changes = []
        self.cellClicked.connect(self._show_diff)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.verticalHeader().hide()
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for column in (0, 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        counts = ChangeCountDelegate(self)
        for column in range(3, 7):
            self.setItemDelegateForColumn(column, counts)
        self.hide()

    def show_changes(self, changes):
        self.changes = changes
        self.setRowCount(len(changes))
        for row, (source, target, stats, detail) in enumerate(changes):
            before = "—" if stats.before_count is None else stats.before_count
            values = (source, target, f"{before} → {stats.after_count}",
                      stats.added, stats.removed, stats.updated, stats.unchanged)
            for column, value in enumerate(values):
                item = QTableWidgetItem("—" if value is None else str(value))
                item.setToolTip(f"{source} → {target}\n{detail}\nBấm hoặc nhấn Enter để xem chi tiết theo key.")
                if column >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.setItem(row, column, item)
        self.show()
        self.resizeRowsToContents()
        self._fit_preview()

    def _show_diff(self, row, column):
        if 0 <= row < len(self.changes):
            source, target, stats, _ = self.changes[row]
            status = ChangeCountDelegate.statuses[column - 3] if column >= 3 else ""
            dialog = TransferDiffDialog(source, target, stats, status, self)
            dialog.exec()
            dialog.deleteLater()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._show_diff(self.currentRow(), self.currentColumn())
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.rowCount():
            self._fit_preview()

    def _fit_preview(self):
        metrics_width = sum(self.columnWidth(column) for column in range(2, 7))
        available = self.viewport().width() - metrics_width
        # Preserve recognizable filenames and locale suffixes at small window sizes.
        minimum = self.fontMetrics().horizontalAdvance("locale_pt-BR.asset") + 18
        source_width = max(minimum, available // 2)
        self.setColumnWidth(0, source_width)
        self.setColumnWidth(1, max(minimum, available - source_width))
        height = self.horizontalHeader().height() + self.verticalHeader().length() + 2 * self.frameWidth()
        if self.horizontalHeader().length() > self.viewport().width():
            height += self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        self.setMinimumHeight(min(280, height))
