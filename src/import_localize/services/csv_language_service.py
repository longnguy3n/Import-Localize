"""Read-only offline language audit. Header names never bias the detector."""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .csv_service import CSV_READ_ENCODING, CsvImportError, _check_cancel, inspect_csv

# ISO codes from the bundled Lingua model; lookup does not load the native model.
LANGUAGE_CODES = {'af': ('afr', 'Afrikaans'),
 'ar': ('ara', 'Arabic'),
 'az': ('aze', 'Azerbaijani'),
 'be': ('bel', 'Belarusian'),
 'bg': ('bul', 'Bulgarian'),
 'bn': ('ben', 'Bengali'),
 'bs': ('bos', 'Bosnian'),
 'ca': ('cat', 'Catalan'),
 'cs': ('ces', 'Czech'),
 'cy': ('cym', 'Welsh'),
 'da': ('dan', 'Danish'),
 'de': ('deu', 'German'),
 'el': ('ell', 'Greek'),
 'en': ('eng', 'English'),
 'eo': ('epo', 'Esperanto'),
 'es': ('spa', 'Spanish'),
 'et': ('est', 'Estonian'),
 'eu': ('eus', 'Basque'),
 'fa': ('fas', 'Persian'),
 'fi': ('fin', 'Finnish'),
 'fr': ('fra', 'French'),
 'ga': ('gle', 'Irish'),
 'gu': ('guj', 'Gujarati'),
 'he': ('heb', 'Hebrew'),
 'hi': ('hin', 'Hindi'),
 'hr': ('hrv', 'Croatian'),
 'hu': ('hun', 'Hungarian'),
 'hy': ('hye', 'Armenian'),
 'id': ('ind', 'Indonesian'),
 'is': ('isl', 'Icelandic'),
 'it': ('ita', 'Italian'),
 'ja': ('jpn', 'Japanese'),
 'ka': ('kat', 'Georgian'),
 'kk': ('kaz', 'Kazakh'),
 'ko': ('kor', 'Korean'),
 'la': ('lat', 'Latin'),
 'lg': ('lug', 'Ganda'),
 'lt': ('lit', 'Lithuanian'),
 'lv': ('lav', 'Latvian'),
 'mi': ('mri', 'Maori'),
 'mk': ('mkd', 'Macedonian'),
 'mn': ('mon', 'Mongolian'),
 'mr': ('mar', 'Marathi'),
 'ms': ('msa', 'Malay'),
 'nb': ('nob', 'Bokmal'),
 'nl': ('nld', 'Dutch'),
 'nn': ('nno', 'Nynorsk'),
 'pa': ('pan', 'Punjabi'),
 'pl': ('pol', 'Polish'),
 'pt': ('por', 'Portuguese'),
 'ro': ('ron', 'Romanian'),
 'ru': ('rus', 'Russian'),
 'sk': ('slk', 'Slovak'),
 'sl': ('slv', 'Slovene'),
 'sn': ('sna', 'Shona'),
 'so': ('som', 'Somali'),
 'sq': ('sqi', 'Albanian'),
 'sr': ('srp', 'Serbian'),
 'st': ('sot', 'Sotho'),
 'sv': ('swe', 'Swedish'),
 'sw': ('swa', 'Swahili'),
 'ta': ('tam', 'Tamil'),
 'te': ('tel', 'Telugu'),
 'th': ('tha', 'Thai'),
 'tl': ('tgl', 'Tagalog'),
 'tn': ('tsn', 'Tswana'),
 'tr': ('tur', 'Turkish'),
 'ts': ('tso', 'Tsonga'),
 'uk': ('ukr', 'Ukrainian'),
 'ur': ('urd', 'Urdu'),
 'vi': ('vie', 'Vietnamese'),
 'xh': ('xho', 'Xhosa'),
 'yo': ('yor', 'Yoruba'),
 'zh': ('zho', 'Chinese'),
 'zu': ('zul', 'Zulu')}

METADATA = {"key", "term", "type", "termtype", "desc", "description", "id", "flags", "comment", "comments", "note", "notes", "context"}
NAMES = {"en": "Tiếng Anh", "vi": "Tiếng Việt", "pt": "Tiếng Bồ Đào Nha", "es": "Tiếng Tây Ban Nha",
         "fr": "Tiếng Pháp", "de": "Tiếng Đức", "it": "Tiếng Ý", "ja": "Tiếng Nhật", "ko": "Tiếng Hàn",
         "zh": "Tiếng Trung", "ru": "Tiếng Nga", "th": "Tiếng Thái", "id": "Tiếng Indonesia"}
STATUS = {"match": "Phù hợp", "mismatch": "Nghi sai ngôn ngữ", "uncertain": "Chưa chắc chắn",
          "short": "Chưa đủ nội dung", "unmapped": "Chưa xác định ngôn ngữ cột"}
COLORS = {"match": ("#dcf5e7", "#14633c"), "mismatch": ("#ffe5e5", "#a1232b"),
          "uncertain": ("#fff0ce", "#865500"), "short": ("#f0f2f5", "#39475a"),
          "unmapped": ("#fff0ce", "#865500")}


def _normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                   if not unicodedata.combining(c)).strip()


@lru_cache(maxsize=1)
def language_catalog():
    names, aliases = {}, {}
    for code, (iso3, english_name) in LANGUAGE_CODES.items():
        name = NAMES.get(code, english_name)
        names[code] = name
        for alias in (code, iso3, english_name, name):
            aliases[_normalize(alias)] = code
    aliases.update({"portuguese/brazil": "pt", "portuguese (brazil)": "pt", "brazilian portuguese": "pt",
                    "chinese (simplified)": "zh", "chinese (traditional)": "zh", "tieng bo dao nha": "pt"})
    return names, aliases


def language_name(code):
    return language_catalog()[0].get(code, code or "—")


def declared_language(header):
    token = header.strip().removeprefix("$").strip()
    match = re.search(r"\[([^\]]+)\]\s*$", token)
    token = match[1] if match else token
    # Compare language families: content cannot reliably distinguish pt-BR/pt-PT.
    normalized = _normalize(token)
    aliases = language_catalog()[1]
    return aliases.get(normalized) or aliases.get(re.split(r"[-_]", normalized)[0])


def clean_text(text):
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"<[^>]*>|\{[^{}]*\}|\[/?i2[^\]]*\]", " ", text)
    text = re.sub(r"https?://\S+|www\.\S+|\b[\w.+-]+@[\w.-]+\.[a-zA-Z]+", " ", text)
    text = re.sub(r"\b\w+(?:[/\\]\w+)+\b|\b\w+_\w+\b|%\d*\$?[sdif]", " ", text)
    return " ".join(text.replace("\\n", " ").split())


@dataclass(frozen=True)
class Prediction:
    code: str | None
    score: float = 0
    margin: float = 0
    enough: bool = False
    warning_eligible: bool = False
    sampled: bool = False

    @property
    def reliable(self):
        return self.enough and self.score >= .55 and self.margin >= .20


class OfflineDetector:
    def __init__(self):
        from lingua import LanguageDetectorBuilder
        self.detector = LanguageDetectorBuilder.from_all_languages().build()
        self.cache = {}

    def predict(self, original):
        return self.predict_many([original])[0]

    @staticmethod
    def prepare(original):
        text = clean_text(original)
        letters = sum(c.isalpha() for c in text)
        words = re.findall(r"[^\W\d_]+", text)
        unspaced = any("\u3400" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff"
                       or "\u0e00" <= c <= "\u0e7f" or "\uac00" <= c <= "\ud7af" for c in text)
        enough = letters >= 8 and (len(words) >= 2 or unspaced)
        if not enough:
            return "", False, False
        # Bound pathological long cells; report sampling rather than pretending
        # the complete text was examined. Normal game strings are used in full.
        sampled = len(text) > 4000
        if sampled:
            text = text[:2000] + " " + text[-2000:]
        return text, letters >= 20 or (unspaced and letters >= 8), sampled

    def predict_many(self, originals):
        prepared = [self.prepare(original) for original in originals]
        missing = list(dict.fromkeys(text for text, _, _ in prepared if text and text not in self.cache))
        if missing:
            results = self.detector.compute_language_confidence_values_in_parallel(missing)
            for text, values in zip(missing, results):
                best = values[0]
                self.cache[text] = (best.language.iso_code_639_1.name.lower(), best.value,
                                    best.value - values[1].value if len(values) > 1 else best.value)
        predictions = []
        for text, eligible, sampled in prepared:
            if not text:
                predictions.append(Prediction(None))
            else:
                code, score, margin = self.cache[text]
                predictions.append(Prediction(code, score, margin, True, eligible, sampled))
        while len(self.cache) > 10000:
            self.cache.pop(next(iter(self.cache)))
        return predictions


@dataclass
class LanguageCell:
    path: Path
    column: str
    line: int
    key: str
    text: str
    expected: str | None
    prediction: Prediction
    status: str


@dataclass
class LanguageColumn:
    path: Path
    column: str
    expected: str | None
    cells: list[LanguageCell] = field(default_factory=list)

    @property
    def counts(self):
        return Counter(cell.status for cell in self.cells)

    @property
    def languages(self):
        return Counter(cell.prediction.code for cell in self.cells if cell.prediction.reliable)


@dataclass
class LanguageReport:
    columns: list[LanguageColumn] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _read_columns(path, cancel):
    info = inspect_csv(path)
    columns = []
    with info.path.open(encoding=CSV_READ_ENCODING, newline="") as stream:
        reader = csv.reader(stream, delimiter=info.delimiter, strict=True)
        header = next((row for row in reader if any(cell.strip() for cell in row)), None)
        if not header:
            raise CsvImportError("CSV rỗng hoặc thiếu tiêu đề.")
        header = [name.strip() for name in header]
        normalized = [name.casefold() for name in header]
        if "" in header or len(set(normalized)) != len(header):
            raise CsvImportError("Tên cột rỗng hoặc trùng nhau.")
        indices = [i for i, name in enumerate(normalized) if name not in METADATA]
        if not indices:
            raise CsvImportError("Không tìm thấy cột nội dung để nhận diện.")
        columns = [LanguageColumn(info.path, header[i], declared_language(header[i])) for i in indices]
        key_index = next((i for i, name in enumerate(normalized) if name in ("key", "term", "id")), None)
        while True:
            _check_cancel(cancel)
            line = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                break
            if not any(cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                raise CsvImportError(f"Dòng {line}: có {len(row)} cột, cần {len(header)}.")
            for i, column in zip(indices, columns):
                column.cells.append(LanguageCell(info.path, column.column, line,
                    row[key_index] if key_index is not None else "", row[i], column.expected, Prediction(None), "short"))
    return columns


def audit_csv_languages(paths, *, cancel_callback=None, progress=None, detector=None):
    report = LanguageReport()
    for path in dict.fromkeys(Path(p).resolve() for p in paths):
        _check_cancel(cancel_callback)
        if progress:
            progress(0, 0, f"Đang đọc {path.name}…")
        try:
            report.columns.extend(_read_columns(path, cancel_callback))
        except (OSError, UnicodeError, csv.Error, CsvImportError) as exc:
            report.errors.append(f"{path.name}: {exc}")
    total = sum(len(col.cells) for col in report.columns)
    if not total:
        return report
    if progress:
        progress(0, total, "Đang chuẩn bị mô hình ngôn ngữ offline…")
    detector = detector or OfflineDetector()
    done = 0
    cells = [cell for column in report.columns for cell in column.cells]
    for start in range(0, total, 32):
        _check_cancel(cancel_callback)
        batch = cells[start:start + 32]
        predictions = (detector.predict_many([cell.text for cell in batch]) if hasattr(detector, "predict_many")
                       else [detector.predict(cell.text) for cell in batch])
        for cell, p in zip(batch, predictions):
            _check_cancel(cancel_callback)
            cell.prediction = p
            if not p.enough:
                cell.status = "short"
            elif not cell.expected:
                cell.status = "unmapped"
            elif not p.reliable:
                cell.status = "uncertain"
            elif p.code == cell.expected:
                cell.status = "match"
            elif p.warning_eligible and p.score >= .80 and p.margin >= .30:
                cell.status = "mismatch"
            else:
                cell.status = "uncertain"
            done += 1
            if progress and (done % 25 == 0 or done == total):
                progress(done, total, f"{cell.path.name} · {cell.column} · đã kiểm tra {done}/{total} ô")
    _check_cancel(cancel_callback)
    return report
