"""Background QgsTask worker functions for queries, statistics, spatial preview, and replacements."""

import math
import re
from array import array

from qgis.PyQt.QtCore import QMetaType
from qgis.core import (QgsFeatureRequest, QgsExpression, QgsRectangle, QgsSpatialIndex,
                       QgsFeature, QgsGeometry, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsCsException, NULL)

from .data_analysis import replace_text
from .editing import attribute_text
from .numeric_statistics import NumericTotal

MAX_VALUE_FEATURES = 2000
MAX_STAT_DISTINCT = 25000
STAT_HISTOGRAM_BINS = 16
MAX_NEARBY_PREVIEW = 100
MAX_NEARBY_CANDIDATES = 50000


def field_kind(field):
    """Map a QgsField to QuickTable's normalized filter/editor kind."""
    if field is None:
        return "text"
    return {QMetaType.Type.Int: "integer", QMetaType.Type.UInt: "integer", QMetaType.Type.LongLong: "integer",
            QMetaType.Type.ULongLong: "integer", QMetaType.Type.Double: "number", QMetaType.Type.Bool: "boolean",
            QMetaType.Type.QDate: "date", QMetaType.Type.QDateTime: "datetime", QMetaType.Type.QTime: "time"}.get(field.type(), "text")


def collect_feature_ids(task, source, expression, sort_field=None, ascending=True, filter_fids=None, filter_rect=None):
    """Find all matches off the UI thread, without retaining attributes/geometry."""
    if task.isCanceled():
        return None
    if filter_fids is not None and len(filter_fids) == 0:
        return ()
    if filter_rect is not None and not isinstance(filter_rect, QgsRectangle) and len(filter_rect) == 0:
        return ()
    request = QgsFeatureRequest()
    request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
    if not sort_field:
        request.setNoAttributes()
    else:
        request.setSubsetOfAttributes([source.fields().indexFromName(sort_field)])
    if filter_rect is not None:
        rect = filter_rect if isinstance(filter_rect, QgsRectangle) else QgsRectangle(*filter_rect)
        if rect.isNull() or rect.isEmpty():
            return ()
        request.setFilterRect(rect)
    allowed_fids = None
    if expression:
        request.setFilterExpression(expression)
        if filter_fids is not None:
            allowed_fids = set(filter_fids)
    elif filter_fids is not None:
        request.setFilterFids(list(dict.fromkeys(filter_fids)))
    if sort_field:
        request.addOrderBy(QgsExpression.quotedColumnRef(sort_field), ascending)
        request.addOrderBy('$id', True)
    features = source.getFeatures(request)
    ids = array('q')
    already_sorted = True
    prev_fid = None
    try:
        for feature in features:
            if task.isCanceled():
                return None
            fid = feature.id()
            if allowed_fids is not None and fid not in allowed_fids:
                continue
            if prev_fid is not None and fid < prev_fid:
                already_sorted = False
            prev_fid = fid
            ids.append(fid)
    finally:
        features.close()
    if task.isCanceled():
        return None
    if not sort_field and not already_sorted:
        ids = array('q', sorted(ids))
    # Compact storage keeps large result sets from retaining one Python int per ID.
    return ids if len(ids) > 50000 else tuple(ids)


def collect_feature_ids_task(task, source, expression, sort_field=None, ascending=True,
                             filter_fids=None, filter_rect=None):
    """QgsTask wrapper around collect_feature_ids preserving empty-result tuples."""
    ids = collect_feature_ids(task, source, expression, sort_field, ascending,
                              filter_fids=filter_fids, filter_rect=filter_rect)
    # QgsTask.fromFunction omits falsy return values from its completion callback.
    return (ids,) if ids is not None else None


def collect_nearby(task, source, selected_ids, distance, source_crs=None, transform_context=None,
                   max_matches=None, max_candidates=None, meta=None):
    """Return IDs touching or within a planar distance of the selected features."""
    selected = set(selected_ids)
    preview_limit = meta.get("preview_limit") if isinstance(meta, dict) else None
    label_field = meta.get("label_field") if isinstance(meta, dict) else None
    label_index = (source.fields().indexFromName(label_field)
                   if label_field and preview_limit is not None else -1)
    request = QgsFeatureRequest().setFilterFids(list(selected))
    if label_index >= 0:
        request.setSubsetOfAttributes([label_index])
    else:
        request.setNoAttributes()
    features = source.getFeatures(request)
    origins = {}
    selected_features = []
    preview_labels = {} if label_index >= 0 else None
    geographic = distance is not None and source_crs is not None and source_crs.isGeographic()
    bounds = None
    try:
        for feature in features:
            if task.isCanceled():
                return None
            if not feature.hasGeometry():
                continue
            geometry = feature.geometry()
            if geometry.isEmpty():
                continue
            selected_features.append(QgsFeature(feature))
            if preview_labels is not None and len(selected_features) <= MAX_NEARBY_PREVIEW:
                text = attribute_text(feature.attribute(label_index))
                if text:
                    preview_labels[feature.id()] = text
            rectangle = QgsRectangle(geometry.boundingBox())
            if bounds is None:
                bounds = rectangle
            else:
                bounds.combineExtentWith(rectangle)
    finally:
        features.close()
    if not selected_features:
        raise ValueError("The selected features have no usable geometry.")
    preview_selected = []
    preview_nearby = []
    if preview_limit is not None:
        preview_selected = [(f.id(), QgsGeometry(f.geometry())) for f in selected_features[:MAX_NEARBY_PREVIEW]]
        meta["preview_data"] = (preview_selected, preview_nearby, len(selected_features),
                                label_field if label_index >= 0 else None, preview_labels)
    transform = None
    if geographic:
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        center = QgsCoordinateTransform(source_crs, wgs84, transform_context).transform(bounds.center())
        local_crs = QgsCoordinateReferenceSystem()
        if not local_crs.createFromProj(
                '+proj=aeqd +lat_0={} +lon_0={} +datum=WGS84 +units=m +no_defs'.format(center.y(), center.x())):
            raise ValueError('Could not create a local measurement coordinate system.')
        transform = QgsCoordinateTransform(source_crs, local_crs, transform_context)
    spatial_index = QgsSpatialIndex()
    bounds = None
    for feature in selected_features:
        geometry = feature.geometry()
        if transform is not None:
            geometry.transform(transform)
            feature.setGeometry(geometry)
        origins[feature.id()] = geometry
        spatial_index.addFeature(feature)
        rectangle = QgsRectangle(geometry.boundingBox())
        if distance is not None:
            rectangle.grow(distance)
        if bounds is None:
            bounds = rectangle
        else:
            bounds.combineExtentWith(rectangle)
    request = QgsFeatureRequest()
    if not geographic:
        filter_rect = QgsRectangle(bounds)
        if distance is None:
            pad = max(filter_rect.width(), filter_rect.height(), 1.0) * 1e-7
            filter_rect.grow(pad)
        request.setFilterRect(filter_rect)
    elif bounds is not None and not bounds.isEmpty():
        try:
            padded = QgsRectangle(bounds)
            pad = max(padded.width(), padded.height()) * 0.01
            if pad > 0:
                padded.grow(pad)
            back_transform = QgsCoordinateTransform(local_crs, source_crs, transform_context)
            filter_rect = back_transform.transformBoundingBox(padded)
            if filter_rect.isFinite() and not filter_rect.isEmpty():
                request.setFilterRect(filter_rect)
        except QgsCsException:
            pass
    if label_index >= 0:
        request.setSubsetOfAttributes([label_index])
    else:
        request.setNoAttributes()
    features = source.getFeatures(request)
    # Keep origin QgsGeometry objects alive for the loop because QgsGeometryEngine borrows constGet().
    prepared_origins = {}
    matches = []
    scanned = 0
    try:
        for feature in features:
            if task.isCanceled():
                return None
            if feature.id() in selected or not feature.hasGeometry():
                continue
            if max_candidates is not None:
                if scanned >= max_candidates:
                    if meta is not None:
                        meta["limited"] = True
                    return tuple(matches)
                scanned += 1
            geometry = feature.geometry()
            if geometry.isEmpty():
                continue
            if transform is not None:
                geometry.transform(transform)
            candidate_bounds = QgsRectangle(geometry.boundingBox())
            if distance is not None:
                candidate_bounds.grow(distance)
            else:
                candidate_bounds.grow(max(candidate_bounds.width(), candidate_bounds.height(), 1.0) * 1e-7)
            for origin_id in spatial_index.intersects(candidate_bounds):
                if task.isCanceled():
                    return None
                origin = origins[origin_id]
                if distance is None:
                    engine = prepared_origins.get(origin_id)
                    if engine is None and origin_id not in prepared_origins:
                        geom_ptr = origin.constGet()
                        engine = QgsGeometry.createGeometryEngine(geom_ptr) if geom_ptr is not None else None
                        if engine is not None:
                            engine.prepareGeometry()
                        prepared_origins[origin_id] = engine
                    matched = engine.intersects(geometry.constGet()) if engine is not None else origin.intersects(geometry)
                else:
                    separation = origin.distance(geometry)
                    if separation < 0:
                        raise ValueError("Could not calculate geometry distance; check the layer geometries.")
                    matched = separation <= distance
                if matched:
                    matches.append(feature.id())
                    if preview_limit is not None and len(preview_nearby) < preview_limit:
                        geom_copy = QgsGeometry(feature.geometry()) if transform is not None else QgsGeometry(geometry)
                        preview_nearby.append((feature.id(), geom_copy))
                        if preview_labels is not None:
                            text = attribute_text(feature.attribute(label_index))
                            if text:
                                preview_labels[feature.id()] = text
                    if max_matches is not None and len(matches) >= max_matches:
                        if meta is not None:
                            meta["limited"] = True
                        return tuple(matches)
                    break
    finally:
        features.close()
    return tuple(matches)


def preview_label_angle(geometry):
    """Return the screen angle of the longest side of a feature's oriented bounds."""
    box = geometry.orientedMinimumBoundingBox()[0]
    vertices = list(box.vertices()) if not box.isEmpty() else list(geometry.vertices())
    segments = [(b.x() - a.x(), b.y() - a.y()) for a, b in zip(vertices, vertices[1:])]
    if not segments:
        return 0.0
    dx, dy = max(segments, key=lambda segment: segment[0] ** 2 + segment[1] ** 2)
    if not (dx or dy):
        return 0.0
    angle = math.degrees(math.atan2(-dy, dx))
    return (angle + 90) % 180 - 90


def preview_label_placement(geometry):
    """Return (x, y, angle) for placing a label inside a geometry, or None."""
    anchor = geometry.pointOnSurface()
    if anchor.isEmpty():
        anchor = geometry.centroid()
    if anchor.isEmpty():
        return None
    point = anchor.asPoint()
    return (point.x(), point.y(), preview_label_angle(geometry))


def collect_nearby_task(task, source, selected_ids, distance, source_crs=None, transform_context=None,
                        max_matches=None, max_candidates=None, preview_limit=None, label_field=None):
    """QgsTask wrapper around collect_nearby preserving empty-result tuples and truncation metadata."""
    meta = {"limited": False}
    if preview_limit is not None:
        meta["preview_limit"] = preview_limit
    if label_field:
        meta["label_field"] = label_field
    ids = collect_nearby(
        task, source, selected_ids, distance, source_crs, transform_context,
        max_matches=max_matches, max_candidates=max_candidates, meta=meta,
    )
    if ids is None:
        return None
    if preview_limit is not None:
        preview_selected, preview_nearby, selected_total, active_label_field, preview_labels = meta.pop(
            "preview_data", ([], [], 0, None, None)
        )
        truncated = selected_total > MAX_NEARBY_PREVIEW or len(ids) > preview_limit
        snapshot = _build_preview_snapshot(
            task, preview_selected, preview_nearby, truncated=truncated,
            label_field=active_label_field, labels=preview_labels,
        )
        if snapshot is None:
            return None
        return (ids, meta["limited"], snapshot)
    return (ids, meta["limited"])


def _preview_wkb_and_geom(geometry, remaining_bytes, target_bytes=262_144):
    """Return compact (WKB, simplified_geometry) for preview rendering."""
    wkb = bytes(geometry.asWkb())
    preview_geom = geometry
    if len(wkb) <= remaining_bytes and len(wkb) <= 65_536:
        return wkb, preview_geom
    rect = geometry.boundingBox()
    span = max(rect.width(), rect.height())
    if span > 0:
        for factor in (0.0005, 0.002, 0.01):
            simplified = geometry.simplify(span * factor)
            if simplified.isEmpty():
                continue
            candidate = bytes(simplified.asWkb())
            if len(candidate) < len(wkb):
                wkb = candidate
                preview_geom = simplified
            if len(wkb) <= remaining_bytes and len(wkb) <= target_bytes:
                return wkb, preview_geom
    return (wkb, preview_geom) if len(wkb) <= remaining_bytes else (None, None)


def _preview_wkb(geometry, remaining_bytes, target_bytes=262_144):
    """Return compact WKB for preview rendering, simplifying dense geometries to keep neighbors visible."""
    return _preview_wkb_and_geom(geometry, remaining_bytes, target_bytes=target_bytes)[0]


def _build_preview_snapshot(task, selected_items, nearby_items, truncated=False, label_field=None, labels=None):
    """Encode bounded selected and nearby geometry pairs into a WKB preview snapshot."""
    result = {"selected": {}, "nearby": {}, "truncated": bool(truncated)}
    if label_field is not None and labels is not None:
        result["label_field"] = label_field
        result["labels"] = {}
        result["label_placements"] = {}
    remaining_bytes = 5_000_000
    for name, items in (("selected", selected_items), ("nearby", nearby_items)):
        for fid, geometry in items:
            if task.isCanceled():
                return None
            wkb, preview_geom = _preview_wkb_and_geom(geometry, remaining_bytes)
            if wkb is None:
                result["truncated"] = True
                continue
            result[name][fid] = wkb
            remaining_bytes -= len(wkb)
            if labels is not None:
                text = labels.get(fid)
                if text:
                    placement = preview_label_placement(preview_geom)
                    if placement is not None:
                        result["labels"][fid] = text
                        result["label_placements"][fid] = placement
    return result


def collect_nearby_preview(task, source, selected_ids, nearby_ids, selected_limit=100, nearby_limit=200):
    """Copy a bounded sample of geometry as WKB for the preview canvas."""
    selected_items = []
    nearby_items = []
    truncated = len(selected_ids) > selected_limit or len(nearby_ids) > nearby_limit
    for bucket, ids, limit in ((selected_items, selected_ids, selected_limit), (nearby_items, nearby_ids, nearby_limit)):
        if task.isCanceled():
            return None
        sample = list(ids[:limit])
        if not sample:
            continue
        request = QgsFeatureRequest().setFilterFids(sample)
        request.setNoAttributes()
        iterator = source.getFeatures(request)
        try:
            for feature in iterator:
                if task.isCanceled():
                    return None
                if not feature.hasGeometry() or feature.geometry().isEmpty():
                    continue
                bucket.append((feature.id(), QgsGeometry(feature.geometry())))
        finally:
            iterator.close()
    return _build_preview_snapshot(task, selected_items, nearby_items, truncated=truncated)


class _ColumnStatState:
    """Compact per-column accumulator to avoid repeated dictionary lookups in stat loops."""

    __slots__ = (
        "index",
        "numeric",
        "integer",
        "non_null",
        "nulls",
        "total",
        "min_val",
        "max_val",
        "categories",
        "numeric_distinct",
        "capped",
        "values",
        "numeric_count",
        "nonfinite",
    )

    def __init__(self, index, numeric, integer):
        self.index = index
        self.numeric = numeric
        self.integer = integer
        self.non_null = 0
        self.nulls = 0
        self.total = NumericTotal(integer) if numeric else None
        self.min_val = None
        self.max_val = None
        self.categories = None if numeric else {}
        self.numeric_distinct = set() if numeric else None
        self.capped = False
        self.values = (array('q') if integer else array('d')) if numeric else None
        self.numeric_count = 0
        self.nonfinite = 0


def collect_column_statistics(task, source, columns, ids, max_distinct=MAX_STAT_DISTINCT, full_layer=False):
    """Collect exact counts and bounded category distributions for filtered IDs."""
    fields = source.fields()
    states = tuple(
        _ColumnStatState(index, numeric, numeric and field_kind(fields[index]) == "integer")
        for index, numeric in columns
    )
    if not ids or not columns:
        return {
            "summaries": {
                state.index: [
                    0,
                    0,
                    0.0,
                    None,
                    None,
                    state.numeric,
                    {"distinct": 0, "capped": False, "top": [], "histogram": [], "numeric_count": 0, "nonfinite": 0},
                ]
                for state in states
            }
        }
    request = QgsFeatureRequest()
    if not full_layer:
        request.setFilterFids(list(ids))
    request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
    request.setSubsetOfAttributes([state.index for state in states])
    features = source.getFeatures(request)
    try:
        for feature in features:
            if task.isCanceled():
                return None
            for state in states:
                value = feature[state.index]
                if value is None or value == NULL:
                    state.nulls += 1
                    continue
                state.non_null += 1
                if not state.numeric:
                    categories = state.categories
                    if categories is not None:
                        label = value if isinstance(value, str) else str(value)
                        if label in categories:
                            categories[label] += 1
                        elif len(categories) < max_distinct:
                            categories[label] = 1
                        else:
                            state.categories = None
                            state.capped = True
                    continue
                try:
                    number = int(value) if state.integer else float(value)
                except (ValueError, TypeError, OverflowError):
                    state.nonfinite += 1
                    distinct = state.numeric_distinct
                    if distinct is not None:
                        key = value if isinstance(value, str) else str(value)
                        if key not in distinct:
                            if len(distinct) < max_distinct:
                                distinct.add(key)
                            else:
                                state.numeric_distinct = None
                                state.capped = True
                    continue
                if not math.isfinite(number):
                    state.nonfinite += 1
                    distinct = state.numeric_distinct
                    if distinct is not None:
                        # Normalize NaN values to a string key so distinct sets do not grow unbounded.
                        key = str(value)
                        if key not in distinct:
                            if len(distinct) < max_distinct:
                                distinct.add(key)
                            else:
                                state.numeric_distinct = None
                                state.capped = True
                    continue
                distinct = state.numeric_distinct
                if distinct is not None and number not in distinct:
                    if len(distinct) < max_distinct:
                        distinct.add(number)
                    else:
                        state.numeric_distinct = None
                        state.capped = True
                state.numeric_count += 1
                values = state.values
                try:
                    values.append(number)
                except OverflowError:
                    values = list(values)
                    values.append(number)
                    state.values = values
                state.total.add(number)
                min_val = state.min_val
                state.min_val = number if min_val is None else (number if number < min_val else min_val)
                max_val = state.max_val
                state.max_val = number if max_val is None else (number if number > max_val else max_val)
    finally:
        features.close()
    summaries = {}
    for state in states:
        if task.isCanceled():
            return None
        meta = {
            "distinct": 0,
            "capped": state.capped,
            "top": [],
            "histogram": [],
            "numeric_count": state.numeric_count,
            "nonfinite": state.nonfinite,
        }
        if state.capped:
            meta["distinct"] = max_distinct + 1
        elif state.numeric:
            meta["distinct"] = len(state.numeric_distinct)
        else:
            categories = state.categories
            meta["distinct"] = len(categories)
            if len(categories) <= 30:
                meta["top"] = sorted(categories.items(), key=lambda item: (-item[1], item[0].casefold()))[:2]
        if state.numeric and state.numeric_count:
            bins = [0] * STAT_HISTOGRAM_BINS
            meta["histogram"] = bins
            low, high = state.min_val, state.max_val
            values = state.values
            state.values = None
            if high > low:
                span = high - low
                finite_span = math.isfinite(span)
                half_span = (high / 2 - low / 2) if not finite_span else 1.0
                for count_idx, number in enumerate(values):
                    if count_idx & 4095 == 0 and task.isCanceled():
                        return None
                    ratio = ((number - low) / span if finite_span else (number / 2 - low / 2) / half_span)
                    if not math.isfinite(ratio):
                        ratio = 0.0 if number == low else 1.0
                    bucket = max(0, min(STAT_HISTOGRAM_BINS - 1, int(ratio * STAT_HISTOGRAM_BINS)))
                    bins[bucket] += 1
            else:
                bins[STAT_HISTOGRAM_BINS // 2] = len(values)
        elif state.numeric:
            state.values = None
        total_value = state.total.total if (state.numeric and state.numeric_count) else 0.0
        summaries[state.index] = [
            state.non_null,
            state.nulls,
            total_value,
            state.min_val,
            state.max_val,
            state.numeric,
            meta,
        ]
    return {"summaries": summaries}


def replace_suggestions(task, source, ids, columns, needle, case_sensitive=False):
    """Collect up to 100 distinct matching text values for Find and Replace autocomplete."""
    matches = set()
    pattern = re.compile(re.escape(needle), 0 if case_sensitive else re.IGNORECASE)
    checked = 0
    batches = (None,) if ids is None else (ids[start:start + 1000] for start in range(0, len(ids), 1000))
    for batch in batches:
        if task.isCanceled():
            return None
        request = QgsFeatureRequest()
        if batch is not None:
            request.setFilterFids(list(batch))
        request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
        request.setSubsetOfAttributes(columns)
        iterator = source.getFeatures(request)
        try:
            for feature in iterator:
                if task.isCanceled():
                    return None
                for column in columns:
                    value = feature[column]
                    if isinstance(value, str) and value and pattern.search(value):
                        matches.add(value)
                checked += 1
                if checked >= MAX_VALUE_FEATURES or len(matches) >= 100:
                    return sorted(matches, key=str.casefold)[:100]
        finally:
            iterator.close()
    return sorted(matches, key=str.casefold)[:100]


def replace_columns_snapshot(task, source, ids, columns, needle, replacement, case_sensitive):
    """Compute proposed multi-column text replacements on a snapshot off the UI thread."""
    if not needle:
        raise ValueError("Enter text to find")
    originals, changes = {}, {}
    batches = (None,) if ids is None else (ids[start:start + 1000] for start in range(0, len(ids), 1000))
    for batch in batches:
        if task.isCanceled():
            return None
        request = QgsFeatureRequest()
        if batch is not None:
            request.setFilterFids(list(batch))
        request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
        request.setSubsetOfAttributes(columns)
        iterator = source.getFeatures(request)
        try:
            for feature in iterator:
                if task.isCanceled():
                    return None
                fid = feature.id()
                originals[fid] = {column: feature[column] for column in columns}
                for column, old in originals[fid].items():
                    if old is not None and old != NULL:
                        new = replace_text(old, needle, replacement, case_sensitive)
                        if new != old:
                            changes.setdefault(fid, {})[column] = new
        finally:
            iterator.close()
    if ids is not None and len(originals) != len(ids):
        raise ValueError("Some features are no longer available")
    return originals, changes


def replace_feature_snapshot(task, source, ids, column, needle, replacement, case_sensitive):
    """Compute proposed single-column text replacements for a specific list of feature IDs."""
    if not needle:
        raise ValueError("Enter text to find")
    originals, changes = {}, {}
    for start in range(0, len(ids), 1000):
        if task.isCanceled():
            return None
        request = QgsFeatureRequest().setFilterFids(list(ids[start:start + 1000]))
        request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
        request.setSubsetOfAttributes([column])
        iterator = source.getFeatures(request)
        try:
            for feature in iterator:
                if task.isCanceled():
                    return None
                old = feature[column]
                originals[feature.id()] = old
                if old is not None and old != NULL:
                    new = replace_text(old, needle, replacement, case_sensitive)
                    if new != old:
                        changes[feature.id()] = new
        finally:
            iterator.close()
    if len(originals) != len(ids):
        raise ValueError("Some features are no longer available")
    return originals, changes


def collect_values(task, source, index, expression):
    """Read a bounded set of suggestions from an independent feature source."""
    request = QgsFeatureRequest()
    request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
    request.setSubsetOfAttributes([index])
    request.setLimit(MAX_VALUE_FEATURES + 1)
    if expression:
        request.setFilterExpression(expression)
    values = {}
    truncated = False
    features = source.getFeatures(request)
    try:
        for count, feature in enumerate(features):
            if task.isCanceled():
                return None
            if count >= MAX_VALUE_FEATURES:
                truncated = True
                break
            value = feature[index]
            if value is not None and value != NULL:
                values.setdefault(attribute_text(value), value)
    finally:
        features.close()
    return values, truncated
