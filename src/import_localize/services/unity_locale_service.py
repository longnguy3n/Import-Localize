"""Offline I2 LanguageSourceAsset Replace Import/Export for Dicegeon.

Only mTerms and mLanguages are replaced; Unity's envelope and other fields stay
byte-identical. CSV translations deliberately do NOT use csv_service._clean_row.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml


class UnityLocaleError(ValueError):
    pass


# Dicegeon's I2 enum with TextMeshPro enabled (no NGUI/TK2D/SVG).
TERM_TYPES = ("Text", "Font", "Texture", "AudioClip", "GameObject", "Sprite",
              "Material", "Child", "Mesh", "TextMeshPFont", "Object", "Video")
DEFAULT_CODES = {"English": "en", "Vietnamese": "vi", "Portuguese": "pt",
                 "Portuguese/Brazil": "pt-BR"}
FALLBACKS = {"XBox": "Controller", "PS4": "Controller", "OculusVR": "VR",
             "ViveVR": "VR", "GearVR": "VR", "Android": "Touch", "IOS": "Touch"}
FIELD = re.compile(r"^    ([A-Za-z_]\w*):[^\r\n]*(?:\r?\n|$)", re.MULTILINE)
SPECIAL = re.compile(r"\[i2s_([^\]]+)\]")


@dataclass
class LocaleAsset:
    path: Path
    original: bytes
    text: str
    spans: dict[str, tuple[int, int]]
    terms: list[dict]
    languages: list[dict]
    sort_rows: bool
    specialization_rows: bool


@dataclass
class ChangeStats:
    source_count: int
    before_count: int | None
    after_count: int
    added: int | None
    removed: int | None
    updated: int | None
    unchanged: int | None
    source_unit: str
    target_unit: str
    duplicate_before: int = 0


@dataclass
class FileChange:
    path: Path
    before: bytes | None
    after: bytes
    summary: str
    warnings: tuple[str, ...] = ()
    source_path: Path | None = None
    stats: ChangeStats | None = None


@dataclass
class LocalePlan:
    changes: list[FileChange]
    sources: dict[Path, bytes]


def read_asset(path: Path) -> LocaleAsset:
    path = Path(path).resolve()
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        if text.count("\n--- ") != 1 or "\n  mSource:\n" not in text.replace("\r\n", "\n"):
            raise UnityLocaleError("Cần một LanguageSourceAsset Unity dạng YAML text.")
        matches = list(FIELD.finditer(text))
        spans = {m[1]: (m.start(), matches[i + 1].start() if i + 1 < len(matches) else len(text))
                 for i, m in enumerate(matches)}
        if len(spans) != len(matches) or not {"mTerms", "mLanguages"} <= spans.keys():
            raise UnityLocaleError("Không tìm thấy mTerms/mLanguages hợp lệ.")
        def section(name):
            start, end = spans[name]
            # BaseLoader preserves strings like 0, 001, yes, null and byte flags 00.
            return yaml.load(text[start:end], Loader=getattr(yaml, "CBaseLoader", yaml.BaseLoader))[name]
        terms, languages = section("mTerms"), section("mLanguages")
        if not isinstance(terms, list) or not isinstance(languages, list) or not languages:
            raise UnityLocaleError("Asset thiếu danh sách term hoặc ngôn ngữ.")
        for language in languages:
            if not isinstance(language, dict) or not language.get("Name") or not language.get("Code"):
                raise UnityLocaleError("Ngôn ngữ phải có Name và Code.")
            int(language.get("Flags", "0"))
        codes = [x["Code"].casefold() for x in languages]
        if len(set(codes)) != len(codes):
            raise UnityLocaleError("Asset có mã ngôn ngữ trùng nhau.")
        for term in terms:
            if (not isinstance(term, dict) or not isinstance(term.get("Term"), str)
                    or not isinstance(term.get("Languages"), list)
                    or len(term["Languages"]) != len(languages)
                    or any(not isinstance(v, str) for v in term["Languages"])):
                raise UnityLocaleError("Term có cấu trúc hoặc số lượng bản dịch không hợp lệ.")
            if not 0 <= int(term.get("TermType", "0")) < len(TERM_TYPES):
                raise UnityLocaleError("TermType không thuộc cấu hình I2 của Dicegeon.")
            touch = term.get("Languages_Touch", [])
            if isinstance(touch, list):
                for index, value in enumerate(touch[:len(languages)]):
                    if not term["Languages"][index] and value:
                        term["Languages"][index] = value
        return LocaleAsset(path, raw, text, spans, terms, languages,
                           section("Spreadsheet_SortRows") != "0" if "Spreadsheet_SortRows" in spans else True,
                           section("Spreadsheet_SpecializationAsRows") != "0" if "Spreadsheet_SpecializationAsRows" in spans else True)
    except (UnicodeError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        raise UnityLocaleError(f"{path.name}: {exc}") from exc


def _specializations(text: str) -> dict[str, str]:
    matches = list(SPECIAL.finditer(text))
    values = {"Any": text[:matches[0].start()] if matches else text}
    for i, match in enumerate(matches):
        values[match[1]] = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
    return values


def _set_translation(text: str, value: str, specialization: str) -> str:
    parts = _specializations(text)
    parts[specialization] = value
    return parts.get("Any", "") + "".join(f"[i2s_{k}]{v}" for k, v in parts.items() if k != "Any" and v)


def _get_translation(text: str, specialization: str) -> str:
    parts = _specializations(text)
    while specialization not in parts and specialization != "Any":
        specialization = FALLBACKS.get(specialization, "Any")
    return parts.get(specialization, "").replace("[i2nt]", "").replace("[/i2nt]", "")


def _valid_key(key: str) -> str:
    key = key.replace("\\", "/").strip()
    if key.startswith("Default/"):
        key = key[8:]
    result, tag, skipped = [], "", False
    for index, char in enumerate(key):
        if not tag and char in "{[<" and not (char == "{" and index + 1 < len(key) and key[index + 1] != "["):
            tag = {"{": "}", "[": "]", "<": ">"}[char]
            continue
        if tag:
            if char == tag:
                tag = ""
            continue
        if char.isspace():
            if result and not skipped:
                result.append(" ")
            skipped = True
        else:
            skipped = False
            result.append(char if char.isalnum() or char in ".-_$#@*()[]{}+:?!&',^=<>~`\\\"/" else " ")
    return "".join(result)


def _read_csv(path: Path, delimiter: str) -> tuple[bytes, list[list[str]]]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        if delimiter == "auto":
            # Headers are small and never contain translation punctuation/newlines.
            delimiter = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t").delimiter
        if delimiter not in (",", ";", "\t"):
            raise UnityLocaleError("Dấu phân cách phải là dấu phẩy, chấm phẩy hoặc tab.")
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
        rows = [row for row in rows if any(row)]
        if not rows or len(rows[0]) < 2 or rows[0][0].casefold() != "key":
            raise UnityLocaleError("CSV phải có cột đầu là Key và ít nhất một ngôn ngữ.")
        return raw, rows
    except (UnicodeError, csv.Error, IndexError) as exc:
        raise UnityLocaleError(f"{path.name}: CSV UTF-8 không hợp lệ: {exc}") from exc


def _columns(header: list[str], asset: LocaleAsset) -> tuple[dict, list[tuple[int, dict]]]:
    metadata, start = {}, 1
    for i in (1, 2):
        if i < len(header) - 1 and header[i].casefold() in ("type", "desc", "description"):
            key = "type" if header[i].casefold() == "type" else "desc"
            if key in metadata:
                raise UnityLocaleError("Cột metadata bị trùng.")
            metadata[key] = i
            start = i + 1
    languages = []
    for i in range(start, len(header)):
        token = header[i]
        if not token:
            continue
        disabled = token.startswith("$")
        token = token.removeprefix("$")
        match = re.fullmatch(r"(.+?)\s*\[([^\]]+)\]", token)
        name, code = (match[1].strip(), match[2]) if match else (token, "")
        candidates = [x for x in asset.languages if (x["Code"].casefold() == code.casefold() if code else x["Name"] == name)]
        if len(candidates) != 1:
            raise UnityLocaleError(f"Ngôn ngữ '{token}' không khớp {asset.path.name}.")
        languages.append((i, {"Name": name, "Code": candidates[0]["Code"], "Flags": int(disabled)}))
    codes = [x[1]["Code"].casefold() for x in languages]
    if len(codes) != len(set(codes)) or set(codes) != {x["Code"].casefold() for x in asset.languages}:
        raise UnityLocaleError(f"CSV phải chứa đúng bộ ngôn ngữ của {asset.path.name}, không trùng cột.")
    return metadata, languages


def _render_section(name: str, items: list[dict], newline: str) -> str:
    lines = [f"    {name}:"] if items else [f"    {name}: []"]
    def quote(value):
        # YAML treats NEL/Unicode line separators as line breaks even inside quotes.
        encoded = json.dumps(str(value), ensure_ascii=False)
        return re.sub(r"[\x7f-\x9f\u2028\u2029]", lambda m: f"\\u{ord(m[0]):04x}", encoded)
    for item in items:
        for index, (key, value) in enumerate(item.items()):
            prefix = "    - " if index == 0 else "      "
            if isinstance(value, list):
                lines.append(f"{prefix}{key}:" + (" []" if not value else ""))
                lines.extend(f"      - {quote(v)}" for v in value)
            elif key in ("TermType", "Flags"):
                lines.append(f"{prefix}{key}: {value}")
            else:
                lines.append(f"{prefix}{key}: {quote(value)}")
    return newline.join(lines) + newline


def import_change(asset: LocaleAsset, rows: list[list[str]]) -> FileChange:
    metadata, columns = _columns(rows[0], asset)
    terms, repeated, normalized = {}, 0, 0
    for number, row in enumerate(rows[1:], 2):
        if len(row) != len(rows[0]):
            raise UnityLocaleError(f"Dòng CSV {number}: có {len(row)} cột, cần {len(rows[0])}.")
        key, specialization = row[0], "Any"
        match = re.fullmatch(r"(.+)\[([^\]]*)\]", key)
        if match:
            key, specialization = match[1], match[2] or "Any"
            if specialization == "touch":
                specialization = "Touch"
        valid_key = _valid_key(key)
        normalized += valid_key != key
        if not valid_key:
            continue
        if valid_key in terms:
            repeated += 1
        term = terms.setdefault(valid_key, {"Term": valid_key, "TermType": 0, "Description": "",
                                            "Languages": [""] * len(columns), "Flags": "00" * len(columns),
                                            "Languages_Touch": []})
        if "type" in metadata:
            # I2 GetTermType searches through Object (Video falls back to Text).
            value = row[metadata["type"]].casefold()
            term["TermType"] = next((i for i, t in enumerate(TERM_TYPES[:-1]) if t.casefold() == value), 0)
        if "desc" in metadata:
            term["Description"] = row[metadata["desc"]]
        for index, (column, _) in enumerate(columns):
            value = row[column]
            if value:
                term["Languages"][index] = _set_translation(term["Languages"][index], "" if value == "-" else value, specialization)
    if not terms:
        raise UnityLocaleError("CSV không có term hợp lệ; không cho phép xóa trắng asset.")
    newline = "\r\n" if "\r\n" in asset.text else "\n"
    text = asset.text
    sections = {"mTerms": list(terms.values()), "mLanguages": [x[1] for x in columns]}
    for name in sorted(sections, key=lambda n: asset.spans[n][0], reverse=True):
        start, end = asset.spans[name]
        text = text[:start] + _render_section(name, sections[name], newline) + text[end:]
    after = (b"\xef\xbb\xbf" if asset.original.startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8")
    old_keys, new_keys = {t["Term"] for t in asset.terms}, set(terms)
    warnings = []
    if repeated:
        warnings.append(f"{repeated} dòng cùng key (kể cả specialization): gộp như I2, ô không rỗng sau cùng thắng; '-' xóa bản dịch.")
    if normalized:
        warnings.append(f"{normalized} key được chuẩn hóa theo I2.")
    if len(asset.terms) != len(old_keys):
        warnings.append(f"Asset hiện có {len(asset.terms) - len(old_keys)} term trùng; Replace sẽ tạo danh sách key duy nhất.")
    def content(term, languages):
        translations = tuple(sorted((language["Code"].casefold(), value)
                                    for language, value in zip(languages, term["Languages"])))
        return int(term["TermType"]), term.get("Description") or "", translations
    new_languages = [column[1] for column in columns]
    changed_keys = {old["Term"] for old in asset.terms if old["Term"] in new_keys
                    and content(old, asset.languages) != content(terms[old["Term"]], new_languages)}
    stats = ChangeStats(len(rows) - 1, len(asset.terms), len(terms), len(new_keys - old_keys),
                        len(old_keys - new_keys), len(changed_keys), len(old_keys & new_keys) - len(changed_keys),
                        "dòng CSV", "term")
    stats.duplicate_before = len(asset.terms) - len(old_keys)
    summary = (f"{stats.source_count} dòng CSV → {stats.after_count} term; đích trước {stats.before_count}; "
               f"thêm {stats.added}, xóa {stats.removed}, sửa {stats.updated}, giữ {stats.unchanged}")
    return FileChange(asset.path, asset.original, after, summary, tuple(warnings), stats=stats)


def prepare_import(asset_paths: list[Path], csv_paths: list[Path], delimiter: str = "auto") -> LocalePlan:
    assets = [read_asset(p) for p in asset_paths]
    if not assets or not csv_paths:
        raise UnityLocaleError("Chọn asset và CSV trước khi xem trước.")
    sources, changes, used = {}, [], set()
    for path in csv_paths:
        path = Path(path).resolve()
        raw, rows = _read_csv(path, delimiter)
        candidates = []
        for asset in assets:
            try:
                _columns(rows[0], asset)
                candidates.append(asset)
            except UnityLocaleError:
                pass
        if len(candidates) != 1:
            raise UnityLocaleError(f"{path.name}: tìm thấy {len(candidates)} asset khớp ngôn ngữ. Chọn đúng một asset cho bộ ngôn ngữ trong CSV.")
        asset = candidates[0]
        if asset.path in used:
            raise UnityLocaleError(f"Có nhiều CSV cùng trỏ vào {asset.path.name}; chỉ chọn một CSV cho mỗi asset.")
        used.add(asset.path)
        sources[path] = raw
        change = import_change(asset, rows)
        change.source_path = path
        change.summary = f"{path.name} → {change.summary}"
        changes.append(change)
    if used != {a.path for a in assets}:
        raise UnityLocaleError("Một số asset đã chọn chưa có CSV tương ứng. Bỏ chọn chúng hoặc thêm CSV.")
    return LocalePlan(changes, sources)


def _validate_pairs(source_paths: list[Path], target_paths: list[Path], target_suffix: str) -> None:
    if not source_paths or len(source_paths) != len(target_paths):
        raise UnityLocaleError("Hai bên phải có cùng số file và ít nhất một cặp. Mỗi hàng là một cặp nguồn → đích.")
    targets = [Path(p).resolve() for p in target_paths]
    if len(set(targets)) != len(targets):
        raise UnityLocaleError("File nhận bị trùng ở nhiều hàng. Mỗi file đích chỉ được ghi một lần.")
    for index, path in enumerate(targets, 1):
        if path.suffix.casefold() != target_suffix:
            raise UnityLocaleError(f"Hàng {index}: file đích phải có đuôi {target_suffix}.")
        if not path.parent.is_dir():
            raise UnityLocaleError(f"Hàng {index}: thư mục đích không tồn tại: {path.parent}")


def prepare_import_pairs(csv_paths: list[Path], asset_paths: list[Path], delimiter: str = "auto") -> LocalePlan:
    """Use exactly the displayed row pairs; never silently rematch languages."""
    _validate_pairs(csv_paths, asset_paths, ".asset")
    changes, sources = [], {}
    for index, (csv_path, asset_path) in enumerate(zip(csv_paths, asset_paths), 1):
        path = Path(csv_path).resolve()
        try:
            raw, rows = _read_csv(path, delimiter)
            change = import_change(read_asset(asset_path), rows)
        except (OSError, ValueError) as exc:
            raise UnityLocaleError(f"Hàng {index}: {path.name} → {Path(asset_path).name}: {exc}") from exc
        sources[path] = raw
        change.source_path = path
        change.summary = f"{path.name} → {change.summary}"
        changes.append(change)
    return LocalePlan(changes, sources)


def prepare_export_pairs(asset_paths: list[Path], csv_paths: list[Path], delimiter: str = ",") -> LocalePlan:
    """Export each asset into the explicit CSV destination on the same row."""
    _validate_pairs(asset_paths, csv_paths, ".csv")
    changes, sources = [], {}
    for index, (asset_path, csv_path) in enumerate(zip(asset_paths, csv_paths), 1):
        target = Path(csv_path).resolve()
        try:
            asset = read_asset(asset_path)
            change = _export_change(asset, target, delimiter)
        except (OSError, ValueError) as exc:
            raise UnityLocaleError(f"Hàng {index}: {Path(asset_path).name} → {target.name}: {exc}") from exc
        sources[asset.path] = asset.original
        changes.append(change)
    return LocalePlan(changes, sources)


def export_csv(asset: LocaleAsset, delimiter: str = ",") -> bytes:
    if delimiter not in (",", ";", "\t"):
        raise UnityLocaleError("Dấu phân cách CSV không hợp lệ.")
    headers = []
    for language in asset.languages:
        name, code = language["Name"], language["Code"]
        token = name if DEFAULT_CODES.get(name, "").casefold() == code.casefold() else f"{name} [{code}]"
        headers.append(("$" if int(language.get("Flags", 0)) & 1 else "") + token)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    writer.writerow(["Key", "Type", "Desc", *headers])
    terms = sorted(asset.terms, key=lambda t: t["Term"].encode("utf-16-be")) if asset.sort_rows else asset.terms
    for term in terms:
        specializations = dict.fromkeys(s for text in term["Languages"] for s in _specializations(text)) if asset.specialization_rows else {None: None}
        for specialization in specializations:
            key = term["Term"] + (f"[{specialization}]" if specialization not in (None, "Any") else "")
            values = [_get_translation(t, specialization) if specialization else t for t in term["Languages"]]
            row = [key, TERM_TYPES[int(term.get("TermType", 0))], term.get("Description", ""), *values]
            writer.writerow([v.replace("\\n", "\n") for v in row])
    return stream.getvalue().encode("utf-8-sig")


def _export_change(asset: LocaleAsset, target: Path, delimiter: str) -> FileChange:
    duplicates = len(asset.terms) - len({t["Term"] for t in asset.terms})
    warnings = (f"Asset có {duplicates} term trùng; Export giữ lại như I2.",) if duplicates else ()
    before = target.read_bytes() if target.exists() else None
    after = export_csv(asset, delimiter)
    new_rows = list(csv.reader(io.StringIO(after.decode("utf-8-sig")), delimiter=delimiter))
    def records(rows):
        # Compare by column name, so column order alone does not imply a change.
        values = {}
        for row in rows[1:]:
            if len(row) != len(rows[0]):
                raise UnityLocaleError("Số cột không hợp lệ")
            values.setdefault(row[0], []).append(dict(zip(rows[0][1:], row[1:])))
        return values
    current, old_rows = records(new_rows), None
    if before is None:
        old_rows = [new_rows[0]]
    else:
        try:
            _, old_rows = _read_csv(target, "auto")
            records(old_rows)
        except (ValueError, OSError):
            old_rows = None
            warnings += ("CSV đích không đọc được theo mẫu Key: chưa xác định số liệu cũ; Replace vẫn ghi đè toàn bộ.",)
    stats = ChangeStats(len(asset.terms), None, len(new_rows) - 1, None, None, None, None, "term", "dòng CSV")
    if old_rows is not None:
        previous = records(old_rows)
        shared = current.keys() & previous.keys()
        changed = sum(current[key] != previous[key] for key in shared)
        stats.before_count = len(old_rows) - 1
        stats.duplicate_before = stats.before_count - len(previous)
        stats.added = len(current.keys() - previous.keys())
        stats.removed = len(previous.keys() - current.keys())
        stats.updated = changed
        stats.unchanged = len(shared) - changed
    return FileChange(target, before, after,
                      f"{len(asset.terms)} term → {stats.after_count} dòng CSV", warnings, asset.path, stats)


def prepare_export(asset_paths: list[Path], output_dir: Path, prefix: str = "DG_Localization", delimiter: str = ",") -> LocalePlan:
    if not asset_paths:
        raise UnityLocaleError("Chọn ít nhất một asset để xuất.")
    if not output_dir.is_dir():
        raise UnityLocaleError("Chọn thư mục CSV đầu ra đã tồn tại.")
    if not prefix.strip() or re.search(r'[<>:"/\\|?*\x00-\x1f]', prefix):
        raise UnityLocaleError("Tên bảng tính không được rỗng hoặc chứa ký tự tên file không hợp lệ.")
    changes, sources, targets = [], {}, set()
    for path in asset_paths:
        asset = read_asset(path)
        code = asset.languages[0]["Code"] if len(asset.languages) == 1 else asset.path.stem
        if not re.fullmatch(r"[\w-]+", code):
            raise UnityLocaleError(f"Mã ngôn ngữ/tên asset không an toàn cho tên file: {code}")
        target = (output_dir / f"{prefix.strip()} - upload_{code}.csv").resolve()
        if target in targets:
            raise UnityLocaleError(f"Nhiều asset tạo cùng file {target.name}.")
        targets.add(target)
        changes.append(_export_change(asset, target, delimiter))
        sources[asset.path] = asset.original
    return LocalePlan(changes, sources)


def _unchanged(path: Path, expected: bytes | None) -> bool:
    return path.read_bytes() == expected if path.exists() else expected is None


def apply_plan(plan: LocalePlan, backup_root: Path, *, progress: Callable[[int, int, str], None] | None = None) -> Path:
    """Preflight all files, back up, stage, then replace. Roll back our writes on failure."""
    if not plan.changes or len({c.path for c in plan.changes}) != len(plan.changes):
        raise UnityLocaleError("Kế hoạch rỗng hoặc có đường dẫn đích trùng nhau.")
    expected = dict(plan.sources)
    expected.update({c.path: c.before for c in plan.changes})
    completed, total = 0, 2 * len(expected) + 3 * len(plan.changes) + 2
    def report(message, *, done=False):
        nonlocal completed
        completed += int(done)
        if progress:
            try:
                progress(completed, total, message)
            except Exception:
                # A UI observer must never interrupt a file transaction.
                pass
    report("Đang kiểm tra các file trước khi ghi…")
    for path, raw in expected.items():
        report(f"Đang kiểm tra: {path.name}")
        if not _unchanged(path, raw):
            raise UnityLocaleError(f"{path.name} đã thay đổi sau khi xem trước. Hãy xem trước lại.")
        report(f"Đã kiểm tra: {path.name}", done=True)
    backup = backup_root / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, exist_ok=False)
    staged, written, manifest = [], [], []
    try:
        for index, change in enumerate(plan.changes):
            name = f"{index:03d}_{change.path.name}.bak"
            report(f"Đang sao lưu: {change.path.name}")
            if change.before is not None:
                (backup / name).write_bytes(change.before)
            report(f"Đã sao lưu: {change.path.name}" if change.before is not None else
                   f"File mới, không có dữ liệu cũ cần sao lưu: {change.path.name}", done=True)
            manifest.append({"path": str(change.path), "backup": name if change.before is not None else None})
            report(f"Đang chuẩn bị dữ liệu: {change.path.name}")
            with tempfile.NamedTemporaryFile(dir=change.path.parent, prefix=".import-localize-", suffix=".tmp", delete=False) as stream:
                staged.append(Path(stream.name))
                stream.write(change.after)
                stream.flush()
                os.fsync(stream.fileno())
            report(f"Đã chuẩn bị dữ liệu: {change.path.name}", done=True)
        report("Đang lưu thông tin khôi phục…")
        (backup / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        report("Đã lưu thông tin khôi phục.", done=True)
        for path, raw in expected.items():
            report(f"Đang kiểm tra lại: {path.name}")
            if not _unchanged(path, raw):
                raise UnityLocaleError(f"{path.name} vừa thay đổi. Hãy xem trước lại.")
            report(f"Đã kiểm tra lại: {path.name}", done=True)
        for change, temporary in zip(plan.changes, staged):
            report(f"Đang ghi: {change.path.name}")
            if not _unchanged(change.path, change.before):
                raise UnityLocaleError(f"{change.path.name} vừa thay đổi trước khi ghi.")
            os.replace(temporary, change.path)
            written.append(change)
            report(f"Đã ghi: {change.path.name}", done=True)
    except Exception as exc:
        failures = []
        for change in reversed(written):
            report(f"Gặp lỗi — đang khôi phục: {change.path.name}")
            try:
                if not _unchanged(change.path, change.after):
                    raise UnityLocaleError("File đã được ứng dụng khác sửa sau khi ghi")
                if change.before is None:
                    change.path.unlink()
                else:
                    with tempfile.NamedTemporaryFile(dir=change.path.parent, prefix=".import-localize-", delete=False) as stream:
                        staged.append(Path(stream.name))
                        stream.write(change.before)
                    os.replace(staged[-1], change.path)
                report(f"Đã khôi phục: {change.path.name}")
            except Exception as rollback_error:
                failures.append(f"{change.path}: {rollback_error}")
        detail = "\nKhông tự khôi phục được: " + "; ".join(failures) if failures else "\nCác file đã ghi đã được khôi phục."
        raise UnityLocaleError(f"Ghi thất bại: {exc}{detail}\nBản sao lưu: {backup}") from exc
    finally:
        report("Đang dọn file tạm…")
        for path in staged:
            path.unlink(missing_ok=True)
    report("Hoàn tất ghi dữ liệu và dọn file tạm.", done=True)
    return backup
