from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import time
import webbrowser
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse
from wsgiref.simple_server import WSGIRequestHandler, make_server
from wsgiref.util import request_uri

import gspread
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from import_localize.app.constants import (
    GOOGLE_REQUEST_TIMEOUT_SECONDS,
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

ProgressCallback = Callable[[int, str], None] | None
LogCallback = Callable[[str], None] | None
CancelCallback = Callable[[], bool] | None

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DRIVE_METADATA_SCOPE = "https://www.googleapis.com/auth/drive.metadata.readonly"
OAUTH_SCOPES = [SHEETS_SCOPE, DRIVE_METADATA_SCOPE]
OAUTH_SCOPE_VERSION = 1


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
    _check_cancel(cancel_callback)
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
        _log(log_callback, "Đã sử dụng phiên đăng nhập Google đã lưu.")
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
        client.set_timeout(30)
    return client


def _check_editor_permission(
    credentials: Credentials,
    spreadsheet_id: str,
    *,
    cancel_callback: CancelCallback = None,
) -> str:
    _check_cancel(cancel_callback)
    session = AuthorizedSession(credentials)
    response = session.get(
        f"https://www.googleapis.com/drive/v3/files/{spreadsheet_id}",
        params={
            "fields": "id,name,mimeType,trashed,capabilities(canEdit)",
            "supportsAllDrives": "true",
        },
        timeout=30,
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
    _progress(progress_callback, 40, "Đang kiểm tra quyền Editor")
    name = _check_editor_permission(
        credentials,
        spreadsheet_id,
        cancel_callback=cancel_callback,
    )
    _check_cancel(cancel_callback)
    client = _authorize(credentials)
    spreadsheet = client.open_by_key(spreadsheet_id)
    _progress(progress_callback, 100, f"Đã kết nối: {name}")
    _log(log_callback, f"Đã xác nhận quyền Editor với '{name}'.")
    return SheetConnection(
        credentials=credentials,
        client=client,
        spreadsheet=spreadsheet,
        spreadsheet_id=spreadsheet_id,
        spreadsheet_name=name,
    )


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


def _build_translate_data_copy_request(
    sheet_id: int,
    last_row: int,
) -> dict[str, object]:
    """Build one Sheets copyPaste request for D2:I2 -> D2:I<last_row>."""
    return {
        "copyPaste": {
            "source": {
                "sheetId": int(sheet_id),
                "startRowIndex": 1,
                "endRowIndex": 2,
                "startColumnIndex": 3,
                "endColumnIndex": 9,
            },
            "destination": {
                "sheetId": int(sheet_id),
                "startRowIndex": 1,
                "endRowIndex": int(last_row),
                "startColumnIndex": 3,
                "endColumnIndex": 9,
            },
            "pasteType": "PASTE_NORMAL",
            "pasteOrientation": "NORMAL",
        }
    }


def fill_translate_data_columns(
    connection: SheetConnection,
    *,
    sheet_name: str = "Translate_Data",
    progress_callback: ProgressCallback = None,
    cancel_callback: CancelCallback = None,
) -> tuple[bool, str, int]:
    """Fill D2:I2 down to the last populated row of A:C in Translate_Data.

    Missing tabs, an empty sample row, or a sheet without rows below row 2 are
    treated as non-fatal skips so the CSV import itself can still complete.
    """
    _check_cancel(cancel_callback)
    _progress(progress_callback, 10, "Đang kiểm tra tab Translate_Data")

    worksheets = connection.spreadsheet.worksheets()
    worksheet = next(
        (item for item in worksheets if item.title.casefold() == sheet_name.casefold()),
        None,
    )
    if worksheet is None:
        return (
            False,
            f"Không tìm thấy tab '{sheet_name}', đã bỏ qua bước fill D2:I2.",
            0,
        )

    _check_cancel(cancel_callback)
    session = AuthorizedSession(connection.credentials)
    spreadsheet_base = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{connection.spreadsheet_id}"
    )
    quoted_title = _quote_sheet_title(worksheet.title)
    response = session.get(
        f"{spreadsheet_base}/values:batchGet",
        params=[
            ("ranges", f"{quoted_title}!A:C"),
            ("ranges", f"{quoted_title}!D2:I2"),
            ("majorDimension", "ROWS"),
            ("valueRenderOption", "FORMULA"),
        ],
        timeout=GOOGLE_REQUEST_TIMEOUT_SECONDS,
    )
    _raise_for_response(response, "Đọc dữ liệu Translate_Data")
    _check_cancel(cancel_callback)

    value_ranges = response.json().get("valueRanges", [])
    data_values = (
        value_ranges[0].get("values", [])
        if len(value_ranges) >= 1
        else []
    )
    sample_values = (
        value_ranges[1].get("values", [])
        if len(value_ranges) >= 2
        else []
    )

    last_row = _last_populated_row(data_values)
    has_sample = any(
        str(value).strip()
        for row in sample_values
        for value in row
        if value is not None
    )
    if not has_sample:
        return (
            False,
            f"Vùng {sheet_name}!D2:I2 đang trống, đã bỏ qua bước fill.",
            last_row,
        )
    if last_row <= 2:
        return (
            False,
            f"Tab '{sheet_name}' chưa có dữ liệu dưới hàng 2 nên không cần fill.",
            last_row,
        )

    _progress(
        progress_callback,
        55,
        f"Đang sao chép D2:I2 xuống hàng {last_row}",
    )
    response = session.post(
        f"{spreadsheet_base}:batchUpdate",
        json={
            "requests": [
                _build_translate_data_copy_request(worksheet.id, last_row)
            ]
        },
        timeout=GOOGLE_REQUEST_TIMEOUT_SECONDS,
    )
    _raise_for_response(response, "Fill Translate_Data")
    _check_cancel(cancel_callback)
    _progress(progress_callback, 100, "Đã fill xong Translate_Data")

    added_rows = max(0, last_row - 2)
    return (
        True,
        f"Đã sao chép {sheet_name}!D2:I2 xuống đến hàng {last_row} "
        f"({added_rows} hàng được fill thêm).",
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
    """Replace one or many tabs using a small number of Sheets API requests.

    Compared with the previous implementation this function:
    - lists worksheets only once;
    - creates/resizes/freezes all tabs in one ``batchUpdate`` request;
    - clears all existing target tabs in one ``batchClear`` request;
    - writes many tabs with ``values:batchUpdate`` instead of one request per
      750 rows and per worksheet.
    """
    if not uploads:
        return 0

    try:
        _check_cancel(cancel_callback)
        _progress(progress_callback, 2, "Đang chuẩn bị dữ liệu Google Sheets")

        # Validate target uniqueness before making any destructive request.
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
        worksheets = connection.spreadsheet.worksheets()
        worksheet_map = {item.title.casefold(): item for item in worksheets}
        session = AuthorizedSession(connection.credentials)
        spreadsheet_base = (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{connection.spreadsheet_id}"
        )

        sheet_requests: list[dict[str, object]] = []
        clear_ranges: list[str] = []
        for bundle, job, values in prepared:
            required_rows = max(1, len(values))
            required_cols = max(
                1,
                max((len(row) for row in values), default=bundle.column_count or 1),
            )
            existing = worksheet_map.get(job.sheet_name.casefold())
            frozen_rows = 1 if bundle.header else 0
            if existing is None:
                sheet_requests.append(
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
            else:
                clear_ranges.append(_quote_sheet_title(job.sheet_name))
                row_count = max(existing.row_count, required_rows)
                column_count = max(existing.col_count, required_cols)
                if (
                    row_count != existing.row_count
                    or column_count != existing.col_count
                    or frozen_rows != 0
                ):
                    sheet_requests.append(
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": existing.id,
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

        if sheet_requests:
            _check_cancel(cancel_callback)
            _progress(progress_callback, 10, "Đang tạo và chuẩn bị các tab đích")
            response = session.post(
                f"{spreadsheet_base}:batchUpdate",
                json={"requests": sheet_requests},
                timeout=GOOGLE_REQUEST_TIMEOUT_SECONDS,
            )
            _raise_for_response(response, "Chuẩn bị tab")

        if clear_ranges:
            _check_cancel(cancel_callback)
            _progress(progress_callback, 20, "Đang xóa dữ liệu cũ của các tab")
            response = session.post(
                f"{spreadsheet_base}/values:batchClear",
                json={"ranges": clear_ranges},
                timeout=GOOGLE_REQUEST_TIMEOUT_SECONDS,
            )
            _raise_for_response(response, "Xóa dữ liệu cũ")

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
            response = session.post(
                f"{spreadsheet_base}/values:batchUpdate",
                json={
                    "valueInputOption": option,
                    "includeValuesInResponse": False,
                    "data": group,
                },
                timeout=GOOGLE_REQUEST_TIMEOUT_SECONDS,
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

        for bundle, job, _values in prepared:
            _log(
                log_callback,
                f"Đã nhập {bundle.row_count} dòng vào tab '{job.sheet_name}'.",
            )
        _log(
            log_callback,
            f"Tối ưu API hoàn tất: {len(prepared)} tab, "
            f"{total_data_rows} dòng dữ liệu.",
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

