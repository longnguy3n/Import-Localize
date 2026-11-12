"""Read-only DG v2 terminology audit. Ambiguous prose remains a review item.

Implements the contract in DG/support/mapping.README.txt. The external project
supplies data only: no scripts, historical audits or pending decisions execute.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from pathlib import Path

from import_localize.app.paths import ASSETS_DIR
from import_localize.services.csv_service import inspect_csv

LOCALES = ("en", "vi", "pt-BR")
PROTECTED = re.compile(r"<[^>]*>|\{[^{}]*\}|(?<!\w)[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?!\w)")


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().replace("’", "'").split())


def _chunks(text):
    return [normalize(chunk) for chunk in PROTECTED.split(text) if chunk.strip()]


def _visible(text):
    return normalize(PROTECTED.sub(" ", text))


def _contains(text, term):
    pattern = re.compile(r"(?<!\w)" + re.escape(normalize(term)) + r"(?!\w)")
    return any(pattern.search(chunk) for chunk in _chunks(text))


@dataclass(frozen=True)
class MappingIssue:
    path: Path
    line: int
    key: str
    locale: str
    source: str
    actual: str
    expected: str
    reason: str
    status: str


@dataclass
class MappingReport:
    mapping_path: Path
    files: list[Path] = field(default_factory=list)
    issues: list[MappingIssue] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    checked_cells: int = 0
    unmapped_cells: int = 0
    records: list[MappingRecord] = field(default_factory=list)

    @property
    def wrong_keys(self) -> set[str]:
        return {issue.key for issue in self.issues if issue.status == "wrong"}

    @property
    def affected_files(self) -> list[Path]:
        return list(dict.fromkeys(issue.path for issue in self.issues))


def _validate(value, schema, root, location="mapping"):
    """Bounded validation of our bundled schema, never external schema code."""
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].split("/")[1:]:
            target = target[part]
        return _validate(value, target, root, location)
    types = {"object": dict, "array": list, "string": str, "boolean": bool}
    if "type" in schema and type(value) is not types[schema["type"]]:
        raise ValueError(f"{location}: sai kiểu dữ liệu")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ValueError(f"{location}: giá trị/cấu hình chưa được hỗ trợ")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location}: giá trị không hợp lệ")
    if isinstance(value, dict):
        if set(schema.get("required", [])) - value.keys():
            raise ValueError(f"{location}: thiếu trường bắt buộc")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(f"{location}: trường chưa được hỗ trợ")
        for name in value.keys() & props.keys():
            _validate(value[name], props[name], root, f"{location}.{name}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{location}: danh sách rỗng")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise ValueError(f"{location}: giá trị trùng")
        for index, item in enumerate(value):
            if "items" in schema:
                _validate(item, schema["items"], root, f"{location}[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or ("pattern" in schema and not re.search(schema["pattern"], value)):
            raise ValueError(f"{location}: chuỗi không hợp lệ")


def load_mapping(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != "2.0.0":
        raise ValueError("Chỉ hỗ trợ mapping schema_version 2.0.0")
    schema = json.loads((ASSETS_DIR / "mapping.schema.json").read_text(encoding="utf-8"))
    _validate(data, schema, schema)
    ids = [e["id"] for e in data["entries"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Mapping chứa ID trùng")
    triples = set()
    for entry in data["entries"]:
        triple = tuple(entry["translations"][l] for l in LOCALES)
        if triple in triples:
            raise ValueError("Mapping chứa bản dịch chuẩn trùng toàn bộ")
        triples.add(triple)
        if entry["translations"]["en"].endswith(" +") or any("_plus_" in key for key in entry["keys"]):
            raise ValueError("Mapping lưu bản nâng cấp thay vì dùng derivation_rules")
        for locale in LOCALES:
            terms = [entry["translations"][locale], *entry["aliases"][locale]]
            if any(not normalize(t) or t != t.strip() or t != unicodedata.normalize("NFC", t) for t in terms):
                raise ValueError(f"Mapping có thuật ngữ rỗng/chưa chuẩn hóa: {entry['id']}")
    for rule in [*data["key_overrides"], *data["abbreviations"]]:
        if rule["entry_id"] not in ids:
            raise ValueError(f"Mapping tham chiếu ID không tồn tại: {rule['entry_id']}")
    for name in ("key_overrides", "derivation_rules"):
        rule_ids = [r["id"] for r in data[name]]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError(f"Mapping có rule ID trùng trong {name}")
    if any(r["key_suffix"] == r["base_key_suffix"] for r in data["derivation_rules"]):
        raise ValueError("Derivation rule phải dẫn tới key gốc khác")
    return data


class MappingIndex:
    def __init__(self, data):
        self.data = data
        self.by_id = {entry["id"]: entry for entry in data["entries"]}
        self.by_key = defaultdict(set)
        self.terms = {}
        for locale in LOCALES:
            index = defaultdict(set)
            for entry in data["entries"]:
                for text in [entry["translations"][locale], *entry["aliases"][locale]]:
                    index[normalize(text)].add(entry["id"])
            self.terms[locale] = [(term, re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)"), ids)
                                  for term, ids in index.items()]
        for entry in data["entries"]:
            for key in entry["keys"]:
                self.by_key[key].add(entry["id"])

    def for_key(self, key):
        overrides = {r["entry_id"] for r in self.data["key_overrides"] if r["value"] in key}
        if overrides:
            return overrides, "", True
        suffix = ""
        for rule in self.data["derivation_rules"]:
            if key.startswith(rule["key_prefix"]) and key.endswith(rule["key_suffix"]):
                key = key[:-len(rule["key_suffix"])] + rule["base_key_suffix"]
                suffix = rule["output_suffix"]
                break
        return self.by_key.get(key, set()), suffix, False

    def find_terms(self, text, locale):
        results = []
        for chunk in _chunks(text):
            matches = [(m.start(), m.end(), term, ids) for term, pattern, ids in self.terms[locale]
                       for m in pattern.finditer(chunk)]
            selected = []
            for start, end, term, ids in sorted(matches, key=lambda m: (-(m[1]-m[0]), m[0], m[2])):
                if not any(start < b and end > a for a, b, _, _ in selected):
                    selected.append((start, end, term, ids))
            results.extend((term, ids) for _, _, term, ids in sorted(selected))
        return results


def _locale(header):
    text = header.strip().lstrip("$").casefold()
    aliases = {"en": ("en", "english", "english (en)"),
               "vi": ("vi", "vietnamese", "vietnamese (vi)", "tiếng việt"),
               "pt-BR": ("pt-br", "pt_br", "portuguese (brazil)", "portuguese (brazil) (pt-br)", "portuguese (brazil) [pt-br]")}
    for code, names in aliases.items():
        if text in names or text.endswith(f"[{code.casefold()}]"):
            return code


def _family(path):
    # Never pair upload with export or unrelated spreadsheets/directories.
    match = re.fullmatch(r"(.*?)(export|upload)_(?:en|vi|pt[-_]br)", path.stem, re.IGNORECASE)
    return (str(path.parent).casefold(), *(part.casefold() for part in match.groups())) if match else (str(path),)


@dataclass
class MappingRecord:
    path: Path
    line: int
    key: str
    values: dict[str, str]
    family: tuple


def _read_csv(path, cancel_callback):
    info = inspect_csv(path)
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=info.delimiter, strict=True)
        headers = next(reader, [])
        keys = [i for i, h in enumerate(headers) if h.strip().casefold() in ("key", "term", "technical key")]
        if len(keys) != 1:
            raise ValueError("CSV cần đúng một cột Key / Term / Technical Key")
        columns = [(i, _locale(h)) for i, h in enumerate(headers) if _locale(h)]
        if not columns:
            raise ValueError("Không có cột ngôn ngữ en, vi hoặc pt-BR được hỗ trợ")
        if len({code for _, code in columns}) != len(columns):
            raise ValueError("CSV có nhiều cột cùng ngôn ngữ; cần chọn một bản nguồn rõ ràng")
        family = _family(path)
        while True:
            if cancel_callback and cancel_callback():
                raise CancelledError()
            line = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                break
            if not row or not any(row):
                continue
            if len(row) != len(headers):
                raise ValueError(f"Dòng {line}: số cột khác tiêu đề")
            key = row[keys[0]]
            if not key:
                raise ValueError(f"Dòng {line}: thiếu key")
            rows.append(MappingRecord(path, line, key, {locale: row[i] for i, locale in columns}, family))
    return rows


def _audit_cell(index, row, locale, actual, source_locale, source, source_problem):
    hints, suffix, override = index.for_key(row.key)
    found = index.find_terms(source, source_locale) if source else []
    # A key attached to a description only resolves entity context. It is never
    # permission to replace the description with the entity's short name.
    # Even *_title can be contextual: e.g. "Equipment Design" references the
    # Equipment entry, and "Relic Name Fragment" references the relic name.
    full_hint = source and any(_visible(source) == normalize(term + suffix)
        for i in hints for term in [index.by_id[i]["translations"][source_locale],
                                    *index.by_id[i]["aliases"][source_locale]])
    override_label = override and source_locale == "en" and row.key.endswith(("_title", "_name")) and any(
        r["value"] in row.key and _visible(source) == normalize(r["value"].replace("_", " "))
        for r in index.data["key_overrides"])
    label = False
    if hints and (full_hint or override_label):
        found = [("", hints)]
        label = True
    elif source:
        whole = [(term, ids) for term, ids in found if _visible(source) == term]
        if whole:
            found, label = whole, True
    if not found:
        if source_problem and locale != source_locale:
            return [("review", "", source_problem)], False
        return [], False

    issues, checked = [], False
    seen = set()
    for matched, candidates in found:
        if override and hints and source_locale == "en" and any(
                r["value"] in row.key and normalize(r["value"].replace("_", " ")) == matched
                for r in index.data["key_overrides"]):
            candidates = hints
        contextual = candidates & hints
        chosen = contextual or candidates
        expected = " | ".join(index.by_id[i]["translations"][locale] + (suffix if label else "") for i in sorted(chosen))
        signature = tuple(sorted(chosen))
        if signature in seen:
            continue
        seen.add(signature)
        checked = True
        if len(chosen) != 1 or (any(index.by_id[i]["context_required"] for i in chosen) and not contextual):
            issues.append(("review", expected, "Thuật ngữ có nhiều nghĩa/cần ngữ cảnh; chưa tự chọn mapping"))
            continue
        entry = index.by_id[next(iter(chosen))]
        expected = entry["translations"][locale] + (suffix if label else "")
        correct = _visible(actual) == normalize(expected) if label else _contains(actual, expected)
        variants = [v for v in entry["variants"] if v["locale"] == locale and _contains(actual, v["text"])]
        rejected = [r for r in entry["rejected"] if r["locale"] == locale and any(_contains(actual, f) for f in r["forms"])]
        if rejected:
            definite = any(not r["condition"] for r in rejected)
            issues.append(("wrong" if definite else "review", expected,
                           "Có cách dịch đã bị loại bỏ" + ("; cần đối chiếu điều kiện: " + "; ".join(r["condition"] for r in rejected) if not definite else "")))
        elif correct:
            continue
        elif variants:
            issues.append(("review", expected, "Có biến thể đích có điều kiện: " + "; ".join(v["condition"] or "cần xác định ngữ cảnh" for v in variants)))
        elif not actual.strip():
            issues.append(("wrong", expected, "Thiếu bản dịch của thuật ngữ đã xác định"))
        elif label:
            issues.append(("wrong", expected, "Tên/nhãn không khớp bản dịch chuẩn"))
        else:
            issues.append(("review", expected, "Chưa tìm thấy thuật ngữ chuẩn trong câu; cần kiểm tra nghĩa và biến đổi ngữ pháp"))
    return issues, checked


def audit_mapping(mapping_path: Path, csv_paths: list[Path], progress_callback=None, cancel_callback=None) -> MappingReport:
    mapping_path = Path(mapping_path).expanduser().resolve()
    index = MappingIndex(load_mapping(mapping_path))
    report = MappingReport(mapping_path)
    rows = []
    for path in dict.fromkeys(Path(p).expanduser().resolve() for p in csv_paths):
        if cancel_callback and cancel_callback():
            raise CancelledError()
        report.files.append(path)
        try:
            rows.extend(_read_csv(path, cancel_callback))
        except (OSError, UnicodeError, ValueError, csv.Error, RuntimeError) as exc:
            if isinstance(exc, CancelledError):
                raise
            report.errors[str(path)] = str(exc)
    report.records = rows
    sources = defaultdict(set)
    for row in rows:
        for locale, value in row.values.items():
            if value.strip():
                sources[row.family, row.key, locale].add(value)
    total = sum(len(row.values) for row in rows)
    done = 0
    if progress_callback:
        progress_callback(0, total, "Đang đối chiếu mapping")
    for row in rows:
        if cancel_callback and cancel_callback():
            raise CancelledError()
        source_locale, source, source_problem = "en", "", "Thiếu bản nguồn English cùng nhóm file/key; chưa đủ dữ liệu đối chiếu"
        for candidate in LOCALES:
            if candidate in row.values and row.values[candidate].strip():
                source_locale, source, source_problem = candidate, row.values[candidate], ""
                break
            values = sources[row.family, row.key, candidate]
            if values:
                source_locale = candidate
                if len(values) == 1:
                    source, source_problem = next(iter(values)), ""
                else:
                    source_problem = f"Có nhiều bản nguồn {candidate} khác nhau cho cùng key; chưa chọn bản để đối chiếu"
                break
        for locale, actual in row.values.items():
            # Self-source monolingual prose cannot establish that a translation
            # omitted a term. Only key-bound labels can be checked that way.
            self_source = len(row.values) == 1 and locale != "en" and source_locale == locale
            found, checked = _audit_cell(index, row, locale, actual, source_locale, source,
                                         source_problem)
            if self_source and (not checked or not index.for_key(row.key)[0]):
                found = [("review", "", "Thiếu bản nguồn English cùng nhóm file/key; chưa đủ dữ liệu đối chiếu")]
                checked = False
            report.checked_cells += int(checked)
            report.unmapped_cells += int(not checked)
            for status, expected, reason in found:
                report.issues.append(MappingIssue(row.path, row.line, row.key, locale, source, actual, expected, reason, status))
            done += 1
            if progress_callback and (done % 50 == 0 or done == total):
                progress_callback(done, total, f"{row.path.name}: {done}/{total} ô")
    return report
