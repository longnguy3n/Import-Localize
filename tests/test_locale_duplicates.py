from pathlib import Path

import pytest

from import_localize.services.locale_duplicate_service import scan_duplicates, prepare_duplicate_cleanup
from import_localize.services.unity_locale_service import apply_plan, read_asset, UnityLocaleError
from test_unity_locale import ASSET


def duplicate_asset(path, conflict=False, bom=False):
    first = ASSET[ASSET.index("    - Term: 001"):ASSET.index("    - Term: obsolete")]
    second = first.replace("- yes", "- other") if conflict else first
    text = ASSET.replace("    - Term: obsolete", second + "    - Term: obsolete")
    raw = text.encode() if not bom else b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode()
    path.write_bytes(raw)
    return raw, first, second


def test_identical_cleanup_preserves_bytes_and_meta(tmp_path):
    path = tmp_path / "locale_en.asset"
    original, _, _ = duplicate_asset(path, bom=True)
    meta = path.with_suffix(".asset.meta")
    meta.write_bytes(b"guid: unchanged")
    scan = scan_duplicates([path, path])
    assert len(scan.assets) == 1 and len(scan.groups) == 1
    assert not scan.groups[0].conflict and scan.groups[0].count == 2
    plan = prepare_duplicate_cleanup(scan, {})
    assert path.read_bytes() == original
    # Only the inserted duplicate disappears, preserving every other byte.
    assert plan.changes[0].after == b"\xef\xbb\xbf" + ASSET.replace("\n", "\r\n").encode()
    backup = apply_plan(plan, tmp_path / "backups")
    assert next(backup.glob("*.bak")).read_bytes() == original
    assert meta.read_bytes() == b"guid: unchanged"
    assert not scan_duplicates([path]).groups


def test_conflicts_require_choice_and_keep_exact_chosen_record(tmp_path):
    path = tmp_path / "locale_en.asset"
    original, first, second = duplicate_asset(path, conflict=True)
    scan = scan_duplicates([path])
    assert scan.groups[0].conflict
    for choice in ({}, {(path, "001"): -1}, {(path, "001"): 2}):
        with pytest.raises(UnityLocaleError, match="cần chọn"):
            prepare_duplicate_cleanup(scan, choice)
    plan = prepare_duplicate_cleanup(scan, {(path, "001"): 1})
    assert plan.changes[0].after == original.replace(first.encode(), b"", 1)
    apply_plan(plan, tmp_path / "backups")
    assert read_asset(path).terms[0]["Languages"] == ["other"]
    assert second.encode() in path.read_bytes()


@pytest.mark.parametrize("old,new", [
    ("Description: old description", "Description: different"),
    ("Flags: 00", "Flags: 01"),
    ("TermType: 0", "TermType: 1"),
    ("Languages_Touch: []", "Languages_Touch: [touch]"),
    ("Flags: 00", "Flags: 00\n      CustomData: {fileID: 42}"),
    ("Flags: 00", "Flags: 00\n      New: 1"),
])
def test_metadata_does_not_make_identical_translations_conflict(tmp_path, old, new):
    path = tmp_path / "locale_en.asset"
    _, first, _ = duplicate_asset(path)
    text = path.read_text()
    path.write_text(text.replace(first, first.replace(old, new), 1))
    original = path.read_bytes()
    scan = scan_duplicates([path])
    assert not scan.groups[0].conflict
    plan = prepare_duplicate_cleanup(scan, {})
    apply_plan(plan, tmp_path / "backups")
    assert not scan_duplicates([path]).groups
    assert first.replace(old, new) in path.read_bytes().decode().replace("\r\n", "\n")
    assert path.read_bytes() != original


@pytest.mark.parametrize("translation", ["new", "yes new", "yes ", "yes<br>", "Yes"])
def test_actual_language_content_is_never_ignored(tmp_path, translation):
    path = tmp_path / "locale_en.asset"
    duplicate_asset(path)
    path.write_text(path.read_text().replace("      - yes", f'      - "{translation}"', 1))
    assert scan_duplicates([path]).groups[0].conflict


def test_all_language_entries_are_compared(tmp_path):
    path = tmp_path / "locale_en.asset"
    duplicate_asset(path)
    text = path.read_text().replace("      - yes", "      - yes\n      - xin chao").replace(
        "      - Delete me", "      - Delete me\n      - xoa")
    text = text.replace("    IgnoreDeviceLanguage:", "    - Name: Vietnamese\n      Code: vi\n      Flags: 0\n    IgnoreDeviceLanguage:")
    path.write_text(text.replace("      - xin chao", "      - chao ban", 1))
    assert scan_duplicates([path]).groups[0].conflict


def test_touch_fallback_must_not_make_different_raw_records_identical(tmp_path):
    path = tmp_path / "locale_en.asset"
    _, first, _ = duplicate_asset(path)
    text = path.read_text().replace(first, first.replace("- yes", '- ""').replace("Languages_Touch: []", "Languages_Touch: [yes]"), 1)
    path.write_text(text)
    assert scan_duplicates([path]).groups[0].conflict


def test_each_file_is_independent_and_stale_plan_is_rejected(tmp_path):
    first, second = tmp_path / "locale_en.asset", tmp_path / "locale_vi.asset"
    first.write_text(ASSET)
    second.write_text(ASSET)
    assert not scan_duplicates([first, second]).groups
    duplicate_asset(first)
    scan = scan_duplicates([first, second])
    plan = prepare_duplicate_cleanup(scan, {})
    assert len(plan.changes) == 1
    old = first.read_bytes()
    second.write_bytes(second.read_bytes() + b"\n")
    with pytest.raises(UnityLocaleError, match="đã thay đổi"):
        apply_plan(plan, tmp_path / "backups")
    assert first.read_bytes() == old


def test_multiple_keys_and_three_variants(tmp_path):
    path = tmp_path / "locale_en.asset"
    _, first, _ = duplicate_asset(path, conflict=True)
    text = path.read_text().replace("    - Term: obsolete", first + first.replace("- yes", "- third") + "    - Term: obsolete")
    last = text[text.index("    - Term: obsolete"):text.index("    CaseInsensitiveTerms:")]
    path.write_text(text.replace("    CaseInsensitiveTerms:", last + "    CaseInsensitiveTerms:"))
    scan = scan_duplicates([path])
    assert [g.count for g in scan.groups] == [4, 2]
    assert [len(g.variants) for g in scan.groups] == [3, 1]
    plan = prepare_duplicate_cleanup(scan, {(path, "001"): 2})
    apply_plan(plan, tmp_path / "backups")
    assert not scan_duplicates([path]).groups
    assert read_asset(path).terms[0]["Languages"] == ["third"]


def test_no_files_no_duplicates_and_invalid_asset(tmp_path):
    with pytest.raises(UnityLocaleError):
        scan_duplicates([])
    path = tmp_path / "locale_en.asset"
    path.write_text(ASSET)
    with pytest.raises(UnityLocaleError, match="Không có key trùng"):
        prepare_duplicate_cleanup(scan_duplicates([path]), {})
    path.write_text("invalid")
    with pytest.raises(UnityLocaleError):
        scan_duplicates([path])
