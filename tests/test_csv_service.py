from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from import_localize.models.import_job import ImportJob  # noqa: E402
from import_localize.services.csv_service import (  # noqa: E402
    CsvImportError,
    HeaderMismatchError,
    load_csv_bundle,
    inspect_csv,
    parse_localization_filename,
    validate_worksheet_title,
)


class CsvServiceTests(unittest.TestCase):
    def make_file(self, directory: Path, name: str, content: str) -> Path:
        path = directory / name
        path.write_text(content, encoding="utf-8-sig")
        return path

    def test_reorders_matching_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first = self.make_file(directory, "Book - tab_a.csv", "Name,Phone\nA,0123\n")
            second = self.make_file(directory, "Book - tab_b.csv", "Phone,Name\n0456,B\n")
            job = ImportJob(
                file_paths=(str(first), str(second)),
                spreadsheet_url="https://docs.google.com/spreadsheets/d/test/edit",
                sheet_name="Data",
            )
            bundle = load_csv_bundle(job)
            self.assertEqual(bundle.header, ["Name", "Phone"])
            self.assertEqual(bundle.rows, [["A", "0123"], ["B", "0456"]])

    def test_union_headers_when_not_strict(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first = self.make_file(directory, "Book - tab_a.csv", "Name,Phone\nA,0123\n")
            second = self.make_file(directory, "Book - tab_b.csv", "Name,Email\nB,b@example.com\n")
            job = ImportJob(
                file_paths=(str(first), str(second)),
                spreadsheet_url="https://docs.google.com/spreadsheets/d/test/edit",
                sheet_name="Data",
                strict_headers=False,
            )
            bundle = load_csv_bundle(job)
            self.assertEqual(bundle.header, ["Name", "Phone", "Email"])
            self.assertEqual(bundle.rows[0], ["A", "0123", ""])
            self.assertEqual(bundle.rows[1], ["B", "", "b@example.com"])

    def test_strict_header_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first = self.make_file(directory, "Book - tab_a.csv", "Name,Phone\nA,0123\n")
            second = self.make_file(directory, "Book - tab_b.csv", "Name,Email\nB,b@example.com\n")
            job = ImportJob(
                file_paths=(str(first), str(second)),
                spreadsheet_url="https://docs.google.com/spreadsheets/d/test/edit",
                sheet_name="Data",
                strict_headers=True,
            )
            with self.assertRaises(HeaderMismatchError):
                load_csv_bundle(job)

    def test_parses_destination_tab_from_filename(self):
        source, target = parse_localization_filename(
            "DG_Localization - import_vi.csv"
        )
        self.assertEqual(source, "DG_Localization")
        self.assertEqual(target, "import_vi")

    def test_invalid_filename_is_rejected(self):
        with self.assertRaises(CsvImportError):
            parse_localization_filename("import_vi.csv")

    def test_single_mode_can_inspect_plain_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_file(Path(temp), "import_vi.csv", "Key,Text\na,Hello\n")
            info = inspect_csv(path, require_localization_name=False)
            self.assertEqual(info.target_sheet_name, "")

    def test_multi_mode_requires_formatted_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.make_file(Path(temp), "import_vi.csv", "Key,Text\na,Hello\n")
            with self.assertRaises(CsvImportError):
                inspect_csv(path, require_localization_name=True)

    def test_validates_manual_sheet_name(self):
        self.assertEqual(validate_worksheet_title(" import_vi "), "import_vi")
        with self.assertRaises(CsvImportError):
            validate_worksheet_title("bad/name")


if __name__ == "__main__":
    unittest.main()
