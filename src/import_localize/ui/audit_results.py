"""Shared results table and empty state for offline reviews."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget


class AuditResults(QStackedWidget):
    def __init__(self, table, search, reset_filters, parent):
        super().__init__(parent)
        self.table = table
        self.addWidget(table)
        self.empty = QWidget()
        layout = QVBoxLayout(self.empty)
        layout.addStretch()
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        self.reset_button = QPushButton("Xóa bộ lọc")
        self.reset_button.setAutoDefault(False)
        self.reset_button.clicked.connect(reset_filters)
        layout.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.addWidget(self.empty)

        find_key = QKeySequence(QKeySequence.StandardKey.Find)
        search.setAccessibleName(search.placeholderText().rstrip("…"))
        search.setToolTip(f"{search.accessibleName()} ({find_key.toString(QKeySequence.SequenceFormat.NativeText)})")
        shortcut = QShortcut(find_key, parent)
        shortcut.activated.connect(search.setFocus)
        shortcut.activated.connect(search.selectAll)

    def show_empty(self, message, action=""):
        self.message.setText(message)
        self.reset_button.setText(action)
        self.reset_button.setVisible(bool(action))
        self.setCurrentWidget(self.empty)

    def show_table(self):
        self.setCurrentWidget(self.table)
