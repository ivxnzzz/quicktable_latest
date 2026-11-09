# QuickTable

Search, filter and edit vector-layer attributes in QGIS, including tables without geometry.

**Version:** 2.00 | **Author:** Iven Paul Rolloque

![QuickTable interface showing attribute filters and column statistics](https://raw.githubusercontent.com/ivxnzzz/quicktable_latest/main/docs/images/quicktable-interface.png)

Sample data: Philippine PSGC administrative boundaries from
[altcoder/philippines-psgc-shapefiles](https://github.com/altcoder/philippines-psgc-shapefiles).

## Features

- **Search and filter:** Search across attributes; filter columns with equals,
  contains, greater than, less than, between, empty and not-empty operators.
  Choose multiple values for an equals filter, combine filters across columns,
  and save named filters for reuse.
- **Browse and organize:** Sort results by a column, show or hide fields,
  resize columns, wrap text, and adjust the display of numeric values. Browse
  results by page or choose **All results**.
- **Select and find nearby:** Synchronize row selection with the QGIS layer,
  show selected features only, zoom to a page, and find features touching or
  within a distance of the current selection.
- **Edit and manage fields:** Edit cells, bulk edit selected rows, autofill
  values, add or delete multiple fields, and delete selected features. Use
  undo and redo while edits are pending.
- **Inspect and export:** Show statistics for visible columns across filtered
  results, copy rows to the clipboard, and export CSV with protection against
  spreadsheet formulas.
- **Personalize:** Choose a font, text size and light or dark theme; pin the
  window on top or collapse the selection and editing tools.

## Requirements

QGIS 3.44 or later in the 3.x series, with Python support. No additional Python
packages are required. QGIS 4 is not supported by this release.

## Installation

1. Obtain a packaged QuickTable ZIP containing a single `quicktable_latest/` folder.
2. In QGIS, open **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the ZIP, install it and enable **QuickTable** if needed.

Restart QGIS after updating an existing installation.

## Usage

Open QuickTable from the Plugins menu or toolbar, then choose a vector layer.
The current QGIS layer is selected on first open when available; after that,
choose the layer you want from QuickTable's layer list.

### Search, filter and sort

Use **Search all attributes** to search across fields. Search text is a literal,
case-insensitive substring; `%` and `_` are ordinary characters in both global
search and column Contains filters. Click the filter area beneath a column name
to choose an operator and enter or select values. An equals filter can match
any of several checked values; filters on different
columns are combined. Suggestions are drawn from a limited number of features,
so type a value if it is not listed. Use **Saved filters** to save, load or
delete named filter sets, and **Clear filters** to reset the view.

Click a column name to sort the matching results. Use **Columns** to choose
visible fields; drag a column border to resize it. The column filter menu also
offers text wrapping and numeric display formats. Numeric formatting changes
the display, not the stored value.

To resize columns to their names, open **Columns** and click **Fit widths to
column names**. The change takes effect immediately, including for hidden and
wrapped columns; you can still drag column borders afterward.

### Results, selection and statistics

Choose a page size at the bottom of the window. **All results** disables
pagination for smaller result sets. Large or wide result sets automatically
return to pages of 500. **Select page** and **Zoom to page** operate on the
current page; when using All results, they operate on all
displayed results.

Selecting rows updates the QGIS layer selection. Turn on **Multi-select** to
toggle rows without holding Ctrl, or use Ctrl and Shift when it is off. Use
**Selected only** to follow the current layer selection. **Nearby** finds
features touching or within a specified distance of selected features. Distance
is measured in layer CRS units; geographic layers use degrees.

Turn on **Statistics** to inspect visible columns across all filtered results,
not just the current page. Depending on field type, summaries include missing
and distinct counts, numeric summaries and a histogram, or common values.
Integer sums and extrema preserve their full precision. Floating-point
summaries and averages are displayed rounded to 12 significant digits.

### Editing and fields

Editing requires a writable layer. Enable **Edit mode**, then double-click a
writable cell to change it. **Bulk edit** changes one field for selected rows
after a preview. **Autofill** applies a single value, a repeating list or a
numeric sequence to selected rows or the current page, with a preview before
applying changes.

Empty text and whitespace are preserved. NULL cells display italic **NULL**;
right-click a writable cell to choose **Set cell to NULL** or **Set cell to empty
text**. In Bulk edit, use **Set NULL**; in Autofill, choose the **Set NULL**
pattern. Empty numeric or temporal input is rejected; use the explicit NULL
option instead. Integer limits, text lengths, ISO date/time syntax and hard
layer constraints are checked before changes are applied.

Use **Fields > Add field** to configure each new field and add it to the fields
list. Each field can have its own type, length and precision. Use **Fields >
Delete field** to check and confirm one or more fields to remove. **Delete
selected** removes the selected features, including their geometry.

Changes remain pending until **Save edits** commits them. Undo and redo are
available while editing. **Discard edits** rolls back all pending edits on the
layer, including edits made elsewhere in QGIS.

### Copy and export

Copy uses selected rows on the current page, or all displayed rows if none are
selected. Export CSV asks you to choose selected rows, the current page, or all
filtered results. Only visible columns are included. Full exports run in the
background without rendering every row; cancel them in the QGIS task manager.
A canceled or failed export preserves an existing destination file. NULL and
empty text both become empty CSV cells. Formula-like text is prefixed with an
apostrophe for spreadsheet safety, so exported text may differ from the
original attribute.

## Development

Repository layout:

```text
quicktable/     Plugin implementation
icons/          PNG and SVG assets
docs/images/    README screenshots
tests/          Regression and QGIS integration tests
tools/          Release packaging script
dist/           Built ZIP (ignored by Git)
```

QGIS loads the root `__init__.py` and reads `metadata.txt`.

Run regression tests:

```sh
python -m unittest discover -s tests -v
```

For QGIS integration tests, use QGIS's Python environment:

```sh
python tests/run_qgis_tests.py
```

Build the release ZIP from the repository root:

```sh
python tools/package_plugin.py
```

This creates `dist/quicktable_latest-2.00.zip` with only the runtime files,
metadata, documentation, license and icons. Development files are excluded.

Validate the built ZIP in an isolated profile:

```sh
python tools/smoke_package.py
```

Run reproducible large-layer measurements with QGIS Python:

```sh
python tools/benchmark_plugin.py
```

The QGIS runner fails on unexpected skipped tests. Set
`QUICKTABLE_TEST_POSTGIS_URI` to a disposable database connection string to run
the real PostGIS test; it creates and removes a unique test schema. Set
`QUICKTABLE_REQUIRE_POSTGIS=1` to make that test mandatory. CI includes a
disposable PostGIS service and requires all QGIS tests to execute.

The automated checks were run on Windows with QGIS 3.44.12. Linux and macOS have not
been verified.
The code uses shared Qt5/Qt6 API forms, but Qt6 runtime compatibility has not
been verified and QGIS 4 remains excluded by the plugin metadata.

## Support

Report bugs and feature requests through
[GitHub Issues](https://github.com/ivxnzzz/quicktable_latest/issues).
Include your QGIS version, operating system and steps to reproduce.

## License

Copyright (C) 2026 Iven Paul Rolloque.
Licensed under the GNU General Public License, version 2 or later.
See [LICENSE](LICENSE) for the full terms. Distributed without warranty.
