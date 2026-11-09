import csv
import io
import unittest

from quicktable.filter_utils import checked_float, clipboard_text, spreadsheet_rows


class NumericConversionTests(unittest.TestCase):
    def test_common_decimal_and_scientific_values(self):
        for text, expected in (("0.1", 0.1), ("-12.50", -12.5), ("1e6", 1000000.0)):
            with self.subTest(text=text):
                self.assertEqual(checked_float(text), expected)

    def test_precision_loss_is_rejected(self):
        for text in ("9007199254740993", "1.234567890123456789", "1e-400"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "precision"):
                    checked_float(text)

    def test_nonfinite_overflow_and_invalid_numbers_are_rejected(self):
        for text in ("NaN", "Infinity", "-inf", "1e400", "abc", ""):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    checked_float(text)


class SpreadsheetTests(unittest.TestCase):
    def test_formula_like_cells_and_headers_are_neutralized(self):
        values = ["=1+1", "+SUM(A1)", "-SUM(A1)", "@SUM(A1)", "  =1+1", "\t=1+1", "\r=1+1", "\n=1+1"]
        self.assertEqual(spreadsheet_rows([values]), [["'" + v for v in values]])

    def test_plain_text_is_preserved(self):
        values = ["Alice", "", "00123", "first\nsecond", 'a"b', "123.45"]
        self.assertEqual(spreadsheet_rows([values]), [values])

    def test_numeric_columns_preserve_negative_numbers_but_not_formulas(self):
        rows = [["-header", "text", "number"], ["safe", "-10", "-10"],
                ["safe", "=1+1", "-1+2"]]
        expected = [["'-header", "text", "number"], ["safe", "'-10", "-10"],
                    ["safe", "'=1+1", "'-1+2"]]
        self.assertEqual(spreadsheet_rows(rows, [2]), expected)
        self.assertEqual(list(csv.reader(io.StringIO(clipboard_text(rows, [2]), newline=""), delimiter="\t")), expected)

    def test_clipboard_roundtrip_preserves_cell_boundaries(self):
        rows = [["name", "notes"], ["Alice", 'first\tsecond\nthird "quoted"'], ["Bob", "line1\r\nline2"]]
        text = clipboard_text(rows)
        actual = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t"))
        self.assertEqual(actual, rows)

    def test_clipboard_and_csv_apply_the_same_safety_rules(self):
        rows = [["=header", "note"], ["=1+1", "embedded,comma\nnewline"]]
        clipboard = list(csv.reader(io.StringIO(clipboard_text(rows), newline=""), delimiter="\t"))
        stream = io.StringIO(newline="")
        csv.writer(stream).writerows(spreadsheet_rows(rows))
        actual = list(csv.reader(io.StringIO(stream.getvalue(), newline="")))
        self.assertEqual(clipboard, actual)
        self.assertEqual(actual[1][0], "'=1+1")


if __name__ == "__main__":
    unittest.main()
