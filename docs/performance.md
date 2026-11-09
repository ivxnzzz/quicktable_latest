# Performance measurements and limits

Measured on 2026-11-09, Windows, QGIS 3.44.12-Solothurn, using
`tools/benchmark_plugin.py`. This is one run on the local machine, not a
cross-platform performance guarantee. Data was a memory layer with an integer
column and a category text column, without geometry; pages contained 500 rows.

| Rows | Collect IDs | Sort | Statistics | First page | Next page | ID cache |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 0.016 s | 0.037 s | 0.079 s | 0.044 s | 0.022 s | 0.36 MB |
| 100,000 | 0.160 s | 0.436 s | 0.813 s | 0.227 s | 0.022 s | 3.60 MB |
| 1,000,000 | 1.646 s | 5.200 s | 10.654 s | 3.299 s | 0.029 s | 36.00 MB |

The ID cache measurement includes the tuple and Python integer objects only,
not process memory, Qt objects, providers, or source data. First-page time
includes asynchronous result collection and rendering; it is not an independent
measurement of render time. The script also checks pre-canceled work, which
does not measure cancellation latency during an active provider request.

## Implemented controls

- Attribute pages request no geometry, and sorted searches request only the
  sort attribute in addition to feature IDs.
- All-results rendering falls back to pages of 500 above 10,000 rows or the
  column-dependent limit `max(100, 250000 // field_count)`, whichever is lower.
- CSV export reads feature snapshots in batches of 1,000 in a QGIS background
  task. Exporting all matches does not construct a full table first. Output
  replaces the destination only after successful completion.
- Nearby searches index the origin geometries and perform exact geometry
  comparisons only for intersecting candidate bounding boxes.
- Numeric totals use exact integer arithmetic or a wide Decimal accumulator;
  histograms and distinct-value storage remain bounded.

## Remaining scale limits

All matching IDs are still cached before the first page is shown. This costs
approximately 36 bytes per row in this benchmark. Moving to provider-specific
cursor paging would be a separate architectural change, with sorting and live
editing semantics to preserve.

Wide layers, large geometries, remote providers, large selected-only scopes,
and active cancellation during slow provider operations need separate
measurements. Large selected/nearby scopes still use ID-list expressions.
Linux execution is configured in CI but has not been observed locally;
macOS runtime behavior remains unverified.

QGIS's official image tags are documented in the
[QGIS Docker README](https://github.com/qgis/QGIS/blob/master/.docker/README.md).
The verification workflow uses the QGIS 3.44 release branch image and a
disposable PostGIS service.
