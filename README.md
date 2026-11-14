# ⚡ QuickTable

Search, filter and edit vector-layer attributes in QGIS—even tables without geometry.

**Version 2.6** · QGIS 3.44+ (3.x) · By Iven Paul Rolloque

![QuickTable interface with attribute filters and column statistics](https://raw.githubusercontent.com/ivxnzzz/quicktable_qgis/main/docs/images/quicktable-interface.png)

_Sample data: Philippine PSGC boundaries from [altcoder/philippines-psgc-shapefiles](https://github.com/altcoder/philippines-psgc-shapefiles)._

## ✨ Features

- **Find records:** Search all attributes, combine column conditions, and select multiple values within a filter.
- **Save views:** Save and restore searches, column filters, sorting, and visible columns for a layer.
- **Organize tables:** Sort, hide, resize and wrap columns; customize numeric display and browse by page.
- **Preview features:** See selected and nearby features on an interactive map, inspect touching features, and label features using a layer field.
- **Work with selections:** Keep table and QGIS selections in sync and jump to a feature's table row from the preview.
- **Explore and clean data:** Preview case-sensitive or case-insensitive find-and-replace edits across writable text fields.
- **Edit attributes:** Update cells, bulk edit, autofill values or number sequences, manage fields and delete features with undo/redo.
- **Inspect and export:** View statistics across filtered results, copy rows and export CSV in the background.
- **Make it yours:** Choose light/dark themes, fonts, text size and window pinning.

## 📦 Install

**QuickTable is available as a stable release** in the [QGIS Plugin Repository](https://plugins.qgis.org/).

1. Open **Plugins → Manage and Install Plugins**.
2. In **All**, search for **QuickTable**.
3. Select it and click **Install Plugin**. If already installed, use **Upgrade Plugin** when available.

Prefer a ZIP? Build the package below, choose **Install from ZIP** and select `quicktable_latest-2.6.zip`.

Restart QGIS after updating.

Requires QGIS **3.44 or later in the 3.x series**. No extra Python packages are needed. QGIS 4 is not supported.

## 🚀 Quick start

1. Open **QuickTable** from the Plugins menu or toolbar (or use the toolbar dropdown arrow / **Plugins → QuickTable** items: *Open All Features*, *Open Selected Features*, *Open Visible on Map*, *Open Edited and New*), then choose a vector layer.
2. Type in **Search all attributes**, or click beneath a column name to filter. Click the name to sort.
3. Select rows to select features in QGIS and click **Zoom to selected** whenever you want to zoom the map to them. Use the **Scope** selector to narrow the view to **All features**, **Selected features**, **Visible on map**, or **Edited and new**.
4. Enable **Edit mode** to change writable cells, or use **Bulk edit** and **Autofill**. Choose **Save edits** to commit.
5. Turn on **Statistics**, copy rows from the current page, or use **Export CSV** to export selected rows, the current page or all filtered results.

### Filters and saved views

Click the filter area beneath a column heading to choose a condition: **Equals**, **Contains**, **Greater than**, **Less than**, **Between**, **Is empty**, or **Is not empty**. For **Equals**, check several values to match any of them. Filters on different columns are combined, and the search box narrows the results further. Search and contains filters match literal text, including `%` and `_`.

Use **Saved filters** to save and restore the search, column filters, sort order, and hidden columns for the current layer. The same column menu offers text wrapping and numeric display formats; formatting changes the display only, not the stored values.

### Editing and data cleanup

Enable **Edit mode** on a writable layer, then double-click a cell. **Bulk edit** changes one field for selected rows on the current page. **Autofill** works on selected rows or the current page and can set one value, generate a number sequence, repeat a list of values, or set NULL. Both tools show a preview before applying changes.

**Find and replace** searches one or all writable text columns. Choose selected rows on the current page, all filtered results, or the entire layer; review the automatic preview before applying. Edits remain undoable until saved. Field management and feature deletion are also available when supported by the layer.

### Statistics and export

Enable **Statistics** to summarize visible columns across all filtered results, rather than just the current page. Copy uses selected rows on the current page, or the whole page when no rows are selected. **Export CSV** offers selected rows on the current page, the current page, or all filtered results. Both use visible columns and protect spreadsheet cells from formula-like text; NULL and empty text export as blank cells.

### Features Preview

With **Features Preview** enabled, select a feature in the table or QGIS to show it in green alongside touching features in gray (or dashed amber when outside the current table or visible map). When nothing is selected, the sidebar asks you to select a feature. The preview does not filter the table.

- **Navigate:** Drag to pan and use the mouse wheel to zoom. The map centers on a new selection while retaining its zoom level. Click a displayed feature to select it and bring its row into view, including on another page. Active table filters still apply, and **Visible on map** limits preview clicks to features currently in that view.
- **Show labels:** Under **Labels**, choose a field such as a lot number. Labels appear on selected and touching features and follow each feature's shape.
- **Hide or reopen:** Click **Close** on the sidebar, or use the **Features Preview** toolbar button.

Previews stop after 100+ touching features or 50,000 checked candidates and keep the table unchanged.

### 💡 Keep in mind

- **NULL and blank text differ:** Right-click a writable cell to set NULL or empty text. Spaces are preserved.
- **Discard edits affects the whole layer**, including pending edits made elsewhere in QGIS.
- Large result sets stay paginated. Export all matches directly through **Export CSV**.

## 🛠️ Development

Run these commands from the repository root. Use **QGIS's Python environment** for the integration suite and package smoke test.

```sh
python -m unittest discover -s tests -v
python tests/run_qgis_tests.py
python tools/package_plugin.py
python tools/smoke_package.py
```

GitHub Actions runs `python3 tests/run_qgis_tests.py --skip-postgis` to exclude
the live database test. Local runs keep it available: configure
`QUICKTABLE_TEST_POSTGIS_URI` and set `QUICKTABLE_REQUIRE_POSTGIS=1` to require
PostGIS verification against a disposable database.

The build creates `dist/quicktable_latest-2.6.zip`. See the [remediation guide](https://github.com/ivxnzzz/quicktable_qgis/blob/main/docs/remediation-guide.md) and [performance notes](https://github.com/ivxnzzz/quicktable_qgis/blob/main/docs/performance.md) for validation details and limits.

Automated checks have been run on **Windows with QGIS 3.44.12**. Linux and macOS remain unverified.

### Folder structure

```text
quicktable_qgis/
├── __init__.py                  # QGIS plugin classFactory entry point
├── metadata.txt                 # QGIS plugin metadata and changelog
├── README.md                    # Documentation
├── LICENSE                      # GNU GPL v2 or later
├── quicktable/                  # Plugin implementation modules
│   ├── __init__.py
│   ├── layer_filter.py          # Plugin orchestration, toolbar scopes, and main dialog UI
│   ├── compact_filters.py       # Column-header controls and cell text presentation
│   ├── filter_widgets.py        # Multi-select checkable Equals dropdown popup
│   ├── filter_logic.py          # Filter expression builder (Qt/QGIS independent)
│   ├── filter_utils.py          # Numeric conversions and spreadsheet serialization
│   ├── editing.py               # Typed attribute conversion and layer-constraint validation
│   ├── data_analysis.py         # Literal text replacement helpers
│   ├── numeric_statistics.py    # Exact integer and bounded-memory Decimal totals
│   ├── pagination.py            # Page boundary calculations
│   ├── preview_panel.py         # Interactive Features Preview sidebar and map-anchored labels
│   ├── table_actions.py         # Schema management and batch editing actions
│   ├── dialogs.py               # Settings, field, bulk edit, find/replace, and autofill dialogs
│   ├── tasks.py                 # Background QgsTask workers (query, stats, nearby, replace)
│   ├── exporting.py             # Background CSV snapshot exporter
│   └── themes.py                # Light/dark themes, stylesheets, and SVG/PNG icon helpers
├── icons/                       # Toolbar PNG and theme-aware SVG UI icons
├── docs/
│   ├── performance.md           # Benchmarks, controls, and scale limits
│   ├── remediation-guide.md     # Validation and hardening notes
│   └── images/                  # Documentation screenshots
├── tests/
│   ├── run_qgis_tests.py        # Offscreen QGIS test runner
│   ├── test_qgis_integration.py # End-to-end UI and workflow integration tests
│   ├── priority_checks.py       # Regression checks for core features
│   ├── provider_checks.py       # Disk-provider and opt-in PostGIS tests
│   └── test_*.py                # Pure-Python unit tests
├── tools/
│   ├── package_plugin.py        # Build and verify quicktable_latest-<version>.zip
│   ├── smoke_package.py         # Isolated ZIP load, query, render, and unload smoke check
│   └── benchmark_plugin.py      # Standalone local QGIS benchmark script
├── dist/                        # Built plugin ZIP archives
└── .github/workflows/
    └── verify.yml               # Automated CI test and package workflow
```

## 💬 Support & license

Report bugs or request features through [GitHub Issues](https://github.com/ivxnzzz/quicktable_qgis/issues). Include your QGIS version, OS and steps to reproduce.

© 2026 Iven Paul Rolloque · [GNU GPL v2 or later](LICENSE) · Distributed without warranty.
