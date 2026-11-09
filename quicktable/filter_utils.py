"""Conversions and spreadsheet serialization independent of QGIS."""

import csv
import io
import math
import re
from decimal import Decimal, InvalidOperation


def checked_float(text):
    """Reject overflow and decimal digits that a QGIS double cannot preserve."""
    try:
        exact = Decimal(text)
        value = float(text)
    except (ValueError, InvalidOperation, OverflowError):
        raise ValueError("Enter a valid number")
    if not math.isfinite(value) or Decimal(str(value)) != exact:
        raise ValueError("This number cannot be stored without losing precision")
    return value


def spreadsheet_cell(value, numeric=False):
    """Keep untrusted text from being interpreted as a spreadsheet formula."""
    text = str(value)
    if numeric and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        return text
    # Spreadsheet applications may ignore whitespace before a formula marker.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def spreadsheet_rows(rows, numeric_columns=()):
    numeric_columns = set(numeric_columns)
    return [[spreadsheet_cell(cell, numeric=index in numeric_columns and row_index > 0)
             for index, cell in enumerate(row)] for row_index, row in enumerate(rows)]


def clipboard_text(rows, numeric_columns=()):
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter="\t", lineterminator="\r\n").writerows(spreadsheet_rows(rows, numeric_columns))
    return stream.getvalue()
