# Performance measurements and limits

Measured on 2026-11-14, Windows, QGIS 3.44.12-Solothurn (v2.6), using
`tools/benchmark_plugin.py`. This is one run on the local machine, not a
cross-platform performance guarantee. Data was a memory layer with an integer
column and a category text column, without geometry; pages contained 500 rows.

| Rows | Collect IDs | Sort | Statistics | First page | Next page | ID cache |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 0.017 s | 0.038 s | 0.047 s | 0.052 s | 0.026 s | 360,040 B (0.36 MB) |
| 100,000 | 0.164 s | 0.437 s | 0.469 s | 0.236 s | 0.030 s | 816,640 B (0.82 MB) |
| 1,000,000 | 1.708 s | 4.945 s | 5.146 s | 2.226 s | 0.025 s | 8,183,816 B (8.18 MB) |

The ID cache measurement includes only the returned container (`tuple` up to
50,000 matches, signed 64-bit `array` above 50,000) and any Python `int` objects
when a tuple is used, not process memory, Qt objects, providers, or source
data. When the provider returns feature IDs already in ascending order, ID
collection skips the extra Python sort copy (`array('q')` keeps minor
over-allocation headroom, ~8.18 MB vs ~8.00 MB exact-fit). First-page time
includes asynchronous result collection and rendering; it is not an independent
measurement of render time. The script also checks pre-canceled work, which
does not measure cancellation latency during an active provider request.

## Implemented controls

- Attribute pages request no geometry and fetch/populate only currently visible
  columns (`setSubsetOfAttributes`), keeping feature IDs in column 0 `UserRole`
  and re-rendering automatically if a hidden column is later shown. Sorted
  searches request only the sort attribute in addition to feature IDs.
- Closed column filter popups defer `collect_values` scans until opened, and
  opening an unfiltered column filter skips redundant search reruns.
- All-results rendering falls back to pages of 500 above 10,000 rows or the
  column-dependent limit `max(100, 250000 // field_count)`, whichever is lower.
- CSV export reads feature snapshots in batches of 1,000 in a QGIS background
  task. Exporting all matches does not construct a full table first. Output
  replaces the destination only after successful completion.
- Nearby searches index the origin geometries, reuse prepared GEOS engines for
  intersecting (`touching`) checks, and perform exact geometry comparisons only
  for intersecting candidate bounding boxes.
- Column statistics reuse compact slot accumulators, use `array('q')` with
  overflow promotion for integer histograms, skip full-table FID filter lists
  on unfiltered committed views, track numeric distinct counts without
  per-row string allocations, and keep totals/histograms bounded.

## Remaining scale limits

All matching IDs are still cached before the first page is shown. For more than
50,000 matches, the cache uses a compact 64-bit array (about 8 bytes per ID,
excluding array overhead, down from ~36 MB to 8,000,080 B at 1,000,000 rows in
the earlier 2026-11-09 tuple baseline). Peak process memory has not yet been
measured. Moving to provider-specific cursor paging would be a separate
architectural change, with sorting and live editing semantics to preserve.

Wide layers, large geometries, remote providers, large selected-only scopes,
and active cancellation during slow provider operations need separate
measurements. `Selected features` and `Edited and new` pass `filter_fids`
directly to ID collection (`setFilterFids` or ID-set intersection with active
expressions) rather than building `$id IN (...)` strings, and `Visible on map`
applies a transformed `filter_rect` spatial extent filter.
Linux execution is configured in CI but has not been observed locally;
macOS runtime behavior remains unverified.

QGIS's official image tags are documented in the
[QGIS Docker README](https://github.com/qgis/QGIS/blob/master/.docker/README.md).
The verification workflow uses a pinned QGIS 3.44 image and a
disposable PostGIS service.
