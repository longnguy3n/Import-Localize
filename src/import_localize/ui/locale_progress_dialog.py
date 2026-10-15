from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QHBoxLayout, QProgressBar, QPushButton, QPlainTextEdit


class LocaleProgressDialog(QDialog):
    """Real worker progress; keep the result visible even for instant operations."""
    def __init__(self, operation, file_count, parent=None):
        super().__init__(parent)
        self.busy = True
        self.backup_path = None
        self.operation, self.file_count = operation, file_count
        self.setWindowTitle(operation)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        self.heading = QLabel(f"Đang thực hiện {operation} · {file_count} file")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.status = QLabel("Đang bắt đầu…")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        hint = QLabel("Tiến trình tính theo các bước thực tế: kiểm tra, sao lưu, chuẩn bị và ghi file.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(100)
        self.details.setMaximumHeight(180)
        self.details.hide()
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.backup_button = QPushButton("Mở bản sao lưu")
        self.backup_button.hide()
        actions.addWidget(self.backup_button)
        actions.addStretch()
        self.close_button = QPushButton("Đóng")
        self.close_button.setEnabled(False)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.close_button.clicked.connect(self.accept)
        self.backup_button.clicked.connect(self.open_backup)

    def update_progress(self, completed, total, message):
        if not self.busy:
            return
        self.status.setText(message)
        self.progress.setRange(0, total)
        self.progress.setValue(completed)
        self.progress.setFormat(f"{completed}/{total} bước · %p%")

    def finish(self, error="", backup_path=None):
        self.busy = False
        self.close_button.setEnabled(True)
        self.details.show()
        if error:
            self.heading.setText(f"{self.operation} không hoàn tất")
            self.heading.setStyleSheet("color: #b4232c; font-weight: bold;")
            self.progress.setStyleSheet("QProgressBar::chunk { background-color: #d94848; }")
            self.status.setText("Có lỗi xảy ra. Xem chi tiết bên dưới trước khi thử lại.")
            if not self.progress.maximum():
                self.progress.setRange(0, 1)
                self.progress.setValue(0)
            self.details.setPlainText(error)
        else:
            self.heading.setText(f"{self.operation} thành công · đã ghi {self.file_count} file")
            self.heading.setStyleSheet("color: #187548; font-weight: bold;")
            self.status.setText("Đã hoàn tất.")
            self.progress.setRange(0, max(1, self.progress.maximum()))
            self.progress.setValue(self.progress.maximum())
            self.progress.setFormat("Hoàn tất · 100%")
            self.backup_path = backup_path
            self.backup_button.setVisible(backup_path is not None)
            follow_up = ("Quay lại Unity và Refresh (Ctrl+R) để nạp dữ liệu."
                         if self.operation == "Replace Import" else "CSV đã sẵn sàng trong các đường dẫn đích đã chọn.")
            self.status.setText("Đã hoàn tất. " + follow_up)
            self.details.setPlainText(f"Bản sao lưu: {backup_path}")
        self.close_button.setFocus()

    def open_backup(self):
        if self.backup_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backup_path)))

    def accept(self):
        if not self.busy:
            super().accept()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
