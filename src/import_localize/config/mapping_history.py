"""Last observed per-key Sheet status, isolated by spreadsheet ID."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import asdict

from import_localize.app.paths import USER_CONFIG_DIR

COMPLETE_STATES = {"written", "already"}
STATES = COMPLETE_STATES | {"pending", "partial", "uncertain", "missing"}


def sheet_identity(url: str) -> str:
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url or "")
    return match.group(1) if match else ""


class MappingHistoryRepository:
    def __init__(self, path: Path | None = None):
        self.path = path or USER_CONFIG_DIR / "mapping_mark_history.json"

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                return {}
            result = {}
            for sheet, records in data.get("sheets", {}).items():
                if not isinstance(records, dict):
                    continue
                result[sheet] = {key: record for key, record in records.items()
                    if isinstance(record, dict) and record.get("status") in STATES
                    and isinstance(record.get("checked_at"), str)
                    and all(type(record.get(name)) is int and record[name] >= 0
                            for name in ("confirmed_rows", "total_rows", "updated_rows", "uncertain_rows"))}
            return result
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def save(self, sheets: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "sheets": sheets},
                             ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def result_records(result) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {item.key: {**asdict(item), "checked_at": timestamp} for item in result.key_results}
