"""Disk-provider checks and opt-in tests against an isolated PostGIS schema."""

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


class ProviderChecks:
    def disk_layer(self, driver='GPKG'):
        from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer, QgsVectorFileWriter

        temporary = tempfile.TemporaryDirectory(prefix='quicktable-provider-')
        # OGR caches SQLite connections until exitQgis; clean files afterward.
        self.addClassCleanup(temporary.cleanup)
        extension = '.gpkg' if driver == 'GPKG' else '.shp'
        path = str(Path(temporary.name) / ('records' + extension))
        source = QgsVectorLayer('Point?crs=EPSG:3857&field=code:string&field=value:integer', 'source', 'memory')
        for number, text in enumerate(('alpha', 'beta')):
            feature = QgsFeature(source.fields())
            feature.setAttributes([text, number])
            feature.setGeometry(QgsGeometry.fromWkt('POINT ({} 0)'.format(number)))
            source.dataProvider().addFeatures([feature])
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = driver
        options.layerName = 'records'
        result = QgsVectorFileWriter.writeAsVectorFormatV3(source, path, QgsProject.instance().transformContext(), options)
        self.assertEqual(result[0], QgsVectorFileWriter.WriterError.NoError, str(result))
        uri = path + '|layername=records' if driver == 'GPKG' else path
        layer = QgsVectorLayer(uri, 'disk provider', 'ogr')
        self.assertTrue(layer.isValid())
        return layer, uri

    def test_geopackage_edit_null_empty_save_reopen_and_discard(self):
        from qgis.core import NULL, QgsVectorLayer
        from qgis.PyQt.QtWidgets import QMessageBox

        layer, uri = self.disk_layer()
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        index = layer.fields().indexFromName('code')
        fid = dialog.row_fid(0)
        dialog.table.item(0, index).setText('   ')
        dialog.save_edits()
        reopened = QgsVectorLayer(uri, 'verify', 'ogr')
        self.assertEqual(reopened.getFeature(fid)['code'], '   ')
        del reopened
        self.wait_for_results(dialog)
        dialog.set_cell_null(0, index)
        dialog.save_edits()
        reopened = QgsVectorLayer(uri, 'verify', 'ogr')
        self.assertEqual(reopened.getFeature(fid)['code'], NULL)
        del reopened
        self.wait_for_results(dialog)
        dialog.set_cell_null(0, index, False)
        dialog.save_edits()
        reopened = QgsVectorLayer(uri, 'verify', 'ogr')
        self.assertEqual(reopened.getFeature(fid)['code'], '')
        del reopened
        self.wait_for_results(dialog)
        dialog.table.item(0, index).setText('discard me')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.discard_edits()
        self.assertEqual(layer.getFeature(fid)['code'], '')

    def test_geopackage_schema_and_feature_deletion_undo_commit(self):
        from qgis.core import QgsVectorLayer
        from qgis.PyQt.QtWidgets import QDialog

        layer, uri = self.disk_layer()
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        def accept_field(options):
            options.name.setText('new_field')
            return QDialog.DialogCode.Accepted
        with patch.object(self.plugin.AddFieldDialog, 'exec', accept_field):
            dialog.add_field()
        self.assertGreaterEqual(layer.fields().indexFromName('new_field'), 0)
        dialog.save_edits()
        self.wait_for_results(dialog)
        reopened = QgsVectorLayer(uri, 'verify', 'ogr')
        self.assertGreaterEqual(reopened.fields().indexFromName('new_field'), 0)
        del reopened
        with patch.object(self.plugin.DeleteFieldsDialog, 'exec', return_value=QDialog.DialogCode.Accepted), \
             patch.object(self.plugin.DeleteFieldsDialog, 'selected_names', return_value=['new_field']), \
             patch.object(self.plugin.QMessageBox, 'question', return_value=self.plugin.QMessageBox.StandardButton.Yes):
            dialog.delete_field()
        dialog.save_edits()
        self.wait_for_results(dialog)
        reopened = QgsVectorLayer(uri, 'verify', 'ogr')
        self.assertEqual(reopened.fields().indexFromName('new_field'), -1)
        del reopened
        dialog.table.selectRow(0)
        fid = dialog.selected_fids()[0]
        def confirm(question):
            for button in question.buttons():
                if question.buttonRole(button) == self.plugin.QMessageBox.ButtonRole.DestructiveRole:
                    button.click()
                    break
            return 0
        with patch.object(self.plugin.QMessageBox, 'exec', confirm):
            dialog.delete_selected()
        self.assertFalse(layer.getFeature(fid).isValid())
        dialog.change_undo_stack(False)
        self.assertTrue(layer.getFeature(fid).isValid())
        dialog.soft_refresh()
        self.wait_for_results(dialog)
        row = next(row for row in range(dialog.table.rowCount()) if dialog.row_fid(row) == fid)
        dialog.table.selectRow(row)
        with patch.object(self.plugin.QMessageBox, 'exec', confirm):
            dialog.delete_selected()
        dialog.save_edits()
        self.wait_for_results(dialog)
        reopened = QgsVectorLayer(uri, 'verify', 'ogr')
        self.assertEqual(reopened.featureCount(), 1)
        self.assertFalse(reopened.getFeature(fid).isValid())
        del reopened

    def test_shapefile_edit_commit_and_reopen(self):
        from qgis.core import QgsVectorLayer

        layer, uri = self.disk_layer('ESRI Shapefile')
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        index = layer.fields().indexFromName('code')
        fid = dialog.row_fid(0)
        dialog.table.item(0, index).setText('updated')
        dialog.save_edits()
        reopened = QgsVectorLayer(uri, 'verify', 'ogr')
        self.assertEqual(reopened.getFeature(fid)['code'], 'updated')
        del reopened

    @unittest.skipUnless(os.environ.get('QUICKTABLE_TEST_POSTGIS_URI'), 'PostGIS test connection not configured')
    def test_real_postgis_schema_edits_constraints_and_reopen(self):
        from qgis.core import QgsDataSourceUri, QgsProviderRegistry, QgsVectorLayer
        from qgis.PyQt.QtWidgets import QDialog

        connection_uri = os.environ['QUICKTABLE_TEST_POSTGIS_URI']
        connection = QgsProviderRegistry.instance().providerMetadata('postgres').createConnection(connection_uri, {})
        schema = 'quicktable_test_' + uuid.uuid4().hex
        connection.executeSql('CREATE SCHEMA "{}"'.format(schema))
        self.addCleanup(connection.executeSql, 'DROP SCHEMA "{}" CASCADE'.format(schema))
        connection.executeSql('CREATE TABLE "{}".records (id serial PRIMARY KEY, code text NOT NULL UNIQUE, value integer CHECK (value >= 0))'.format(schema))
        connection.executeSql("INSERT INTO \"{}\".records (code, value) VALUES ('alpha', 1), ('beta', 2)".format(schema))
        uri = QgsDataSourceUri(connection_uri)
        uri.setDataSource(schema, 'records', '', '', 'id')
        layer = QgsVectorLayer(uri.uri(False), 'isolated PostGIS test', 'postgres')
        self.assertTrue(layer.isValid(), 'Could not open the isolated PostGIS table')
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        index = layer.fields().indexFromName('code')
        fid = dialog.row_fid(0)
        dialog.table.item(0, index).setText('updated')
        dialog.save_edits()
        self.wait_for_results(dialog)
        reopened = QgsVectorLayer(uri.uri(False), 'verify', 'postgres')
        self.assertEqual(reopened.getFeature(fid)['code'], 'updated')
        del reopened
        def accept_field(options):
            options.name.setText('added_field')
            return QDialog.DialogCode.Accepted
        with patch.object(self.plugin.AddFieldDialog, 'exec', accept_field):
            dialog.add_field()
        dialog.save_edits()
        self.wait_for_results(dialog)
        reopened = QgsVectorLayer(uri.uri(False), 'verify', 'postgres')
        self.assertGreaterEqual(reopened.fields().indexFromName('added_field'), 0)
        del reopened
        number_index = layer.fields().indexFromName('value')
        dialog.table.item(0, number_index).setText('-1')
        dialog.save_edits()
        self.assertTrue(layer.isModified())
        self.assertIn('Could not save', dialog.status.text())
        self.assertTrue(layer.rollBack())
