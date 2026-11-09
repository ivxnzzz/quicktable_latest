import unittest
from decimal import Decimal

from quicktable.numeric_statistics import NumericTotal, format_stat


class NumericStatisticsTests(unittest.TestCase):
    def test_integer_total_and_display_are_exact_above_double_precision(self):
        total = NumericTotal(integer=True)
        total.add(9007199254740993)
        total.add(2)
        self.assertEqual(total.total, 9007199254740995)
        self.assertEqual(format_stat(total.total), "9007199254740995")

    def test_float_sum_survives_overflow_and_cancellation(self):
        total = NumericTotal()
        for value in (1e308, 1e308, 1.0, -1e308, -1e308):
            total.add(value)
        self.assertEqual(total.total, Decimal(1))

    def test_large_finite_total_has_a_finite_average(self):
        total = NumericTotal()
        total.add(1e308)
        total.add(1e308)
        self.assertTrue(total.total.is_finite())
        self.assertEqual(float(total.total / 2), 1e308)
