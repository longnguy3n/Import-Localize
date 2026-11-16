"""Inputs for the two directions of the CSV / Google Sheets workflow."""
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)


class CsvSheetPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("csvSheetPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 12, 0)
        self.direction = QComboBox()
        self.direction.setAccessibleName("Chiều chuyển giữa CSV và Google Sheets")
        self.direction.addItem("Nhập · CSV → Sheet", "import")
        self.direction.addItem("Xuất · Sheet → CSV", "download")
        header.addWidget(QLabel("Chiều chuyển"))
        header.addWidget(self.direction)
        header.addStretch()
        layout.addLayout(header)

        layout.addStretch()
