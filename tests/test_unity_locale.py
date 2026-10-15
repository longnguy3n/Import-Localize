from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from import_localize.services import unity_locale_service as service
from import_localize.services.unity_locale_service import (
    FileChange, LocalePlan, UnityLocaleError, apply_plan, export_csv, prepare_export,
    prepare_import, read_asset,
)


ASSET = '''%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_Script: {fileID: 11500000, guid: abc123, type: 3}
  m_Name: locale_en
  mSource:
    GoogleLiveSyncIsUptoDate: 1
    mTerms:
    - Term: 001
      TermType: 0
      Description: old description
      Languages:
      - yes
      Flags: 00
      Languages_Touch: []
    - Term: obsolete
      TermType: 0
      Description:
      Languages:
      - Delete me
      Flags: 00
      Languages_Touch: []
    CaseInsensitiveTerms: 0
    OnMissingTranslation: 1
    mTerm_AppName:
    mLanguages:
    - Name: English
      Code: en
      Flags: 0
    IgnoreDeviceLanguage: 0
    Assets:
    - {fileID: 123, guid: def456, type: 3}
    Spreadsheet_LocalFileName: F:/Original/file.csv
    Spreadsheet_LocalCSVSeparator: ','
    Spreadsheet_SpecializationAsRows: 1
    Spreadsheet_SortRows: 1
'''


@pytest.fixture
def asset(tmp_path):
    path = tmp_path / "locale_en.asset"
    path.write_bytes(b"\xef\xbb\xbf" + ASSET.replace("\n", "\r\n").encode())
    path.with_suffix(".asset.meta").write_text("guid: do-not-change\n")
    return path


def write_csv(path, rows, delimiter=","):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream, delimiter=delimiter).writerows(rows)
    return path


def test_import_replace_unicode_and_metadata(asset, tmp_path):
    original = asset.read_bytes()
    translation = '  Tiếng Việt, "quoted"\n{0} <color=#fff>😀</color>\u0085\u2028\u2029  '
    source = write_csv(tmp_path / "translated.csv", [
        ["Key", "Type", "Desc", "English"],
        ["001", "Text", "new\ndescription", translation],
        ["new", "Sprite", "", "sprite_name"],
    ])
    plan = prepare_import([asset], [source])
    assert "thêm 1, xóa 1" in plan.changes[0].summary
    assert asset.read_bytes() == original  # preview is read-only
    backup = apply_plan(plan, tmp_path / "backups")
    loaded = read_asset(asset)
    assert [t["Term"] for t in loaded.terms] == ["001", "new"]
    assert loaded.terms[0]["Languages"] == [translation]
    assert loaded.terms[0]["Description"] == "new\ndescription"
    assert loaded.terms[1]["TermType"] == "5"
    assert loaded.original.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in loaded.original
    assert loaded.text[:loaded.spans["mTerms"][0]] == original.decode("utf-8-sig").split("    mTerms:")[0]
    for field in ("CaseInsensitiveTerms", "OnMissingTranslation", "Assets", "Spreadsheet_LocalFileName"):
        before_asset = tmp_path / "before.asset"
        before_asset.write_bytes(original)
        old = read_asset(before_asset)
        assert old.text[slice(*old.spans[field])] == loaded.text[slice(*loaded.spans[field])]
    assert asset.with_suffix(".asset.meta").read_text() == "guid: do-not-change\n"
    manifest = json.loads((backup / "manifest.json").read_text())
    assert (backup / manifest[0]["backup"]).read_bytes() == original


def test_duplicate_empty_dash_and_specializations(asset, tmp_path):
    source = write_csv(tmp_path / "input.csv", [
        ["Key", "Type", "Desc", "$English [en]"],
        ["same", "Text", "first", "base"],
        ["same", "Text", "second", ""],
        ["same[touch]", "Text", "third", "tap"],
        ["clear", "Text", "", "old"],
        ["clear", "Text", "", "-"],
    ])
    plan = prepare_import([asset], [source])
    assert plan.changes[0].warnings
    apply_plan(plan, tmp_path / "backups")
    loaded = read_asset(asset)
    assert len(loaded.terms) == 2
    assert loaded.terms[0]["Languages"] == ["base[i2s_Touch]tap"]
    assert loaded.terms[0]["Description"] == "third"
    assert loaded.terms[1]["Languages"] == [""]
    assert loaded.languages[0]["Flags"] == "1"
    rows = list(csv.reader(io.StringIO(export_csv(loaded).decode("utf-8-sig"))))
    assert rows[0] == ["Key", "Type", "Desc", "$English"]
    assert rows[-2][0::3] == ["same", "base"]
    assert rows[-1][0::3] == ["same[Touch]", "tap"]


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_export_import_cycle_and_scalar_strings(asset, tmp_path, delimiter):
    output = prepare_export([asset], tmp_path, "DG_Localization", delimiter)
    assert output.changes[0].path.name == "DG_Localization - upload_en.csv"
    apply_plan(output, tmp_path / "backups")
    incoming = prepare_import([asset], [output.changes[0].path])
    apply_plan(incoming, tmp_path / "backups")
    assert read_asset(asset).terms[0]["Languages"] == ["yes"]
    assert read_asset(asset).terms[0]["Term"] == "001"


@pytest.mark.parametrize("rows", [
    [["Wrong", "English"], ["key", "value"]],
    [["Key", "Vietnamese"], ["key", "value"]],
    [["Key", "English", "English"], ["key", "v", "v"]],
    [["Key", "Type", "Desc", "English"], ["key", "Text", "missing"]],
    [["Key", "English"]],
    [["Key", "English"], ["<empty>", "v"]],
])
def test_invalid_csv_never_writes(asset, tmp_path, rows):
    before = asset.read_bytes()
    source = write_csv(tmp_path / "bad.csv", rows)
    with pytest.raises(UnityLocaleError):
        prepare_import([asset], [source])
    assert asset.read_bytes() == before


@pytest.mark.parametrize("changed", ["source", "target"])
def test_stale_preview_rejected(asset, tmp_path, changed):
    source = write_csv(tmp_path / "input.csv", [["Key", "English"], ["key", "value"]])
    plan = prepare_import([asset], [source])
    path = source if changed == "source" else asset
    path.write_bytes(path.read_bytes() + b"\n")
    before = asset.read_bytes()
    with pytest.raises(UnityLocaleError, match="xem trước"):
        apply_plan(plan, tmp_path / "backups")
    assert asset.read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_batch_mapping_and_missing_or_ambiguous_csv(asset, tmp_path):
    vi = tmp_path / "locale_vi.asset"
    vi.write_text(ASSET.replace("English", "Vietnamese").replace("Code: en", "Code: vi"))
    en_csv = write_csv(tmp_path / "one.csv", [["Key", "English"], ["key", "en"]])
    vi_csv = write_csv(tmp_path / "two.csv", [["Key", "Vietnamese"], ["key", "vi"]])
    plan = prepare_import([asset, vi], [vi_csv, en_csv])
    assert [c.path for c in plan.changes] == [vi.resolve(), asset.resolve()]
    with pytest.raises(UnityLocaleError):
        prepare_import([asset, vi], [en_csv])
    with pytest.raises(UnityLocaleError):
        prepare_import([asset], [en_csv, en_csv])
    other = tmp_path / "locale_en_copy.asset"
    other.write_bytes(asset.read_bytes())
    with pytest.raises(UnityLocaleError):
        prepare_import([asset, other], [en_csv])
    with pytest.raises(UnityLocaleError):
        prepare_export([asset, other], tmp_path)


def test_batch_rollback_after_second_replace_fails(tmp_path, monkeypatch):
    first, second = tmp_path / "one.csv", tmp_path / "two.csv"
    first.write_bytes(b"old")
    plan = LocalePlan([FileChange(first, b"old", b"new", ""), FileChange(second, None, b"new", "")], {})
    original_replace = service.os.replace
    def fail_second(src, dst):
        if dst == second:
            raise PermissionError("locked")
        return original_replace(src, dst)
    monkeypatch.setattr(service.os, "replace", fail_second)
    with pytest.raises(UnityLocaleError, match="khôi phục"):
        apply_plan(plan, tmp_path / "backups")
    assert first.read_bytes() == b"old"
    assert not second.exists()
    assert not list(tmp_path.glob(".import-localize-*"))
    assert list((tmp_path / "backups").rglob("manifest.json"))


def test_backup_failure_prevents_all_writes(asset, tmp_path, monkeypatch):
    source = write_csv(tmp_path / "input.csv", [["Key", "English"], ["key", "value"]])
    plan = prepare_import([asset], [source])
    before = asset.read_bytes()
    original = Path.write_bytes
    def fail_backup(path, data):
        if path.suffix == ".bak":
            raise OSError("disk full")
        return original(path, data)
    monkeypatch.setattr(Path, "write_bytes", fail_backup)
    with pytest.raises(UnityLocaleError):
        apply_plan(plan, tmp_path / "backups")
    assert asset.read_bytes() == before


def test_specialization_fallback_raw_export_and_literal_newlines(asset):
    loaded = read_asset(asset)
    loaded.terms[0]["Languages"] = ["[i2nt]base[/i2nt]\\nline[i2s_Touch]tap[i2s_Android]android"]
    rows = list(csv.reader(io.StringIO(export_csv(loaded).decode("utf-8-sig"))))
    assert rows[1][3] == "base\nline"
    assert rows[2][3] == "tap"
    assert rows[3][3] == "android"
    assert service._get_translation("base[i2s_Touch]tap", "IOS") == "tap"
    loaded.specialization_rows = False
    rows = list(csv.reader(io.StringIO(export_csv(loaded).decode("utf-8-sig"))))
    assert rows[1][3].startswith("[i2nt]base[/i2nt]\nline[i2s_Touch]")


def test_key_normalization(asset, tmp_path):
    source = write_csv(tmp_path / "input.csv", [["Key", "English"], [" Default\\folder\\<b>Name</b> ", "value"]])
    plan = prepare_import([asset], [source])
    apply_plan(plan, tmp_path / "backups")
    assert read_asset(asset).terms[0]["Term"] == "folder/Name"


def test_explicit_import_pairs_do_not_rematch_languages(asset, tmp_path):
    vi = tmp_path / "locale_vi.asset"
    vi.write_text(ASSET.replace("English", "Vietnamese").replace("Code: en", "Code: vi"))
    en_csv = write_csv(tmp_path / "en.csv", [["Key", "English"], ["key", "en"]])
    vi_csv = write_csv(tmp_path / "vi.csv", [["Key", "Vietnamese"], ["key", "vi"]])
    before = {p: p.read_bytes() for p in (asset, vi)}
    with pytest.raises(UnityLocaleError, match="Hàng 1"):
        service.prepare_import_pairs([en_csv, vi_csv], [vi, asset])
    assert all(p.read_bytes() == raw for p, raw in before.items())
    plan = service.prepare_import_pairs([vi_csv, en_csv], [vi, asset])
    assert [c.path for c in plan.changes] == [vi, asset]


def test_explicit_pairs_require_complete_unique_targets(asset, tmp_path):
    source = write_csv(tmp_path / "en.csv", [["Key", "English"], ["key", "value"]])
    with pytest.raises(UnityLocaleError, match="cùng số file"):
        service.prepare_import_pairs([source], [])
    with pytest.raises(UnityLocaleError, match="trùng"):
        service.prepare_import_pairs([source, source], [asset, asset])
    with pytest.raises(UnityLocaleError, match="trùng"):
        service.prepare_export_pairs([asset, asset], [source, source])
    with pytest.raises(UnityLocaleError, match="đuôi"):
        service.prepare_export_pairs([asset], [tmp_path / "wrong.asset"])
    with pytest.raises(UnityLocaleError, match="không tồn tại"):
        service.prepare_export_pairs([asset], [tmp_path / "missing" / "out.csv"])


def test_explicit_export_overwrites_chosen_csv_and_preserves_source(asset, tmp_path):
    original = asset.read_bytes()
    target = tmp_path / "custom.csv"
    target.write_bytes(b"old content")
    plan = service.prepare_export_pairs([asset], [target])
    assert target.read_bytes() == b"old content"
    assert plan.changes[0].path == target
    backup = apply_plan(plan, tmp_path / "backups")
    assert target.read_bytes() == export_csv(read_asset(asset))
    assert asset.read_bytes() == original
    assert next(backup.glob("*.bak")).read_bytes() == b"old content"
