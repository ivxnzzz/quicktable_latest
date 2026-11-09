"""Regression scenarios mixed into the shared QGIS application test case."""

from decimal import Decimal
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
