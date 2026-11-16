from pathlib import Path

import pytest

from import_localize.services.transfer_files import (
    TransferFileError, parse_asset_filename, parse_csv_filename, parse_tab_code,
    scan_folder, validate_asset_language, validate_csv_header,
)


def test_role_specific_discovery_is_shallow_and_sorted_by_locale(tmp_path):
    for name in (
        "Book - chapter - upload_vi.csv", "upload_pt-BR.csv", "Book - upload_en.CSV",
        "Book - export_vi.csv", "locale_vi.asset", "runtime_locale_term.asset",
        "locale_vi.asset.meta", "notes.csv", "upload_en.csv.bak",
    ):
        (tmp_path / name).touch()
    nested = tmp_path / "backup"
    nested.mkdir()
    (nested / "upload_vi.csv").touch()
    upload = scan_folder(tmp_path, "upload")
    assert not upload.issues
    assert [path.name for path in upload.paths] == ["Book - upload_en.CSV", "upload_pt-BR.csv", "Book - chapter - upload_vi.csv"]
    assert scan_folder(tmp_path, "export").paths == (tmp_path / "Book - export_vi.csv",)
    assert scan_folder(tmp_path, "unity").paths == (tmp_path / "locale_vi.asset",)
    assert parse_csv_filename(upload.paths[-1], "upload") == ("Book - chapter", "vi")


def test_ambiguous_or_malformed_names_are_identified_not_selected(tmp_path):
    for name in ("upload_pt_BR.csv", "Book - upload_pt-br.csv", "upload_en!.csv", "upload_vi.csv"):
        (tmp_path / name).touch()
    result = scan_folder(tmp_path, "upload")
    assert result.paths == (tmp_path / "upload_vi.csv",)
    assert len(result.issues) == 2
    assert all(any(name in issue for issue in result.issues) for name in ("Book - upload_pt-br.csv", "upload_pt_BR.csv", "upload_en!.csv"))
    assert scan_folder(tmp_path / "missing", "unity").issues
    with pytest.raises(TransferFileError):
        parse_csv_filename("Book - upload_en.csv", "export")
    with pytest.raises(TransferFileError):
        parse_asset_filename("runtime_locale_term.asset")


@pytest.mark.parametrize(("header", "code"), [
    ("English", "en"), ("$English [en]", "en"), ("Tiếng Việt", "vi"),
    ("Portuguese (Brazil)", "pt-BR"), ("$Portuguese/Brazil [PT_br]", "PT-BR"),
    ("zh-Hant-TW", "zh_Hant_TW"), ("Spanish [es-419]", "es-419"), ("id", "id"),
])
def test_header_checks_the_precise_language(header, code):
    validate_csv_header(["Key", "Type", "Desc", header], code)
    assert parse_tab_code("upload_" + code, "upload") == code.casefold().replace("_", "-")


@pytest.mark.parametrize("columns", [
    ["Key", "Type", "Desc", "Portuguese"], ["Key", "English [pt-BR]"],
    ["Key", "Portuguese (Brazil) [pt-PT]"], ["Key", "Portuguese [pt-PT]"],
    ["Key", "Portuguese (Brazil)", "en"], ["Key", "Portuguese (Brazil)", "id"],
    ["Key", "pt-BR", "pt_br"], ["Key", "Desc"],
])
def test_wrong_ambiguous_or_missing_header_fails(columns):
    with pytest.raises(TransferFileError):
        validate_csv_header(columns, "pt-BR", "export_pt-BR.csv")


def test_asset_must_have_one_matching_internal_language():
    path = Path("locale_pt-BR.asset")
    assert validate_asset_language(path, [{"Name": "Portuguese (Brazil)", "Code": "PT_br"}]) == "pt-br"
    for languages in ([{"Name": "Portuguese", "Code": "pt"}], [{"Name": "English", "Code": "pt-BR"}],
                      [{"Name": "Portuguese (Brazil)", "Code": "pt-BR"}, {"Name": "Portuguese", "Code": "pt"}]):
        with pytest.raises(TransferFileError):
            validate_asset_language(path, languages)
