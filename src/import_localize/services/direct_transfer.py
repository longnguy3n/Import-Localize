"""Snapshot a direct Unity/Sheet transfer, then apply exactly the reviewed rows."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from import_localize.models.import_job import CsvBundle, ImportJob
from import_localize.services import google_service as sheets
from import_localize.services.csv_service import bundle_from_asset_rows, validate_worksheet_title
from import_localize.services.unity_locale_service import (
    LocalePlan, UnityLocaleError, apply_plan, export_rows, import_change,
    parse_locale_csv, read_asset,
)


@dataclass(frozen=True)
class TransferPair:
    asset_path: Path
    tab_name: str
    row_count: int
    summary: str
    tab_id: int | None


@dataclass
class TransferPlan:
    direction: Literal["upload", "download"]
    spreadsheet_url: str
    spreadsheet_name: str
    pairs: list[TransferPair] = field(default_factory=list)
    uploads: list[tuple[CsvBundle, ImportJob]] = field(default_factory=list, repr=False)
    files: LocalePlan = field(default_factory=lambda: LocalePlan([], {}), repr=False)


def _code_key(code: str) -> str:
    return code.casefold().replace("_", "-")


def _tab_lookup(connection, prefix):
    matches = {}
    for tab in sheets._get_worksheets(connection, force=True):
        if tab.title.casefold().startswith(prefix):
            key = _code_key(tab.title[len(prefix):])
            matches.setdefault(key, []).append(tab)
    return matches


def prepare_transfer(direction, spreadsheet_url: str, asset_paths: list[Path], *,
                     value_input_option="RAW", progress_callback=None,
                     cancel_callback=None, annotations=None) -> TransferPlan:
    if direction not in ("upload", "download"):
        raise ValueError("Chiều chuyển không hợp lệ.")
    if not asset_paths:
        raise UnityLocaleError("Chọn ít nhất một file locale*.asset.")
    sheets._check_cancel(cancel_callback)
    sheets._progress(progress_callback, 0, "Đang kết nối Google Sheets…")
    connection = sheets.connect_to_spreadsheet(spreadsheet_url, cancel_callback=cancel_callback)
    plan = TransferPlan(direction, spreadsheet_url, connection.spreadsheet_name)
    prefix = "upload_" if direction == "upload" else "export_"
    tabs = _tab_lookup(connection, prefix)
    seen = set()
    for i, path in enumerate(asset_paths, 1):
        sheets._check_cancel(cancel_callback)
        asset = read_asset(Path(path))
        if len(asset.languages) != 1:
            raise UnityLocaleError(f"{asset.path.name} có nhiều ngôn ngữ. Dùng chế độ CSV để ghép file này.")
        code = asset.languages[0]["Code"]
        if not re.fullmatch(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", code):
            raise UnityLocaleError(f"{asset.path.name}: mã ngôn ngữ không hợp lệ: {code!r}.")
        key = _code_key(code)
        if key in seen:
            raise UnityLocaleError(f"Nhiều asset có cùng mã {code}. Chỉ chọn một asset cho mỗi ngôn ngữ.")
        seen.add(key)
        matches = tabs.get(key, [])
        if len(matches) > 1:
            raise UnityLocaleError(f"Nhiều tab {prefix} có cùng mã {code}: " + ", ".join(t.title for t in matches))
        tab = matches[0] if matches else None
        name = tab.title if tab else validate_worksheet_title(prefix + code)
        if direction == "upload":
            job = ImportJob((str(asset.path),), spreadsheet_url, sheet_name=name,
                            value_input_option=value_input_option)
            rows = export_rows(asset, annotations=annotations)
            bundle = bundle_from_asset_rows(job, asset.path, rows, cancel_callback=cancel_callback)
            if not bundle.row_count:
                raise UnityLocaleError(f"{asset.path.name} không có dòng dữ liệu để ghi lên {name}.")
            plan.uploads.append((bundle, job))
            plan.files.sources[asset.path] = asset.original
            count = bundle.row_count
            action = "Ghi đè tab" if tab else "Tạo tab"
            summary = f"{action} {name} · {count} dòng"
            removed = len(rows) - 1 - count
            if removed:
                summary += f" · bỏ {removed} dòng trùng key"
        else:
            if tab is None:
                raise UnityLocaleError(f"{asset.path.name}: không tìm thấy tab {name} trong {connection.spreadsheet_name}.")
            payload = sheets.read_worksheet_csv(connection, tab, cancel_callback=cancel_callback)
            rows = parse_locale_csv(payload, name, ",")
            change = import_change(asset, rows)
            plan.files.changes.append(change)
            count = len(rows) - 1
            summary = "\n".join((change.summary, *change.warnings))
        plan.pairs.append(TransferPair(asset.path, name, count, summary, tab.id if tab else None))
        sheets._progress(progress_callback, i * 100 // len(asset_paths), f"Đã xem trước {name}")
    sheets._check_cancel(cancel_callback)
    return plan


def apply_transfer(plan: TransferPlan, backup_root: Path, *, progress_callback=None, cancel_callback=None):
    sheets._check_cancel(cancel_callback)
    if not plan.pairs:
        raise UnityLocaleError("Chưa có dữ liệu xem trước.")
    if plan.direction == "download":
        def progress(completed, total, message):
            sheets._progress(progress_callback, completed * 100 // total, message)
        # apply_plan validates the local targets, stages backups and owns rollback.
        return apply_plan(plan.files, backup_root, progress=progress)

    for path, raw in plan.files.sources.items():
        sheets._check_cancel(cancel_callback)
        if not path.is_file() or path.read_bytes() != raw:
            raise UnityLocaleError(f"{path.name} đã thay đổi. Hãy xem trước lại.")
    sheets._progress(progress_callback, 0, "Đang kiểm tra lại tab đích…")
    connection = sheets.connect_to_spreadsheet(plan.spreadsheet_url, cancel_callback=cancel_callback)
    tabs = _tab_lookup(connection, "upload_")
    for pair in plan.pairs:
        matches = tabs.get(_code_key(pair.tab_name[len("upload_"):]), [])
        if pair.tab_id is None and not matches:
            continue
        if len(matches) != 1 or (matches[0].id, matches[0].title) != (pair.tab_id, pair.tab_name):
            raise UnityLocaleError(f"Tab {pair.tab_name} đã thay đổi. Hãy xem trước lại.")
    write_started = False

    def upload_progress(percent, message):
        nonlocal write_started
        # upload_bundles_fast starts add/resize requests after preparing all values.
        write_started |= percent >= 8
        sheets._progress(progress_callback, percent, message)

    try:
        sheets.upload_bundles_fast(connection, plan.uploads, progress_callback=upload_progress,
                                   cancel_callback=cancel_callback)
    except Exception as exc:
        if not write_started:
            raise
        names = ", ".join(pair.tab_name for pair in plan.pairs)
        raise sheets.GoogleServiceError(
            f"{exc}\nMột phần thay đổi có thể đã được ghi. Kiểm tra các tab {names} trước khi chạy lại."
        ) from exc
    return None
