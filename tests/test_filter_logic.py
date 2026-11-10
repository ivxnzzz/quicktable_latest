import unittest
import sqlite3

from quicktable.filter_logic import comparison_value, field_filter


def quote(text):
    return "'" + text.replace("'", "''").replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t") + "'"


class FieldFilterTests(unittest.TestCase):
    def test_temporal_inputs_reject_invalid_dates_and_reversed_bounds(self):
        for kind, value in (("date", "2026-02-30"), ("time", "25:00:00"),
                            ("datetime", "not a datetime")):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.build("Equals", value, kind=kind)
        with self.assertRaisesRegex(ValueError, "range start"):
            self.build("Between", "2026-11-10", "2026-11-09", kind="date")

    def build(self, operator, text="", upper="", kind="text"):
        return field_filter('"value"', operator, text, upper, kind, quote)

    def test_contains_is_a_literal_case_insensitive_substring(self):
        expression = self.build("Contains", r"50%_O'Brien\new")
        self.assertEqual(expression, 'strpos(lower(to_string("value")), lower(' + quote(r"50%_O'Brien\new") + ')) > 0')
        self.assertNotIn("ILIKE", expression)

    def test_empty_contains_does_not_filter(self):
        self.assertIsNone(self.build("Contains"))

    def test_equals_preserves_leading_zeros_and_spaces_in_text(self):
        self.assertEqual(self.build("Equals", " 00123 "), '"value" = \' 00123 \'')

    def test_equals_empty_string_is_distinct_from_is_empty(self):
        self.assertEqual(self.build("Equals", ""), '"value" = \'\'')
        self.assertIn("IS NULL", self.build("Is empty"))

    def test_integer_comparisons_keep_precision(self):
        self.assertEqual(self.build("Greater than", "9007199254740993", kind="integer"),
                         '"value" > 9007199254740993')
        self.assertEqual(self.build("Less than", "-2", kind="integer"), '"value" < -2')

    def test_numeric_comparison_supports_decimal_and_scientific_notation(self):
        self.assertEqual(self.build("Equals", "1.25", kind="number"), '"value" = 1.25')
        self.assertEqual(self.build("Equals", "1e6", kind="number"), '"value" = 1E+6')

    def test_between_includes_both_bounds(self):
        self.assertEqual(self.build("Between", "10", "20", "integer"),
                         '("value" >= 10 AND "value" <= 20)')

    def test_range_rejects_missing_and_reversed_bounds(self):
        for lower, upper in (("", "2"), ("1", ""), ("3", "2")):
            with self.subTest(lower=lower, upper=upper), self.assertRaises(ValueError):
                self.build("Between", lower, upper, "number")

    def test_numeric_inputs_reject_expressions_and_nonfinite_values(self):
        for text in ("1 OR TRUE", "NaN", "Infinity", "1e400", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.build("Equals", text, kind="number")

    def test_integer_inputs_reject_fractions_and_expressions(self):
        for text in ("1.2", "1 OR TRUE", "", "1e3"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.build("Equals", text, kind="integer")

    def test_empty_operators_ignore_stale_input(self):
        self.assertEqual(self.build("Is empty", "old", "old"),
                         '("value" IS NULL OR to_string("value") = \'\')')
        self.assertEqual(self.build("Is not empty", "old"),
                         '("value" IS NOT NULL AND to_string("value") != \'\')')

    def test_boolean_values_are_typed(self):
        self.assertEqual(self.build("Equals", "true", kind="boolean"), '"value" = TRUE')
        self.assertEqual(self.build("Equals", "0", kind="boolean"), '"value" = FALSE')
        with self.assertRaises(ValueError):
            self.build("Equals", "maybe", kind="boolean")

    def test_date_values_use_typed_literals(self):
        self.assertEqual(comparison_value("2026-11-06", "date", quote), "to_date('2026-11-06')")
        self.assertEqual(comparison_value("09:30:00", "time", quote), "to_time('09:30:00')")

    def test_multiple_integer_values_match_any_value(self):
        expression = field_filter('"barangay"', "Equals", "", "", "integer", quote, ["1", "2", "3"])
        self.assertEqual(expression, '"barangay" IN (1, 2, 3)')

    def test_multiple_text_values_keep_commas_quotes_and_leading_zeros(self):
        values = ["001", "Smith, John", "O'Brien", r"C:\new"]
        expression = field_filter('"name"', "Equals", "", "", "text", quote, values)
        self.assertEqual(expression, '"name" IN (' + ", ".join(quote(v) for v in values) + ')')

    def test_multiple_values_deduplicate_equivalent_numbers(self):
        expression = field_filter('"value"', "Equals", "", "", "integer", quote, ["1", "01", "2"])
        self.assertEqual(expression, '"value" IN (1, 2)')

    def test_multiple_values_reject_invalid_numeric_input(self):
        with self.assertRaises(ValueError):
            field_filter('"value"', "Equals", "", "", "integer", quote, ["1", "2 OR TRUE"])

    def test_without_checks_equals_uses_typed_text(self):
        self.assertEqual(field_filter('"value"', "Equals", "stale", "", "text", quote, []), '"value" = \'stale\'')

    def test_multiple_values_allow_empty_text_as_an_exact_value(self):
        self.assertEqual(field_filter('"value"', "Equals", "", "", "text", quote, ["", "A"]),
                         '"value" IN (\'\', \'A\')')

    def test_any_values_use_or_while_another_field_uses_and(self):
        # IN and equality use the same SQL semantics in this expression subset.
        with sqlite3.connect(":memory:") as database:
            database.execute("CREATE TABLE features (barangay INTEGER, status TEXT)")
            database.executemany("INSERT INTO features VALUES (?, ?)",
                                 [(1, "Open"), (2, "Closed"), (2, "Open"), (3, "Open")])
            first = field_filter('"barangay"', "Equals", "", "", "integer", quote, ["1", "2"])
            second = field_filter('"status"', "Equals", "Open", "", "text", quote)
            rows = database.execute("SELECT barangay FROM features WHERE " + first + " AND " + second).fetchall()
            self.assertEqual(rows, [(1,), (2,)])


if __name__ == "__main__":
    unittest.main()
