from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import time
import webbrowser
from concurrent.futures import CancelledError, FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse
from wsgiref.simple_server import WSGIRequestHandler, make_server
from wsgiref.util import request_uri

import gspread
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    ReadTimeout,
    Timeout as RequestsTimeout,
)

from import_localize.app.constants import (
    CSV_EXPORT_REQUEST_TIMEOUT_SECONDS,
    EXPORT_SHEET_PREFIX,
    GOOGLE_REQUEST_TIMEOUT_SECONDS,
    GOOGLE_CONNECT_TIMEOUT_SECONDS,
    GOOGLE_CANCELLABLE_READ_TIMEOUT_SECONDS,
    GOOGLE_CANCEL_POLL_SECONDS,
    GOOGLE_REQUEST_RETRY_ATTEMPTS,
    GOOGLE_REQUEST_RETRY_BASE_DELAY_SECONDS,
    GOOGLE_STRUCTURE_BATCH_SIZE,
    GOOGLE_CLEAR_BATCH_SIZE,
    GOOGLE_CONNECTION_CACHE_TTL_SECONDS,
    GOOGLE_WORKSHEET_CACHE_TTL_SECONDS,
    MAX_PARALLEL_EXPORT_DOWNLOADS,
    UPLOAD_MAX_CELLS_PER_RANGE,
    UPLOAD_MAX_REQUEST_BYTES,
    UPLOAD_MAX_ROWS_PER_RANGE,
)
from import_localize.app.paths import (
    OAUTH_CLIENT_FILE,
    OAUTH_TOKEN_FILE,
    PROJECT_DIR,
    USER_CONFIG_DIR,
    application_dir,
)
from import_localize.models.import_job import CsvBundle, ImportJob
from import_localize.services.fill_service import (
    FillSelectionError,
    build_fill_copy_requests,
    column_letters_to_number,
    column_number_to_letters,
    group_consecutive_columns,
    normalize_column_selection,
    parse_column_selection,
)
from import_localize.services.session_permission_cache import (
    EditorPermissionSessionCache,
)

ProgressCallback = Callable[[int, str], None] | None
LogCallback = Callable[[str], None] | None
CancelCallback = Callable[[], bool] | None

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DRIVE_METADATA_SCOPE = "https://www.googleapis.com/auth/drive.metadata.readonly"
OAUTH_SCOPES = [SHEETS_SCOPE, DRIVE_METADATA_SCOPE]
OAUTH_SCOPE_VERSION = 1


# Quyền Editor chỉ được kiểm tra một lần cho mỗi tài khoản + spreadsheet
# trong vòng đời tiến trình ứng dụng. Cache này chỉ nằm trong RAM.
_EDITOR_PERMISSION_CACHE = EditorPermissionSessionCache(
    scope_version=OAUTH_SCOPE_VERSION
)

# Cache phiên Google và kết nối Spreadsheet trong RAM. Ứng dụng chỉ chạy một
# tác vụ Google tại một thời điểm nên các đối tượng này được tái sử dụng an toàn
# giữa các QThread tuần tự trong cùng session.
_SESSION_CACHE_LOCK = RLock()
_CACHED_CREDENTIALS: Credentials | None = None
_CONNECTION_CACHE: dict[str, SheetConnection] = {}


def clear_session_google_cache() -> None:
    """Xóa mọi cache Google chỉ tồn tại trong RAM của session hiện tại."""
    global _CACHED_CREDENTIALS
    with _SESSION_CACHE_LOCK:
        _CACHED_CREDENTIALS = None
        _CONNECTION_CACHE.clear()
    _EDITOR_PERMISSION_CACHE.clear()


def clear_session_editor_permission_cache() -> None:
    """Tên tương thích cũ; hiện xóa cả quyền, credential và kết nối session."""
    clear_session_google_cache()


def _cached_editor_permission_name(
    credentials: Credentials,
    spreadsheet_id: str,
) -> str | None:
    return _EDITOR_PERMISSION_CACHE.get(credentials, spreadsheet_id)


def _remember_editor_permission(
    credentials: Credentials,
    spreadsheet_id: str,
    spreadsheet_name: str,
) -> None:
    _EDITOR_PERMISSION_CACHE.remember(
        credentials,
        spreadsheet_id,
        spreadsheet_name,
    )


def _forget_editor_permission(
    credentials: Credentials,
    spreadsheet_id: str,
) -> None:
    _EDITOR_PERMISSION_CACHE.forget(credentials, spreadsheet_id)


class GoogleServiceError(RuntimeError):
    pass


class OAuthConfigurationError(GoogleServiceError):
    pass


class SheetPermissionError(GoogleServiceError):
    pass


@dataclass(slots=True)
class SheetConnection:
    credentials: Credentials
    client: gspread.Client
    spreadsheet: gspread.Spreadsheet
    spreadsheet_id: str
    spreadsheet_name: str
    authorized_session: AuthorizedSession
    connected_at: float = field(default_factory=time.monotonic)
    worksheet_cache: dict[str, gspread.Worksheet] = field(default_factory=dict)
    worksheet_cache_loaded_at: float = 0.0


def _same_google_identity(left: Credentials, right: Credentials) -> bool:
    return (
        str(getattr(left, "client_id", "") or ""),
        str(getattr(left, "refresh_token", "") or ""),
    ) == (
        str(getattr(right, "client_id", "") or ""),
        str(getattr(right, "refresh_token", "") or ""),
    )


def _get_memory_credentials() -> Credentials | None:
    with _SESSION_CACHE_LOCK:
        return _CACHED_CREDENTIALS


def _remember_memory_credentials(credentials: Credentials) -> None:
    global _CACHED_CREDENTIALS
    with _SESSION_CACHE_LOCK:
        if (
            _CACHED_CREDENTIALS is not None
            and not _same_google_identity(_CACHED_CREDENTIALS, credentials)
        ):
            _CONNECTION_CACHE.clear()
            _EDITOR_PERMISSION_CACHE.clear()
        _CACHED_CREDENTIALS = credentials


def _get_cached_connection(
    credentials: Credentials,
    spreadsheet_id: str,
) -> SheetConnection | None:
    with _SESSION_CACHE_LOCK:
        connection = _CONNECTION_CACHE.get(str(spreadsheet_id))
        if connection is None:
            return None
        if not _same_google_identity(connection.credentials, credentials):
            _CONNECTION_CACHE.pop(str(spreadsheet_id), None)
            return None
        if (
            time.monotonic() - connection.connected_at
            > GOOGLE_CONNECTION_CACHE_TTL_SECONDS
        ):
            _CONNECTION_CACHE.pop(str(spreadsheet_id), None)
            return None
        return connection


def _remember_connection(connection: SheetConnection) -> None:
    with _SESSION_CACHE_LOCK:
        _CONNECTION_CACHE[str(connection.spreadsheet_id)] = connection


def _forget_connection(spreadsheet_id: str) -> None:
    with _SESSION_CACHE_LOCK:
        _CONNECTION_CACHE.pop(str(spreadsheet_id), None)


def _get_worksheets(
    connection: SheetConnection,
    *,
    force: bool = False,
) -> list[gspread.Worksheet]:
    now = time.monotonic()
    if (
        not force
        and connection.worksheet_cache
        and now - connection.worksheet_cache_loaded_at
        <= GOOGLE_WORKSHEET_CACHE_TTL_SECONDS
    ):
        return list(connection.worksheet_cache.values())

    worksheets = connection.spreadsheet.worksheets()
    connection.worksheet_cache = {
        worksheet.title.casefold(): worksheet for worksheet in worksheets
    }
    connection.worksheet_cache_loaded_at = now
    return worksheets


def _invalidate_worksheet_cache(connection: SheetConnection) -> None:
    connection.worksheet_cache.clear()
    connection.worksheet_cache_loaded_at = 0.0


def _check_cancel(callback: CancelCallback) -> None:
    if callback and callback():
        raise CancelledError("Người dùng đã dừng thao tác.")


def _log(callback: LogCallback, message: str) -> None:
    if callback:
        callback(message)


def _progress(callback: ProgressCallback, value: int, message: str) -> None:
    if callback:
        callback(max(0, min(100, int(value))), message)


def validate_oauth_client_json(path: str | Path) -> dict:
    client_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(client_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OAuthConfigurationError(
            f"Không thể đọc OAuth Client JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict) or "installed" not in payload:
        if isinstance(payload, dict) and "web" in payload:
            raise OAuthConfigurationError(
                "OAuth Client đang là loại Web application. Hãy tạo client loại Desktop app."
            )
        raise OAuthConfigurationError(
            "File không có cấu hình 'installed'. Hãy dùng OAuth Client loại Desktop app."
        )

    installed = payload.get("installed") or {}
    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    missing = [field for field in required if not installed.get(field)]
    if missing:
        raise OAuthConfigurationError(
            "OAuth Client JSON thiếu trường: " + ", ".join(missing)
        )
    return payload


def install_oauth_client(source_path: str | Path) -> Path:
    source = Path(source_path).expanduser().resolve()
    validate_oauth_client_json(source)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if source != OAUTH_CLIENT_FILE.resolve():
        shutil.copy2(source, OAUTH_CLIENT_FILE)
    clear_session_editor_permission_cache()
    return OAUTH_CLIENT_FILE


def _oauth_client_candidates(explicit_path: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())

    environment = os.getenv("IMPORT_LOCALIZE_OAUTH_CLIENT", "").strip()
    if environment:
        candidates.append(Path(environment).expanduser())

    candidates.extend(
        [
            OAUTH_CLIENT_FILE,
            # Reuse the OAuth Desktop Client already configured for SK Export.
            USER_CONFIG_DIR.parent / "SK-Export" / "oauth_client.json",
            application_dir() / "oauth_client.json",
            PROJECT_DIR / "oauth_client.json",
            Path.cwd() / "oauth_client.json",
        ]
    )

    unique: list[Path] = []
    for item in candidates:
        try:
            resolved = item.resolve()
        except OSError:
            resolved = item.absolute()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def resolve_oauth_client_path(explicit_path: str | None = None) -> Path:
    candidates = _oauth_client_candidates(explicit_path)
    for candidate in candidates:
        if candidate.is_file():
            validate_oauth_client_json(candidate)
            return candidate

    checked = "\n".join(f"- {path}" for path in candidates)
    raise OAuthConfigurationError(
        "Chưa cấu hình OAuth Client. Trong Cài đặt, hãy chọn file JSON của "
        "OAuth Client loại Desktop app.\n\nCác vị trí đã kiểm tra:\n" + checked
    )


def oauth_configuration_status() -> dict[str, object]:
    client_path: Path | None = None
    try:
        client_path = resolve_oauth_client_path()
        client_ready = True
        client_message = str(client_path)
    except OAuthConfigurationError as exc:
        client_ready = False
        client_message = str(exc).split("\n", 1)[0]

    return {
        "client_ready": client_ready,
        "client_path": client_message,
        "token_exists": OAUTH_TOKEN_FILE.is_file(),
        "token_path": str(OAUTH_TOKEN_FILE),
    }


class _QuietOAuthRequestHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class _OAuthRedirectApplication:
    def __init__(self) -> None:
        self.last_request_uri: str | None = None

    def __call__(self, environ, start_response):
        self.last_request_uri = request_uri(environ)
        query = parse_qs(environ.get("QUERY_STRING", ""))
        denied = bool(query.get("error"))
        title = "Đăng nhập Google chưa hoàn tất" if denied else "Đăng nhập Google thành công"
        detail = (
            "Google không cấp quyền. Bạn có thể đóng tab này và quay lại Import Localize."
            if denied
            else "Bạn có thể đóng tab này và quay lại Import Localize."
        )
        body = (
            "<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
            f"<title>{title}</title></head><body style='font-family:Segoe UI,Arial;"
            "max-width:720px;margin:64px auto;padding:0 24px'>"
            f"<h1>{title}</h1><p>{detail}</p></body></html>"
        ).encode("utf-8")
        start_response(
            "200 OK",
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [body]


def _run_cancellable_oauth_flow(
    flow: InstalledAppFlow,
    *,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
    timeout_seconds: int = 600,
) -> Credentials:
    _check_cancel(cancel_callback)
    app = _OAuthRedirectApplication()
    server = make_server(
        "127.0.0.1",
        0,
        app,
        handler_class=_QuietOAuthRequestHandler,
    )
    server.timeout = 0.25

    try:
        flow.redirect_uri = f"http://localhost:{server.server_port}/"
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent select_account",
        )
        opened = webbrowser.open(authorization_url, new=1, autoraise=True)
        if not opened:
            _log(log_callback, "Không thể tự mở trình duyệt. Hãy mở URL dưới đây:")
            print(authorization_url)

        started = time.monotonic()
        while app.last_request_uri is None:
            _check_cancel(cancel_callback)
            if time.monotonic() - started >= timeout_seconds:
                raise OAuthConfigurationError(
                    "Đăng nhập Google quá thời gian chờ 10 phút."
                )
            server.handle_request()

        _check_cancel(cancel_callback)
        response_uri = app.last_request_uri
        parsed = urlparse(response_uri)
        query = parse_qs(parsed.query)
        if query.get("error"):
            error = query.get("error", ["access_denied"])[0]
            description = query.get("error_description", [""])[0]
            raise OAuthConfigurationError(
                f"Google từ chối cấp quyền: {error}. {description}".strip()
            )

        flow.fetch_token(
            authorization_response=response_uri.replace("http://", "https://", 1)
        )
        _check_cancel(cancel_callback)
        return flow.credentials
    finally:
        server.server_close()


def _save_credentials(credentials: Credentials) -> None:
    OAUTH_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(credentials.to_json())
    payload["import_localize_scope_version"] = OAUTH_SCOPE_VERSION
    payload["scopes"] = list(OAUTH_SCOPES)
    temporary = OAUTH_TOKEN_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(OAUTH_TOKEN_FILE)
    try:
        OAUTH_TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _load_saved_credentials(log_callback: LogCallback = None) -> Credentials | None:
    if not OAUTH_TOKEN_FILE.is_file():
        return None
    try:
        payload = json.loads(OAUTH_TOKEN_FILE.read_text(encoding="utf-8"))
        if payload.get("import_localize_scope_version") != OAUTH_SCOPE_VERSION:
            OAUTH_TOKEN_FILE.unlink(missing_ok=True)
            return None
        credentials = Credentials.from_authorized_user_info(
            payload,
            scopes=OAUTH_SCOPES,
        )
        if not credentials.has_scopes(OAUTH_SCOPES):
            OAUTH_TOKEN_FILE.unlink(missing_ok=True)
            return None
        return credentials
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _log(log_callback, f"Token Google cũ không hợp lệ, sẽ đăng nhập lại: {exc}")
        OAUTH_TOKEN_FILE.unlink(missing_ok=True)
        return None


def get_oauth_credentials(
    *,
    oauth_client_path: str | None = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> Credentials:
    """Return OAuth credentials, preferring the in-memory session cache."""
    _check_cancel(cancel_callback)

    credentials = _get_memory_credentials()
    if credentials is not None:
        if credentials.expired and credentials.refresh_token:
            try:
                _log(log_callback, "Đang làm mới phiên Google trong session...")
                credentials.refresh(Request())
                _check_cancel(cancel_callback)
                _save_credentials(credentials)
            except RefreshError:
                clear_session_google_cache()
                OAUTH_TOKEN_FILE.unlink(missing_ok=True)
                credentials = None
        if credentials is not None and credentials.valid:
            _log(log_callback, "Đã dùng phiên Google đang hoạt động trong RAM.")
            return credentials

    client_path = resolve_oauth_client_path(oauth_client_path)
    credentials = _load_saved_credentials(log_callback)

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            _log(log_callback, "Đang làm mới phiên đăng nhập Google...")
            credentials.refresh(Request())
            _check_cancel(cancel_callback)
            _save_credentials(credentials)
        except RefreshError:
            OAUTH_TOKEN_FILE.unlink(missing_ok=True)
            credentials = None

    if credentials and credentials.valid:
        _remember_memory_credentials(credentials)
        _log(log_callback, "Đã nạp phiên Google đã lưu vào session.")
        return credentials

    _log(log_callback, "Đang mở trình duyệt để đăng nhập Google...")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_path),
        scopes=OAUTH_SCOPES,
    )
    credentials = _run_cancellable_oauth_flow(
        flow,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )
    if not credentials or not credentials.valid:
        raise OAuthConfigurationError("Google không trả về phiên đăng nhập hợp lệ.")
    _save_credentials(credentials)
    _remember_memory_credentials(credentials)
    _log(log_callback, f"Đã lưu phiên Google tại {OAUTH_TOKEN_FILE}.")
    return credentials

def authenticate_google_account(
    *,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> tuple[bool, str]:
    try:
        credentials = get_oauth_credentials(
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )
        return bool(credentials.valid), (
            "Đăng nhập Google thành công. Tài khoản có thể dùng mọi Google Sheet "
            "mà tài khoản đó có quyền Editor."
        )
    except CancelledError:
        raise
    except Exception as exc:
        return False, str(exc)


def clear_saved_oauth_token() -> tuple[bool, str]:
    clear_session_editor_permission_cache()
    try:
        if OAUTH_TOKEN_FILE.exists():
            OAUTH_TOKEN_FILE.unlink()
            return True, "Đã đăng xuất và xóa phiên Google trên máy này."
        return True, "Chưa có phiên Google được lưu."
    except OSError as exc:
        return False, f"Không thể xóa token Google: {exc}"


def extract_spreadsheet_id(url: str) -> str:
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url or "")
    if not match:
        raise GoogleServiceError(
            "Link Google Sheet không hợp lệ. Link phải chứa /spreadsheets/d/<ID>."
        )
    return match.group(1)


def _authorize(credentials: Credentials) -> gspread.Client:
    client = gspread.authorize(credentials)
    if hasattr(client, "set_timeout"):
        # Giữ các lệnh gspread metadata ngắn để nút Dừng không phải chờ lâu.
        client.set_timeout(GOOGLE_CANCELLABLE_READ_TIMEOUT_SECONDS)
    return client


def _check_editor_permission(
    credentials: Credentials,
    spreadsheet_id: str,
    *,
    cancel_callback: CancelCallback = None,
) -> str:
    _check_cancel(cancel_callback)
    session = AuthorizedSession(credentials)
    response = _request_with_retry(
        session,
        "GET",
        f"https://www.googleapis.com/drive/v3/files/{spreadsheet_id}",
        action="Kiểm tra quyền Editor",
        cancel_callback=cancel_callback,
        timeout=45,
        params={
            "fields": "id,name,mimeType,trashed,capabilities(canEdit)",
            "supportsAllDrives": "true",
        },
    )
    _check_cancel(cancel_callback)

    if response.status_code == 404:
        raise SheetPermissionError(
            "Không tìm thấy Google Sheet hoặc tài khoản hiện tại không có quyền truy cập."
        )
    if response.status_code >= 400:
        detail = response.text
        try:
            detail = response.json().get("error", {}).get("message", detail)
        except Exception:
            pass
        lowered = str(detail).casefold()
        if response.status_code == 403 and "drive api" in lowered and "disabled" in lowered:
            raise OAuthConfigurationError(
                "Google Drive API chưa được bật cho OAuth Project."
            )
        if response.status_code == 403:
            raise SheetPermissionError(
                "Tài khoản Google hiện tại không có quyền chỉnh sửa file này."
            )
        raise GoogleServiceError(
            f"Không thể kiểm tra quyền Google Drive ({response.status_code}): {detail}"
        )

    payload = response.json()
    if payload.get("trashed"):
        raise SheetPermissionError("Google Sheet đang nằm trong Thùng rác.")
    if not (payload.get("capabilities") or {}).get("canEdit", False):
        raise SheetPermissionError(
            "Tài khoản đang đăng nhập chỉ có quyền xem. Hãy cấp quyền Editor hoặc đổi tài khoản."
        )
    return payload.get("name") or spreadsheet_id


def connect_to_spreadsheet(
    spreadsheet_url: str,
    *,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> SheetConnection:
    _progress(progress_callback, 5, "Đang xác thực Google")
    credentials = get_oauth_credentials(
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)

    cached_connection = _get_cached_connection(credentials, spreadsheet_id)
    name = _cached_editor_permission_name(credentials, spreadsheet_id)

    if cached_connection is not None and name is not None:
        _progress(progress_callback, 100, f"Đã kết nối nhanh: {name}")
        _log(
            log_callback,
            f"Tái sử dụng kết nối Google Sheet '{name}' trong session; "
            "không mở lại spreadsheet.",
        )
        return cached_connection

    if name is not None:
        _progress(
            progress_callback,
            40,
            "Dùng quyền Editor đã xác nhận trong session",
        )
        _log(
            log_callback,
            f"Bỏ qua kiểm tra quyền Editor: '{name}' đã được xác nhận trong session này.",
        )
    else:
        _progress(progress_callback, 35, "Đang kiểm tra quyền Editor")
        name = _check_editor_permission(
            credentials,
            spreadsheet_id,
            cancel_callback=cancel_callback,
        )
        _remember_editor_permission(credentials, spreadsheet_id, name)
        _log(log_callback, f"Đã xác nhận quyền Editor với '{name}'.")

    _check_cancel(cancel_callback)
    client = _authorize(credentials)
    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.APIError:
        _forget_editor_permission(credentials, spreadsheet_id)
        _forget_connection(spreadsheet_id)
        raise

    connection = SheetConnection(
        credentials=credentials,
        client=client,
        spreadsheet=spreadsheet,
        spreadsheet_id=spreadsheet_id,
        spreadsheet_name=name,
        authorized_session=AuthorizedSession(credentials),
    )
    _remember_connection(connection)
    _progress(progress_callback, 100, f"Đã kết nối: {name}")
    return connection


_INVALID_WINDOWS_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1F]')


def sanitize_export_filename_part(value: object) -> str:
    """Return a Windows-safe filename component matching the Apps Script rule."""
    safe_name = _INVALID_WINDOWS_FILENAME_CHARS.sub("_", str(value or ""))
    safe_name = re.sub(r"[. ]+$", "", safe_name).strip()
    return safe_name or "export"


def build_csv_export_filename(spreadsheet_name: str, sheet_name: str) -> str:
    """Build ``[Spreadsheet] - [Tab].csv`` for one exported worksheet."""
    return (
        f"{sanitize_export_filename_part(spreadsheet_name)} - "
        f"{sanitize_export_filename_part(sheet_name)}.csv"
    )


def _csv_export_error_detail(response) -> str:
    """Extract a compact message from an export endpoint response."""
    content_type = str(response.headers.get("Content-Type", "")).casefold()
    if "json" in content_type:
        try:
            payload = response.json()
            return str(payload.get("error", {}).get("message") or payload)
        except Exception:
            pass
    text = str(getattr(response, "text", "") or "").strip()
    if text:
        text = re.sub(r"<[^>]+>", " ", text)
        text = " ".join(text.split())
        return text[:500]
    return f"HTTP {response.status_code}"


def download_export_tabs_as_csv(
    connection: SheetConnection,
    output_dir: str | Path,
    *,
    prefix: str = EXPORT_SHEET_PREFIX,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> list[Path]:
    """Download all ``export_*`` tabs concurrently as Google's raw CSV bytes."""
    _check_cancel(cancel_callback)
    destination = Path(output_dir).expanduser().resolve()
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GoogleServiceError(
            f"Không thể tạo thư mục lưu CSV '{destination}': {exc}"
        ) from exc
    if not destination.is_dir():
        raise GoogleServiceError(f"Đường dẫn lưu không phải thư mục: {destination}")

    _progress(progress_callback, 5, "Đang quét các tab export_*")
    try:
        worksheets = _get_worksheets(connection)
    except gspread.exceptions.APIError as exc:
        _invalidate_worksheet_cache(connection)
        raise GoogleServiceError(_format_api_error(exc)) from exc

    export_sheets = [sheet for sheet in worksheets if sheet.title.startswith(prefix)]
    if not export_sheets:
        raise GoogleServiceError(
            f"Không tìm thấy tab nào có tên bắt đầu bằng '{prefix}'."
        )

    total = len(export_sheets)
    max_workers = max(1, min(MAX_PARALLEL_EXPORT_DOWNLOADS, total))
    _log(
        log_callback,
        f"Đã tìm thấy {total} tab bắt đầu bằng '{prefix}'. "
        f"Tải song song tối đa {max_workers} file.",
    )
    export_url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{connection.spreadsheet_id}/export"
    )

    def download_one(index: int, worksheet) -> tuple[int, Path, int, str]:
        _check_cancel(cancel_callback)
        filename = build_csv_export_filename(
            connection.spreadsheet_name,
            worksheet.title,
        )
        output_path = destination / filename
        partial_path = output_path.with_name(output_path.name + ".part")
        session = AuthorizedSession(connection.credentials)
        try:
            response = _request_with_retry(
                session,
                "GET",
                export_url,
                action=f"Tải CSV tab {worksheet.title}",
                log_callback=log_callback,
                cancel_callback=cancel_callback,
                timeout=CSV_EXPORT_REQUEST_TIMEOUT_SECONDS,
                params={"format": "csv", "gid": str(worksheet.id)},
                headers={"Accept": "text/csv,*/*;q=0.8"},
            )
            _check_cancel(cancel_callback)
            if response.status_code < 200 or response.status_code >= 300:
                detail = _csv_export_error_detail(response)
                if response.status_code in (401, 403):
                    raise SheetPermissionError(
                        "Phiên Google không có quyền xuất CSV của bảng tính này. "
                        f"Chi tiết: {detail}"
                    )
                raise GoogleServiceError(
                    f"Google Sheets không thể tạo CSV cho tab '{worksheet.title}' "
                    f"(HTTP {response.status_code}): {detail}"
                )

            content = bytes(response.content)
            content_type = str(response.headers.get("Content-Type", "")).casefold()
            preview = content[:300].lstrip().lower()
            if "text/html" in content_type or preview.startswith(b"<!doctype html"):
                raise GoogleServiceError(
                    f"Google trả về trang HTML thay vì CSV cho tab '{worksheet.title}'. "
                    "Hãy đăng xuất Google trong Cài đặt rồi đăng nhập lại."
                )

            partial_path.write_bytes(content)
            _check_cancel(cancel_callback)
            partial_path.replace(output_path)
            return index, output_path, len(content), worksheet.title
        except Exception:
            partial_path.unlink(missing_ok=True)
            raise

    results: dict[int, Path] = {}
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="csv-export")
    futures = {
        executor.submit(download_one, index, worksheet): (index, worksheet.title)
        for index, worksheet in enumerate(export_sheets, start=1)
    }
    completed_count = 0
    pending = set(futures)
    try:
        # Không dùng as_completed() vì nó có thể block đến khi một request mạng
        # hoàn thành. Poll rất ngắn để nút Dừng phản hồi gần như tức thời.
        while pending:
            _check_cancel(cancel_callback)
            done, pending = wait(
                pending,
                timeout=GOOGLE_CANCEL_POLL_SECONDS,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                continue
            for future in done:
                _check_cancel(cancel_callback)
                index, output_path, size_bytes, title = future.result()
                results[index] = output_path
                completed_count += 1
                _log(
                    log_callback,
                    f"Đã lưu {output_path.name} ({size_bytes:,} byte).",
                )
                _progress(
                    progress_callback,
                    8 + round(completed_count / total * 92),
                    f"Đã tải {completed_count}/{total}: {title}",
                )
    except Exception:
        for future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    created_files = [results[index] for index in sorted(results)]
    _progress(progress_callback, 100, f"Đã tải xong {total} file CSV")
    return created_files

def _normalize_header(values: list[object]) -> list[str]:
    return [" ".join(str(value or "").split()).casefold() for value in values]


def _format_api_error(exc: gspread.exceptions.APIError) -> str:
    message = str(exc)
    lowered = message.casefold()
    if "403" in message or "permission_denied" in lowered:
        return "Tài khoản Google hiện tại không có quyền Editor với bảng tính này."
    if "404" in message:
        return "Không tìm thấy bảng tính hoặc tab đích."
    if "429" in message or "resource_exhausted" in lowered:
        return "Google Sheets API đang giới hạn tần suất. Hãy thử lại sau ít phút."
    return f"Lỗi Google Sheets API: {message}"


def _last_populated_row(values: list[list[object]]) -> int:
    """Return the 1-based index of the last non-empty row."""
    last_row = 0
    for row_index, row in enumerate(values, start=1):
        if any(str(value).strip() for value in row if value is not None):
            last_row = row_index
    return last_row


def fill_translate_data_columns(
    connection: SheetConnection,
    *,
    sheet_name: str = "Translate_Data",
    source_row: int = 2,
    columns: str = "D:I",
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> tuple[bool, str, int]:
    """Fill selected cells to the tab's current grid row count.

    No reference column is read. The destination limit comes from lightweight
    worksheet metadata (``gridProperties.rowCount``), which is independent of
    formula calculation and imported values. Only the small source row is read
    to validate that selected source cells are populated and are not
    ARRAYFORMULA cells.
    """
    cleaned_sheet_name = str(sheet_name or "").strip()
    if not cleaned_sheet_name:
        raise GoogleServiceError("Tên tab cần fill không được để trống.")
    try:
        source_row = int(source_row)
    except (TypeError, ValueError) as exc:
        raise GoogleServiceError("Hàng nguồn phải là số nguyên lớn hơn hoặc bằng 1.") from exc
    if source_row < 1:
        raise GoogleServiceError("Hàng nguồn phải là số nguyên lớn hơn hoặc bằng 1.")

    try:
        selected_columns = parse_column_selection(columns)
        normalized_columns = normalize_column_selection(columns)
    except FillSelectionError as exc:
        raise GoogleServiceError(str(exc)) from exc

    _check_cancel(cancel_callback)
    _progress(progress_callback, 8, f"Đang đọc cấu trúc tab {cleaned_sheet_name}")

    # Chỉ đọc metadata cấu trúc; includeGridData=false nên không chờ công thức,
    # dữ liệu import hoặc giá trị hiển thị trong bất kỳ cột nào.
    try:
        sheet_properties = _fetch_sheet_properties_fast(
            connection,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )
    except Exception as exc:
        if isinstance(exc, (GoogleServiceError, CancelledError)):
            raise
        raise GoogleServiceError(f"Không thể đọc cấu trúc tab phục vụ Fill: {exc}") from exc

    properties = sheet_properties.get(cleaned_sheet_name.casefold())
    if properties is None:
        return False, f"Không tìm thấy tab '{cleaned_sheet_name}'.", 0

    actual_title = str(properties.get("title") or cleaned_sheet_name)
    sheet_id = int(properties.get("sheetId") or 0)
    grid = properties.get("gridProperties", {}) or {}
    last_row = int(grid.get("rowCount") or 0)
    column_count = int(grid.get("columnCount") or 0)

    if last_row < 1:
        raise GoogleServiceError(f"Không xác định được số hàng hiện có của tab '{actual_title}'.")
    if source_row > last_row:
        raise GoogleServiceError(
            f"Hàng nguồn {source_row} vượt quá số hàng hiện có của tab ({last_row})."
        )
    if source_row == last_row:
        return (
            False,
            f"Hàng nguồn {source_row} đang là hàng cuối hiện có của tab; "
            "không có hàng bên dưới để fill.",
            source_row,
        )

    max_selected_column = max(selected_columns)
    if max_selected_column > column_count:
        invalid = column_number_to_letters(max_selected_column)
        raise GoogleServiceError(
            f"Tab '{actual_title}' chưa có cột {invalid}. "
            f"Số cột hiện tại: {column_count}."
        )

    _check_cancel(cancel_callback)
    spreadsheet_base = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{connection.spreadsheet_id}"
    )
    quoted_title = _quote_sheet_title(actual_title)
    column_groups = group_consecutive_columns(selected_columns)
    source_ranges = [
        f"{quoted_title}!{column_number_to_letters(start)}{source_row}:"
        f"{column_number_to_letters(end)}{source_row}"
        for start, end in column_groups
    ]
    source_params: list[tuple[str, str]] = [
        ("ranges", item) for item in source_ranges
    ]
    source_params.extend(
        [
            ("majorDimension", "ROWS"),
            ("valueRenderOption", "FORMULA"),
        ]
    )

    _progress(progress_callback, 26, f"Đang kiểm tra nhanh hàng nguồn {source_row}")
    try:
        source_response = _request_with_retry(
            connection.authorized_session,
            "GET",
            f"{spreadsheet_base}/values:batchGet",
            action=f"Đọc hàng nguồn {source_row}",
            log_callback=log_callback,
            cancel_callback=cancel_callback,
            params=source_params,
        )
    except CancelledError:
        raise
    except Exception as exc:
        raise GoogleServiceError(
            f"Không thể đọc hàng nguồn phục vụ Fill: {exc}"
        ) from exc

    _raise_for_response(source_response, f"Đọc hàng nguồn {source_row}")
    _check_cancel(cancel_callback)

    source_value_ranges = source_response.json().get("valueRanges", [])
    missing_cells: list[str] = []
    array_formula_cells: list[str] = []
    for range_index, (start_column, end_column) in enumerate(column_groups):
        expected_width = end_column - start_column + 1
        values = (
            source_value_ranges[range_index].get("values", [])
            if range_index < len(source_value_ranges)
            else []
        )
        row_values = list(values[0]) if values else []
        row_values.extend([""] * (expected_width - len(row_values)))
        for offset, cell_value in enumerate(row_values[:expected_width]):
            column_number = start_column + offset
            cell_name = f"{column_number_to_letters(column_number)}{source_row}"
            text_value = str(cell_value or "").strip()
            if not text_value:
                missing_cells.append(cell_name)
            elif re.match(r"^=\s*ARRAYFORMULA\s*\(", text_value, re.IGNORECASE):
                array_formula_cells.append(cell_name)

    if missing_cells:
        return (
            False,
            "Các ô nguồn sau đang trống nên không thể fill: "
            + ", ".join(missing_cells),
            last_row,
        )
    if array_formula_cells:
        return (
            False,
            "Không fill ARRAYFORMULA tại: " + ", ".join(array_formula_cells)
            + ". ARRAYFORMULA tự mở rộng xuống dưới.",
            last_row,
        )

    _progress(
        progress_callback,
        58,
        f"Đang fill {normalized_columns} đến hàng {last_row}",
    )
    response = _request_with_retry(
        connection.authorized_session,
        "POST",
        f"{spreadsheet_base}:batchUpdate",
        action=f"Fill dữ liệu tab {actual_title}",
        log_callback=log_callback,
        cancel_callback=cancel_callback,
        json={
            "requests": build_fill_copy_requests(
                sheet_id,
                source_row,
                last_row,
                selected_columns,
            )
        },
    )
    _raise_for_response(response, f"Fill dữ liệu tab {actual_title}")
    _check_cancel(cancel_callback)
    _progress(progress_callback, 100, f"Đã fill xong tab {actual_title}")

    added_rows = max(0, last_row - source_row)
    filled_cells = added_rows * len(selected_columns)
    return (
        True,
        f"Đã fill {actual_title}!{normalized_columns} từ hàng {source_row} "
        f"đến hàng cuối hiện có của tab ({last_row}) "
        f"({added_rows} hàng, {filled_cells} ô đích).",
        last_row,
    )

def _prepare_value(value: object, option: str) -> object:
    if value is None:
        return ""
    if option == "RAW":
        return value
    text = str(value)
    stripped = text.strip()
    if stripped.startswith("0") and len(stripped) > 1 and stripped.isdigit():
        return "'" + stripped
    return value


def _prepare_rows(rows: list[list[object]], option: str) -> list[list[object]]:
    return [[_prepare_value(value, option) for value in row] for row in rows]


def _quote_sheet_title(title: str) -> str:
    """Return an A1-safe quoted worksheet title."""
    return "'" + str(title).replace("'", "''") + "'"


def _response_error_detail(response) -> str:
    detail = response.text
    try:
        payload = response.json()
        detail = payload.get("error", {}).get("message", detail)
    except Exception:
        pass
    return str(detail or f"HTTP {response.status_code}")


def _raise_for_response(response, action: str) -> None:
    if response.status_code < 400:
        return
    detail = _response_error_detail(response)
    lowered = detail.casefold()
    if response.status_code == 403:
        raise SheetPermissionError(
            "Tài khoản Google hiện tại không có quyền Editor với bảng tính này."
        )
    if response.status_code == 404:
        raise GoogleServiceError("Không tìm thấy bảng tính hoặc tab đích.")
    if response.status_code == 429 or "resource_exhausted" in lowered:
        raise GoogleServiceError(
            "Google Sheets API đang giới hạn tần suất. Hãy thử lại sau ít phút."
        )
    raise GoogleServiceError(f"{action} thất bại: {detail}")


def _sleep_with_cancel(seconds: float, cancel_callback: CancelCallback) -> None:
    """Sleep in short intervals so the Stop button remains responsive."""
    deadline = time.monotonic() + max(0.0, float(seconds))
    while True:
        _check_cancel(cancel_callback)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(GOOGLE_CANCEL_POLL_SECONDS, remaining))


def _retry_delay_seconds(attempt: int, response=None) -> float:
    """Return exponential backoff, honoring Retry-After when provided."""
    if response is not None:
        raw = str(getattr(response, "headers", {}).get("Retry-After", "") or "").strip()
        if raw:
            try:
                return min(30.0, max(0.5, float(raw)))
            except ValueError:
                pass
    return min(
        8.0,
        GOOGLE_REQUEST_RETRY_BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1)),
    )


def _is_transient_http_status(status_code: int) -> bool:
    return int(status_code) in {408, 429, 500, 502, 503, 504}


def _effective_request_timeout(
    timeout: int | float | tuple[float, float],
    cancel_callback: CancelCallback,
) -> int | float | tuple[float, float]:
    """Giới hạn thời gian chờ socket cho tác vụ có thể bị người dùng dừng.

    requests/urllib3 không thể hủy một recv() đồng bộ đang block chỉ bằng Event.
    Vì vậy các worker có nút Dừng dùng read-timeout ngắn và request nhỏ; sau
    timeout, callback được kiểm tra ngay trước khi quyết định retry.
    """
    if not cancel_callback:
        return timeout
    if isinstance(timeout, tuple):
        connect_timeout = min(float(timeout[0]), GOOGLE_CONNECT_TIMEOUT_SECONDS)
        read_timeout = min(
            float(timeout[1]), GOOGLE_CANCELLABLE_READ_TIMEOUT_SECONDS
        )
        return (max(0.5, connect_timeout), max(0.5, read_timeout))
    read_timeout = min(float(timeout), GOOGLE_CANCELLABLE_READ_TIMEOUT_SECONDS)
    return (GOOGLE_CONNECT_TIMEOUT_SECONDS, max(0.5, read_timeout))


def _request_with_retry(
    session: AuthorizedSession,
    method: str,
    url: str,
    *,
    action: str,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
    timeout: int | float | tuple[float, float] = GOOGLE_REQUEST_TIMEOUT_SECONDS,
    max_attempts: int = GOOGLE_REQUEST_RETRY_ATTEMPTS,
    **kwargs,
):
    """Run an idempotent Google API request with cancellable retry/backoff."""
    last_error: Exception | None = None
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        _check_cancel(cancel_callback)
        try:
            response = session.request(
                method=method,
                url=url,
                timeout=_effective_request_timeout(timeout, cancel_callback),
                **kwargs,
            )
        except (ReadTimeout, RequestsTimeout, RequestsConnectionError) as exc:
            _check_cancel(cancel_callback)
            last_error = exc
            if attempt >= max_attempts:
                break
            delay = _retry_delay_seconds(attempt)
            _log(
                log_callback,
                f"{action}: Google phản hồi chậm/mất kết nối; thử lại "
                f"{attempt + 1}/{max_attempts} sau {delay:.1f}s.",
            )
            _sleep_with_cancel(delay, cancel_callback)
            continue

        _check_cancel(cancel_callback)
        if _is_transient_http_status(response.status_code) and attempt < max_attempts:
            delay = _retry_delay_seconds(attempt, response)
            _log(
                log_callback,
                f"{action}: Google trả HTTP {response.status_code}; thử lại "
                f"{attempt + 1}/{max_attempts} sau {delay:.1f}s.",
            )
            _sleep_with_cancel(delay, cancel_callback)
            continue
        return response

    raise GoogleServiceError(
        f"{action} không nhận được phản hồi ổn định từ Google Sheets sau "
        f"{max_attempts} lần thử. Lỗi cuối: {last_error}"
    ) from last_error


def _chunked(items: list[object], size: int) -> list[list[object]]:
    chunk_size = max(1, int(size))
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def _fetch_sheet_properties_fast(
    connection: SheetConnection,
    *,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> dict[str, dict[str, object]]:
    """Fetch only worksheet properties using the lightweight Sheets REST API."""
    spreadsheet_base = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{connection.spreadsheet_id}"
    )
    response = _request_with_retry(
        connection.authorized_session,
        "GET",
        spreadsheet_base,
        action="Đọc cấu trúc tab",
        log_callback=log_callback,
        cancel_callback=cancel_callback,
        params={
            "includeGridData": "false",
            "fields": (
                "sheets(properties(sheetId,title,"
                "gridProperties(rowCount,columnCount,frozenRowCount)))"
            ),
        },
    )
    _raise_for_response(response, "Đọc cấu trúc tab")
    result: dict[str, dict[str, object]] = {}
    for item in response.json().get("sheets", []):
        properties = item.get("properties", {}) or {}
        title = str(properties.get("title") or "")
        if title:
            result[title.casefold()] = properties
    return result


def _build_structure_requests(
    prepared: list[tuple[CsvBundle, ImportJob, list[list[object]]]],
    sheet_properties: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], list[str]]:
    """Build only the structural mutations still required at this moment."""
    requests_out: list[dict[str, object]] = []
    clear_ranges: list[str] = []
    for bundle, job, values in prepared:
        required_rows = max(1, len(values))
        required_cols = max(
            1,
            max((len(row) for row in values), default=bundle.column_count or 1),
        )
        existing = sheet_properties.get(job.sheet_name.casefold())
        frozen_rows = 1 if bundle.header else 0
        if existing is None:
            requests_out.append(
                {
                    "addSheet": {
                        "properties": {
                            "title": job.sheet_name,
                            "gridProperties": {
                                "rowCount": max(100, required_rows),
                                "columnCount": max(10, required_cols),
                                "frozenRowCount": frozen_rows,
                            },
                        }
                    }
                }
            )
            continue

        clear_ranges.append(_quote_sheet_title(job.sheet_name))
        grid = existing.get("gridProperties", {}) or {}
        current_rows = int(grid.get("rowCount") or 0)
        current_cols = int(grid.get("columnCount") or 0)
        current_frozen = int(grid.get("frozenRowCount") or 0)
        row_count = max(current_rows, required_rows)
        column_count = max(current_cols, required_cols)
        if (
            row_count != current_rows
            or column_count != current_cols
            or frozen_rows != current_frozen
        ):
            requests_out.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": int(existing.get("sheetId")),
                            "gridProperties": {
                                "rowCount": row_count,
                                "columnCount": column_count,
                                "frozenRowCount": frozen_rows,
                            },
                        },
                        "fields": (
                            "gridProperties.rowCount,"
                            "gridProperties.columnCount,"
                            "gridProperties.frozenRowCount"
                        ),
                    }
                }
            )
    return requests_out, clear_ranges


def _apply_structure_requests_resilient(
    connection: SheetConnection,
    prepared: list[tuple[CsvBundle, ImportJob, list[list[object]]]],
    *,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> list[str]:
    """Apply add/resize/freeze requests in small batches with timeout recovery.

    ``addSheet`` is not safe to retry blindly: the server may have created a tab
    before the client timed out. On every ambiguous failure we re-read metadata,
    rebuild the remaining work, and therefore never issue a duplicate addSheet
    for a tab that already exists.
    """
    spreadsheet_base = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{connection.spreadsheet_id}"
    )
    max_passes = max(2, GOOGLE_REQUEST_RETRY_ATTEMPTS)

    for recovery_pass in range(1, max_passes + 1):
        _check_cancel(cancel_callback)
        properties = _fetch_sheet_properties_fast(
            connection,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )
        structural_requests, clear_ranges = _build_structure_requests(
            prepared,
            properties,
        )
        if not structural_requests:
            _invalidate_worksheet_cache(connection)
            return clear_ranges

        chunks = _chunked(structural_requests, GOOGLE_STRUCTURE_BATCH_SIZE)
        restart_after_ambiguous_failure = False
        for chunk_index, chunk in enumerate(chunks, start=1):
            _check_cancel(cancel_callback)
            try:
                response = connection.authorized_session.post(
                    f"{spreadsheet_base}:batchUpdate",
                    json={"requests": chunk},
                    timeout=GOOGLE_REQUEST_TIMEOUT_SECONDS,
                )
            except (ReadTimeout, RequestsTimeout, RequestsConnectionError) as exc:
                if recovery_pass >= max_passes:
                    raise GoogleServiceError(
                        "Chuẩn bị tab bị timeout nhiều lần. Google có thể đã xử lý "
                        f"một phần request. Lỗi cuối: {exc}"
                    ) from exc
                delay = _retry_delay_seconds(recovery_pass)
                _log(
                    log_callback,
                    "Chuẩn bị tab bị timeout; đang đọc lại trạng thái thực tế từ "
                    f"Google rồi tiếp tục (lần {recovery_pass + 1}/{max_passes}).",
                )
                _sleep_with_cancel(delay, cancel_callback)
                restart_after_ambiguous_failure = True
                break

            if _is_transient_http_status(response.status_code):
                if recovery_pass >= max_passes:
                    _raise_for_response(response, "Chuẩn bị tab")
                delay = _retry_delay_seconds(recovery_pass, response)
                _log(
                    log_callback,
                    f"Chuẩn bị tab nhận HTTP {response.status_code}; đang đồng bộ "
                    "lại metadata trước khi thử tiếp.",
                )
                _sleep_with_cancel(delay, cancel_callback)
                restart_after_ambiguous_failure = True
                break

            _raise_for_response(response, "Chuẩn bị tab")
            _progress(
                progress_callback,
                10 + round(chunk_index / max(1, len(chunks)) * 8),
                f"Đang chuẩn bị tab {chunk_index}/{len(chunks)}",
            )

        if restart_after_ambiguous_failure:
            continue

        # Re-read once so clear ranges include tabs that were just created.
        final_properties = _fetch_sheet_properties_fast(
            connection,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )
        _remaining, clear_ranges = _build_structure_requests(prepared, final_properties)
        _invalidate_worksheet_cache(connection)
        return clear_ranges

    raise GoogleServiceError("Không thể hoàn tất bước chuẩn bị tab sau nhiều lần khôi phục.")


def _split_value_ranges(
    sheet_name: str,
    values: list[list[object]],
) -> list[dict[str, object]]:
    """Split one worksheet payload into API-friendly row/cell chunks."""
    if not values:
        return []
    width = max((len(row) for row in values), default=1)
    rows_by_cells = max(1, UPLOAD_MAX_CELLS_PER_RANGE // max(1, width))
    chunk_rows = max(1, min(UPLOAD_MAX_ROWS_PER_RANGE, rows_by_cells))
    quoted = _quote_sheet_title(sheet_name)
    entries: list[dict[str, object]] = []
    for begin in range(0, len(values), chunk_rows):
        chunk = values[begin : begin + chunk_rows]
        entries.append(
            {
                "range": f"{quoted}!A{begin + 1}",
                "majorDimension": "ROWS",
                "values": chunk,
            }
        )
    return entries


def _group_entries_by_payload_size(
    entries: list[dict[str, object]],
) -> list[list[dict[str, object]]]:
    """Group value ranges so each HTTP request stays comfortably below 10 MB."""
    groups: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_bytes = 0
    for entry in entries:
        entry_bytes = len(
            json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        if current and current_bytes + entry_bytes > UPLOAD_MAX_REQUEST_BYTES:
            groups.append(current)
            current = []
            current_bytes = 0
        current.append(entry)
        current_bytes += entry_bytes
    if current:
        groups.append(current)
    return groups


def upload_bundles_fast(
    connection: SheetConnection,
    uploads: list[tuple[CsvBundle, ImportJob]],
    *,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> int:
    """Replace one or many tabs with timeout recovery and bounded batches.

    Performance is still based on Sheets batch APIs, but large structural
    requests are split into smaller groups. Idempotent clear/value writes are
    retried automatically. ``addSheet`` timeouts are recovered by re-reading
    server metadata before rebuilding the remaining structural work.
    """
    if not uploads:
        return 0

    started_at = time.monotonic()
    try:
        _check_cancel(cancel_callback)
        _progress(progress_callback, 2, "Đang chuẩn bị dữ liệu Google Sheets")

        target_names: dict[str, str] = {}
        prepared: list[tuple[CsvBundle, ImportJob, list[list[object]]]] = []
        total_data_rows = 0
        for bundle, job in uploads:
            key = job.sheet_name.casefold()
            if key in target_names:
                raise GoogleServiceError(
                    f"Tab '{job.sheet_name}' xuất hiện nhiều lần trong cùng lượt import."
                )
            target_names[key] = job.sheet_name
            input_option = (
                "USER_ENTERED"
                if job.value_input_option == "USER_ENTERED"
                else "RAW"
            )
            header = (
                _prepare_rows([bundle.header], input_option)[0]
                if bundle.header
                else []
            )
            rows = _prepare_rows(bundle.rows, input_option)
            values = ([header] if header else []) + rows
            prepared.append((bundle, job, values))
            total_data_rows += bundle.row_count

        _check_cancel(cancel_callback)
        spreadsheet_base = (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{connection.spreadsheet_id}"
        )

        # Structural work is the only non-idempotent phase because addSheet may
        # already have succeeded when a response times out. The resilient helper
        # always re-reads metadata before retrying so duplicate tabs are avoided.
        _progress(progress_callback, 8, "Đang tạo và chuẩn bị các tab đích")
        clear_ranges = _apply_structure_requests_resilient(
            connection,
            prepared,
            progress_callback=progress_callback,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )

        if clear_ranges:
            _progress(progress_callback, 20, "Đang xóa dữ liệu cũ của các tab")
            clear_groups = _chunked(clear_ranges, GOOGLE_CLEAR_BATCH_SIZE)
            for group_index, ranges in enumerate(clear_groups, start=1):
                _check_cancel(cancel_callback)
                response = _request_with_retry(
                    connection.authorized_session,
                    "POST",
                    f"{spreadsheet_base}/values:batchClear",
                    action="Xóa dữ liệu cũ",
                    log_callback=log_callback,
                    cancel_callback=cancel_callback,
                    json={"ranges": ranges},
                )
                _raise_for_response(response, "Xóa dữ liệu cũ")
                _progress(
                    progress_callback,
                    20 + round(group_index / max(1, len(clear_groups)) * 5),
                    f"Đang xóa dữ liệu cũ {group_index}/{len(clear_groups)}",
                )

        # Google requires one valueInputOption per batch request. Group by mode.
        entries_by_option: dict[str, list[dict[str, object]]] = {}
        rows_by_entry_id: dict[int, int] = {}
        for bundle, job, values in prepared:
            option = (
                "USER_ENTERED"
                if job.value_input_option == "USER_ENTERED"
                else "RAW"
            )
            entries = _split_value_ranges(job.sheet_name, values)
            entries_by_option.setdefault(option, []).extend(entries)
            for entry in entries:
                rows_by_entry_id[id(entry)] = len(entry.get("values", []))

        all_groups: list[tuple[str, list[dict[str, object]]]] = []
        for option, entries in entries_by_option.items():
            for group in _group_entries_by_payload_size(entries):
                all_groups.append((option, group))

        total_value_rows = sum(
            rows_by_entry_id.get(id(entry), 0)
            for _option, group in all_groups
            for entry in group
        )
        written_value_rows = 0
        for request_index, (option, group) in enumerate(all_groups, start=1):
            _check_cancel(cancel_callback)
            response = _request_with_retry(
                connection.authorized_session,
                "POST",
                f"{spreadsheet_base}/values:batchUpdate",
                action=f"Ghi dữ liệu gói {request_index}/{len(all_groups)}",
                log_callback=log_callback,
                cancel_callback=cancel_callback,
                json={
                    "valueInputOption": option,
                    "includeValuesInResponse": False,
                    "data": group,
                },
            )
            _raise_for_response(response, "Ghi dữ liệu")
            written_value_rows += sum(
                rows_by_entry_id.get(id(entry), 0) for entry in group
            )
            percent = 25 + round(
                written_value_rows / max(1, total_value_rows) * 75
            )
            _progress(
                progress_callback,
                min(100, percent),
                f"Đang ghi nhanh {request_index}/{len(all_groups)} gói dữ liệu",
            )

        _invalidate_worksheet_cache(connection)
        for bundle, job, _values in prepared:
            _log(
                log_callback,
                f"Đã nhập {bundle.row_count} dòng vào tab '{job.sheet_name}'.",
            )
        elapsed = time.monotonic() - started_at
        _log(
            log_callback,
            f"Tối ưu API hoàn tất: {len(prepared)} tab, "
            f"{total_data_rows} dòng dữ liệu trong {elapsed:.2f} giây.",
        )
        _progress(progress_callback, 100, "Đã ghi xong dữ liệu")
        return total_data_rows
    except gspread.exceptions.APIError as exc:
        raise GoogleServiceError(_format_api_error(exc)) from exc

def upload_bundle(
    connection: SheetConnection,
    bundle: CsvBundle,
    job: ImportJob,
    *,
    progress_callback: ProgressCallback = None,
    log_callback: LogCallback = None,
    cancel_callback: CancelCallback = None,
) -> int:
    """Backward-compatible wrapper for uploading one CSV bundle."""
    return upload_bundles_fast(
        connection,
        [(bundle, job)],
        progress_callback=progress_callback,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )

