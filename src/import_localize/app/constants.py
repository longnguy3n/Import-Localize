from __future__ import annotations

APP_NAME = "Import Localize"
APP_ID = "import-localize"
ORGANIZATION_NAME = "Import Localize"
APP_VERSION = "1.8.1"

DEFAULT_WINDOW_WIDTH = 760
DEFAULT_WINDOW_HEIGHT = 950
MIN_WINDOW_WIDTH = 660
MIN_WINDOW_HEIGHT = 780

MAX_CSV_FILES = 200
# Legacy fallback for older upload code. The fast uploader uses dynamic chunks.
UPLOAD_BATCH_SIZE = 5000
UPLOAD_MAX_ROWS_PER_RANGE = 2500
UPLOAD_MAX_CELLS_PER_RANGE = 60000
UPLOAD_MAX_REQUEST_BYTES = 3_000_000
# Các request Google được giữ nhỏ để nút Dừng không phải chờ socket quá lâu.
# Khi worker truyền cancel_callback, read-timeout thực tế bị giới hạn bởi
# GOOGLE_CANCELLABLE_READ_TIMEOUT_SECONDS.
GOOGLE_REQUEST_TIMEOUT_SECONDS = 120
GOOGLE_CONNECT_TIMEOUT_SECONDS = 3.0
GOOGLE_CANCELLABLE_READ_TIMEOUT_SECONDS = 6.0
GOOGLE_CANCEL_POLL_SECONDS = 0.05
GOOGLE_REQUEST_RETRY_ATTEMPTS = 6
GOOGLE_REQUEST_RETRY_BASE_DELAY_SECONDS = 0.4
# Fill trên sheet nặng dùng timeout riêng dài hơn. Request được chạy trong
# background daemon thread nên nút Dừng vẫn phản hồi ngay mà không cần ép
# socket timeout xuống 6 giây như các request thông thường.
FILL_REQUEST_CONNECT_TIMEOUT_SECONDS = 5.0
FILL_REQUEST_READ_TIMEOUT_SECONDS = 180.0
FILL_VERIFY_READ_TIMEOUT_SECONDS = 20.0
FILL_VERIFY_ATTEMPTS = 5
FILL_VERIFY_POLL_SECONDS = 0.6
GOOGLE_STRUCTURE_BATCH_SIZE = 10
GOOGLE_CLEAR_BATCH_SIZE = 25

EXPORT_SHEET_PREFIX = "export_"
CSV_EXPORT_REQUEST_TIMEOUT_SECONDS = 12
GOOGLE_CONNECTION_CACHE_TTL_SECONDS = 900
GOOGLE_WORKSHEET_CACHE_TTL_SECONDS = 120
MAX_PARALLEL_EXPORT_DOWNLOADS = 4

# Auto-update uses the latest GitHub Release of this repository. During build,
# build_app.py can replace this value through --github-repo owner/repository.
DEFAULT_GITHUB_REPOSITORY = ""
UPDATE_REQUEST_TIMEOUT_SECONDS = 30
UPDATE_DOWNLOAD_CHUNK_BYTES = 1024 * 256
UPDATE_ASSET_PREFIX = "Import_Localize_v"
