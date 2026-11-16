"""File roles and exact locale identities shared by the transfer workflows."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .csv_language_service import METADATA, _normalize, language_catalog
from .csv_service import FILENAME_SEPARATOR


class TransferFileError(ValueError):
    pass


# I2 uses a language, optionally followed by a script and/or a region.
# Preserve these subtags: Portuguese, pt-BR and pt-PT have separate targets.
_CODE = re.compile(r"[a-z]{2,3}(?:[-_][a-z]{4})?(?:[-_](?:[a-z]{2}|[0-9]{3}))?", re.I | re.ASCII)
_REGIONAL_NAMES = {
    "portuguese (brazil)": "pt-br", "portuguese/brazil": "pt-br", "brazilian portuguese": "pt-br",
    "portuguese (portugal)": "pt-pt", "portuguese/portugal": "pt-pt",
    "chinese (simplified)": "zh-hans", "chinese (traditional)": "zh-hant",
}
_KEY_COLUMNS = {"key", "term", "technical key", "id"}


def normalize_code(code: str) -> str:
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise TransferFileError(f"Mã ngôn ngữ không hợp lệ: {code!r}.")
    return code.replace("_", "-").casefold()


def parse_tab_code(title: str, role: str) -> str:
    if role not in ("upload", "export"):
        raise ValueError(f"Loại tab không hợp lệ: {role!r}")
    prefix = role + "_"
    if not title.casefold().startswith(prefix):
        raise TransferFileError(f"'{title}' phải có dạng {prefix}<mã ngôn ngữ>.")
    return normalize_code(title[len(prefix):])


def parse_csv_filename(path: str | Path, role: str) -> tuple[str, str]:
    """Return optional workbook prefix and normalized code from a CSV filename."""
    path = Path(path)
    if path.suffix.casefold() != ".csv":
        raise TransferFileError(f"{path.name}: cần một file CSV.")
    spreadsheet, separator, tab = path.stem.rpartition(FILENAME_SEPARATOR)
    if separator and not spreadsheet.strip():
        raise TransferFileError(f"{path.name}: thiếu tên bảng tính trước '{FILENAME_SEPARATOR}'.")
    try:
        code = parse_tab_code(tab, role)
    except TransferFileError as exc:
        raise TransferFileError(f"{path.name}: {exc}") from exc
    return spreadsheet, code


def parse_asset_filename(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.casefold() != ".asset" or not path.stem.casefold().startswith("locale_"):
        raise TransferFileError(f"{path.name}: tên asset phải có dạng locale_<mã ngôn ngữ>.asset.")
    try:
        return normalize_code(path.stem[len("locale_"):])
    except TransferFileError as exc:
        raise TransferFileError(f"{path.name}: {exc}") from exc


def _label_code(label: str) -> str:
    name = label.casefold()
    if name in _REGIONAL_NAMES:
        return _REGIONAL_NAMES[name]
    if _CODE.fullmatch(label):
        return normalize_code(label)
    return language_catalog()[1].get(_normalize(label), "")


def _label_agrees_with_code(label_code: str, code: str) -> bool:
    return label_code in (code, code.split("-")[0])


def validate_asset_language(path: str | Path, languages: list[dict]) -> str:
    expected = parse_asset_filename(path)
    name = Path(path).name
    if len(languages) != 1:
        raise TransferFileError(f"{name}: mỗi asset truyền theo mã cần chứa đúng một ngôn ngữ.")
    language = languages[0]
    code = normalize_code(language.get("Code", ""))
    if code != expected:
        raise TransferFileError(f"{name}: tên file mang mã {expected}, còn mLanguages.Code là {code}.")
    label = language.get("Name", "")
    label_code = _label_code(label)
    if label_code and not _label_agrees_with_code(label_code, code):
        raise TransferFileError(f"{name}: tên ngôn ngữ '{label}' không khớp mLanguages.Code '{code}'.")
    return code


def validate_csv_header(header, code: str, source_name: str = "", *, language_name: str = "") -> None:
    """Require exactly one translation column and the locale specified by the filename/tab."""
    expected = normalize_code(code)
    origin = source_name or f"CSV {code}"
    columns = [column.strip() for column in header]
    if not columns or columns[0].removeprefix("\ufeff").casefold() not in _KEY_COLUMNS:
        raise TransferFileError(f"{origin}: thiếu cột key ở đầu bảng.")
    translations = []
    for column in columns[1:]:
        field = column.removeprefix("$").strip()
        # "id" is also a valid language (Indonesian) after the key column.
        if field.casefold() in METADATA and field.casefold() not in _KEY_COLUMNS:
            continue
        translations.append(field)
    if len(translations) != 1 or not translations[0]:
        raise TransferFileError(f"{origin}: cần đúng một cột bản dịch cho mã '{code}'.")
    label = translations[0]
    match = re.fullmatch(r"(.*?)\s*\[([^\[\]]+)\]", label)
    if match:
        declared = normalize_code(match[2])
        label_code = _label_code(match[1].strip())
        if label_code and not _label_agrees_with_code(label_code, declared):
            raise TransferFileError(f"{origin}: tên và mã ngôn ngữ trong cột '{label}' không khớp nhau.")
    else:
        declared = _label_code(label)
        if not declared and language_name and label.casefold() == language_name.strip().casefold():
            declared = expected
    if declared != expected:
        raise TransferFileError(f"{origin}: cột '{label}' không khớp mã '{code}'.")


@dataclass(frozen=True)
class FolderScan:
    paths: tuple[Path, ...]
    issues: tuple[str, ...]


def scan_folder(folder: str | Path, role: str) -> FolderScan:
    """Discover only immediate files in this role; never pick a winner for duplicate locales."""
    if role not in ("upload", "export", "unity"):
        raise ValueError(f"Loại thư mục không hợp lệ: {role!r}")
    if not folder:
        return FolderScan((), ())
    candidates: dict[str, list[Path]] = {}
    issues = []
    try:
        for path in sorted(Path(folder).iterdir(), key=lambda p: (p.name.casefold(), p.name)):
            if role == "unity":
                relevant = path.suffix.casefold() == ".asset" and path.stem.casefold().startswith("locale_")
            else:
                tab = path.stem.rsplit(FILENAME_SEPARATOR, 1)[-1]
                relevant = path.suffix.casefold() == ".csv" and tab.casefold().startswith(role + "_")
            if not relevant or not path.is_file():
                continue
            try:
                code = parse_asset_filename(path) if role == "unity" else parse_csv_filename(path, role)[1]
            except TransferFileError as exc:
                issues.append(str(exc))
                continue
            candidates.setdefault(code, []).append(path)
    except OSError as exc:
        return FolderScan((), (f"Không đọc được thư mục {folder}: {exc}",))
    paths = []
    for code, group in sorted(candidates.items()):
        if len(group) == 1:
            paths.append(group[0])
        else:
            issues.append(f"Nhiều file cùng mã {code}: " + ", ".join(path.name for path in group))
    return FolderScan(tuple(paths), tuple(issues))
