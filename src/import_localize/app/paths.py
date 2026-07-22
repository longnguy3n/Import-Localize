from __future__ import annotations

import os
import sys
from pathlib import Path

# The paths below work in both source mode and PyInstaller one-folder builds.
PACKAGE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_DIR.parent
PROJECT_DIR = SRC_DIR.parent

FORMS_DIR = PACKAGE_DIR / "ui" / "forms"
THEMES_DIR = SRC_DIR / "themes"
ASSETS_DIR = SRC_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
IMAGES_DIR = ASSETS_DIR / "images"

# Canonical application artwork paths.
APP_LOGO_SVG = IMAGES_DIR / "import_localize_logo.svg"
APP_LOGO_PNG = IMAGES_DIR / "import_localize_logo.png"
APP_ICON_ICO = IMAGES_DIR / "import_localize_logo.ico"

# Backward-compatible aliases for earlier UI/bootstrap revisions.
APP_LOGO = APP_LOGO_SVG
APP_ICON = APP_ICON_ICO


def application_dir() -> Path:
    """Directory containing the executable or the source project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_DIR


def user_config_dir() -> Path:
    """Return and create the per-user configuration directory."""
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA")
        path = (
            Path(base) / "Import Localize"
            if base
            else Path.home() / "AppData" / "Roaming" / "Import Localize"
        )
    elif sys.platform == "darwin":
        path = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Import Localize"
        )
    else:
        xdg = os.getenv("XDG_CONFIG_HOME", "").strip()
        path = (
            Path(xdg) / "import-localize"
            if xdg
            else Path.home() / ".config" / "import-localize"
        )

    path.mkdir(parents=True, exist_ok=True)
    return path


USER_CONFIG_DIR = user_config_dir()
CONFIG_FILE = USER_CONFIG_DIR / "config.json"
OAUTH_CLIENT_FILE = USER_CONFIG_DIR / "oauth_client.json"
OAUTH_TOKEN_FILE = USER_CONFIG_DIR / "google_oauth_token.json"

# Auto-update files are kept outside the installation directory so an update
# can replace the complete PyInstaller onedir folder safely.
UPDATE_CACHE_DIR = USER_CONFIG_DIR / "updates"
