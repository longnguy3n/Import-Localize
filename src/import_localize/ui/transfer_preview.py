"""Compact, read-only preview shared by folder-based transfers."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem


class TransferPreview(QTableWidget):
    def __init__(self):
        super().__init__(0, 6)
        self.setAccessibleName("Thay đổi theo key")
        self.setHorizontalHeaderLabels(["Nguồn → Đích", "Trước → Sau", "Thêm", "Xóa", "Sửa", "Giữ"])
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.hide()

    def show_changes(self, changes):
        self.setRowCount(len(changes))
        for row, (source, target, stats, detail) in enumerate(changes):
            before = "—" if stats.before_count is None else stats.before_count
            values = (f"{source} → {target}", f"{before} → {stats.after_count}",
                      stats.added, stats.removed, stats.updated, stats.unchanged)
            for column, value in enumerate(values):
                item = QTableWidgetItem("—" if value is None else str(value))
                item.setToolTip(f"{source} → {target}\n{detail}")
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.setItem(row, column, item)
        self.show()
        self.resizeRowsToContents()
        self.setMinimumHeight(min(280, self.horizontalHeader().height() + self.verticalHeader().length() + 6))
