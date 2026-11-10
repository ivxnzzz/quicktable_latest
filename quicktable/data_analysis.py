"""Literal text replacement helpers."""

import re


def replace_text(value, needle, replacement, case_sensitive):
    if not needle:
        raise ValueError("Enter text to find")
    if value is None:
        return None
    if case_sensitive:
        return value.replace(needle, replacement)
    return re.sub(re.escape(needle), lambda match: replacement, value, flags=re.IGNORECASE)
