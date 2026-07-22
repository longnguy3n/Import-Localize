from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class LogRow(QWidget):
    """Compact log row styled by QSS through its level property."""

    def __init__(self, level: str, message: str, parent=None):
        super().__init__(parent)
        normalized = (level or "INFO").upper()
        self.setObjectName("logRow")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(5)

        timestamp = QLabel(datetime.now().strftime("%H:%M:%S"))
        timestamp.setObjectName("logTimestamp")
        timestamp.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        timestamp.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        level_label = QLabel(f"[{normalized}]:")
        level_label.setObjectName("logLevel")
        level_label.setProperty("level", normalized)
        level_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        level_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        message_label = QLabel(message)
        message_label.setObjectName("logMessage")
        message_label.setWordWrap(True)
        message_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout.addWidget(timestamp, 0)
        layout.addWidget(level_label, 0)
        layout.addWidget(message_label, 1)


class BottomAlignedLogView(QScrollArea):
    """Log view that keeps short logs anchored to the bottom edge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logConsole")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.viewport().setObjectName("logViewport")

        self.content = QWidget()
        self.content.setObjectName("logContent")
        self.content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding,
        )

        self.rows_layout = QVBoxLayout(self.content)
        self.rows_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetMinimumSize
        )
        self.rows_layout.setContentsMargins(8, 3, 4, 3)
        self.rows_layout.setSpacing(0)
        self.rows_layout.addStretch(1)
        self.setWidget(self.content)

        scrollbar = self.verticalScrollBar()
        scrollbar.setSingleStep(18)
        scrollbar.setPageStep(80)

    def append_entry(self, level: str, message: str) -> None:
        row = LogRow(level, message, self.content)
        self.rows_layout.addWidget(row)
        self.content.updateGeometry()
        self.updateGeometry()
        QTimer.singleShot(
            0,
            lambda: self.verticalScrollBar().setValue(
                self.verticalScrollBar().maximum()
            ),
        )

    def clear(self) -> None:
        # Item 0 is the permanent top stretch.
        for index in range(self.rows_layout.count() - 1, 0, -1):
            item = self.rows_layout.takeAt(index)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.content.updateGeometry()
        self.updateGeometry()
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(0))
