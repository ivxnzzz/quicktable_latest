"""Cancellable CSV export from a feature snapshot without rendering every row."""

import csv
import os
from pathlib import Path
import tempfile

from qgis.core import QgsFeatureRequest
from qgis.PyQt.QtCore import QMetaType

from .editing import attribute_text
from .filter_utils import spreadsheet_cell, spreadsheet_rows


def export_csv_task(task, source, ids, columns, names, path):
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='quicktable-', suffix='.csv', dir=destination.parent)
    count = 0
    numeric_types = (QMetaType.Type.Int, QMetaType.Type.UInt, QMetaType.Type.LongLong,
                     QMetaType.Type.ULongLong, QMetaType.Type.Double)
    numeric_columns = {column for column in columns if source.fields()[column].type() in numeric_types}
    try:
        with os.fdopen(descriptor, 'w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            writer.writerows(spreadsheet_rows([names]))
            for start in range(0, len(ids), 1000):
                if task.isCanceled():
                    return None
                batch = ids[start:start + 1000]
                request = QgsFeatureRequest().setFilterFids(list(batch))
                request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
                request.setSubsetOfAttributes(columns)
                iterator = source.getFeatures(request)
                try:
                    features = {feature.id(): feature for feature in iterator}
                finally:
                    iterator.close()
                for fid in batch:
                    if task.isCanceled():
                        return None
                    if fid not in features:
                        raise ValueError('Feature {} is no longer available; export was not replaced'.format(fid))
                    writer.writerow([spreadsheet_cell(attribute_text(features[fid][column]), column in numeric_columns)
                                     for column in columns])
                    count += 1
                task.setProgress(count * 100 / max(1, len(ids)))
        if task.isCanceled():
            return None
        os.replace(temporary, destination)
        return {'rows': count, 'path': str(destination)}
    finally:
        Path(temporary).unlink(missing_ok=True)
