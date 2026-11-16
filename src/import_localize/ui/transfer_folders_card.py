from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget,
)


class TransferFoldersCard(QFrame):
    changed = Signal(str, str)
    refresh_requested = Signal()
    roles = {"upload": "CSV upload", "export": "CSV export", "unity": "Unity locale"}
    patterns = {"upload": "upload_<mã>.csv", "export": "export_<mã>.csv", "unity": "locale_<mã>.asset"}

    def __init__(self, settings, files_button):
        super().__init__()
        self.setObjectName("transferFoldersCard")
        self.settings = settings
        self.rows = {}
        self.results = {}
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 4, 10, 4)
        box.setSpacing(2)
        header = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setText("Thư mục truyền dữ liệu")
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        header.addWidget(self.toggle)
        self.summary = QLabel()
        header.addWidget(self.summary, 1)
        header.addWidget(files_button)
        self.rescan = QPushButton("Quét lại")
        self.rescan.clicked.connect(self.refresh_requested)
        header.addWidget(self.rescan)
        box.addLayout(header)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setColumnStretch(1, 1)
        box.addWidget(body)
        for row, (role, title) in enumerate(self.roles.items()):
            field = QLineEdit()
            field.setReadOnly(True)
            field.setAccessibleName("Thư mục " + title)
            field.setPlaceholderText("Chọn thư mục chứa " + self.patterns[role])
            detail = QToolButton()
            detail.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            detail.setMenu(QMenu(detail))
            choose = QPushButton("Chọn…")
            choose.setAccessibleName("Chọn thư mục " + title)
            choose.clicked.connect(lambda _, r=role: self.choose(r))
            clear = QToolButton()
            clear.setText("×")
            clear.setAccessibleName("Bỏ thư mục " + title)
            clear.setToolTip("Bỏ thư mục đã chọn")
            clear.clicked.connect(lambda _, r=role: self.changed.emit(r, ""))
            for column, widget in enumerate((QLabel(title), field, detail, choose, clear)):
                grid.addWidget(widget, row, column)
            self.rows[role] = field, detail, clear
            self.set_result(role, (), ())
        self.toggle.toggled.connect(body.setVisible)
        self.toggle.toggled.connect(lambda opened: self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow))
        expanded = not all(getattr(settings, role + "_folder") for role in self.roles)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        body.setVisible(expanded)
        self.toggle.setChecked(expanded)

    def choose(self, role):
        initial = getattr(self.settings, role + "_folder")
        if not initial:
            initial = {"upload": self.settings.last_csv_dir, "export": self.settings.last_export_dir,
                       "unity": self.settings.unity_locale_dir}[role]
        chosen = QFileDialog.getExistingDirectory(self, "Chọn thư mục " + self.roles[role], initial)
        if chosen:
            self.changed.emit(role, chosen)

    def set_result(self, role, paths, issues):
        self.results[role] = (tuple(paths), tuple(issues))
        folder = getattr(self.settings, role + "_folder")
        field, detail, clear = self.rows[role]
        field.setText(folder)
        field.setToolTip(folder)
        detail.menu().clear()
        for label in (*issues, *(path.name for path in paths)):
            detail.menu().addAction(label)
        detail.setText(f"{len(issues)} lỗi" if issues else f"{len(paths)} tệp")
        detail.setEnabled(bool(paths or issues))
        detail.setAccessibleName("Kết quả quét " + self.roles[role])
        clear.setEnabled(bool(folder))
        folders = sum(bool(getattr(self.settings, r + "_folder")) for r in self.roles)
        errors = sum(len(result[1]) for result in self.results.values())
        self.summary.setText(f"{folders}/3 thư mục" + (f" · {errors} lỗi" if errors else ""))
        self.rescan.setEnabled(bool(folders))
