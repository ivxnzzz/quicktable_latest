import unittest

from quicktable.data_analysis import analyze_records, replace_text


class DataAnalysisTests(unittest.TestCase):
    def test_duplicates_support_list_and_dictionary_values(self):
        rows = [(1, ([1, 2], {"x": 3})), (2, ([1, 2], {"x": 3}))]
        self.assertEqual(analyze_records(rows, {"duplicates"})["duplicates"]["ids"], {1, 2})
    def test_duplicates_keep_null_empty_and_types_distinct(self):
        rows = [(1, (None,)), (2, (None,)), (3, ("",)), (4, ("",)),
                (5, (1,)), (6, ("1",))]
        result = analyze_records(rows, {"duplicates"})
        self.assertEqual(result["duplicates"]["groups"], 2)
        self.assertEqual(result["duplicates"]["ids"], {1, 2, 3, 4})

    def test_quality_checks_detect_missing_ranges_whitespace_and_case(self):
        rows = [(1, (None,)), (2, ("",)), (3, (" Foo ",)),
                (4, ("Foo",)), (5, ("foo",)), (6, (12,)), (7, (4,))]
        result = analyze_records(rows, {"missing", "range", "whitespace", "case"}, (5, 10))
        self.assertEqual(result["missing"]["ids"], {1, 2})
        self.assertEqual(result["range"]["ids"], {6, 7})
        self.assertEqual(result["whitespace"]["ids"], {3})
        self.assertEqual(result["case"]["ids"], {4, 5})

    def test_literal_replace_respects_case_and_null(self):
        self.assertIsNone(replace_text(None, "x", "y", False))
        self.assertEqual(replace_text(" Cat cat ", "cat", "dog", False), " dog dog ")
        self.assertEqual(replace_text("Cat cat", "cat", "dog", True), "Cat dog")
        with self.assertRaises(ValueError):
            replace_text("abc", "", "x", False)
