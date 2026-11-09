"""Load the built ZIP from an isolated directory, not the source checkout."""

import configparser
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import zipfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
root = Path(__file__).resolve().parents[1]
metadata = configparser.ConfigParser()
metadata.read(root / 'metadata.txt', encoding='utf-8')
archive_path = root / 'dist' / ('quicktable_latest-' + metadata['general']['version'] + '.zip')


def main():
    from qgis.core import QgsApplication, QgsFeature, QgsProject, QgsVectorLayer
    from qgis.PyQt.QtCore import QSettings
    from qgis.PyQt.QtWidgets import QMainWindow

    with tempfile.TemporaryDirectory(prefix='quicktable-package-') as directory:
        destination = Path(directory)
        profile = destination / 'profile'
        os.environ['QGIS_CUSTOM_CONFIG_PATH'] = str(profile)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(profile))
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.namelist():
                if not (destination / member).resolve().is_relative_to(destination.resolve()):
                    raise ValueError('Archive member leaves the isolated directory')
            archive.extractall(destination)
        sys.path.insert(0, directory)
        module = importlib.import_module('quicktable_latest')
        if not Path(module.__file__).resolve().is_relative_to(destination.resolve()):
            raise RuntimeError('Smoke test imported the checkout instead of the package')
        app = QgsApplication([], False)
        app.initQgis()
        window = QMainWindow()
        layer = QgsVectorLayer('None?field=name:string', 'packaged smoke', 'memory')
        feature = QgsFeature(layer.fields())
        feature.setAttributes(['packaged'])
        layer.dataProvider().addFeatures([feature])
        QgsProject.instance().addMapLayer(layer)
        signal = SimpleNamespace(connect=lambda slot: None, disconnect=lambda slot: None)
        iface = SimpleNamespace(mainWindow=lambda: window, activeLayer=lambda: layer,
            currentLayerChanged=signal, addPluginToMenu=lambda *args: None,
            addToolBarIcon=lambda *args: None, removePluginMenu=lambda *args: None,
            removeToolBarIcon=lambda *args: None)
        plugin = module.classFactory(iface)
        try:
            plugin.initGui()
            plugin.show()
            deadline = time.monotonic() + 15
            while plugin.dlg.query_task is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            if plugin.dlg.table.rowCount() != 1 or plugin.dlg.table.item(0, 0).text() != 'packaged':
                raise RuntimeError('Packaged plugin did not load and render the test layer')
        finally:
            plugin.unload()
            QgsProject.instance().clear()
            app.processEvents()
            window.deleteLater()
            app.exitQgis()
        print('Packaged plugin passed: classFactory, initGui, query, render, unload.')


if __name__ == '__main__':
    main()
