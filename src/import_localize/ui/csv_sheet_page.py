"""Inputs for the two directions of the CSV / Google Sheets workflow."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)


class CsvSheetPage(QWidget):
    def __init__(self, files_card, export_dir):
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

        pages = QStackedWidget()
        pages.addWidget(files_card)
        export = QWidget()
        form = QFormLayout(export)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        source = QLabel("Tất cả tab có tên bắt đầu bằng export_* trong bảng tính đã chọn.")
        source.setWordWrap(True)
        form.addRow("Nguồn", source)
        output = QHBoxLayout()
        self.folder = QLineEdit(export_dir)
        self.folder.setReadOnly(True)
        self.folder.setAccessibleName("Thư mục nhận CSV")
        self.folder.setPlaceholderText("Chọn thư mục lưu các file CSV")
        self.choose_folder = QPushButton("Chọn thư mục…")
        output.addWidget(self.folder, 1)
        output.addWidget(self.choose_folder)
        form.addRow("Lưu CSV vào", output)
        pages.addWidget(export)
        layout.addWidget(pages, 1)
        self.direction.currentIndexChanged.connect(pages.setCurrentIndex)
