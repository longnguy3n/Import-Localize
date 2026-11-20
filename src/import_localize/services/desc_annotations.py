"""Session-local review decisions for outgoing localization tables."""
from __future__ import annotations

import re
import csv
import io
from pathlib import Path


WRONG_MAPPING = "Wrong mapping"
WRONG_LANGUAGE = "Wrong languague"


def upload_mapping_path(settings):
    if settings.mapping_path:
        return settings.mapping_path
    if settings.upload_folder:
        candidate = Path(settings.upload_folder) / "data" / "mapping.json"
        if candidate.is_file():
            return candidate


def clean_upload_mapping(plans, mapping_path, cancel_callback):
    """Recheck only marked keys, using the outgoing translations across upload tabs."""
    if not mapping_path:
        return
    from .mapping_audit_service import LOCALES, audit_mapping
    supported = {_code(locale) for locale in LOCALES}

    keys = set()
    tables = []
    for bundle, job in plans:
        if not supported.intersection(locales_for_table(bundle.header, job.sheet_name)):
            continue
        header = [name.strip().casefold() for name in bundle.header]
        desc = next((i for i, name in enumerate(header) if name in ("desc", "description")), None)
        key = next((i for i, name in enumerate(header) if name in ("key", "term", "technical key")), None)
        if key is None:
            continue
        tables.append((bundle, job, key))
        if desc is not None:
            keys.update(row[key] for row in bundle.rows if any(line.strip() == WRONG_MAPPING for line in row[desc].splitlines()))
    if not keys:
        return
    sources = {}
    for bundle, job, key in tables:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(bundle.header)
        writer.writerows(row for row in bundle.rows if row[key] in keys)
        sources[Path(job.sheet_name + ".csv")] = stream.getvalue().encode("utf-8")
    report = audit_mapping(Path(mapping_path), [], sources=sources, cancel_callback=cancel_callback)
    verified = DescAnnotations()
    verified.reconcile_mapping(report)
    for bundle, job, _ in tables:
        rows = [bundle.header, *bundle.rows]
        cleaned = verified.apply_rows(rows, locales_for_table(bundle.header, job.sheet_name))
        if cleaned is not rows:
            bundle.rows = cleaned[1:]


def _code(locale: str) -> str:
    return locale.strip().replace("_", "-").casefold()


def locales_for_table(headers, tab_name="") -> tuple[str, ...]:
    from .csv_language_service import METADATA, declared_language

    codes = []
    tab = re.search(r"(?:^| - )(?:upload|export|locale)_([a-zA-Z]{2,3}(?:[-_][a-zA-Z0-9]+)*)$", tab_name, re.I)
    for header in headers:
        token = header.strip().lstrip("$").strip()
        if token.casefold() in METADATA or token.casefold() == "technical key":
            continue
        explicit = re.search(r"\[([\w-]+)\]$", token)
        if explicit:
            code = explicit[1]
        elif token.casefold() in {"portuguese/brazil", "portuguese (brazil)"}:
            code = "pt-BR"
        elif re.fullmatch("[a-zA-Z]{2,3}(?:[-_][a-zA-Z0-9]+)+", token):
            code = token
        else:
            code = declared_language(token)
            if tab and code and _code(tab[1]).split("-")[0] == _code(code):
                code = tab[1]
        if code:
            codes.append(_code(code))
    return tuple(dict.fromkeys(codes)) or ((_code(tab[1]),) if tab else ())


class DescAnnotations:
    def __init__(self):
        self._marks: dict[tuple[str, str], set[str]] = {}
        self._verified = {}

    def __bool__(self):
        return bool(self._marks)

    def has_export_changes(self):
        return bool(self._marks or self._verified)

    def __len__(self):
        return len(self._marks)

    def snapshot(self, *, include_verified=True):
        copy = DescAnnotations()
        copy._marks = {where: reasons.copy() for where, reasons in self._marks.items()}
        if include_verified:
            copy._verified = self._verified.copy()
        return copy

    def clear(self):
        self._marks.clear()
        self._verified.clear()

    def reconcile_mapping(self, report):
        """Only clear a marker when every audited occurrence passed for this key and locale."""
        if report.errors:
            return False
        values = {}
        for record in report.records:
            for locale, text in record.values.items():
                values.setdefault((_code(locale), record.key), set()).add(text)
        verified = {(_code(locale), key, value) for locale, key, value in report.verified_cells}
        changed = False
        for where, texts in values.items():
            if all((*where, value) in verified for value in texts):
                if self._verified.get(where) != texts or self.has(*where, WRONG_MAPPING):
                    self.set_mark(*where, WRONG_MAPPING, False)
                    self._verified[where] = texts
                    changed = True
            elif where in self._verified:
                del self._verified[where]
                changed = True
        return changed

    def has(self, locale, key, reason) -> bool:
        return reason in self._marks.get((_code(locale), key), ())

    def set_mark(self, locale, key, reason, enabled=True):
        if reason not in (WRONG_MAPPING, WRONG_LANGUAGE):
            raise ValueError(f"Unknown Desc annotation: {reason}")
        if not locale or not key:
            return
        where = (_code(locale), key)
        if enabled:
            self._marks.setdefault(where, set()).add(reason)
            if reason == WRONG_MAPPING:
                self._verified.pop(where, None)
        elif where in self._marks:
            self._marks[where].discard(reason)
            if not self._marks[where]:
                del self._marks[where]

    def apply_rows(self, rows, locales):
        """Copy affected rows only; append Desc if a marked table lacks that column."""
        if not self.has_export_changes() or not rows:
            return rows
        header = [name.strip().casefold() for name in rows[0]]
        key_columns = [i for i, name in enumerate(header) if name in {"key", "term", "technical key", "id"}]
        if len(key_columns) != 1:
            return rows
        key_col = key_columns[0]
        desc_col = next((i for i, name in enumerate(header) if name in {"desc", "description"}), len(header))
        codes = {_code(code) for code in locales}
        adding_column = desc_col == len(header)
        if adding_column:
            desc_col = key_col + 1
            if desc_col < len(header) and header[desc_col] in {"type", "termtype"}:
                desc_col += 1
        changes = {}
        language_columns = {code: i for i, name in enumerate(rows[0]) for code in locales_for_table([name])}
        for index, row in enumerate(rows[1:], 1):
            if key_col >= len(row):
                continue
            reasons = set()
            for code in codes:
                reasons.update(self._marks.get((code, row[key_col]), ()))
            desc = "" if adding_column or desc_col >= len(row) else row[desc_col]
            if WRONG_MAPPING in desc and codes and WRONG_MAPPING not in reasons and all(
                    code in language_columns and language_columns[code] < len(row)
                    and row[language_columns[code]] in self._verified.get((code, row[key_col]), ())
                    for code in codes):
                cleaned = "".join(line for line in desc.splitlines(keepends=True) if line.strip() != WRONG_MAPPING)
                if desc.splitlines()[-1].strip() == WRONG_MAPPING and not desc.endswith(("\n", "\r")):
                    cleaned = re.sub(r"(?:\r\n|\n|\r)\Z", "", cleaned)
                if cleaned != desc:
                    changes[index] = desc = cleaned
            if not reasons:
                continue
            existing = {line.strip() for line in desc.splitlines()}
            extra = [label for label in (WRONG_MAPPING, WRONG_LANGUAGE) if label in reasons - existing]
            if extra:
                separator = "\n" if desc and not desc.endswith(("\r", "\n")) else ""
                changes[index] = desc + separator + "\n".join(extra)
        if not changes:
            return rows
        result = list(rows)
        if adding_column:
            for index, row in enumerate(rows):
                result[index] = list(row[:desc_col]) + [""] * max(0, desc_col - len(row)) + [""] + list(row[desc_col:])
            result[0][desc_col] = "Desc"
        for i, value in changes.items():
            row = list(result[i])
            row.extend([""] * (desc_col + 1 - len(row)))
            row[desc_col] = value
            result[i] = row
        return result
