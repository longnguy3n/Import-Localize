import csv
import socket
from concurrent.futures import CancelledError
from pathlib import Path

import pytest

from import_localize.services.csv_language_service import (
    OfflineDetector, Prediction, audit_csv_languages, clean_text, declared_language,
)


@pytest.fixture(scope="module")
def detector():
    return OfflineDetector()


def write_csv(path, rows, delimiter=","):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream, delimiter=delimiter).writerows(rows)
    return path


@pytest.mark.parametrize("header,expected", [
    ("English", "en"), ("Vietnamese [vi]", "vi"), ("$English", "en"),
    ("Portuguese (Brazil) [pt-BR]", "pt"), ("pt-PT", "pt"),
    ("Chinese [zh-CN]", "zh"), ("Tiếng Việt", "vi"), ("eng", "en"),
    ("Translation", None), ("English [xx]", None),
])
def test_declared_language(header, expected):
    assert declared_language(header) == expected


def test_offline_real_detection_wrong_rows_regions_and_no_mutation(tmp_path, detector, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Language analysis must not use the network")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    path = write_csv(tmp_path / "input.csv", [
        ["Key", "Type", "Desc", "English", "Vietnamese", "Portuguese (Brazil) [pt-BR]"],
        ["a", "Text", "Ignored", "Increase damage against enemies", "Tăng sát thương lên kẻ địch", "Aumenta o dano causado aos inimigos durante a batalha"],
        ["b", "Text", "Ignored", "Tăng sát thương lên kẻ địch", "Increase damage against enemies", "Mana"],
        ["b", "Text", "Ignored", "Asmodeus", "{0}%", "OK"],
    ])
    before = path.read_bytes()
    events = []
    report = audit_csv_languages([path], detector=detector, progress=lambda *e: events.append(e))
    assert not report.errors
    assert [c.expected for c in report.columns] == ["en", "vi", "pt"]
    assert [c.cells[0].status for c in report.columns] == ["match"] * 3
    assert [c.cells[1].status for c in report.columns] == ["mismatch", "mismatch", "short"]
    assert [c.cells[2].status for c in report.columns] == ["short"] * 3
    assert report.columns[0].cells[1].line == 3
    assert report.columns[0].languages == {"en": 1, "vi": 1}
    assert path.read_bytes() == before
    assert events[-1][:2] == (9, 9)


def test_cleaning_and_unmapped_columns(tmp_path, detector):
    original = '<color=#ffffff>Increase damage</color> against enemies {0} [i2s_Touch]'
    assert clean_text(original) == "Increase damage against enemies"
    path = write_csv(tmp_path / "arbitrary.csv", [["Key", "Translation"], ["a", original]])
    cell = audit_csv_languages([path], detector=detector).columns[0].cells[0]
    assert cell.status == "unmapped" and cell.prediction.code == "en"
    assert cell.text == original


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_multiline_rows_duplicate_keys_and_metadata(tmp_path, delimiter):
    path = write_csv(tmp_path / "input.csv", [["Key", "Vietnamese"],
        ["same", "Line one\nLine two"], ["same", "Another line"]], delimiter)
    class Stub:
        def predict(self, text):
            return Prediction("en", .99, .9, True, True)
    report = audit_csv_languages([path], detector=Stub())
    assert [c.line for c in report.columns[0].cells] == [2, 4]
    assert len(report.columns[0].cells) == 2


def test_weak_prediction_never_becomes_wrong_language_warning(tmp_path):
    class Stub:
        def predict(self, text):
            return Prediction("en", .6, .25, True, True)
    path = write_csv(tmp_path / "input.csv", [["Key", "Vietnamese"], ["a", "Ambiguous sentence"]])
    cell = audit_csv_languages([path], detector=Stub()).columns[0].cells[0]
    assert cell.status == "uncertain"


def test_bad_file_does_not_hide_other_results_or_keep_partial_file(tmp_path):
    good = write_csv(tmp_path / "good.csv", [["Key", "English"], ["a", "OK"]])
    bad = write_csv(tmp_path / "bad.csv", [["Key", "English"], ["a", "Fine"], ["broken"]])
    report = audit_csv_languages([bad, good, tmp_path / "missing.csv"])
    assert len(report.errors) == 2
    assert [c.path for c in report.columns] == [good]


def test_cancel_mid_scan_does_not_return_a_completed_report(tmp_path):
    path = write_csv(tmp_path / "input.csv", [["Key", "English"], ["a", "First sentence"], ["b", "Second sentence"]])
    cancelled = False
    class Stub:
        def predict(self, text):
            nonlocal cancelled
            cancelled = True
            return Prediction("en", 1, 1, True, True)
    with pytest.raises(CancelledError):
        audit_csv_languages([path], cancel_callback=lambda: cancelled, detector=Stub())
