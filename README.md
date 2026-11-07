# QuickTable

Search, filter and edit vector-layer attributes in QGIS, including tables without geometry.

**Version:** 1.00 (experimental) | **Author:** Iven Paul Rolloque

## Features

- Search across fields and filter columns by values, text, ranges or empty values.
- Sort, resize, hide and wrap columns; save filters for reuse.
- Select features in sync with QGIS and find nearby features.
- Edit attributes, bulk edit, autofill and manage fields with undo/redo.
- View column statistics, browse paginated results and export spreadsheet-safe CSV.
- Customize fonts, light/dark themes and window settings.

## Requirements

QGIS 3 with Python support; no additional Python packages required.
The declared minimum is QGIS 3.16, pending compatibility testing for this release.
QGIS 4 support has not been verified.

## Installation

1. Obtain a packaged QuickTable ZIP containing a single `quicktable_latest/` folder.
2. In QGIS, open **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the ZIP, install it and enable **QuickTable** if needed.

Restart QGIS after updating an existing installation.

## Usage

1. Open **QuickTable** from the plugin menu or toolbar, or press **Ctrl+Shift+F**.
2. Choose a vector layer. Use the search box or column filters to narrow results;
   click a column name to sort.
3. Select rows to select their features in QGIS. Use **Selected only** to limit
   results to the current selection.
4. Enable edit mode to change attributes. Use **Save edits** to commit or
   **Discard edits** to roll back all pending changes on the layer.
5. Copy rows or export CSV using the toolbar.

Nearby distances use the layer CRS units. Editing requires a writable data source.

## Development

Run regression tests:

```sh
python -m unittest discover -s tests -v
```

For QGIS integration tests, use QGIS's Python environment:

```sh
python tests/run_qgis_tests.py
```

To package, place the Python modules, `metadata.txt`, icons, `README.md` and
`LICENSE` inside one `quicktable_latest/` folder and ZIP it. Exclude Git files,
caches and test outputs.

## Support

Report bugs and feature requests through
[GitHub Issues](https://github.com/ivxnzzz/quicktable_latest/issues).
Include your QGIS version, operating system and steps to reproduce.

## License

Copyright (C) 2026 Iven Paul Rolloque.
Licensed under the GNU General Public License, version 2 or later.
See [LICENSE](LICENSE) for the full terms. Distributed without warranty.
