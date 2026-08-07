from pathlib import Path

from import_localize.models.import_job import CsvFileInfo, ImportJob
from import_localize.services.csv_service import load_csv_bundle


def _write_csv(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_upload_en_removes_duplicate_keys_keep_first(tmp_path: Path):
    csv_path = tmp_path / "Demo - upload_en.csv"
    _write_csv(
        csv_path,
        "key,en,note\n"
        "hello,Hello,first\n"
        "bye,Bye,one\n"
        "hello,Hello again,second\n"
        "hello,Third,third\n",
    )
    info = CsvFileInfo(csv_path, csv_path.stat().st_size, "utf-8", ",", "Demo", "upload_en")
    logs = []
    job = ImportJob(
        file_paths=(str(csv_path),),
        spreadsheet_url="https://example.invalid",
        target_mode="multiple",
        sheet_name="upload_en",
        first_row_is_header=True,
    )
    bundle = load_csv_bundle(
        job,
        log_callback=logs.append,
        info_lookup={str(csv_path.resolve()): info},
    )
    assert bundle.header == ["key", "en", "note"]
    assert bundle.rows == [
        ["hello", "Hello", "first"],
        ["bye", "Bye", "one"],
    ]
    assert any("đã loại 2 dòng" in message for message in logs)


def test_upload_en_keeps_blank_keys_and_case_sensitive_keys(tmp_path: Path):
    csv_path = tmp_path / "Demo - upload_en.csv"
    _write_csv(
        csv_path,
        "KEY,en\n"
        ",Blank A\n"
        ",Blank B\n"
        "Foo,Upper\n"
        "foo,Lower\n",
    )
    info = CsvFileInfo(csv_path, csv_path.stat().st_size, "utf-8", ",", "Demo", "upload_en")
    job = ImportJob(
        file_paths=(str(csv_path),),
        spreadsheet_url="https://example.invalid",
        target_mode="multiple",
        sheet_name="UPLOAD_EN",
        first_row_is_header=True,
    )
    bundle = load_csv_bundle(
        job,
        info_lookup={str(csv_path.resolve()): info},
    )
    assert len(bundle.rows) == 4


def test_other_target_does_not_dedupe(tmp_path: Path):
    csv_path = tmp_path / "Demo - upload_vi.csv"
    _write_csv(csv_path, "key,vi\na,A\na,A2\n")
    info = CsvFileInfo(csv_path, csv_path.stat().st_size, "utf-8", ",", "Demo", "upload_vi")
    job = ImportJob(
        file_paths=(str(csv_path),),
        spreadsheet_url="https://example.invalid",
        target_mode="multiple",
        sheet_name="upload_vi",
        first_row_is_header=True,
    )
    bundle = load_csv_bundle(
        job,
        info_lookup={str(csv_path.resolve()): info},
    )
    assert len(bundle.rows) == 2
