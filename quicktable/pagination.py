"""Page boundaries shared by the table and its navigation controls."""

from collections import namedtuple

PAGE_SIZES = (100, 250, 500, 1000, 2000, 0)
DEFAULT_PAGE_SIZE = 500
PageWindow = namedtuple("PageWindow", "page pages start stop")


def normalize_page_size(value):
    try:
        size = int(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_PAGE_SIZE
    return size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE


def page_window(total, page, size):
    """Zero-based page and slice; size zero means all results."""
    if total < 0 or size < 0:
        raise ValueError("Result count and page size cannot be negative")
    pages = max(1, (total + size - 1) // size) if size else 1
    page = min(max(0, page), pages - 1)
    start = page * size if size else 0
    stop = min(start + size, total) if size else total
    return PageWindow(page, pages, start, stop)
