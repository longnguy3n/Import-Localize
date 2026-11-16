from pathlib import Path
from types import SimpleNamespace

import pytest

from import_localize.models.import_job import ImportJob
from import_localize.services import direct_transfer as direct
from import_localize.services import google_service as sheets
from import_localize.services.csv_service import load_csv_bundle
from import_localize.services.desc_annotations import DescAnnotations, WRONG_LANGUAGE
from import_localize.services.unity_locale_service import (
    UnityLocaleError, prepare_export_pairs, prepare_import_pairs, read_asset,
)
from test_unity_locale import ASSET


@pytest.fixture
def world(tmp_path, monkeypatch):
    asset = tmp_path / "locale_en.asset"
    asset.write_text(ASSET, encoding="utf-8")
    state = SimpleNamespace(tabs=[], payloads={}, writes=[], reads=[])
    spreadsheet = SimpleNamespace(worksheets=lambda: state.tabs)
    connection = sheets.SheetConnection(object(), object(), spreadsheet, "sample", "Demo", object())
    monkeypatch.setattr(sheets, "connect_to_spreadsheet", lambda *a, **kw: connection)

    def fetch(connection, tab, **kw):
        state.reads.append(tab.id)
        return state.payloads[tab.id]

    def write(connection, uploads, **kw):
        for bundle, job in uploads:
            state.writes.append((job.sheet_name, bundle.header, bundle.rows, job.value_input_option))
        return sum(len(bundle.rows) for bundle, _ in uploads)

    monkeypatch.setattr(sheets, "read_worksheet_csv", fetch)
    monkeypatch.setattr(sheets, "upload_bundles_fast", write)
    return state, asset


def test_direct_upload_matches_csv_route_and_preserves_preview(world, tmp_path):
    state, asset = world
    asset.write_text(ASSET.replace("Term: obsolete", "Term: 001"), encoding="utf-8")
    marks = DescAnnotations()
    marks.set_mark("en", "001", WRONG_LANGUAGE)
    plan = direct.prepare_transfer("upload", "url", [asset], annotations=marks)
    assert not state.writes
    assert not list(tmp_path.glob("*.csv"))
    assert (plan.pairs[0].tab_name, plan.pairs[0].row_count) == ("upload_en", 1)

    stats = plan.pairs[0].stats
    assert (stats.before_count, stats.after_count, stats.added) == (0, 1, 1)

    csv_path = tmp_path / "Demo - upload_en.csv"
    csv_path.write_bytes(prepare_export_pairs([asset], [csv_path], annotations=marks).changes[0].after)
    expected = load_csv_bundle(ImportJob((str(csv_path),), "url", sheet_name="upload_en"))
    marks.clear()
    direct.apply_transfer(plan, tmp_path / "backups")
    assert state.writes == [("upload_en", expected.header, expected.rows, "RAW")]
    assert expected.rows[0][0] == "001"
    assert WRONG_LANGUAGE in expected.rows[0][2]


def test_direct_download_applies_reviewed_snapshot_and_backup(world, tmp_path):
    state, asset = world
    original = asset.read_bytes()
    state.tabs = [SimpleNamespace(id=8, title="export_en"), SimpleNamespace(id=2, title="export_vi")]
    data = 'Key,Type,Desc,English\r\n001,Text,note,"  Xin chào {0}\r\nworld  "\r\n'.encode()
    state.payloads[8] = data
    plan = direct.prepare_transfer("download", "url", [asset])
    assert plan.pairs[0].stats == plan.files.changes[0].stats
    assert asset.read_bytes() == original and not list(tmp_path.glob("*.csv"))
    csv_path = tmp_path / "Demo - export_en.csv"
    csv_path.write_bytes(data)
    expected = prepare_import_pairs([csv_path], [asset], ",").changes[0].after
    state.payloads[8] = b"changed after preview"
    backup = direct.apply_transfer(plan, tmp_path / "backups")
    assert asset.read_bytes() == expected
    assert next(backup.glob("*.bak")).read_bytes() == original
    assert state.reads == [8] and not state.writes


def test_ambiguous_or_stale_pairs_block_writes(world, tmp_path):
    state, asset = world
    with pytest.raises(UnityLocaleError, match="không tìm thấy tab"):
        direct.prepare_transfer("download", "url", [asset])
    with pytest.raises(UnityLocaleError, match="cùng mã"):
        direct.prepare_transfer("upload", "url", [asset, asset])
    plan = direct.prepare_transfer("upload", "url", [asset])
    state.payloads[1] = b""
    state.tabs = [SimpleNamespace(title="upload_en", id=1)]
    with pytest.raises(UnityLocaleError, match="Tab upload_en đã thay đổi"):
        direct.apply_transfer(plan, tmp_path)
    plan = direct.prepare_transfer("upload", "url", [asset])
    asset.write_text(ASSET.replace("old description", "edited"), encoding="utf8")
    with pytest.raises(UnityLocaleError, match="đã thay đổi"):
        direct.apply_transfer(plan, tmp_path)
    assert not state.writes


def test_export_annotates_only_matching_locale_and_retains_original_bytes(world):
    base = b"Key,Type,Desc,English\r\n001,Text,old,yes\r\n"
    marks = DescAnnotations()
    marks.set_mark("vi", "001", WRONG_LANGUAGE)
    assert sheets._annotated_export(base, "export_en", marks) == base
    marks.set_mark("en", "001", WRONG_LANGUAGE)
    assert b"old\nWrong languague" in sheets._annotated_export(base, "export_en", marks)


@pytest.mark.parametrize("payload", [
    b"",
    b"Key,Type,Desc,English\n",
    b"Key,Type,Desc,Vietnamese\n001,Text,,abc\n",
    b"garbage\n#REF!\n",
])
def test_empty_or_mismatched_download_keeps_assets(world, payload):
    state, asset = world
    original = asset.read_bytes()
    state.tabs = [SimpleNamespace(id=8, title="export_en")]
    state.payloads[8] = payload
    with pytest.raises(UnityLocaleError):
        direct.prepare_transfer("download", "url", [asset])
    assert asset.read_bytes() == original


def test_region_pair_is_distinct_from_base_locale_and_ambiguous_alias_blocked(world):
    state, asset = world
    renamed = asset.with_name("locale_pt-BR.asset")
    asset.rename(renamed)
    asset = renamed
    asset.write_text(ASSET.replace("Code: en", "Code: pt-BR").replace("Name: English", "Name: Portuguese/Brazil"))
    base = SimpleNamespace(id=8, title="export_pt")
    region = SimpleNamespace(id=9, title="export_pt_BR")
    state.tabs = [base, region]
    state.payloads[9] = b"Key,Type,Desc,Portuguese/Brazil\n001,Text,,abc\n"
    plan = direct.prepare_transfer("download", "url", [asset])
    assert state.reads == [9] and plan.pairs[0].tab_id == 9
    state.tabs.append(SimpleNamespace(id=10, title="export_pt-br"))
    with pytest.raises(UnityLocaleError, match="Nhiều tab"):
        direct.prepare_transfer("download", "url", [asset])


@pytest.mark.parametrize("direction", ["upload", "download"])
def test_mislabeled_asset_is_rejected_in_either_direction(world, direction):
    state, asset = world
    wrong = asset.with_name("locale_vi.asset")
    asset.rename(wrong)
    with pytest.raises(UnityLocaleError, match="mLanguages.Code"):
        direct.prepare_transfer(direction, "url", [wrong])
    assert not state.writes and not state.reads


@pytest.mark.parametrize("direction", ["upload", "download"])
def test_folder_change_since_preview_blocks_direct_transfer(world, direction, tmp_path):
    state, asset = world
    state.tabs = [SimpleNamespace(id=5, title="export_en")]
    state.payloads[5] = b"Key,Type,Desc,en\nk,Text,,new\n"
    plan = direct.prepare_transfer(direction, "url", [asset], asset_folder=tmp_path)
    (tmp_path / "locale_vi.asset").write_text(ASSET.replace("Code: en", "Code: vi"))
    with pytest.raises(UnityLocaleError, match="thay đổi"):
        direct.apply_transfer(plan, tmp_path / "backups")
    assert asset.read_text() == ASSET and not state.writes


def test_empty_asset_will_not_clear_tab(world):
    state, asset = world
    first, last = ASSET.index("    mTerms:"), ASSET.index("    CaseInsensitiveTerms:")
    asset.write_text(ASSET[:first] + "    mTerms: []\n" + ASSET[last:])
    state.payloads[1] = b""
    state.tabs = [SimpleNamespace(title="upload_en", id=1)]
    with pytest.raises(UnityLocaleError, match="không có dòng"):
        direct.prepare_transfer("upload", "url", [asset])
    assert not state.writes

def test_direct_preview_compares_existing_tab_by_key(world):
    state, asset = world
    state.tabs = [SimpleNamespace(id=4, title="upload_en")]
    state.payloads[4] = b"Key,Type,Desc,English\nobsolete,Text,changed,old\nremoved,Text,,bye\n"
    pair = direct.prepare_transfer("upload", "url", [asset]).pairs[0]
    stats = pair.stats
    assert (stats.before_count, stats.after_count) == (2, 2)
    assert (stats.added, stats.removed, stats.updated, stats.unchanged) == (1, 1, 1, 0)
    assert state.reads == [4] and not state.writes
