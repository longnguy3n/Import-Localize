from types import SimpleNamespace
from threading import Event
from time import monotonic

from PySide6.QtTest import QTest

from import_localize.config.settings import AppSettings, SettingsRepository
from import_localize.services import google_service
from import_localize.ui import main_window
from test_unity_locale_ui import app


def test_cached_connection_uses_current_title(monkeypatch):
    cached = SimpleNamespace(spreadsheet_name="DG_Localization — Key-safe")
    monkeypatch.setattr(google_service, "get_oauth_credentials", lambda **kw: object())
    monkeypatch.setattr(google_service, "_get_cached_connection", lambda *args: cached)
    monkeypatch.setattr(google_service, "_cached_editor_permission_name", lambda *args: cached.spreadsheet_name)
    monkeypatch.setattr(google_service, "_read_sheet_title", lambda credentials, sheet_id: "DG_Localization")
    result = google_service.connect_to_spreadsheet("https://docs.google.com/spreadsheets/d/example/edit")
    assert result is cached
    assert result.spreadsheet_name == "DG_Localization"


def test_link_change_discards_pending_title(app, tmp_path, monkeypatch):
    repo = SettingsRepository(tmp_path / "config.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    started, done = Event(), Event()

    def lookup(url):
        if url.endswith("/first"):
            started.set()
            done.wait(5)
            return "Old title"
        return "New title"

    monkeypatch.setattr(main_window, "preview_sheet_title", lookup)
    window = main_window.MainWindow()
    window.show()
    try:
        assert window.sheet_url_edit.isVisible() and window.open_sheet_button.isVisible()
        window.sheet_url_edit.setText("https://docs.google.com/spreadsheets/d/first")
        QTest.qWait(500)
        assert started.wait(1)
        window.sheet_url_edit.setText("https://docs.google.com/spreadsheets/d/second")
        done.set()
        deadline = monotonic() + 3
        while "New title" not in window.sheet_title_label.text() and monotonic() < deadline:
            QTest.qWait(50)
            assert "Old title" not in window.sheet_title_label.text()
        assert window.sheet_title_label.text() == "Tên bảng tính: New title"
        window.sheet_url_edit.clear()
        assert window.sheet_title_label.isHidden() and not window.open_sheet_button.isEnabled()
    finally:
        done.set()
        window.close()


def test_drive_links_resolve_to_same_target_and_marks(app, tmp_path, monkeypatch):
    from import_localize.services.sheet_link import sheet_id_from_link
    repo = SettingsRepository(tmp_path / "config.json")
    repo.save(AppSettings(auto_check_updates=False))
    monkeypatch.setattr(main_window, "SettingsRepository", lambda: repo)
    window = main_window.MainWindow()
    try:
        window.sheet_url_edit.setText("https://drive.google.com/open?id=file-one")
        window.desc_annotations.set_mark("vi", "skill", "Wrong mapping")
        for link in ("https://docs.google.com/spreadsheets/d/file-one/edit#gid=19",
                     "https://drive.google.com/file/d/file-one/view?usp=sharing"):
            window.sheet_url_edit.setText(link)
            assert window.open_sheet_button.isEnabled()
            assert window.desc_annotations.has("vi", "skill", "Wrong mapping")
        window.sheet_url_edit.setText("https://drive.google.com/open?id=file-two")
        assert not window.desc_annotations.has("vi", "skill", "Wrong mapping")
        assert sheet_id_from_link("https://drive.google.com/drive/folders/file-one") is None
    finally:
        window.close()
