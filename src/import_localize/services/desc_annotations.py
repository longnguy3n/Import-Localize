"""Session-local review decisions for outgoing localization tables."""
from __future__ import annotations

import re


WRONG_MAPPING = "Wrong mapping"
WRONG_LANGUAGE = "Wrong languague"


def _code(locale: str) -> str:
    return locale.strip().replace("_", "-").casefold()


def locales_for_table(headers, tab_name="") -> tuple[str, ...]:
    from .csv_language_service import METADATA, declared_language

    codes = []
    tab = re.search(r"(?:^| - )(?:upload|export)_([a-zA-Z]{2,3}(?:[-_][a-zA-Z0-9]+)*)$", tab_name, re.I)
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

    def __bool__(self):
        return bool(self._marks)

    def __len__(self):
        return len(self._marks)

    def snapshot(self):
        copy = DescAnnotations()
        copy._marks = {where: reasons.copy() for where, reasons in self._marks.items()}
        return copy

    def clear(self):
        self._marks.clear()

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
        elif where in self._marks:
            self._marks[where].discard(reason)
            if not self._marks[where]:
                del self._marks[where]

    def apply_rows(self, rows, locales):
        """Copy affected rows only; append Desc if a marked table lacks that column."""
        if not self._marks or not rows:
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
        for index, row in enumerate(rows[1:], 1):
            if key_col >= len(row):
                continue
            reasons = set()
            for code in codes:
                reasons.update(self._marks.get((code, row[key_col]), ()))
            if not reasons:
                continue
            desc = "" if adding_column or desc_col >= len(row) else row[desc_col]
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
