# QuickTable

Search, filter and edit vector-layer attributes in QGIS, including tables without geometry.

**Version:** 2.0 | **Author:** Iven Paul Rolloque

![QuickTable interface showing attribute filters and column statistics](https://raw.githubusercontent.com/ivxnzzz/quicktable_latest/main/docs/images/quicktable-interface.png)

Sample data: Philippine PSGC administrative boundaries from
[altcoder/philippines-psgc-shapefiles](https://github.com/altcoder/philippines-psgc-shapefiles).

## Features

- Search across fields and filter columns by values, text, ranges or empty values.
- Sort, resize, hide and wrap columns; save filters for reuse.
- Select features in sync with QGIS and find nearby features.
- Edit attributes, bulk edit, autofill and manage fields with undo/redo.
- View column statistics, browse paginated results and export spreadsheet-safe CSV.
- Customize fonts, light/dark themes and window settings.

## Requirements

QGIS 3.44 or later in the 3.x series, with Python support. No additional Python
packages are required. QGIS 4 is not supported by this release.

## Installation

1. Obtain a packaged QuickTable ZIP containing a single `quicktable_latest/` folder.
2. In QGIS, open **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the ZIP, install it and enable **QuickTable** if needed.

Restart QGIS after updating an existing installation.

## Usage

1. Open QuickTable from the Plugins menu or toolbar.
2. Choose a vector layer. Use the search box or column filters to narrow results;
   click a column name to sort.
3. Select rows to select their features in QGIS. Use **Selected only** to limit
   results to the current selection.
4. Enable edit mode to change attributes. Use **Save edits** to commit or
   **Discard edits** to roll back all pending changes on the layer.
5. Copy rows or export CSV using the toolbar.

Nearby distances use the layer CRS units. Editing requires a writable data source.

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

This creates `dist/quicktable_latest-2.0.zip` with only the runtime files,
metadata, documentation, license and icons. Development files are excluded.

The verified target is Windows with QGIS 3.44.12. Linux and macOS have not
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
