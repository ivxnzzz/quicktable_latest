"""Cancellable CSV export from a feature snapshot without rendering every row."""

import csv
import os
from pathlib import Path
import tempfile

from qgis.core import QgsFeatureRequest

from .editing import attribute_text
from .filter_utils import spreadsheet_rows


def export_csv_task(task, source, ids, columns, names, path):
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='quicktable-', suffix='.csv', dir=destination.parent)
    count = 0
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
                    writer.writerows(spreadsheet_rows([[attribute_text(features[fid][column]) for column in columns]]))
                    count += 1
                task.setProgress(count * 100 / max(1, len(ids)))
        if task.isCanceled():
            return None
        os.replace(temporary, destination)
        return {'rows': count, 'path': str(destination)}
    finally:
        Path(temporary).unlink(missing_ok=True)
