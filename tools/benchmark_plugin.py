"""Reproducible QGIS benchmark; run with QGIS Python, outside the test suite."""

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))


def main():
    from qgis.core import Qgis, QgsApplication, QgsFeature, QgsProject, QgsVectorLayer, QgsVectorLayerFeatureSource
    from qgis.PyQt.QtCore import QSettings

    parser = argparse.ArgumentParser()
    parser.add_argument('--sizes', type=int, nargs='+', default=[10000, 100000, 1000000])
    parser.add_argument('--output', type=Path, default=root / 'dist' / 'benchmark.json')
    args = parser.parse_args()
    app = QgsApplication([], False)
    app.initQgis()
    module = importlib.import_module(root.name + '.quicktable.layer_filter')
    task = SimpleNamespace(isCanceled=lambda: False)
    signal = SimpleNamespace(connect=lambda slot: None, disconnect=lambda slot: None)
    measurements = []
    with tempfile.TemporaryDirectory(prefix='quicktable-benchmark-') as profile:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, profile)
        QSettings().setValue('LayerFilter/pageSize', 500)
        for count in args.sizes:
            layer = QgsVectorLayer('None?field=number:integer&field=label:string', 'benchmark', 'memory')
            for start in range(0, count, 5000):
                batch = []
                for number in range(start, min(start + 5000, count)):
                    feature = QgsFeature(layer.fields())
                    feature.setAttributes([number, 'category_' + str(number % 100)])
                    batch.append(feature)
                layer.dataProvider().addFeatures(batch)
            source = QgsVectorLayerFeatureSource(layer)
            row = {'rows': count, 'fields': 2, 'provider': 'memory'}
            began = time.perf_counter()
            ids = module.collect_feature_ids(task, source, '')
            row['collect_ids_seconds'] = time.perf_counter() - began
            row['id_cache_bytes'] = sys.getsizeof(ids) + sum(sys.getsizeof(fid) for fid in ids)
            began = time.perf_counter()
            module.collect_feature_ids(task, source, '', 'number', False)
            row['sort_seconds'] = time.perf_counter() - began
            began = time.perf_counter()
            module.collect_column_statistics(task, source, [(0, True), (1, False)], ids)
            row['statistics_seconds'] = time.perf_counter() - began
            began = time.perf_counter()
            module.collect_feature_ids(SimpleNamespace(isCanceled=lambda: True), source, '')
            row['precanceled_seconds'] = time.perf_counter() - began
            QgsProject.instance().addMapLayer(layer)
            iface = SimpleNamespace(activeLayer=lambda: layer, currentLayerChanged=signal)
            dialog = module.FinderDialog(iface)
            began = time.perf_counter()
            dialog.refresh()
            deadline = time.monotonic() + 120
            while dialog.query_task is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            if dialog.result_ids is None:
                raise RuntimeError(dialog.status.text())
            row['first_page_seconds'] = time.perf_counter() - began
            began = time.perf_counter()
            dialog.change_page(1)
            row['next_page_seconds'] = time.perf_counter() - began
            dialog.shutdown()
            QgsProject.instance().removeMapLayer(layer.id())
            app.processEvents()
            measurements.append(row)
            print(json.dumps(row), flush=True)
    app.exitQgis()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'qgis': Qgis.QGIS_VERSION, 'platform': sys.platform,
        'measurements': measurements}, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
