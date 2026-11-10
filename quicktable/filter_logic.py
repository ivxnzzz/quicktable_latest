"""Build simple field filters without depending on Qt or live QGIS layers."""

import math
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation


FILTER_OPERATORS = ("Equals", "Contains", "Greater than", "Less than", "Between",
                    "Is empty", "Is not empty")


def comparison_value(text, kind, quote):
    if kind == "integer":
        if not re.fullmatch(r"[+-]?\d+", text.strip()):
            raise ValueError("Enter a whole number")
        return str(int(text))
    if kind == "number":
        try:
            value = Decimal(text.strip())
            if not value.is_finite() or not math.isfinite(float(value)):
                raise ValueError("Enter a finite number")
        except (InvalidOperation, OverflowError):
            raise ValueError("Enter a valid number")
        return str(value)
    if kind == "boolean":
        value = text.strip().lower()
        if value not in ("true", "false", "1", "0"):
            raise ValueError("Enter true or false")
        return "TRUE" if value in ("true", "1") else "FALSE"
    literal = quote(text)
    if kind in ("date", "datetime", "time"):
        try:
            {"date": date, "datetime": datetime, "time": time}[kind].fromisoformat(text.strip())
        except ValueError:
            raise ValueError("Enter a valid ISO {}".format(kind))
        return "to_{}({})".format(kind, literal)
    return literal


def field_filter(column, operator, text, upper, kind, quote, values=()):
    """Return a QGIS expression; column and quote come from QgsExpression."""
    if operator not in FILTER_OPERATORS:
        raise ValueError("Choose a filter operator")
    if operator == "Equals" and values:
        literals = list(dict.fromkeys(comparison_value(value, kind, quote) for value in values))
        return "{} IN ({})".format(column, ", ".join(literals))
    if operator == "Is empty":
        return "({0} IS NULL OR to_string({0}) = '')".format(column)
    if operator == "Is not empty":
        return "({0} IS NOT NULL AND to_string({0}) != '')".format(column)
    if operator == "Contains":
        if not text:
            return None
        # Literal substring matching: %, _ and backslashes are not wildcards.
        return "strpos(lower(to_string({})), lower({})) > 0".format(column, quote(text))
    if operator == "Between":
        if not text.strip() or not upper.strip():
            raise ValueError("Enter both ends of the range")
        if kind in ("integer", "number"):
            low = comparison_value(text, kind, quote)
            high = comparison_value(upper, kind, quote)
            if Decimal(low) > Decimal(high):
                raise ValueError("The range start must not exceed its end")
        else:
            low = comparison_value(text, kind, quote)
            high = comparison_value(upper, kind, quote)
            if kind in ("date", "datetime", "time"):
                parser = {"date": date, "datetime": datetime, "time": time}[kind].fromisoformat
                try:
                    reversed_bounds = parser(text.strip()) > parser(upper.strip())
                except TypeError:
                    raise ValueError("Use matching time zones for both range bounds")
                if reversed_bounds:
                    raise ValueError("The range start must not exceed its end")
        return "({0} >= {1} AND {0} <= {2})".format(column, low, high)
    literal = comparison_value(text, kind, quote)
    symbol = {"Equals": "=", "Greater than": ">", "Less than": "<"}[operator]
    return "{} {} {}".format(column, symbol, literal)
