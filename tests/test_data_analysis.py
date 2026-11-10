import unittest

from quicktable.data_analysis import replace_text


class DataAnalysisTests(unittest.TestCase):
    def test_literal_replace_respects_case_and_null(self):
        self.assertIsNone(replace_text(None, "x", "y", False))
        self.assertEqual(replace_text(" Cat cat ", "cat", "dog", False), " dog dog ")
        self.assertEqual(replace_text("Cat cat", "cat", "dog", True), "Cat dog")
        with self.assertRaises(ValueError):
            replace_text("abc", "", "x", False)
