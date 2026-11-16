"""Navigation for feature views hosted in the main workspace."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout, QWidget


def feature_action_panel(dialog):
    """Host the feature's existing controls so their signals and worker state stay intact."""
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    for widget in dialog.action_messages:
        layout.addWidget(widget)
    buttons = QHBoxLayout()
    buttons.addStretch()
    layout.addLayout(buttons)
    for widget in dialog.action_buttons:
        buttons.addWidget(widget)
    buttons.addStretch()
    return panel


class FeatureWorkspace(QStackedWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.pages = []

    def add_feature(self, dialog, after_close=None):
        area = QScrollArea()
        area.setWidgetResizable(True)
        dialog.setParent(area, Qt.WindowType.Widget)
        dialog.setModal(False)
        dialog.workspace = self
        area.setWidget(dialog)
        self.addWidget(area)
        self.pages.append(dialog)
        self.setCurrentWidget(area)
        dialog.action_panel = feature_action_panel(dialog)
        self.owner.action_pages.addWidget(dialog.action_panel)
        self.owner.action_pages.setCurrentWidget(dialog.action_panel)
        dialog.windowTitleChanged.connect(self.owner._sync_action_title)
        dialog.finished.connect(lambda _: self._finished(dialog, area, after_close))
        dialog.show()
        self.owner._sync_feature_controls()

    def _finished(self, dialog, area, callback):
        if not self.pages or self.pages[-1] is not dialog:
            return
        self.pages.pop()
        actions = self.owner.action_pages
        actions.removeWidget(dialog.action_panel)
        dialog.action_panel.setParent(dialog)
        dialog.action_panel.hide()
        actions.setCurrentIndex(actions.count() - 1)
        self.removeWidget(area)
        self.setCurrentIndex(self.count() - 1)
        if callback:
            callback()
        area.deleteLater()
        self.owner._sync_feature_controls()
        self.owner.save_settings()

    def leave_features(self):
        while self.pages:
            page = self.pages[-1]
            if getattr(page, "worker", None) is not None:
                self.owner.statusBar().showMessage("Đợi tác vụ hoàn tất hoặc bấm Dừng trước khi chuyển chức năng.", 4500)
                return False
            if getattr(page, "focus_mode", False):
                page.toggle_focus_mode()
            page.reject()
            if self.pages and self.pages[-1] is page:
                return False
        return True


def open_child_feature(parent, dialog, after_close=None):
    workspace = getattr(parent, "workspace", None)
    if workspace is not None:
        workspace.add_feature(dialog, after_close)
    else:
        try:
            dialog.exec()
            if after_close:
                after_close()
        finally:
            dialog.deleteLater()
