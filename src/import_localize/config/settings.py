from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from import_localize.app.paths import CONFIG_FILE


@dataclass(slots=True)
class AppSettings:
    sheet_url: str = ""
    sheet_name: str = ""
    target_mode: str = "multiple"
    import_mode: str = "overwrite"
    value_input_option: str = "RAW"
    first_row_is_header: bool = True
    strict_headers: bool = True
    add_source_column: bool = False
    theme: str = "light"
    last_csv_dir: str = ""
    window_width: int = 720
    window_height: int = 900
    update_repository: str = ""
    auto_check_updates: bool = True


class SettingsRepository:
    def __init__(self, path: Path = CONFIG_FILE):
        self.path = path

    def load(self) -> AppSettings:
        if not self.path.is_file():
            return AppSettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = AppSettings.__dataclass_fields__.keys()
            values = {key: payload[key] for key in allowed if key in payload}
            return AppSettings(**values)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.path)
