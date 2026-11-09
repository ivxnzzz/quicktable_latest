"""Bounded-memory numeric totals without integer rounding or float overflow."""

from decimal import Context, Decimal


class NumericTotal:
    def __init__(self, integer=False):
        self.integer = integer
        self.total = 0 if integer else Decimal(0)
        # Covers the entire finite double exponent range, including cancellation
        # between subnormal and very large values, plus ample counting headroom.
        self.context = Context(prec=1100)

    def add(self, value):
        if self.integer:
            self.total += int(value)
        else:
            self.total = self.context.add(self.total, Decimal.from_float(float(value)))


def format_stat(value, digits=12):
    return str(value) if isinstance(value, int) else format(value, ".{}g".format(digits))
