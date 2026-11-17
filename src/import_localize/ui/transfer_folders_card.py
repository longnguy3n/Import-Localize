from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)


class TransferFoldersCard(QFrame):
    changed = Signal(str, str)
    refresh_requested = Signal()
    roles = {"upload": "CSV upload", "export": "CSV export", "unity": "Unity locale"}
    patterns = {"upload": "upload_<mã>.csv", "export": "export_<mã>.csv", "unity": "locale_<mã>.asset"}

    def __init__(self, settings):
        super().__init__()
        self.setObjectName("transferFoldersCard")
        self.settings = settings
        self.rows = {}
        self.results = dict.fromkeys(self.roles, ((), ()))
        self.folder_menus = {}
        self.issue_labels = {}
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 6, 10, 6)
        box.setSpacing(4)
        header = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setText("Thư mục truyền dữ liệu")
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        header.addWidget(self.toggle)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        header.addWidget(self.summary, 1)
        self.rescan = QPushButton("Quét lại")
        self.rescan.setToolTip("Quét lại các thư mục đã chọn")
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
            field.setPlaceholderText("Chưa chọn · " + self.patterns[role])
            detail = QToolButton()
            detail.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            detail.setMenu(QMenu(detail))
            choose = QToolButton()
            choose.clicked.connect(lambda _, r=role: self.choose(r))
            menu = QMenu(choose)
            clear = menu.addAction("Bỏ chọn thư mục " + title)
            clear.triggered.connect(lambda _, r=role: self.changed.emit(r, ""))
            self.folder_menus[role] = menu
            for column, widget in enumerate((QLabel(title), field, detail, choose)):
                grid.addWidget(widget, row * 2, column)
            issue_label = QLabel()
            issue_label.setObjectName("folderIssue")
            issue_label.setTextFormat(Qt.TextFormat.PlainText)
            issue_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            issue_label.setWordWrap(True)
            issue_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            grid.addWidget(issue_label, row * 2 + 1, 1, 1, 3)
            self.issue_labels[role] = issue_label
            self.rows[role] = field, detail, choose
            self.set_result(role, (), ())
        self.toggle.toggled.connect(body.setVisible)
        self.toggle.toggled.connect(lambda opened: self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow))
        self.toggle.toggled.connect(self._update_summary)
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
        previous_issues = self.results[role][1]
        paths, issues = tuple(paths), tuple(issues)
        self.results[role] = paths, issues
        folder = getattr(self.settings, role + "_folder")
        field, detail, choose = self.rows[role]
        if field.text() != folder:
            field.setText(folder)
        field.setToolTip(folder or "Chọn thư mục chứa " + self.patterns[role])
        title = self.roles[role]
        choose.setText("Đổi…" if folder else "Chọn…")
        choose.setAccessibleName(("Đổi thư mục " if folder else "Chọn thư mục ") + title)
        choose.setMenu(self.folder_menus[role] if folder else None)
        choose.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup if folder
                            else QToolButton.ToolButtonPopupMode.DelayedPopup)
        detail.menu().clear()
        for label in (*issues, *(path.name for path in paths)):
            detail.menu().addAction(label.replace("&", "&&"))
        detail.setText(f"{len(issues)} lỗi" if issues else f"{len(paths)} tệp")
        detail.setVisible(bool(folder))
        if folder and not paths and not issues:
            detail.menu().addAction("Chưa có " + self.patterns[role]).setEnabled(False)
        detail.setAccessibleName(f"{title} · {detail.text()} · Xem kết quả quét")
        detail.setToolTip("Xem kết quả quét " + title)
        issue_label = self.issue_labels[role]
        issue_label.setText(issues[0] if issues else "")
        issue_label.setVisible(bool(issues))
        if issues and issues != previous_issues:
            self.toggle.setChecked(True)
        self._update_summary()

    def _update_summary(self):
        folders = sum(bool(getattr(self.settings, r + "_folder")) for r in self.roles)
        errors = sum(len(result[1]) for result in self.results.values())
        if errors:
            summary = f"{errors} lỗi thư mục"
        elif self.toggle.isChecked() or not folders:
            summary = f"Đã chọn {folders}/3" if folders else "Chưa chọn thư mục"
        else:
            counts = []
            for role, name in (("upload", "Upload"), ("export", "Export"), ("unity", "Unity")):
                count = len(self.results[role][0]) if getattr(self.settings, role + "_folder") else "—"
                counts.append(f"{name} {count}")
            summary = " · ".join(counts)
        self.summary.setText(summary)
        self.rescan.setEnabled(bool(folders))
