from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORMS = ROOT / "src" / "import_localize" / "ui" / "forms"

REQUIRED = {
    "main_window.ui": {
        "logoLabel",
        "filesCard",
        "filesIconLabel",
        "fileTable",
        "moveUpButton",
        "moveDownButton",
        "targetCard",
        "targetIconLabel",
        "sheetUrlEdit",
        "targetModeCombo",
        "singleSheetNameEdit",
        "valueInputCombo",
        "actionCard",
        "startButton",
        "stopButton",
        "progressBar",
        "logCard",
        "logPlaceholder",
        "settingsButton",
    },
    "settings_dialog.ui": {
        "dialogCard",
        "dialogIconLabel",
        "oauthClientPathEdit",
        "chooseOauthButton",
        "loginGoogleButton",
        "logoutGoogleButton",
        "settingsTabs",
        "updateRepositoryEdit",
        "autoCheckUpdatesCheckBox",
        "checkUpdateButton",
        "installUpdateButton",
        "updateProgressBar",
        "releaseNotesEdit",
        "closeIconButton",
    },
    "help_dialog.ui": {
        "dialogCard",
        "dialogIconLabel",
        "helpTextBrowser",
        "closeButton",
        "closeIconButton",
    },
}


def main() -> int:
    failed = False
    for filename, required_names in REQUIRED.items():
        path = FORMS / filename
        try:
            tree = ET.parse(path)
        except (OSError, ET.ParseError) as exc:
            print(f"[FAIL] {filename}: {exc}")
            failed = True
            continue
        names = {
            element.attrib.get("name", "")
            for element in tree.iter()
            if element.tag in {"widget", "layout", "spacer"}
        }
        missing = sorted(required_names - names)
        if missing:
            print(f"[FAIL] {filename}: thiếu {', '.join(missing)}")
            failed = True
        else:
            print(f"[OK] {filename}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
