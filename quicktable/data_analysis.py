"""Pure helpers for attribute analysis and literal replacement."""

import re
from collections import defaultdict
from numbers import Real


def _key(value):
    if isinstance(value, dict):
        return ("dict", frozenset((_key(k), _key(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(_key(v) for v in value))
    try:
        hash(value)
        return (type(value).__name__, value)
    except TypeError:
        return (type(value).__name__, str(value))


def replace_text(value, needle, replacement, case_sensitive):
    if not needle:
        raise ValueError("Enter text to find")
    if value is None:
        return None
    if case_sensitive:
        return value.replace(needle, replacement)
    return re.sub(re.escape(needle), lambda match: replacement, value, flags=re.IGNORECASE)


def analyze_records(rows, checks, bounds=None, canceled=lambda: False):
    """Analyze (feature id, tuple of values); return IDs and group counts."""
    results = {name: {"ids": set(), "groups": 0} for name in checks}
    duplicates = defaultdict(list)
    cases = defaultdict(lambda: defaultdict(set))
    for fid, values in rows:
        if canceled():
            return None
        if "duplicates" in checks:
            duplicates[tuple(_key(v) for v in values)].append(fid)
        for index, value in enumerate(values):
            if "missing" in checks and (value is None or value == ""):
                results["missing"]["ids"].add(fid)
            if "range" in checks and isinstance(value, Real) and not isinstance(value, bool):
                if bounds is not None and not bounds[0] <= value <= bounds[1]:
                    results["range"]["ids"].add(fid)
            if isinstance(value, str):
                if "whitespace" in checks and value != value.strip():
                    results["whitespace"]["ids"].add(fid)
                if "case" in checks and value:
                    cases[(index, value.casefold())][value].add(fid)
    for group in duplicates.values():
        if len(group) > 1:
            results["duplicates"]["groups"] += 1
            results["duplicates"]["ids"].update(group)
    for variants in cases.values():
        if len(variants) > 1:
            results["case"]["groups"] += 1
            for ids in variants.values():
                results["case"]["ids"].update(ids)
    return results
