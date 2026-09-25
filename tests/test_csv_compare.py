from __future__ import annotations

import sys
import tempfile
import unittest
from concurrent.futures import CancelledError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from import_localize.services.csv_compare_service import compare_csv_files
from import_localize.services.csv_service import CsvImportError


class CsvCompareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = Path(self.temp.name) / "old.csv"
        self.new = Path(self.temp.name) / "new.csv"

    def compare(self, old, new):
        self.old.write_text(old, encoding="utf-8-sig", newline="")
        self.new.write_text(new, encoding="utf-8", newline="")
        return compare_csv_files(self.old, self.new)

    def test_key_and_column_reordering_is_unchanged(self):
        result = self.compare("key,en,vi\na,Hi,Chào\nb,Bye,Tạm biệt\n", "vi,key,en\nTạm biệt,b,Bye\nChào,a,Hi\n")
        self.assertEqual(result.count("unchanged"), 2)
        self.assertEqual(result.count("changed"), 0)

    def test_counts_keys_and_exposes_values_and_new_columns(self):
        result = self.compare("key,en,vi\na,Hi,Chào\nb,Bye,Tạm biệt\nd,Old,Cũ\n", "key,en,vi\nb,Goodbye,Tạm biệt!\na,Hi,Chào\nc,New,Mới\n")
        self.assertEqual([result.count(s) for s in ("added", "removed", "changed", "unchanged")], [1, 1, 1, 1])
        diffs = {item.key: item for item in result.differences}
        self.assertEqual(diffs["c"].after, {"en": "New", "vi": "Mới"})
        self.assertEqual(diffs["b"].changed_columns, ("en", "vi"))
        self.assertEqual(diffs["d"].status, "removed")

    def test_missing_column_differs_from_empty_value(self):
        result = self.compare("key,en\na,Hi\n", "key,vi\na,\n")
        self.assertEqual(result.added_columns, ("vi",))
        self.assertEqual(result.removed_columns, ("en",))
        self.assertEqual(result.differences[0].changed_columns, ("en", "vi"))

    def test_preserves_whitespace_multiline_quotes_and_key_case(self):
        result = self.compare('key,en\na,"Hello, ""world""\nHi"\nA,test\n', 'KEY;en\na;"Hello, ""world""\nHi "\nA;test\n')
        self.assertEqual(result.count("changed"), 1)
        self.assertEqual(result.count("unchanged"), 1)
        self.assertEqual(result.differences[0].after["en"], 'Hello, "world"\nHi ')

    def test_swapping_direction_reverses_added_removed(self):
        self.compare("key,en\na,Hi\n", "key,en\na,Hi\nb,New\nc,Another\n")
        result = compare_csv_files(self.new, self.old)
        self.assertEqual(result.count("removed"), 2)
        self.assertEqual(result.count("added"), 0)

    def test_rejects_ambiguous_or_malformed_data(self):
        for data in ("", "id,en\na,Hi\n", "key,en,EN\na,x,y\n", "key,en\na,Hi\na,Again\n", "key,en\n,Hi\n", "key,en\na,x,y\n", 'key,en\na,"unfinished'):
            with self.subTest(data=data), self.assertRaises(CsvImportError):
                self.compare(data, "key,en\na,Hi\n")

    def test_header_only_short_rows_and_blank_lines(self):
        result = self.compare("key,en\n", "key,en\n\na\n")
        self.assertEqual(result.count("added"), 1)
        self.assertEqual(result.differences[0].after, {"en": ""})

    def test_key_only_files(self):
        result = self.compare("key\na\n", "key\na\nb\n")
        self.assertEqual(result.count("added"), 1)
        self.assertEqual(result.count("unchanged"), 1)

    def test_cancel(self):
        with self.assertRaises(CancelledError):
            compare_csv_files(self.old, self.new, cancel_callback=lambda: True)

    def test_invalid_utf8(self):
        self.old.write_bytes(b"key,en\na,\xff\n")
        self.new.write_text("key,en\n", encoding="utf-8")
        with self.assertRaises(CsvImportError):
            compare_csv_files(self.old, self.new)


if __name__ == "__main__":
    unittest.main()
