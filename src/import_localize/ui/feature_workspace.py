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
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidgetResizable(True)
        dialog.setParent(area, Qt.WindowType.Widget)
        dialog.setModal(False)
        dialog.workspace = self
        if hasattr(dialog, "close_button"):
            dialog.close_button.setText("Quay lại")
            if self.pages:
                dialog.close_button.setToolTip(self.pages[-1].windowTitle())
        area.setWidget(dialog)
        self.addWidget(area)
        self.pages.append(dialog)
        self.setCurrentWidget(area)
        dialog.action_panel = feature_action_panel(dialog)
        self.owner.action_pages.addWidget(dialog.action_panel)
        self.owner.action_pages.setCurrentWidget(dialog.action_panel)
        dialog.windowTitleChanged.connect(self.owner._sync_action_title)
        if hasattr(dialog, "desc_marks_changed"):
            dialog.desc_marks_changed.connect(self.owner._refresh_desc_count)
        dialog.finished.connect(lambda _: self._finished(dialog, area, after_close))
        if dialog.worker is not None:
            dialog.worker.finished.connect(self.owner._sync_shared_controls, Qt.ConnectionType.QueuedConnection)
        dialog.installEventFilter(self.owner)
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

    def leave_features(self, keep=0):
        while len(self.pages) > keep:
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


def start_feature_worker(dialog):
    workspace = getattr(dialog, "workspace", None)
    if workspace is not None:
        workspace.owner._sync_shared_controls()
        dialog.worker.finished.connect(workspace.owner._sync_shared_controls, Qt.ConnectionType.QueuedConnection)
    dialog.worker.start()


def open_child_feature(parent, dialog, after_close=None):
    workspace = getattr(parent, "workspace", None)
    if workspace is not None:
        workspace.owner.open_audit_popup(dialog, after_close)
    else:
        try:
            dialog.exec()
            if after_close:
                after_close()
        finally:
            dialog.deleteLater()
