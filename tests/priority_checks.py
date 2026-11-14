"""Regression scenarios mixed into the shared QGIS application test case."""

from decimal import Decimal
import time
from types import SimpleNamespace
from unittest.mock import patch


class PriorityChecks:
    def test_large_result_ids_use_compact_storage_and_preserve_order(self):
        from array import array
        from qgis.core import QgsVectorLayerFeatureSource
        layer = self.make_layer(50001)
        source = QgsVectorLayerFeatureSource(layer)
        ids = self.plugin.collect_feature_ids(SimpleNamespace(isCanceled=lambda: False), source, None)
        self.assertIsInstance(ids, array)
        self.assertEqual(len(ids), 50001)
        self.assertEqual(list(ids[:10]), sorted(ids[:10]))
        self.assertEqual(len(set(ids)), len(ids))
        dialog = self.create_dialog(layer)
        self.assertIsInstance(dialog.result_ids, array)
        self.assertEqual(len(dialog.result_ids), 50001)
        self.assertGreater(dialog.table.rowCount(), 0)
        dialog.change_page(1)
        self.assertEqual(dialog.page, 1)

    def test_temporal_filter_suggestions_are_iso_strings(self):
        from qgis.core import QgsFeature, QgsVectorLayer, QgsVectorLayerFeatureSource
        from qgis.PyQt.QtCore import QDate, QDateTime, QTime
        layer = QgsVectorLayer('None?field=day:date&field=moment:datetime&field=clock:time', 'dates', 'memory')
        feature = QgsFeature(layer.fields())
        feature.setAttributes([QDate(2026, 11, 10), QDateTime(QDate(2026, 11, 10), QTime(12, 30)), QTime(12, 30)])
        layer.dataProvider().addFeatures([feature])
        source = QgsVectorLayerFeatureSource(layer)
        for index, expected in enumerate(('2026-11-10', '2026-11-10T12:30:00.000', '12:30:00.000')):
            values, truncated = self.plugin.collect_values(SimpleNamespace(isCanceled=lambda: False), source, index, None)
            self.assertEqual(list(values), [expected])
            self.plugin.field_filter('"value"', 'Equals', expected, '', ('date', 'datetime', 'time')[index], self.plugin.QgsExpression.quotedString)

    def test_csv_and_clipboard_keep_numeric_values_and_protect_text(self):
        import csv
        import tempfile
        from pathlib import Path
        from qgis.core import QgsFeature, QgsVectorLayer, QgsVectorLayerFeatureSource
        from qgis.PyQt.QtWidgets import QApplication
        layer = QgsVectorLayer('None?field=number:integer&field=text:string', 'numbers', 'memory')
        feature = QgsFeature(layer.fields())
        feature.setAttributes([-25, '-25'])
        layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.copy_rows()
        self.assertEqual(list(csv.reader(QApplication.clipboard().text().splitlines(), delimiter='\t'))[1], ['-25', "'-25"])
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'numbers.csv'
        source = QgsVectorLayerFeatureSource(layer)
        self.plugin.export_csv_task(SimpleNamespace(isCanceled=lambda: False, setProgress=lambda value: None),
                                    source, tuple(f.id() for f in layer.getFeatures()), [0, 1], ['number', 'text'], str(path))
        with path.open(newline='', encoding='utf-8-sig') as stream:
            self.assertEqual(list(csv.reader(stream))[1], ['-25', "'-25"])

    def test_csv_exports_all_filtered_results_without_rendering_all_rows(self):
        import csv
        import tempfile
        import time
        from pathlib import Path
        from qgis.core import QgsApplication

        layer = self.make_layer(150)
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = str(Path(temporary.name) / 'export.csv')
        with patch.object(self.plugin.QInputDialog, 'getItem', return_value=('All filtered results', True)), \
             patch.object(self.plugin.QFileDialog, 'getSaveFileName', return_value=(path, 'CSV (*.csv)')):
            dialog.export_csv()
        deadline = time.monotonic() + 10
        while dialog.csv_task is not None and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.assertIsNone(dialog.csv_task, dialog.status.text())
        with open(path, newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(len(rows), 151)
        self.assertEqual(rows[-1], ['149'])
        self.assertEqual(dialog.table.rowCount(), 100)

    def test_cancelled_csv_export_preserves_existing_destination(self):
        import tempfile
        from pathlib import Path
        from qgis.core import QgsVectorLayerFeatureSource

        layer = self.make_layer(20)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'export.csv'
        path.write_text('original', encoding='utf-8')
        checks = []
        def canceled():
            checks.append(True)
            return len(checks) > 5
        result = self.plugin.export_csv_task(SimpleNamespace(isCanceled=canceled, setProgress=lambda value: None),
            QgsVectorLayerFeatureSource(layer), tuple(feature.id() for feature in layer.getFeatures()),
            [0], ['name'], str(path))
        self.assertIsNone(result)
        self.assertEqual(path.read_text(encoding='utf-8'), 'original')
        self.assertEqual(list(Path(temporary.name).iterdir()), [path])

    def test_bulk_constraint_failure_rolls_back_the_entire_command(self):
        from qgis.core import QgsFieldConstraints
        from qgis.PyQt.QtWidgets import QDialog

        layer = self.make_layer(3)
        layer.setFieldConstraint(0, QgsFieldConstraints.Constraint.ConstraintUnique,
                                 QgsFieldConstraints.ConstraintStrength.ConstraintStrengthHard)
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        dialog.select_all()
        def accept(editor):
            editor.input.setText('duplicate')
            editor.update_preview()
            return QDialog.DialogCode.Accepted
        with patch.object(self.plugin.BulkEditDialog, 'exec', accept):
            dialog.bulk_edit()
        self.assertEqual([feature['name'] for feature in layer.getFeatures()], ['0', '1', '2'])
        self.assertFalse(layer.undoStack().canUndo())
        self.assertIn('Bulk edit failed', dialog.status.text())

    def test_text_null_empty_whitespace_and_editor_roundtrip(self):
        from qgis.core import NULL
        from qgis.PyQt.QtWidgets import QStyleOptionViewItem

        role = self.plugin.NULL_ROLE
        layer = self.make_layer(1)
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        fid = dialog.row_fid(0)
        item = dialog.table.item(0, 0)
        for text in ("", "   ", "NULL"):
            item.setText(text)
            self.assertEqual(layer.getFeature(fid)[0], text)
        dialog.set_cell_null(0, 0)
        self.assertEqual(layer.getFeature(fid)[0], NULL)
        self.assertTrue(item.data(role))
        delegate = dialog.column_delegates['name']
        index = dialog.table.model().index(0, 0)
        editor = delegate.createEditor(dialog.table, QStyleOptionViewItem(), index)
        self.addCleanup(editor.deleteLater)
        delegate.setEditorData(editor, index)
        delegate.setModelData(editor, dialog.table.model(), index)
        self.assertEqual(layer.getFeature(fid)[0], NULL)
        dialog.set_cell_null(0, 0, False)
        self.assertEqual(layer.getFeature(fid)[0], "")
        self.assertFalse(item.data(role))

    def test_global_search_matches_wildcard_characters_literally(self):
        from qgis.core import QgsFeature, QgsVectorLayer

        layer = QgsVectorLayer('None?field=name:string', 'literal search', 'memory')
        for text in ('a%b', 'a_b', 'ordinary', 'A%B', "O'Brien\\x"):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([text])
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        for query, expected in (('%', ['a%b', 'A%B']), ('_', ['a_b']), ("O'Brien\\x", ["O'Brien\\x"])):
            with self.subTest(query=query):
                dialog.edit.setText(query)
                dialog.run_search()
                self.wait_for_results(dialog)
                self.assertEqual([dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())], expected)

    def test_integer_bounds_and_iso_temporal_conversion(self):
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QMetaType, QDateTime, QTime

        convert = self.plugin.FinderDialog.convert
        for kind, low, high in ((QMetaType.Type.Int, -(2**31), 2**31 - 1),
                                (QMetaType.Type.UInt, 0, 2**32 - 1),
                                (QMetaType.Type.LongLong, -(2**63), 2**63 - 1),
                                (QMetaType.Type.ULongLong, 0, 2**64 - 1)):
            field = QgsField('value', kind)
            for value in (low, high):
                self.assertEqual(convert(field, str(value)), value)
            for value in (low - 1, high + 1):
                with self.assertRaisesRegex(ValueError, 'range'):
                    convert(field, str(value))
        self.assertIsInstance(convert(QgsField('t', QMetaType.Type.QTime), '12:34:56'), QTime)
        self.assertIsInstance(convert(QgsField('t', QMetaType.Type.QDateTime), '2026-11-09T12:34:56Z'), QDateTime)
        for kind in (QMetaType.Type.QDate, QMetaType.Type.QDateTime, QMetaType.Type.QTime):
            with self.assertRaises(ValueError):
                convert(QgsField('t', kind), 'invalid')
        from quicktable.editing import attribute_text
        for kind, value in ((QMetaType.Type.QTime, '12:34:56.789'),
                            (QMetaType.Type.QDateTime, '2026-11-09T12:34:56.789Z')):
            field = QgsField('t', kind)
            self.assertEqual(attribute_text(convert(field, value)), value)
        with self.assertRaisesRegex(ValueError, 'length'):
            convert(QgsField('short', QMetaType.Type.QString, len=3), 'four')

    def test_hard_constraint_rejects_cell_edit_and_preserves_undo(self):
        from qgis.core import QgsFieldConstraints

        layer = self.make_layer(1)
        layer.setConstraintExpression(0, 'length("name") > 0', 'Name is required')
        layer.setFieldConstraint(0, QgsFieldConstraints.Constraint.ConstraintExpression,
                                 QgsFieldConstraints.ConstraintStrength.ConstraintStrengthHard)
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        fid = dialog.row_fid(0)
        dialog.table.item(0, 0).setText('')
        self.assertEqual(layer.getFeature(fid)[0], '0')
        self.assertEqual(dialog.table.item(0, 0).text(), '0')
        self.assertFalse(layer.undoStack().canUndo())

    def test_statistics_keep_integer_extrema_and_avoid_float_overflow(self):
        from qgis.core import QgsFeature, QgsVectorLayer, QgsVectorLayerFeatureSource

        for kind, values, expected in (('long', [9007199254740993, 2], 9007199254740995),
                                       ('double', [1e308, 1e308], None)):
            layer = QgsVectorLayer('None?field=value:' + kind, 'precise statistics', 'memory')
            for value in values:
                feature = QgsFeature(layer.fields())
                feature.setAttributes([value])
                layer.dataProvider().addFeatures([feature])
            result = self.plugin.collect_column_statistics(SimpleNamespace(isCanceled=lambda: False),
                QgsVectorLayerFeatureSource(layer), [(0, True)], [feature.id() for feature in layer.getFeatures()])
            summary = result['summaries'][0]
            if expected is not None:
                self.assertEqual(summary[2], expected)
                self.assertEqual(summary[4], 9007199254740993)
            else:
                self.assertIsInstance(summary[2], Decimal)
                self.assertTrue(summary[2].is_finite())
                self.assertEqual(float(summary[2] / 2), 1e308)

    def test_large_all_results_falls_back_to_safe_paging(self):
        dialog = self.create_dialog(self.make_layer(130))
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        with patch.object(self.plugin, 'MAX_RENDER_ROWS', 120):
            dialog.page_size.setCurrentIndex(dialog.page_size.findData(0))
        self.assertEqual(dialog.page_size.currentData(), 500)
        self.assertIn('display limit', dialog.status.text())

    def test_failed_save_and_discard_retain_pending_changes(self):
        from qgis.PyQt.QtWidgets import QMessageBox

        layer = self.make_layer(1)
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        dialog.table.item(0, 0).setText('changed')
        with patch.object(layer, 'commitChanges', return_value=False), \
             patch.object(layer, 'commitErrors', return_value=['test failure']):
            dialog.save_edits()
        self.assertTrue(layer.isModified())
        self.assertIn('test failure', dialog.status.text())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(layer, 'rollBack', return_value=False):
            dialog.discard_edits()
        self.assertTrue(layer.isModified())
        self.assertIn('Could not discard', dialog.status.text())

    def test_selected_scope_filters_without_id_list_expression(self):
        from qgis.core import QgsFeature, QgsVectorLayer, QgsVectorLayerFeatureSource

        layer = QgsVectorLayer('None?field=name:string&field=rank:integer', 'selected scope', 'memory')
        rows = [('alpha', 30), ('beta', 10), ('alpha_two', 20), ('gamma', 5)]
        features = []
        for name, rank in rows:
            feature = QgsFeature(layer.fields())
            feature.setAttributes([name, rank])
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        fids = [feature.id() for feature in layer.getFeatures()]
        source = QgsVectorLayerFeatureSource(layer)
        task = SimpleNamespace(isCanceled=lambda: False)

        self.assertEqual(self.plugin.collect_feature_ids(task, source, '', filter_fids=()), ())
        self.assertEqual(
            self.plugin.collect_feature_ids(task, source, '', 'rank', True, filter_fids=[fids[0], fids[1], fids[0]]),
            (fids[1], fids[0]),
        )
        self.assertEqual(
            self.plugin.collect_feature_ids(task, source, 'strpos("name", \'alpha\') > 0', 'rank', True,
                                            filter_fids=fids[:3]),
            (fids[2], fids[0]),
        )

        dialog = self.create_dialog(layer)
        layer.selectByIds(fids[:3])
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData('selected'))
        self.wait_for_results(dialog)
        self.assertNotIn('$id IN', dialog.build_expr())
        self.assertEqual(set(dialog.result_ids), set(fids[:3]))

        dialog.edit.setText('alpha')
        dialog.sort_header_column(1)
        self.wait_for_results(dialog)
        self.assertNotIn('$id IN', dialog.build_expr())
        self.assertEqual(tuple(dialog.result_ids), (fids[2], fids[0]))

    def test_visible_scope_filters_map_extent_and_tracks_pan(self):
        from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsProject, QgsRectangle, QgsVectorLayer
        from qgis.gui import QgsMapCanvas
        from qgis.PyQt.QtCore import Qt

        layer = QgsVectorLayer('Point?crs=EPSG:4326&field=name:string', 'visible scope', 'memory')
        for name, lon in (('west', 0.0), ('mid', 1.0), ('east', 10.0)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([name])
            feature.setGeometry(QgsGeometry.fromWkt('POINT ({} 0)'.format(lon)))
            layer.dataProvider().addFeatures([feature])
        ids = {f['name']: f.id() for f in layer.getFeatures()}

        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())
        canvas = QgsMapCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
        canvas.setLayers([layer])
        canvas.setExtent(QgsRectangle(-60000, -60000, 130000, 60000))
        signal = SimpleNamespace(connect=lambda slot: None, disconnect=lambda slot: None)
        iface = SimpleNamespace(currentLayerChanged=signal, activeLayer=lambda: layer, mapCanvas=lambda: canvas)

        dialog = self.plugin.FinderDialog(iface)
        self.addCleanup(dialog.shutdown)
        dialog.refresh()
        self.wait_for_results(dialog)
        dialog.show()

        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData('visible'))
        self.wait_for_results(dialog)
        self.assertEqual(set(dialog.result_ids), {ids['west'], ids['mid']})

        canvas.setExtent(QgsRectangle(1000000, -60000, 1200000, 60000))
        deadline = time.monotonic() + 10
        while (dialog.canvas_extent_timer.isActive() or dialog.query_task is not None) and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.wait_for_results(dialog)
        self.assertEqual(set(dialog.result_ids), {ids['east']})

        table_layer = QgsVectorLayer('None?field=name:string', 'plain table', 'memory')
        QgsProject.instance().addMapLayer(table_layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, table_layer.id())
        dialog.refresh_available_layers()
        dialog.layer.setCurrentIndex(dialog.layer.findData(table_layer.id()))
        self.wait_for_results(dialog)
        visible_item = dialog.scope_combo.model().item(dialog.scope_combo.findData('visible'))
        self.assertFalse(bool(visible_item.flags() & Qt.ItemFlag.ItemIsEnabled))

    def test_edited_and_new_scope_tracks_edit_buffer_changes(self):
        from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsVectorLayer

        layer = QgsVectorLayer('Point?crs=EPSG:4326&field=name:string', 'edited scope', 'memory')
        for name, lon in (('keep', 0.0), ('attr_edit', 1.0), ('geom_edit', 2.0), ('to_delete', 3.0)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([name])
            feature.setGeometry(QgsGeometry.fromWkt('POINT ({} 0)'.format(lon)))
            layer.dataProvider().addFeatures([feature])
        ids = {f['name']: f.id() for f in layer.getFeatures()}

        dialog = self.create_dialog(layer)
        dialog.show()
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData('edited'))
        self.wait_for_results(dialog)
        self.assertEqual(dialog.result_ids, ())

        self.assertTrue(layer.startEditing())
        self.assertTrue(layer.changeAttributeValue(ids['attr_edit'], 0, 'attr_edited'))
        self.assertTrue(layer.changeGeometry(ids['geom_edit'], QgsGeometry.fromWkt('POINT (9 0)')))
        self.assertTrue(layer.changeAttributeValue(ids['to_delete'], 0, 'changed_then_deleted'))
        self.assertTrue(layer.deleteFeature(ids['to_delete']))
        added = QgsFeature(layer.fields())
        added.setAttributes(['added_row'])
        added.setGeometry(QgsGeometry.fromWkt('POINT (4 0)'))
        self.assertTrue(layer.addFeature(added))

        deadline = time.monotonic() + 10
        while (dialog.timer.isActive() or dialog.query_task is not None) and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.wait_for_results(dialog)
        names = {layer.getFeature(fid)['name'] for fid in dialog.result_ids}
        self.assertEqual(names, {'attr_edited', 'geom_edit', 'added_row'})

        dialog.save_edits()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.result_ids, ())

    def test_features_preview_closed_by_default_and_selection_avoids_flicker(self):
        from qgis.core import QgsApplication

        layer, ids = self.make_preview_lots()
        flashed = []
        zoomed = []
        signal = SimpleNamespace(connect=lambda slot: None, disconnect=lambda slot: None)
        canvas = SimpleNamespace(
            zoomToSelected=lambda target: zoomed.append(target.id()),
            flashFeatureIds=lambda target, fids: flashed.append((target.id(), tuple(fids))),
        )
        iface = SimpleNamespace(currentLayerChanged=signal, activeLayer=lambda: layer, mapCanvas=lambda: canvas)
        from qgis.core import QgsProject
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())
        dialog = self.plugin.FinderDialog(iface)
        self.addCleanup(dialog.shutdown)
        dialog.refresh()
        self.wait_for_results(dialog)
        dialog.show()

        self.assertFalse(dialog.btn_nearby.isChecked())
        self.assertFalse(dialog.nearby_enabled)
        self.assertIsNone(dialog.nearby_preview_dialog)

        dialog.table.selectRow(0)
        QgsApplication.processEvents()
        self.assertEqual(zoomed, [])
        self.assertEqual(flashed, [])
        self.assertIsNone(dialog.nearby_preview_dialog)
        dialog.btn_zoom.click()
        self.assertEqual(zoomed, [layer.id()])

        dialog.btn_nearby.setChecked(True)
        first_panel = self.wait_for_lot_preview(dialog, [ids['first']], [ids['second']])
        layer.selectByIds([ids['second']])
        self.assertIs(dialog.nearby_preview_dialog, first_panel)
        updated_panel = self.wait_for_lot_preview(dialog, [ids['second']], [ids['first']])
        self.assertIs(updated_panel, first_panel)

    def test_zoom_to_selected_button_tracks_selection_without_auto_zoom(self):
        from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsRectangle
        from qgis.gui import QgsMapCanvas

        layer, ids = self.make_preview_lots()
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())
        canvas = QgsMapCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
        canvas.setLayers([layer])
        full_extent = QgsRectangle(-5, -5, 25, 5)
        canvas.setExtent(full_extent)
        signal = SimpleNamespace(connect=lambda slot: None, disconnect=lambda slot: None)
        iface = SimpleNamespace(currentLayerChanged=signal, activeLayer=lambda: layer, mapCanvas=lambda: canvas)

        dialog = self.plugin.FinderDialog(iface)
        self.addCleanup(dialog.shutdown)
        dialog.refresh()
        self.wait_for_results(dialog)
        dialog.show()

        self.assertFalse(hasattr(dialog, 'auto_zoom_cb'))
        self.assertEqual(dialog.btn_zoom.text(), 'Zoom to selected')
        self.assertFalse(dialog.btn_zoom.isEnabled())

        dialog.table.selectRow(0)
        QgsApplication.processEvents()
        self.assertAlmostEqual(canvas.extent().width(), full_extent.width(), places=5)
        self.assertTrue(dialog.btn_zoom.isEnabled())

        dialog.btn_zoom.click()
        QgsApplication.processEvents()
        self.assertLess(canvas.extent().width(), 10)
        self.assertEqual(set(layer.selectedFeatureIds()), {dialog.row_fid(0)})

        dialog.unselect_all()
        QgsApplication.processEvents()
        self.assertFalse(dialog.btn_zoom.isEnabled())

        canvas.setExtent(full_extent)
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData('visible'))
        self.wait_for_results(dialog)
        self.assertEqual(set(dialog.result_ids), set(ids.values()))

        before_select_extent = QgsRectangle(canvas.extent())
        dialog.table.selectRow(2)
        QgsApplication.processEvents()
        self.assertAlmostEqual(canvas.extent().width(), before_select_extent.width(), places=5)
        self.assertTrue(dialog.btn_zoom.isEnabled())

        dialog.btn_zoom.click()
        QgsApplication.processEvents()
        self.assertLess(canvas.extent().width(), before_select_extent.width())
        self.assertEqual(set(layer.selectedFeatureIds()), {dialog.row_fid(2)})

    def test_preview_click_blocks_offscreen_features_in_visible_scope(self):
        from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsRectangle
        from qgis.gui import QgsMapCanvas
        from qgis.PyQt.QtCore import QPoint, Qt
        from qgis.PyQt.QtTest import QTest

        layer, ids = self.make_preview_lots()
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())
        canvas = QgsMapCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(400, 400)
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
        canvas.setLayers([layer])
        canvas.setExtent(QgsRectangle(-1.0, 0.0, 0.4, 0.8))
        signal = SimpleNamespace(connect=lambda slot: None, disconnect=lambda slot: None)
        iface = SimpleNamespace(currentLayerChanged=signal, activeLayer=lambda: layer, mapCanvas=lambda: canvas)

        dialog = self.plugin.FinderDialog(iface)
        self.addCleanup(dialog.shutdown)
        dialog.refresh()
        self.wait_for_results(dialog)
        dialog.show()
        dialog.btn_nearby.setChecked(True)
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData('visible'))
        self.wait_for_results(dialog)
        self.assertEqual(set(dialog.result_ids), {ids['first']})

        layer.selectByIds([ids['first']])
        panel = self.wait_for_lot_preview(dialog, [ids['first']], [ids['second']])
        self.assertGreater(panel.outside_band.numberOfVertices(), 0)
        self.assertEqual(panel.nearby_band.numberOfVertices(), 0)
        self.assertTrue(panel.outside_label.isVisibleTo(panel))
        self.assertIn('1 outside table', panel.message.text())
        offscreen_point = panel.canvas.getCoordinateTransform().transform(1.5, 0.5)
        QTest.mouseClick(panel.canvas.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(round(offscreen_point.x()), round(offscreen_point.y())))
        QgsApplication.processEvents()
        self.assertEqual(set(layer.selectedFeatureIds()), {ids['first']})
        self.assertEqual(set(dialog.result_ids), {ids['first']})
        self.assertIn('Visible on map', dialog.status.text())

        canvas.setExtent(QgsRectangle(-0.5, -0.5, 2.5, 2.5))
        deadline = time.monotonic() + 5
        while (dialog.canvas_extent_timer.isActive() or dialog.query_task is not None
               or set(dialog.result_ids or ()) != {ids['first'], ids['second']}) and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.assertEqual(set(dialog.result_ids), {ids['first'], ids['second']})
        self.assertGreater(panel.nearby_band.numberOfVertices(), 0)
        self.assertEqual(panel.outside_band.numberOfVertices(), 0)
        self.assertFalse(panel.outside_label.isVisibleTo(panel))

        visible_point = panel.canvas.getCoordinateTransform().transform(1.5, 0.5)
        QTest.mouseClick(panel.canvas.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(round(visible_point.x()), round(visible_point.y())))
        QgsApplication.processEvents()
        self.assertEqual(set(layer.selectedFeatureIds()), {ids['second']})
        self.assertEqual(dialog.row_fid(dialog.table.currentRow()), ids['second'])

    def test_touching_preview_is_touching_only_and_caps_results(self):
        from qgis.core import (QgsFeature, QgsGeometry, QgsRectangle,
                               QgsProject, QgsVectorLayer, QgsVectorLayerFeatureSource)

        layer = QgsVectorLayer('Polygon?crs=EPSG:3857&field=name:string', 'dense_lots', 'memory')
        features = []
        origin = QgsFeature(layer.fields())
        origin.setGeometry(QgsGeometry.fromRect(QgsRectangle(0.0, 0.0, 120.0, 1.0)))
        origin.setAttributes(['origin'])
        features.append(origin)
        for index in range(115):
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromRect(QgsRectangle(float(index), 1.0, float(index) + 0.5, 2.0)))
            feat.setAttributes([f'p{index}'])
            features.append(feat)
        layer.dataProvider().addFeatures(features)
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())

        early = self.plugin.collect_nearby(
            SimpleNamespace(isCanceled=lambda: False),
            QgsVectorLayerFeatureSource(layer), [1], None, max_matches=3,
        )
        self.assertEqual(len(early), 3)

        meta = {'limited': False}
        scanned = self.plugin.collect_nearby(
            SimpleNamespace(isCanceled=lambda: False),
            QgsVectorLayerFeatureSource(layer), [1], None, max_candidates=4, meta=meta,
        )
        self.assertTrue(meta['limited'])
        self.assertEqual(len(scanned), 4)

        dialog = self.create_dialog(layer)
        dialog.show()
        dialog.btn_nearby.setChecked(True)
        layer.selectByIds([1])

        deadline = time.monotonic() + 8
        while (dialog.nearby_update_timer.isActive() or dialog.nearby_task is not None
               or not (isinstance(dialog.nearby_preview_dialog, self.plugin.NearbyPreviewPanel)
                       and dialog.nearby_preview_dialog.nearby_limited)) and time.monotonic() < deadline:
            from qgis.core import QgsApplication
            QgsApplication.processEvents()
            time.sleep(0.01)

        panel = dialog.nearby_preview_dialog
        self.assertIsInstance(panel, self.plugin.NearbyPreviewPanel)
        self.assertFalse(hasattr(panel, 'distance_value'))
        self.assertFalse(hasattr(panel, 'distance_units'))
        self.assertFalse(hasattr(panel, 'apply_distance'))
        self.assertTrue(panel.nearby_limited)
        self.assertEqual(panel.nearby_count, 100)
        self.assertEqual(len(dialog.nearby_match_ids), 100)
        self.assertIn('100+ touching feature(s) found.', panel.message.text())
        self.assertIn('Map preview is limited; the table is unchanged.', panel.message.text())

    def test_preview_autofits_when_recentered_extent_misses_selected_multipolygon(self):
        from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer

        layer = QgsVectorLayer('Polygon?crs=EPSG:4326&field=name:string', 'islands', 'memory')
        small = QgsFeature(layer.fields())
        small.setAttributes(['small'])
        small.setGeometry(QgsGeometry.fromWkt(
            'POLYGON ((121.0 14.0, 121.001 14.0, 121.001 14.001, 121.0 14.001, 121.0 14.0))'))
        islands = QgsFeature(layer.fields())
        islands.setAttributes(['islands'])
        islands.setGeometry(QgsGeometry.fromWkt(
            'MULTIPOLYGON (((120.0 10.0, 120.1 10.0, 120.1 10.1, 120.0 10.1, 120.0 10.0)),'
            '((120.5 10.4, 120.6 10.4, 120.6 10.5, 120.5 10.5, 120.5 10.4)))'
        ))
        layer.dataProvider().addFeatures([small, islands])
        ids = {f['name']: f.id() for f in layer.getFeatures()}
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())

        dialog = self.create_dialog(layer)
        dialog.show()
        dialog.btn_nearby.setChecked(True)
        layer.selectByIds([ids['small']])
        self.wait_for_lot_preview(dialog, [ids['small']], [])

        layer.selectByIds([ids['islands']])
        panel = self.wait_for_lot_preview(dialog, [ids['islands']], [])
        QgsApplication.processEvents()
        self.assertGreater(panel.canvas.extent().width(), 0.5)
        self.assertIn('No touching features found.', panel.message.text())

    def test_collect_nearby_geographic_spatial_prefilter(self):
        from qgis.core import (QgsFeature, QgsGeometry, QgsPointXY,
                               QgsProject, QgsVectorLayer, QgsVectorLayerFeatureSource)

        layer = QgsVectorLayer('Point?crs=EPSG:4326&field=name:string', 'geo_pts', 'memory')
        origin = QgsFeature(layer.fields())
        origin.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(121.0, 14.5)))
        origin.setAttributes(['origin'])
        near = QgsFeature(layer.fields())
        near.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(121.0001, 14.5)))
        near.setAttributes(['near'])
        far = QgsFeature(layer.fields())
        far.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-60.0, -20.0)))
        far.setAttributes(['far'])
        layer.dataProvider().addFeatures([origin, near, far])
        fids = {f.attribute('name'): f.id() for f in layer.getFeatures()}

        matches = self.plugin.collect_nearby(
            SimpleNamespace(isCanceled=lambda: False),
            QgsVectorLayerFeatureSource(layer), [fids['origin']], 50.0,
            layer.crs(), QgsProject.instance().transformContext(),
        )
        self.assertEqual(matches, (fids['near'],))

    def test_touching_preview_detects_overlaps_and_prefers_nearby_on_shared_click(self):
        from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
        from qgis.PyQt.QtCore import QPoint, Qt
        from qgis.PyQt.QtTest import QTest

        layer = QgsVectorLayer('Polygon?crs=EPSG:3857&field=name:string', 'overlap_lots', 'memory')
        small = QgsFeature(layer.fields())
        small.setAttributes(['small'])
        small.setGeometry(QgsGeometry.fromWkt('POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))'))
        huge = QgsFeature(layer.fields())
        huge.setAttributes(['huge'])
        huge.setGeometry(QgsGeometry.fromWkt('POLYGON ((1 0, 20 0, 20 20, 1 20, 1 0))'))
        layer.dataProvider().addFeatures([small, huge])
        ids = {f['name']: f.id() for f in layer.getFeatures()}
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())

        dialog = self.create_dialog(layer)
        dialog.show()
        self.wait_for_results(dialog)
        dialog.btn_nearby.setChecked(True)
        layer.selectByIds([ids['small']])
        panel = self.wait_for_lot_preview(dialog, [ids['small']], [ids['huge']])
        QgsApplication.processEvents()

        overlap_point = panel.canvas.getCoordinateTransform().transform(2.0, 1.5)
        QTest.mouseClick(panel.canvas.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(round(overlap_point.x()), round(overlap_point.y())))
        QgsApplication.processEvents()
        self.assertEqual(set(layer.selectedFeatureIds()), {ids['huge']})
        panel = self.wait_for_lot_preview(dialog, [ids['huge']], [ids['small']])
        self.assertGreater(panel.canvas.extent().width(), 15.0)

    def test_collect_nearby_preview_simplifies_dense_geometries_instead_of_dropping_neighbors(self):
        import math
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer, QgsVectorLayerFeatureSource

        layer = QgsVectorLayer('Polygon?crs=EPSG:3857&field=name:string', 'dense_provinces', 'memory')
        features = []
        # 5 dense polygons (~1.6 MB WKB each -> ~8 MB total raw, exceeds 5 MB raw budget)
        n_verts = 100000
        for idx in range(5):
            ring = [
                QgsPointXY(
                    idx * 10000.0 + 4000.0 * math.cos(2 * math.pi * k / n_verts),
                    4000.0 * math.sin(2 * math.pi * k / n_verts),
                )
                for k in range(n_verts)
            ]
            ring.append(ring[0])
            feat = QgsFeature(layer.fields())
            feat.setAttributes([f'prov{idx}'])
            feat.setGeometry(QgsGeometry.fromPolygonXY([ring]))
            features.append(feat)
        layer.dataProvider().addFeatures(features)
        ids = [f.id() for f in layer.getFeatures()]

        snapshot = self.plugin.collect_nearby_preview(
            SimpleNamespace(isCanceled=lambda: False),
            QgsVectorLayerFeatureSource(layer),
            [ids[0]],
            ids[1:],
        )
        self.assertEqual(set(snapshot['selected']), {ids[0]})
        self.assertEqual(set(snapshot['nearby']), set(ids[1:]))
        self.assertFalse(snapshot['truncated'])

    def test_collect_nearby_task_builds_preview_snapshot_in_single_pass(self):
        from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer, QgsVectorLayerFeatureSource

        layer = QgsVectorLayer('Polygon?crs=EPSG:3857&field=name:string', 'single_pass_lots', 'memory')
        specs = [
            ('center', 'POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))'),
            ('west', 'POLYGON ((-10 0, 0 0, 0 10, -10 10, -10 0))'),
            ('east', 'POLYGON ((10 0, 20 0, 20 10, 10 10, 10 0))'),
            ('far', 'POLYGON ((50 50, 60 50, 60 60, 50 60, 50 50))'),
        ]
        features = []
        for name, wkt in specs:
            feat = QgsFeature(layer.fields())
            feat.setAttributes([name])
            feat.setGeometry(QgsGeometry.fromWkt(wkt))
            features.append(feat)
        layer.dataProvider().addFeatures(features)
        ids = {f['name']: f.id() for f in layer.getFeatures()}

        source = QgsVectorLayerFeatureSource(layer)
        task_stub = SimpleNamespace(isCanceled=lambda: False)
        matches, limited, snapshot = self.plugin.collect_nearby_task(
            task_stub, source, [ids['center']], None, max_matches=101, preview_limit=100
        )
        self.assertEqual(set(matches), {ids['west'], ids['east']})
        self.assertFalse(limited)
        self.assertEqual(set(snapshot['selected']), {ids['center']})
        self.assertEqual(set(snapshot['nearby']), {ids['west'], ids['east']})
        self.assertFalse(snapshot['truncated'])

        limited_matches, hit_limit, limited_snapshot = self.plugin.collect_nearby_task(
            task_stub, source, [ids['center']], None, max_matches=2, preview_limit=1
        )
        self.assertEqual(len(limited_matches), 2)
        self.assertTrue(hit_limit)
        self.assertEqual(len(limited_snapshot['nearby']), 1)
        self.assertTrue(limited_snapshot['truncated'])

    def test_attribute_edit_on_unrelated_column_skips_requery_and_tracks_stale_popups(self):
        from qgis.core import QgsFeature, QgsProject, QgsVectorLayer

        layer = QgsVectorLayer('None?field=name:string&field=notes:string', 'edit_opt', 'memory')
        features = []
        for name, note in (('alpha', 'n1'), ('beta', 'n2'), ('gamma', 'n3')):
            feat = QgsFeature(layer.fields())
            feat.setAttributes([name, note])
            features.append(feat)
        layer.dataProvider().addFeatures(features)
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())

        dialog = self.create_dialog(layer)
        dialog.open_field_filter('name')
        filter_row = dialog.filter_rows[0]
        filter_row.value.set_selected_values(['alpha', 'beta'])
        filter_row.widget.hide()
        dialog.edit_cb.setChecked(True)
        dialog.run_search()
        self.wait_for_results(dialog)

        old_token = dialog._result_ids_token
        self.assertFalse(dialog._edit_requires_requery('notes'))
        dialog.table.item(0, 1).setText('updated_note')
        self.assertIsNone(dialog.query_task)
        self.assertEqual(dialog._result_ids_token, old_token)
        self.assertIn(id(filter_row), dialog._stale_value_rows)

        dialog.open_field_filter('name')
        filter_row.widget.hide()
        self.assertNotIn(id(filter_row), dialog._stale_value_rows)

    def test_collect_nearby_task_precomputes_labels_and_panel_reuses_placements(self):
        import importlib
        from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer, QgsVectorLayerFeatureSource

        layer = QgsVectorLayer('Polygon?crs=EPSG:3857&field=name:string', 'label_cache_lots', 'memory')
        specs = [
            ('center', 'POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))'),
            ('west', 'POLYGON ((-10 0, 0 0, 0 10, -10 10, -10 0))'),
            ('east', 'POLYGON ((10 0, 20 0, 20 10, 10 10, 10 0))'),
        ]
        features = []
        for name, wkt in specs:
            feat = QgsFeature(layer.fields())
            feat.setAttributes([name])
            feat.setGeometry(QgsGeometry.fromWkt(wkt))
            features.append(feat)
        layer.dataProvider().addFeatures(features)
        ids = {f['name']: f.id() for f in layer.getFeatures()}
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())

        source = QgsVectorLayerFeatureSource(layer)
        _, _, snapshot = self.plugin.collect_nearby_task(
            SimpleNamespace(isCanceled=lambda: False),
            source, [ids['center']], None, preview_limit=100, label_field='name'
        )
        self.assertEqual(snapshot['labels'], {ids['center']: 'center', ids['west']: 'west', ids['east']: 'east'})
        self.assertEqual(set(snapshot['label_placements']), set(snapshot['labels']))
        for placement in snapshot['label_placements'].values():
            self.assertEqual(len(placement), 3)

        dialog = self.create_dialog(layer)
        dialog.show()
        dialog.btn_nearby.setChecked(True)
        layer.selectByIds([ids['center']])
        panel = self.wait_for_lot_preview(dialog, [ids['center']], [ids['west'], ids['east']])
        panel.label_field.setCurrentIndex(panel.label_field.findData('name'))
        QgsApplication.processEvents()
        self.assertEqual(set(panel._label_placements), set(ids.values()))

        preview_mod = importlib.import_module(self.plugin.__package__ + '.preview_panel')
        with patch.object(preview_mod, 'preview_label_placement', side_effect=AssertionError('should reuse cache')):
            panel.update_labels(refresh_values=False)

    def test_collect_column_statistics_single_pass_histogram(self):
        from qgis.core import QgsFeature, QgsVectorLayer, QgsVectorLayerFeatureSource

        layer = QgsVectorLayer('None?field=ival:integer&field=dval:double&field=label:string', 'stats_opt', 'memory')
        features = []
        for i in range(25):
            feat = QgsFeature(layer.fields())
            feat.setAttributes([i, i * 1.5, f'k{i % 5}'])
            features.append(feat)
        layer.dataProvider().addFeatures(features)

        result = self.plugin.collect_column_statistics(
            SimpleNamespace(isCanceled=lambda: False),
            QgsVectorLayerFeatureSource(layer),
            [(0, True), (1, True), (2, False)],
            [f.id() for f in layer.getFeatures()],
        )
        summaries = result['summaries']
        self.assertEqual(summaries[0][:6], [25, 0, 300, 0, 24, True])
        self.assertEqual(sum(summaries[0][6]['histogram']), 25)
        self.assertEqual(len(summaries[0][6]['histogram']), 16)
        self.assertEqual(summaries[1][:6], [25, 0, 450.0, 0.0, 36.0, True])
        self.assertEqual(sum(summaries[1][6]['histogram']), 25)
        self.assertEqual(summaries[2][6]['distinct'], 5)

    def test_value_popup_defers_refresh_when_hidden_and_updates_counts_incrementally(self):
        from qgis.PyQt.QtCore import Qt

        layer = self.make_layer(3)
        dialog = self.create_dialog(layer)
        dialog.open_field_filter('name')
        row = dialog.filter_rows[0]
        popup = row.choices
        row.widget.hide()

        popup.schedule_refresh()
        self.assertFalse(popup.refresh_timer.isActive())

        row.value.clear()
        row.value.addItem('All values')
        for val in ('0', '1', '2'):
            row.value.addItem(val)
        popup.refresh_choices()
        popup.items['1'].setCheckState(Qt.CheckState.Checked)
        self.assertEqual(row.value.selected_values, ['1'])
        self.assertEqual(popup.items[None].checkState(), Qt.CheckState.Unchecked)
        self.assertIn('1 checked', popup.count.text())

        popup.items[None].setCheckState(Qt.CheckState.Checked)
        self.assertEqual(row.value.selected_values, [])
        self.assertEqual(popup.items['1'].checkState(), Qt.CheckState.Unchecked)
        self.assertIn('0 checked', popup.count.text())

    def test_edit_mode_toggle_keeps_query_cache_and_rollback_invalidates_it(self):
        from qgis.core import QgsApplication

        layer = self.make_layer(5)
        dialog = self.create_dialog(layer)
        dialog.show()
        QgsApplication.processEvents()
        token_before = dialog._result_ids_token
        ids_before = list(dialog.result_ids)
        fid = dialog.row_fid(0)
        original_text = dialog.table.item(0, 0).text()

        dialog.edit_cb.setChecked(True)
        QgsApplication.processEvents()
        self.assertTrue(layer.isEditable())
        self.assertEqual(dialog._result_ids_token, token_before)
        self.assertEqual(list(dialog.result_ids), ids_before)
        self.assertIsNone(dialog.query_task)
        self.assertFalse(dialog.timer.isActive())

        self.assertTrue(layer.changeAttributeValue(fid, 0, 'edited'))
        dialog.refresh()
        self.wait_for_results(dialog)
        self.assertTrue(layer.rollBack())
        QgsApplication.processEvents()
        self.assertFalse(layer.isEditable())
        self.assertFalse(dialog.edit_cb.isChecked())
        self.assertTrue(dialog.timer.isActive())
        self.assertIsNone(dialog.result_ids)
        dialog.refresh()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.table.item(0, 0).text(), original_text)

    def test_preview_labels_follow_dark_theme_and_refresh_on_theme_change(self):
        from qgis.core import QgsApplication
        from qgis.PyQt.QtGui import QImage, QPainter
        from qgis.PyQt.QtWidgets import QStyleOptionGraphicsItem
        from quicktable.themes import THEMES

        for key in ('preview_halo', 'preview_label_selected', 'preview_label'):
            self.assertIn(key, THEMES['light'])
            self.assertIn(key, THEMES['dark'])

        layer, ids = self.make_preview_lots()
        dialog = self.create_dialog(layer)
        dialog.theme = 'light'
        dialog.apply_theme()
        dialog.show()
        dialog.btn_nearby.setChecked(True)
        layer.selectByIds([ids['first']])
        panel = self.wait_for_lot_preview(dialog, [ids['first']], [ids['second']])
        panel.label_field.setCurrentIndex(panel.label_field.findData('name'))
        QgsApplication.processEvents()
        self.assertEqual(panel.label_items[ids['first']].theme, 'light')

        dialog.theme = 'dark'
        dialog.apply_theme()
        QgsApplication.processEvents()
        dark_item = panel.label_items[ids['first']]
        self.assertEqual(dark_item.theme, 'dark')
        image = QImage(160, 48, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            dark_item.paint(painter, QStyleOptionGraphicsItem(), None)
        finally:
            painter.end()

    def test_column_text_delegate_reuses_size_document(self):
        from qgis.PyQt.QtWidgets import QStyleOptionViewItem

        layer = self.make_layer(3)
        dialog = self.create_dialog(layer)
        delegate = dialog.table.itemDelegateForColumn(0)
        doc_before = delegate._size_document
        index = dialog.table.model().index(0, 0)
        hint_first = delegate.sizeHint(QStyleOptionViewItem(), index)
        hint_second = delegate.sizeHint(QStyleOptionViewItem(), dialog.table.model().index(1, 0))
        self.assertIs(delegate._size_document, doc_before)
        self.assertGreater(hint_first.height(), 0)
        self.assertGreater(hint_second.height(), 0)

    def test_validation_request_only_fetches_geometry_for_hard_constraints(self):
        from qgis.core import QgsFeature, QgsFeatureRequest, QgsFieldConstraints, QgsVectorLayer
        from quicktable.editing import validation_request

        layer = QgsVectorLayer('Polygon?crs=EPSG:3857&field=name:string', 'constraints', 'memory')
        feature = QgsFeature(layer.fields())
        feature.setAttributes(['lot'])
        layer.dataProvider().addFeatures([feature])
        fid = next(layer.getFeatures()).id()

        layer.setConstraintExpression(0, 'area($geometry) > 0', 'geometry check')
        layer.setFieldConstraint(
            0,
            QgsFieldConstraints.Constraint.ConstraintExpression,
            QgsFieldConstraints.ConstraintStrength.ConstraintStrengthSoft,
        )
        soft_req = validation_request(layer, [fid])
        self.assertTrue(bool(soft_req.flags() & QgsFeatureRequest.Flag.NoGeometry))

        layer.setFieldConstraint(
            0,
            QgsFieldConstraints.Constraint.ConstraintExpression,
            QgsFieldConstraints.ConstraintStrength.ConstraintStrengthHard,
        )
        hard_req = validation_request(layer, [fid])
        self.assertFalse(bool(hard_req.flags() & QgsFeatureRequest.Flag.NoGeometry))

    def test_render_page_reuses_items_and_clears_edited_background_on_page_flip(self):
        from qgis.PyQt.QtCore import Qt

        layer = self.make_layer(150)
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        self.wait_for_results(dialog)
        dialog.edit_cb.setChecked(True)
        fid = dialog.row_fid(0)
        self.assertTrue(layer.changeAttributeValue(fid, 0, 'edited-cell'))
        dialog.refresh()
        self.wait_for_results(dialog)

        first_item = dialog.table.item(0, 0)
        self.assertNotEqual(first_item.background().style(), Qt.BrushStyle.NoBrush)
        dialog.change_page(1)
        self.assertIs(dialog.table.item(0, 0), first_item)
        self.assertEqual(first_item.background().style(), Qt.BrushStyle.NoBrush)

    def test_toolbar_dropdown_and_menu_launch_prefiltered_scopes_under_option_a(self):
        from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
        from qgis.PyQt.QtWidgets import QMainWindow, QToolBar, QToolButton

        spatial = QgsVectorLayer('Point?crs=EPSG:3857&field=name:string', 'points', 'memory')
        for label, x in (('first', 0), ('second', 1), ('third', 2)):
            feat = QgsFeature(spatial.fields())
            feat.setAttributes([label])
            feat.setGeometry(QgsGeometry.fromWkt('POINT ({} 0)'.format(x)))
            spatial.dataProvider().addFeatures([feat])
        plain = QgsVectorLayer('None?field=name:string', 'table_only', 'memory')
        QgsProject.instance().addMapLayer(spatial)
        QgsProject.instance().addMapLayer(plain)
        self.addCleanup(QgsProject.instance().removeMapLayer, spatial.id())
        self.addCleanup(QgsProject.instance().removeMapLayer, plain.id())

        spatial_ids = [f.id() for f in spatial.getFeatures()]
        spatial.selectByIds([spatial_ids[1]])

        current_active = [plain]
        signal = SimpleNamespace(connect=lambda slot: None, disconnect=lambda slot: None)
        window = QMainWindow()
        toolbar = QToolBar(window)
        self.addCleanup(window.deleteLater)
        menu_added, menu_removed = [], []
        iface = SimpleNamespace(
            mainWindow=lambda: window,
            activeLayer=lambda: current_active[0],
            currentLayerChanged=signal,
            pluginToolBar=lambda: toolbar,
            addToolBarIcon=toolbar.addAction,
            removeToolBarIcon=toolbar.removeAction,
            addPluginToMenu=lambda name, act: menu_added.append((name, act)),
            removePluginMenu=lambda name, act: menu_removed.append((name, act)),
        )
        plugin = self.plugin.QuickFilter(iface)
        self.addCleanup(plugin.unload)
        plugin.initGui()

        button = toolbar.widgetForAction(plugin.action)
        self.assertIsInstance(button, QToolButton)
        self.assertEqual(button.popupMode(), QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.assertEqual([a.data() for a in plugin.scope_menu.actions()], ['all', 'selected', 'visible', 'edited'])
        self.assertEqual(
            [a.text() for a in plugin.scope_menu.actions()],
            ['Open All Features', 'Open Selected Features', 'Open Visible on Map', 'Open Edited and New'],
        )
        self.assertTrue(all(not a.icon().isNull() for a in plugin.scope_actions.values()))
        self.assertEqual([name for name, _ in menu_added], ['&QuickTable'] * 4)
        self.assertEqual([act.data() for _, act in menu_added], ['all', 'selected', 'visible', 'edited'])

        # Non-spatial target disables "visible" in the dropdown menu without touching Plugins menu actions.
        plugin.update_scope_menu_state()
        self.assertFalse(plugin.scope_actions['visible'].isEnabled())
        self.assertTrue(plugin.menu_actions['visible'].isEnabled())

        current_active[0] = spatial
        plugin.update_scope_menu_state()
        self.assertTrue(plugin.scope_actions['visible'].isEnabled())

        # Fresh launch into Selected Features runs only one search pre-filtered to the selection.
        run_calls = []
        orig_run = self.plugin.FinderDialog.run_search

        def counting_run(dlg, *args, **kwargs):
            run_calls.append(dlg.current_scope())
            return orig_run(dlg, *args, **kwargs)

        with patch.object(self.plugin.FinderDialog, 'run_search', counting_run):
            plugin.scope_actions['selected'].trigger()
            self.wait_for_results(plugin.dlg)

        self.assertEqual(run_calls, ['selected'])
        self.assertEqual(plugin.dlg.current_scope(), 'selected')
        self.assertEqual(list(plugin.dlg.result_ids), [spatial_ids[1]])

        # Switching QGIS active layer + clicking the main button preserves open layer and scope (Option A).
        plugin.dlg.edit.setText('second')
        current_active[0] = plain
        plugin.action.trigger()
        QgsApplication.processEvents()
        self.assertEqual(plugin.dlg.current_layer().id(), spatial.id())
        self.assertEqual(plugin.dlg.current_scope(), 'selected')
        self.assertEqual(plugin.dlg.edit.text(), 'second')

        # Picking All from the dropdown switches scope while keeping QuickTable's layer and text filter.
        plugin.scope_actions['all'].trigger()
        self.wait_for_results(plugin.dlg)
        self.assertEqual(plugin.dlg.current_layer().id(), spatial.id())
        self.assertEqual(plugin.dlg.current_scope(), 'all')
        self.assertEqual(plugin.dlg.edit.text(), 'second')

        plugin.unload()
        self.assertEqual(len(menu_removed), 4)
        self.assertIsNone(plugin.dlg)
        self.assertIsNone(plugin.action)

    def test_collect_nearby_prepared_geometry_matches_touching_and_overlapping(self):
        import importlib
        from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer, QgsVectorLayerFeatureSource

        tasks = importlib.import_module('quicktable.tasks')
        layer = QgsVectorLayer('Polygon?crs=EPSG:3857&field=name:string', 'nearby_prep', 'memory')
        specs = [
            ('origin', 'POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))'),
            ('touching', 'POLYGON ((10 0, 20 0, 20 10, 10 10, 10 0))'),
            ('overlapping', 'POLYGON ((5 5, 15 5, 15 15, 5 15, 5 5))'),
            ('corner', 'POLYGON ((-5 -5, 0 -5, 0 0, -5 0, -5 -5))'),
            ('far', 'POLYGON ((100 100, 110 100, 110 110, 100 110, 100 100))'),
        ]
        features = []
        for name, wkt in specs:
            feat = QgsFeature(layer.fields())
            feat.setAttributes([name])
            feat.setGeometry(QgsGeometry.fromWkt(wkt))
            features.append(feat)
        layer.dataProvider().addFeatures(features)
        by_name = {feat['name']: feat.id() for feat in layer.getFeatures()}

        matches = tasks.collect_nearby(
            SimpleNamespace(isCanceled=lambda: False),
            QgsVectorLayerFeatureSource(layer),
            [by_name['origin']],
            distance=None,
            source_crs=layer.crs(),
        )
        self.assertEqual(set(matches), {by_name['touching'], by_name['overlapping'], by_name['corner']})

    def test_collect_feature_ids_skips_sort_when_ordered_and_sorts_out_of_order(self):
        import importlib

        tasks = importlib.import_module('quicktable.tasks')

        class _FakeIterator:
            def __init__(self, fids):
                self._fids = fids
                self.closed = False

            def __iter__(self):
                return (SimpleNamespace(id=lambda fid=fid: fid) for fid in self._fids)

            def close(self):
                self.closed = True

        def make_source(fids):
            return SimpleNamespace(getFeatures=lambda req: _FakeIterator(fids))

        sort_calls = []
        orig_sorted = sorted

        def tracking_sorted(iterable, *args, **kwargs):
            sort_calls.append(len(iterable))
            return orig_sorted(iterable, *args, **kwargs)

        with patch.object(tasks, 'sorted', tracking_sorted, create=True):
            ordered = tasks.collect_feature_ids(
                SimpleNamespace(isCanceled=lambda: False),
                make_source([1, 2, 5, 5, 9]),
                expression='',
            )
            self.assertEqual(ordered, (1, 2, 5, 5, 9))
            self.assertEqual(sort_calls, [])

            unordered = tasks.collect_feature_ids(
                SimpleNamespace(isCanceled=lambda: False),
                make_source([5, 1, 9, 2]),
                expression='',
            )
            self.assertEqual(unordered, (1, 2, 5, 9))
            self.assertEqual(sort_calls, [4])

    def test_collect_column_statistics_full_layer_and_integer_overflow(self):
        import importlib
        from qgis.core import QgsFeature, QgsVectorLayer, QgsVectorLayerFeatureSource

        tasks = importlib.import_module('quicktable.tasks')
        layer = QgsVectorLayer(
            'None?field=ival:integer8&field=dval:double&field=tag:string',
            'stats_full_layer',
            'memory',
        )
        rows = [
            [10, 1.5, 'alpha'],
            [20, float('nan'), 'beta'],
            [10, 2.5, 'alpha'],
            [None, None, None],
        ]
        features = []
        for attrs in rows:
            feat = QgsFeature(layer.fields())
            feat.setAttributes(attrs)
            features.append(feat)
        layer.dataProvider().addFeatures(features)
        fids = [feat.id() for feat in layer.getFeatures()]
        source = QgsVectorLayerFeatureSource(layer)
        cols = [(0, True), (1, True), (2, False)]

        filtered = self.plugin.collect_column_statistics(
            SimpleNamespace(isCanceled=lambda: False), source, cols, fids, full_layer=False
        )
        full = self.plugin.collect_column_statistics(
            SimpleNamespace(isCanceled=lambda: False), source, cols, fids, full_layer=True
        )
        self.assertEqual(filtered, full)
        self.assertEqual(full['summaries'][0][:6], [3, 1, 40, 10, 20, True])
        self.assertEqual(full['summaries'][0][6]['distinct'], 2)
        self.assertEqual(full['summaries'][1][6]['nonfinite'], 1)
        self.assertEqual(full['summaries'][1][6]['numeric_count'], 2)

        # Signed 64-bit integer array promotes cleanly when an oversized integer arrives.
        big_int = 2 ** 70

        class _FakeFields:
            def __getitem__(self, _idx):
                return SimpleNamespace(isNumeric=lambda: True)

        class _FakeIter:
            def __iter__(self):
                return iter(([5], [big_int], [5]))

            def close(self):
                pass

        fake_fields = _FakeFields()
        fake_source = SimpleNamespace(
            fields=lambda: fake_fields,
            getFeatures=lambda _req: _FakeIter(),
        )
        with patch.object(tasks, 'field_kind', lambda _f: 'integer'):
            overflow_result = tasks.collect_column_statistics(
                SimpleNamespace(isCanceled=lambda: False), fake_source, [(0, True)], (1, 2, 3)
            )
        summary = overflow_result['summaries'][0]
        self.assertEqual(summary[0], 3)
        self.assertEqual(summary[2], big_int + 10)
        self.assertEqual(summary[4], big_int)
        self.assertEqual(sum(summary[6]['histogram']), 3)

    def test_render_page_fetches_visible_columns_and_unhides_via_apply_visibility(self):
        from qgis.PyQt.QtCore import QSettings, Qt
        from qgis.core import QgsFeature, QgsProject, QgsVectorLayer

        layer = QgsVectorLayer('None?field=col0:string&field=col1:string&field=col2:string', 'vis_cols', 'memory')
        for idx in range(3):
            feat = QgsFeature(layer.fields())
            feat.setAttributes([f'a{idx}', f'b{idx}', f'c{idx}'])
            layer.dataProvider().addFeatures([feat])
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())

        dialog = self.create_dialog(layer)
        key = dialog.column_settings_key()
        self.addCleanup(QSettings().remove, key)
        QSettings().setValue(key, ['col0', 'col1'])

        captured_subsets = []
        orig_get_features = QgsVectorLayer.getFeatures

        def spy_get_features(lyr, req=None):
            if req is not None and lyr.id() == layer.id():
                captured_subsets.append(list(req.subsetOfAttributes()))
            return orig_get_features(lyr, req) if req is not None else orig_get_features(lyr)

        with patch.object(QgsVectorLayer, 'getFeatures', spy_get_features):
            dialog._column_layout_dirty = True
            dialog.render_page()

        self.assertIn([2], captured_subsets)
        self.assertTrue(dialog.table.isColumnHidden(0))
        self.assertTrue(dialog.table.isColumnHidden(1))
        self.assertFalse(dialog.table.isColumnHidden(2))
        self.assertIsNone(dialog.table.item(0, 1))
        self.assertEqual(dialog.table.item(0, 2).text(), 'c0')
        # Hidden column 0 retains UserRole FID so selection works reliably.
        expected_fid = dialog.result_ids[0]
        self.assertEqual(dialog.table.item(0, 0).data(Qt.ItemDataRole.UserRole), expected_fid)
        dialog.table.selectRow(0)
        self.assertEqual(dialog.selected_fids(), [expected_fid])

        # Making col1 visible through settings repopulates the missing column automatically.
        captured_subsets.clear()
        QSettings().setValue(key, ['col0'])
        with patch.object(QgsVectorLayer, 'getFeatures', spy_get_features):
            dialog.apply_column_visibility()
        self.assertIn([1, 2], captured_subsets)
        self.assertEqual(dialog.table.item(0, 1).text(), 'b0')

    def test_closed_filter_popups_defer_scans_and_skip_redundant_search(self):
        import time
        from qgis.core import QgsApplication, QgsFeature, QgsProject, QgsVectorLayer

        layer = QgsVectorLayer('None?field=barangay:string&field=section:string&field=zone:string', 'lazy_popups', 'memory')
        for b, s, z in (('A', 'S1', 'Z1'), ('B', 'S2', 'Z2')):
            feat = QgsFeature(layer.fields())
            feat.setAttributes([b, s, z])
            layer.dataProvider().addFeatures([feat])
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())

        dialog = self.create_dialog(layer)
        fill_calls = []
        run_calls = []
        orig_fill = dialog.fill_values
        orig_run = dialog.run_search

        def wait_value_tasks():
            deadline = time.monotonic() + 10
            while dialog.value_tasks and time.monotonic() < deadline:
                QgsApplication.processEvents()
                time.sleep(0.01)
            self.assertFalse(dialog.value_tasks)

        def spy_fill(field_combo, *args, **kwargs):
            fill_calls.append(field_combo.currentText())
            return orig_fill(field_combo, *args, **kwargs)

        def spy_run(*args, **kwargs):
            run_calls.append(True)
            return orig_run(*args, **kwargs)

        with patch.object(dialog, 'fill_values', spy_fill), patch.object(dialog, 'run_search', spy_run):
            dialog.open_field_filter('section')
            section_row = dialog.filter_rows[0]
            wait_value_tasks()
            # Opening an unfiltered popup scans only 'section' once and triggers no redundant search.
            self.assertEqual(fill_calls, ['section'])
            self.assertEqual(run_calls, [])

            section_row.widget.hide()
            dialog.open_field_filter('zone')
            zone_row = dialog.filter_rows[1]
            zone_row.widget.hide()
            wait_value_tasks()
            self.assertEqual(fill_calls, ['section', 'zone'])

            fill_calls.clear()
            run_calls.clear()
            zone_row.value.set_selected_values(['Z1'])
            dialog.refresh_dependent_values()
            self.wait_for_results(dialog)
            wait_value_tasks()
            # Closed 'section' and 'zone' popups did not run fill_values on cascade.
            self.assertEqual(fill_calls, [])
            self.assertEqual(len(run_calls), 1)
            self.assertIn(id(section_row), dialog._stale_value_rows)

            dialog.show_filter_popup(section_row)
            section_row.widget.hide()
            wait_value_tasks()
            self.assertEqual(fill_calls, ['section'])
            self.assertNotIn(id(section_row), dialog._stale_value_rows)
