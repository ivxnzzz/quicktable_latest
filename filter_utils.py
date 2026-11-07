"""Conversions and spreadsheet serialization independent of QGIS."""

import csv
import io
import math
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


def spreadsheet_cell(value):
    """Keep untrusted text from being interpreted as a spreadsheet formula."""
    text = str(value)
    # Spreadsheet applications may ignore whitespace before a formula marker.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def spreadsheet_rows(rows):
    return [[spreadsheet_cell(cell) for cell in row] for row in rows]


def clipboard_text(rows):
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter="\t", lineterminator="\r\n").writerows(spreadsheet_rows(rows))
    return stream.getvalue()
