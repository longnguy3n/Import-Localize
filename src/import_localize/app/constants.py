from __future__ import annotations

APP_NAME = "Import Localize"
APP_ID = "import-localize"
ORGANIZATION_NAME = "Import Localize"
APP_VERSION = "1.1.3"

DEFAULT_WINDOW_WIDTH = 760
DEFAULT_WINDOW_HEIGHT = 950
MIN_WINDOW_WIDTH = 660
MIN_WINDOW_HEIGHT = 780

MAX_CSV_FILES = 200
# Legacy fallback for older upload code. The fast uploader uses dynamic chunks.
UPLOAD_BATCH_SIZE = 5000
UPLOAD_MAX_ROWS_PER_RANGE = 5000
UPLOAD_MAX_CELLS_PER_RANGE = 120000
UPLOAD_MAX_REQUEST_BYTES = 7_000_000
GOOGLE_REQUEST_TIMEOUT_SECONDS = 60

# Auto-update uses the latest GitHub Release of this repository. During build,
# build_app.py can replace this value through --github-repo owner/repository.
DEFAULT_GITHUB_REPOSITORY = ""
UPDATE_REQUEST_TIMEOUT_SECONDS = 30
UPDATE_DOWNLOAD_CHUNK_BYTES = 1024 * 256
UPDATE_ASSET_PREFIX = "Import_Localize_v"
