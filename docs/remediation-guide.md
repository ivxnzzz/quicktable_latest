# QuickTable audit remediation guide

This guide records the audit remediation starting from commit `911af77`,
version 2.00, with the follow-up changes included in that same version. The two
high-risk editing bugs and the remaining local correctness findings are
implemented. External verification is listed explicitly below.

## Step 1: Establish the baseline

1. Check `git status --short` and preserve unrelated work.
2. Run the existing suite in QGIS's Python environment:

   ```powershell
   & 'C:/Program Files/QGIS 3.44.12/bin/python-qgis-ltr.bat' tests/run_qgis_tests.py
   ```

   Adjust the installation path on another machine. Plain Python skips the
   QGIS integration tests, so it cannot validate the editing fixes.
3. The audit baseline passed 118 tests on Windows with QGIS 3.44.12.

## Step 2: Reproduce stale filter and sort results

1. Open a writable layer in QuickTable and turn statistics off.
2. Filter for a value, enable editing, and change a matching cell so it no
   longer matches. After the refresh delay, the row should disappear and the
   result count should decrease.
3. Clear the filter, sort a numeric field, and change its first value so it
   should move to the end. The row must move to its correct sorted position.
4. Undo the change and verify that the previous value and result order return.
5. Add automated regressions for these behaviors before changing the code.

## Step 3: Refresh results after every successful cell edit

1. Update `FinderDialog.on_cell_edited` in `quicktable/layer_filter.py`.
2. Invalidate cached result IDs after a successful change regardless of
   statistics visibility.
3. Use the existing delayed refresh timer so rebuilding the table does not
   happen inside the cell-change signal handler.
4. Preserve edit commands, unsaved-change highlighting, and selection
   synchronization. Rejected input must leave the stored value unchanged.

## Step 4: Reproduce and correct ValueMap matching

1. Configure a text field with ValueMap entries whose stored values include
   both `A` and `a`, with different labels.
2. Open the editor for each value and accept it without changing the choice.
   The stored value and selected label must remain exact.
3. Include an existing value absent from the map; accepting its editor must
   preserve that value too.
4. Update `ColumnTextDelegate.setEditorData` in
   `quicktable/compact_filters.py` to compare ValueMap values case-sensitively.
5. Keep boolean-only normalization for `true`, `false`, `1`, and `0`.
   Preserve zero and false when reading typed model values.
6. Verify that deliberately choosing a different entry remains undoable.

## Step 5: Validate the changes

1. Run the new regressions against the original implementation and confirm
   that they expose the bugs.
2. Apply the fixes and run the complete QGIS suite using Step 1's command.
3. Confirm that existing selection, pagination, statistics, and undo tests
   still pass.
4. Perform Steps 2 and 4 manually against a disposable GeoPackage. Automated
   memory-layer tests do not establish on-disk commit behavior.

## Step 6: Prepare a reviewable release artifact

1. Review `git diff --check` and the complete diff.
2. Build the ZIP:

   ```powershell
   python tools/package_plugin.py
   ```

3. The builder checks metadata, runtime file membership, ZIP integrity, size,
   and equality with source files.
4. The current metadata produces `dist/quicktable_latest-2.0.1.zip`. The
   changelog and README have been updated together.
5. Install the ZIP into a disposable QGIS profile and repeat the manual
   checks. Record the QGIS version, OS, provider, and results.
6. Tag the reviewed source and upload that exact ZIP through the established
   release process.

## Priority completion status

| Finding | Implementation and verification |
| --- | --- |
| Stale filter/sort results | Delayed refresh after every successful edit; selection and undo regressions pass |
| Case-sensitive ValueMaps | Exact matching; unmapped values and boolean zero/false preserved |
| NULL versus empty text | Explicit cell, bulk-edit and autofill controls; preserved through GeoPackage commits and reopen |
| Numeric statistics | Exact integer sums/extrema; wide Decimal totals avoid float overflow and cancellation loss |
| Global search semantics | Literal substring matching for `%`, `_`, quotes and backslashes; temporal filters validate ISO input |
| Field validation | Integer bounds, text lengths, date/time parsing and hard layer constraints; failed bulk edits undo the entire command |
| Failure recovery | Failed save/rollback retain pending edits and report failure; discard checks whether edit mode restarts |
| Real providers | GeoPackage save/reopen/discard, schema add/delete and feature deletion/undo; Shapefile commit/reopen pass locally |
| PostGIS | Live database test and mandatory CI service added; not run locally without a configured disposable database |
| Automated release checks | QGIS runner rejects unexpected skips; workflow includes QGIS/PostGIS, compilation, package validation and isolated ZIP loading |
| Large layers | No geometry in page requests, bounded All-results display, batched cancellable CSV export, indexed nearby candidates; 10K/100K/1M measurements recorded |
| Maintainability | Conversion/constraint checks, numeric accumulation and export isolated in focused modules |

## External verification and release steps

1. Run the GitHub Actions workflow. Its QGIS job requires the live PostGIS
   test and fails if that test is skipped. The workflow has not been run from
   this local session.
2. To run PostGIS locally, set `QUICKTABLE_TEST_POSTGIS_URI` to a disposable
   database connection string and `QUICKTABLE_REQUIRE_POSTGIS=1`. The test
   creates a UUID-named schema, uses only that schema, and drops it afterward.
   The database role needs schema creation and DDL permissions. Never use a
   production database for this test.
3. Verify Linux results from CI and perform a macOS smoke test. Configuring a
   workflow is not evidence that it has passed on another OS.
4. Review the measured limits in [performance.md](performance.md). Wide,
   spatial and remote layers remain additional benchmark scenarios, and full
   matching-ID caching remains an architectural scaling limit.
5. Install the validated ZIP in a disposable interactive QGIS profile and
   check the NULL controls and export scope prompt. The automated package
   smoke test covers classFactory, GUI initialization, query, rendering and
   unload from the ZIP in an isolated offscreen profile.
6. Review, tag and publish the exact verified artifact through the established
   release process. No upload or change to the experimental flag was made.

## Execution record (2026-11-09)

- Implemented unconditional delayed result refresh after successful cell edits.
- Implemented exact ValueMap matching and boolean-only normalization, including
  preserving typed zero and false when initializing an editor.
- Added four integration tests covering filter membership, numeric sort order,
  selection preservation, undo, ValueMap acceptance and deliberate changes,
  unmapped values, and boolean normalization.
- Confirmed that the original implementation failed the new checks: stale
  filters, stale sorting, incorrect `a`/`A` matching, and empty selections for
  typed zero and false (five failing assertions across four tests).
- Ran the complete suite after the fixes: **122 tests passed** on Windows with
  QGIS 3.44.12. The log is `dist/high-risk-after.log`.
- The initial high-risk cycle passed 122 tests; that result is superseded by
  the full priority cycle, including real GeoPackage and Shapefile checks.
- The priority cycle currently discovers 140 tests: 139 execute locally and
  the live PostGIS test is explicitly skipped without its connection setting.
  See `dist/priority-complete-tests.log` for the latest full QGIS run.
- The isolated package smoke test passes. The release version is 2.00 and the
  experimental flag is unchanged. External verification remains as listed
  above; the changes have not been published.
