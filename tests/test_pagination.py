import unittest

from quicktable.pagination import DEFAULT_PAGE_SIZE, normalize_page_size, page_window


class PaginationTests(unittest.TestCase):
    def test_traversal_has_no_gaps_or_duplicates(self):
        ids = list(range(2341))
        visited = []
        page = 0
        while True:
            window = page_window(len(ids), page, 100)
            visited.extend(ids[window.start:window.stop])
            if window.page + 1 == window.pages:
                break
            page += 1
        self.assertEqual(visited, ids)
        self.assertEqual(window.pages, 24)
        self.assertEqual(window.stop - window.start, 41)

    def test_all_results_does_not_keep_the_old_row_limit(self):
        window = page_window(12345, 7, 0)
        self.assertEqual((window.start, window.stop), (0, 12345))
        self.assertEqual((window.page, window.pages), (0, 1))

    def test_empty_results_have_a_valid_empty_first_page(self):
        for size in (0, 100, 500):
            with self.subTest(size=size):
                window = page_window(0, 99, size)
                self.assertEqual(tuple(window), (0, 1, 0, 0))

    def test_exact_multiple_does_not_add_an_empty_page(self):
        window = page_window(1000, 1, 500)
        self.assertEqual(tuple(window), (1, 2, 500, 1000))

    def test_shrinking_results_clamps_to_the_new_last_page(self):
        old = page_window(2500, 4, 500)
        new = page_window(650, old.page, 500)
        self.assertEqual(tuple(new), (1, 2, 500, 650))

    def test_previous_on_first_page_stays_on_first_page(self):
        self.assertEqual(page_window(900, -1, 100).page, 0)

    def test_invalid_saved_page_sizes_fall_back_to_default(self):
        for value in (None, "bad", "", -100, 42, float("inf")):
            with self.subTest(value=value):
                self.assertEqual(normalize_page_size(value), DEFAULT_PAGE_SIZE)

    def test_page_size_preferences_roundtrip(self):
        for value in (100, 250, 500, 1000, 2000, 0):
            with self.subTest(value=value):
                self.assertEqual(normalize_page_size(str(value)), value)


if __name__ == "__main__":
    unittest.main()
