"""Run using QGIS's Python environment; skipped under plain Python."""

import importlib
import os
import pathlib
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from qgis.core import (QgsApplication, QgsExpression, QgsFeature, QgsField, QgsGeometry,
                           QgsProject, QgsFeatureRequest, QgsVectorLayer, QgsVectorLayerFeatureSource)
    from qgis.PyQt.QtCore import Qt, QVariant, QSettings, QLocale, QPoint
    from qgis.PyQt.QtGui import QFont, QFontDatabase, QFontMetrics
    from qgis.PyQt.QtWidgets import QComboBox, QLineEdit, QAbstractItemView, QDialog
except ImportError:
    QgsApplication = None


@unittest.skipIf(QgsApplication is None, "Requires QGIS Python environment")
class QgisIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owns_app = QgsApplication.instance() is None
        if cls.owns_app:
            cls.app = QgsApplication([], False)
            cls.app.initQgis()
        root = pathlib.Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root.parent))
        cls.plugin = importlib.import_module(root.name + ".layer_filter")

    @classmethod
    def tearDownClass(cls):
        if cls.owns_app:
            cls.app.exitQgis()

    def combo(self, text):
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItem(self.plugin.ALL_VALUES)
        combo.setEditText(text)
        return combo

    def test_refresh_retains_partial_and_removed_values(self):
        for text in ("Al", "Deleted value", ""):
            with self.subTest(text=text):
                combo = self.combo(self.plugin.ALL_VALUES)
                self.plugin.FinderDialog.restore_value(combo, text)
                self.assertEqual(combo.currentText(), text)
                self.assertFalse(combo.signalsBlocked())

    def test_search_escapes_literal_backslashes_quotes_and_newlines(self):
        for text in (r"C:\new\tax", "O'Brien", "line\nbreak"):
            with self.subTest(text=text):
                field = QComboBox()
                field.addItem("name")
                value = self.combo(text)
                operator = QComboBox()
                operator.addItem("Contains")
                finder = SimpleNamespace(fields=["name"], filter_rows=[SimpleNamespace(field=field, operator=operator, upper=QLineEdit())],
                                         current_layer=lambda: None)
                expression = self.plugin.FinderDialog.part_expr(finder, field, value)
                query = QgsExpression(expression)
                self.assertFalse(query.hasParserError(), query.parserErrorString())
                self.assertIn(QgsExpression.quotedString(text), expression)

    def test_global_search_quotes_the_pattern(self):
        edit = QLineEdit()
        edit.setText(r"C:\new\O'Brien")
        finder = SimpleNamespace(fields=["name"], edit=edit, selected_scope_ids=None, filter_rows=[SimpleNamespace(field=None, value=None)],
                                 part_expr=lambda *args: None)
        expression = self.plugin.FinderDialog.build_expr(finder)
        self.assertFalse(QgsExpression(expression).hasParserError())
        self.assertIn(QgsExpression.quotedString("%" + edit.text() + "%"), expression)

    def test_integer_fields_keep_large_exact_values(self):
        field = QgsField("id", QVariant.LongLong, "numeric")
        self.assertEqual(self.plugin.FinderDialog.convert(field, "9007199254740993"), 9007199254740993)

    def test_double_field_rejects_precision_loss(self):
        field = QgsField("value", QVariant.Double, "numeric")
        with self.assertRaisesRegex(ValueError, "precision"):
            self.plugin.FinderDialog.convert(field, "9007199254740993")

    def make_layer(self, count):
        layer = QgsVectorLayer("None?field=name:string", "test", "memory")
        features = []
        for i in range(count):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([str(i)])
            features.append(feature)
        self.assertTrue(layer.dataProvider().addFeatures(features)[0])
        return layer

    def test_suggestions_are_bounded(self):
        layer = self.make_layer(self.plugin.MAX_VALUE_FEATURES + 10)
        values, truncated = self.plugin.collect_values(
            SimpleNamespace(isCanceled=lambda: False), QgsVectorLayerFeatureSource(layer), 0, None)
        self.assertEqual(len(values), self.plugin.MAX_VALUE_FEATURES)
        self.assertTrue(truncated)

    def test_canceled_suggestions_are_not_returned(self):
        layer = self.make_layer(2)
        result = self.plugin.collect_values(
            SimpleNamespace(isCanceled=lambda: True), QgsVectorLayerFeatureSource(layer), 0, None)
        self.assertIsNone(result)

    def test_dependent_suggestions_respect_first_filter(self):
        layer = self.make_layer(10)
        values, truncated = self.plugin.collect_values(
            SimpleNamespace(isCanceled=lambda: False), QgsVectorLayerFeatureSource(layer), 0, '"name" = \'3\'')
        self.assertEqual(values, {"3": "3"})
        self.assertFalse(truncated)

    def test_late_suggestions_cannot_overwrite_newer_query_or_typed_text(self):
        layer = self.make_layer(2)
        field = QComboBox()
        field.addItem("name")
        value = self.combo("Al")
        tasks = []

        def make_task(description, function, **kwargs):
            task = SimpleNamespace(canceled=False, callback=kwargs["on_finished"])
            task.cancel = lambda: setattr(task, "canceled", True)
            task.setDependentLayers = lambda layers: None
            tasks.append(task)
            return task

        dialog = SimpleNamespace(
            value_tasks={}, value_versions={}, closing=False, current_layer=lambda: layer,
            restore_value=self.plugin.FinderDialog.restore_value,
            natural_key=self.plugin.FinderDialog.natural_key,
            value1=None, update_second_filter=lambda: None, schedule_search=lambda: None)
        with patch.object(self.plugin, "QgsTask", SimpleNamespace(fromFunction=make_task)), \
             patch.object(self.plugin, "QgsApplication", SimpleNamespace(
                 taskManager=lambda: SimpleNamespace(addTask=lambda task: None))):
            self.plugin.FinderDialog.fill_values(dialog, field, value, None)
            self.plugin.FinderDialog.fill_values(dialog, field, value, None)
        value.setEditText("Al")
        self.assertTrue(tasks[0].canceled)
        tasks[0].callback(None, ({"stale": "stale"}, False))
        self.assertEqual(value.findText("stale"), -1)
        self.assertIs(dialog.value_tasks[value], tasks[1])
        tasks[1].callback(None, ({"Alpha": "Alpha"}, False))
        self.assertEqual(value.currentText(), "Al")
        self.assertGreater(value.findText("Alpha"), 0)
        self.assertFalse(value.signalsBlocked())

    def test_suggestions_are_ignored_after_shutdown(self):
        layer = self.make_layer(1)
        field = QComboBox()
        field.addItem("name")
        value = self.combo("Al")
        callbacks = []

        def make_task(description, function, **kwargs):
            callbacks.append(kwargs["on_finished"])
            return SimpleNamespace(setDependentLayers=lambda layers: None)

        dialog = SimpleNamespace(value_tasks={}, value_versions={}, closing=False,
                                 current_layer=lambda: layer)
        with patch.object(self.plugin, "QgsTask", SimpleNamespace(fromFunction=make_task)), \
             patch.object(self.plugin, "QgsApplication", SimpleNamespace(
                 taskManager=lambda: SimpleNamespace(addTask=lambda task: None))):
            self.plugin.FinderDialog.fill_values(dialog, field, value, None)
        dialog.closing = True
        callbacks[0](None, ({"late": "late"}, False))
        self.assertEqual(value.findText("late"), -1)

    def create_dialog(self, layer):
        QgsProject.instance().addMapLayer(layer)
        self.addCleanup(QgsProject.instance().removeMapLayer, layer.id())
        signal = SimpleNamespace(connect=lambda slot: None, disconnect=lambda slot: None)
        canvas = SimpleNamespace(zoomToSelected=lambda layer: None,
                                 flashFeatureIds=lambda layer, ids: None)
        iface = SimpleNamespace(currentLayerChanged=signal, activeLayer=lambda: layer,
                                mapCanvas=lambda: canvas)
        dialog = self.plugin.FinderDialog(iface)
        self.addCleanup(dialog.shutdown)
        dialog.refresh()
        self.wait_for_results(dialog)
        return dialog

    def wait_for_results(self, dialog):
        deadline = time.monotonic() + 10
        while dialog.query_task is not None and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.assertIsNotNone(dialog.result_ids, dialog.status.text())

    def test_sort_orders_all_results_before_paging(self):
        layer = QgsVectorLayer("None?field=number:integer", "sorting", "memory")
        for number in reversed(range(130)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([number])
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        dialog.open_field_filter("number")
        dialog.sort_filter_column(dialog.filter_rows[0], Qt.AscendingOrder)
        self.wait_for_results(dialog)
        self.assertEqual([int(dialog.table.item(i, 0).text()) for i in range(100)], list(range(100)))
        dialog.change_page(1)
        self.assertEqual([int(dialog.table.item(i, 0).text()) for i in range(30)], list(range(100, 130)))
        self.assertTrue(dialog.table.verticalHeader().isVisibleTo(dialog.table))
        self.assertEqual(dialog.table.verticalHeaderItem(0).text(), "101")
        self.assertEqual(dialog.table.verticalHeaderItem(29).text(), "130")

    def test_header_sort_and_filter_have_separate_click_targets(self):
        from qgis.PyQt.QtCore import QPoint
        from qgis.PyQt.QtTest import QTest
        dialog = self.create_dialog(self.make_layer(3))
        dialog.show()
        QgsApplication.processEvents()
        header = dialog.table.horizontalHeader()
        x = header.sectionViewportPosition(0) + min(40, header.sectionSize(0) // 2)
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(x, header.height() // 4))
        self.wait_for_results(dialog)
        self.assertEqual(dialog.sort_field, "name")
        self.assertEqual(dialog.sort_order, Qt.AscendingOrder)
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(x, header.height() // 4))
        self.wait_for_results(dialog)
        self.assertEqual(dialog.sort_order, Qt.DescendingOrder)
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(x, 3 * header.height() // 4))
        self.assertEqual(len(dialog.filter_rows), 1)
        row = dialog.filter_rows[0]
        self.assertTrue(row.widget.isVisible())
        row.value.set_selected_values(["1"])
        dialog.update_filter_rows_layout()
        self.assertIn("1", header.filter_labels[0])
        row.widget.hide()

    def test_toolbar_can_be_collapsed_and_preference_is_remembered(self):
        settings = QSettings()
        key = "LayerFilter/toolbarVisible"
        old = settings.value(key, "true")
        self.addCleanup(settings.setValue, key, old)
        settings.setValue(key, True)
        dialog = self.create_dialog(self.make_layer(2))
        dialog.show()
        QgsApplication.processEvents()
        self.assertEqual(dialog.windowTitle(), "QuickTable")
        self.assertTrue(dialog.selection_tools.isVisible())
        dialog.btn_toolbar.click()
        self.assertFalse(dialog.selection_tools.isVisible())
        self.assertFalse(dialog.edit_tools.isVisible())
        self.assertTrue(dialog.layer.isVisible())
        self.assertTrue(dialog.edit.isVisible())
        self.assertTrue(dialog.btn_settings.isVisible())
        reopened = self.plugin.FinderDialog(dialog.iface)
        self.addCleanup(reopened.shutdown)
        self.assertFalse(reopened.btn_toolbar.isChecked())
        reopened.btn_toolbar.click()
        self.assertTrue(reopened.btn_toolbar.isChecked())

    def test_filter_row_is_visibly_painted_in_both_themes(self):
        dialog = self.create_dialog(self.make_layer(3))
        dialog.show()
        header = dialog.table.horizontalHeader()
        for theme in ("light", "dark"):
            dialog.theme = theme
            dialog.apply_theme()
            QgsApplication.processEvents()
            image = header.viewport().grab().toImage()
            width = min(header.sectionSize(0), image.width())
            pixels = [image.pixelColor(x, y) for x in range(8, max(9, width - 20))
                      for y in range(header.height() // 2 + 5, header.height() - 5)]
            if theme == "light":
                visible_text = sum(1 for c in pixels if max(c.red(), c.green(), c.blue()) < 180)
            else:
                visible_text = sum(1 for c in pixels if min(c.red(), c.green(), c.blue()) > 110)
            self.assertGreater(visible_text, 5, "Filter control text is not painted in " + theme)

    def test_selection_scope_tracks_live_qgis_selection(self):
        layer = self.make_layer(4)
        dialog = self.create_dialog(layer)
        ids = [feature.id() for feature in layer.getFeatures()]
        layer.selectByIds(ids[:2])
        dialog.selected_only_cb.setChecked(True)
        self.wait_for_results(dialog)
        self.assertEqual(set(dialog.result_ids), set(ids[:2]))
        layer.selectByIds(ids[2:])
        deadline = time.monotonic() + 10
        while (dialog.selection_filter_timer.isActive() or dialog.query_task is not None) and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.wait_for_results(dialog)
        self.assertEqual(set(dialog.result_ids), set(ids[2:]))
        layer.removeSelection()
        dialog.selection_filter_timer.stop()
        dialog.run_search()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.result_ids, ())
        dialog.selected_only_cb.setChecked(False)
        self.wait_for_results(dialog)
        self.assertEqual(len(dialog.result_ids), 4)

    def test_clear_filters_resets_scopes_but_keeps_map_selection(self):
        layer = self.make_layer(4)
        dialog = self.create_dialog(layer)
        ids = dialog.all_fids()
        layer.selectByIds([ids[1]])
        dialog.open_field_filter("name")
        row = dialog.filter_rows[0]
        row.widget.hide()
        row.value.set_selected_values(["1"])
        dialog.edit.setText("1")
        dialog.selected_only_cb.setChecked(True)
        self.wait_for_results(dialog)
        dialog.btn_clear_filters.click()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.edit.text(), "")
        self.assertEqual(dialog.filter_rows, [])
        self.assertFalse(dialog.selected_only_cb.isChecked())
        self.assertIsNone(dialog.selected_scope_ids)
        self.assertIsNone(dialog.nearby_scope_ids)
        self.assertEqual(len(dialog.result_ids), 4)
        self.assertEqual(set(layer.selectedFeatureIds()), {ids[1]})

    def test_nearby_touching_and_distance_search(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:3857&field=name:string", "parcels", "memory")
        for name, x in (("origin", 0), ("touching", 1), ("near", 2.5), ("far", 10)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([name])
            feature.setGeometry(QgsGeometry.fromWkt(
                "POLYGON (({0} 0, {1} 0, {1} 1, {0} 1, {0} 0))".format(x, x + 1)))
            layer.dataProvider().addFeatures([feature])
        features = {feature["name"]: feature.id() for feature in layer.getFeatures()}
        source = QgsVectorLayerFeatureSource(layer)
        task = SimpleNamespace(isCanceled=lambda: False)
        touching = self.plugin.collect_nearby(task, source, [features["origin"]], None)
        self.assertEqual(set(touching), {features["touching"]})
        nearby = self.plugin.collect_nearby(task, source, [features["origin"]], 1.5)
        self.assertEqual(set(nearby), {features["touching"], features["near"]})
        self.assertIsNone(self.plugin.collect_nearby(SimpleNamespace(isCanceled=lambda: True), source, [features["origin"]], 1))

    def test_nearby_results_and_clear_in_dialog(self):
        layer = QgsVectorLayer("Point?crs=EPSG:3857&field=name:string", "points", "memory")
        for name, x in (("origin", 0), ("near", 2), ("far", 20)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([name])
            feature.setGeometry(QgsGeometry.fromWkt("POINT ({} 0)".format(x)))
            layer.dataProvider().addFeatures([feature])
        ids = {feature["name"]: feature.id() for feature in layer.getFeatures()}
        dialog = self.create_dialog(layer)
        layer.selectByIds([ids["origin"]])
        dialog.find_nearby(3, "metres")
        deadline = time.monotonic() + 10
        while dialog.nearby_task is not None and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.wait_for_results(dialog)
        self.assertEqual(set(dialog.result_ids), {ids["near"]})
        self.assertEqual(set(layer.selectedFeatureIds()), {ids["origin"]})
        dialog.clear_nearby()
        self.wait_for_results(dialog)
        self.assertEqual(len(dialog.result_ids), 3)

    def test_nearby_without_matches_keeps_empty_result(self):
        layer = QgsVectorLayer("Point?crs=EPSG:3857&field=name:string", "points", "memory")
        feature = QgsFeature(layer.fields())
        feature.setAttributes(["only"])
        feature.setGeometry(QgsGeometry.fromWkt("POINT (0 0)"))
        layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        layer.selectByIds([next(layer.getFeatures()).id()])
        dialog.find_nearby(1, "metres")
        deadline = time.monotonic() + 10
        while dialog.nearby_task is not None and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.wait_for_results(dialog)
        self.assertEqual(dialog.result_ids, ())
        self.assertEqual(dialog.table.columnCount(), 1)
        self.assertNotIn("canceled", dialog.status.text().lower())

    def test_empty_multi_filter_keeps_headers_and_can_be_adjusted(self):
        layer = QgsVectorLayer("None?field=area:string&field=category:string", "filters", "memory")
        for values in (("A", "Residential"), ("B", "Commercial")):
            feature = QgsFeature(layer.fields())
            feature.setAttributes(list(values))
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        for first, second in (("area", "category"), ("category", "area")):
            with self.subTest(first=first):
                dialog.clear_filters()
                self.wait_for_results(dialog)
                for field, value in ((first, "A" if first == "area" else "Commercial"),
                                     (second, "A" if second == "area" else "Commercial")):
                    dialog.open_field_filter(field)
                    row = next(r for r in dialog.filter_rows if r.field.currentText() == field)
                    row.widget.hide()
                    row.value.set_selected_values([value])
                dialog.refresh_dependent_values()
                self.wait_for_results(dialog)
                self.assertEqual(dialog.result_ids, ())
                self.assertEqual(dialog.table.columnCount(), 2)
                self.assertIn("No matching records", dialog.status.text())
                self.assertNotIn("canceled", dialog.status.text().lower())
                dialog.remove_filter_row(next(r for r in dialog.filter_rows if r.field.currentText() == "category"))
                self.wait_for_results(dialog)
                self.assertEqual(len(dialog.result_ids), 1)

    def test_filter_suggestions_follow_all_other_fields_and_remove_stale_choices(self):
        layer = QgsVectorLayer("None?field=barangay:string&field=section:integer", "suggestions", "memory")
        for values in (("A", 1), ("A", 2), ("B", 4)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes(list(values))
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.open_field_filter("section")
        section = dialog.filter_rows[0]
        section.widget.hide()
        dialog.open_field_filter("barangay")
        barangay = dialog.filter_rows[1]
        barangay.widget.hide()
        barangay.value.set_selected_values(["A"])
        dialog.refresh_dependent_values()
        deadline = time.monotonic() + 10
        while dialog.value_tasks and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.assertFalse(dialog.value_tasks)
        section.choices.refresh_choices()
        self.assertIn("1", section.choices.items)
        self.assertIn("2", section.choices.items)
        self.assertNotIn("4", section.choices.items)
        barangay.value.set_selected_values(["B"])
        dialog.refresh_dependent_values()
        deadline = time.monotonic() + 10
        while dialog.value_tasks and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.assertFalse(dialog.value_tasks)
        section.choices.refresh_choices()
        self.assertIn("4", section.choices.items)
        self.assertNotIn("1", section.choices.items)
        self.assertNotIn("2", section.choices.items)

    def test_edit_undo_redo_and_highlighting(self):
        layer = self.make_layer(1)
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        fid = dialog.row_fid(0)
        dialog.table.item(0, 0).setText("changed")
        self.assertEqual(layer.getFeature(fid)[0], "changed")
        self.assertEqual(dialog.table.item(0, 0).toolTip(), "Unsaved attribute change")
        self.assertTrue(dialog.btn_undo.isEnabled())
        dialog.change_undo_stack(False)
        self.assertEqual(layer.getFeature(fid)[0], "0")
        dialog.change_undo_stack(True)
        self.assertEqual(layer.getFeature(fid)[0], "changed")

    def test_statistics_cover_supplied_features(self):
        layer = QgsVectorLayer("None?field=number:integer", "statistics", "memory")
        for number in (1, 3, None):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([number])
            layer.dataProvider().addFeatures([feature])
        ids = [feature.id() for feature in layer.getFeatures()]
        result = self.plugin.collect_column_statistics(SimpleNamespace(isCanceled=lambda: False),
                                                       QgsVectorLayerFeatureSource(layer), [(0, True)], ids)
        self.assertEqual(result["summaries"][0][:6], [2, 1, 4.0, 1.0, 3.0, True])
        self.assertEqual(result["summaries"][0][6]["distinct"], 2)
        self.assertEqual(sum(result["summaries"][0][6]["histogram"]), 2)

    def test_statistics_distinct_and_category_distribution(self):
        layer = QgsVectorLayer("None?field=area:string&field=amount:double", "stats", "memory")
        for area, amount in (("A", 1.0), ("A", 2.0), ("B", 3.0), ("C", None), (None, 4.0)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([area, amount])
            layer.dataProvider().addFeatures([feature])
        ids = [feature.id() for feature in layer.getFeatures()]
        result = self.plugin.collect_column_statistics(SimpleNamespace(isCanceled=lambda: False),
                                                       QgsVectorLayerFeatureSource(layer), [(0, False), (1, True)], ids)
        text = result["summaries"][0]
        self.assertEqual(text[:2], [4, 1])
        self.assertEqual(text[6]["distinct"], 3)
        self.assertEqual(text[6]["top"], [("A", 2), ("B", 1)])
        numeric = result["summaries"][1]
        self.assertEqual(numeric[6]["distinct"], 4)
        self.assertEqual(sum(numeric[6]["histogram"]), 4)
        self.assertEqual(numeric[6]["histogram"][0], 1)
        self.assertEqual(numeric[6]["histogram"][-1], 1)

    def test_statistics_large_distinct_count_is_bounded_and_marked(self):
        layer = self.make_layer(4)
        ids = [feature.id() for feature in layer.getFeatures()]
        with patch.object(self.plugin, "MAX_STAT_DISTINCT", 2):
            result = self.plugin.collect_column_statistics(SimpleNamespace(isCanceled=lambda: False),
                                                           QgsVectorLayerFeatureSource(layer), [(0, False)], ids)
        info = result["summaries"][0][6]
        self.assertTrue(info["capped"])
        self.assertEqual(info["distinct"], 3)
        self.assertEqual(info["top"], [])

    def wait_for_statistics(self, dialog):
        deadline = time.monotonic() + 15
        while (dialog.statistics_task is not None or dialog.statistics_refresh_timer.isActive()) and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.assertIsNone(dialog.statistics_task, "Statistics task did not finish")
        self.assertEqual(dialog.statistics_strip.state, "ready", dialog.statistics_strip.message)

    def test_statistics_strip_uses_all_filtered_results_and_not_just_page(self):
        self.remember_page_size_preference()
        settings = QSettings()
        old = settings.value("LayerFilter/statisticsVisible", "false")
        self.addCleanup(settings.setValue, "LayerFilter/statisticsVisible", old)
        settings.setValue("LayerFilter/statisticsVisible", False)
        layer = QgsVectorLayer("None?field=number:integer&field=name:string", "stats", "memory")
        for i in range(105):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([i if i != 2 else None, "group" if i < 102 else None])
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        self.assertFalse(dialog.btn_statistics.isChecked())
        dialog.btn_statistics.setChecked(True)
        self.wait_for_statistics(dialog)
        number = dialog.statistics_strip.summaries[0]
        self.assertEqual(number[:2], [104, 1])
        self.assertEqual(number[2], sum(range(105)) - 2)
        self.assertEqual(dialog.statistics_strip.summaries[1][:2], [102, 3])
        key, version = dialog.statistics_key, dialog.statistics_version
        dialog.change_page(1)
        QgsApplication.processEvents()
        self.assertEqual(dialog.statistics_key, key)
        self.assertEqual(dialog.statistics_version, version)
        dialog.edit.setText("group")
        dialog.run_search()
        self.wait_for_results(dialog)
        self.wait_for_statistics(dialog)
        self.assertEqual(dialog.statistics_strip.summaries[0][:2], [101, 1])
        self.assertEqual(dialog.statistics_strip.summaries[1][:2], [102, 0])
        dialog.edit.setText("not-a-match")
        dialog.run_search()
        self.wait_for_results(dialog)
        self.wait_for_statistics(dialog)
        self.assertEqual(dialog.statistics_strip.summaries[0][:2], [0, 0])
        self.assertIn("Sum: —", dialog.statistics_strip.lines_for(0))

    def test_statistics_strip_alignment_visibility_and_preferences(self):
        settings = QSettings()
        old = settings.value("LayerFilter/statisticsVisible", "false")
        self.addCleanup(settings.setValue, "LayerFilter/statisticsVisible", old)
        settings.setValue("LayerFilter/statisticsVisible", False)
        layer = QgsVectorLayer("None?field=a:string&field=b:integer&field=c:string", "layout", "memory")
        feature = QgsFeature(layer.fields())
        feature.setAttributes(["a", 5, "c"])
        layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.show()
        dialog.btn_statistics.setChecked(True)
        self.wait_for_statistics(dialog)
        self.assertTrue(dialog.statistics_strip.isVisible())
        header = dialog.table.horizontalHeader()
        self.assertEqual(dialog.statistics_strip.viewport_offset(),
                         dialog.statistics_strip.mapFromGlobal(dialog.table.viewport().mapToGlobal(QPoint(0, 0))).x())
        header.setStretchLastSection(False)
        for column in range(3):
            dialog.table.setColumnWidth(column, 500)
        dialog.table.horizontalScrollBar().setValue(100)
        QgsApplication.processEvents()
        self.assertEqual(header.sectionViewportPosition(0), -dialog.table.horizontalScrollBar().value())
        dialog.table.setColumnHidden(1, True)
        dialog.refresh_statistics()
        self.wait_for_statistics(dialog)
        self.assertNotIn(1, dialog.statistics_strip.summaries)
        self.assertIn(2, dialog.statistics_strip.summaries)
        dialog.btn_toolbar.setChecked(False)
        self.assertTrue(dialog.btn_statistics.isVisible())
        for theme in ("light", "dark"):
            dialog.theme = theme
            dialog.apply_theme()
            QgsApplication.processEvents()
            self.assertFalse(dialog.statistics_strip.grab().isNull())
        reopened = self.plugin.FinderDialog(dialog.iface)
        self.addCleanup(reopened.shutdown)
        self.assertTrue(reopened.btn_statistics.isChecked())
        dialog.btn_statistics.setChecked(False)
        self.assertFalse(dialog.statistics_strip.isVisible())

    def test_statistics_ignore_obsolete_background_completion(self):
        settings = QSettings()
        old = settings.value("LayerFilter/statisticsVisible", "false")
        self.addCleanup(settings.setValue, "LayerFilter/statisticsVisible", old)
        settings.setValue("LayerFilter/statisticsVisible", False)
        dialog = self.create_dialog(self.make_layer(2))
        tasks = []
        def make_task(description, function, **kwargs):
            task = SimpleNamespace(callback=kwargs["on_finished"], canceled=False)
            task.cancel = lambda: setattr(task, "canceled", True)
            task.setDependentLayers = lambda layers: None
            tasks.append(task)
            return task
        with patch.object(self.plugin, "QgsTask", SimpleNamespace(fromFunction=make_task)), \
             patch.object(self.plugin, "QgsApplication", SimpleNamespace(taskManager=lambda: SimpleNamespace(addTask=lambda task: None))):
            dialog.btn_statistics.setChecked(True)
            dialog.cancel_statistics()
            dialog.refresh_statistics()
            self.assertTrue(tasks[0].canceled)
            tasks[0].callback(None, {"summaries": {0: [99, 0, 0, None, None, False]}})
            self.assertEqual(dialog.statistics_strip.state, "loading")
            tasks[1].callback(None, {"summaries": {0: [2, 0, 0, None, None, False]}})
        self.assertEqual(dialog.statistics_strip.summaries[0][0], 2)

    def test_statistics_update_after_edit_and_selected_only(self):
        settings = QSettings()
        old = settings.value("LayerFilter/statisticsVisible", "false")
        self.addCleanup(settings.setValue, "LayerFilter/statisticsVisible", old)
        settings.setValue("LayerFilter/statisticsVisible", False)
        layer = QgsVectorLayer("None?field=number:integer", "editing stats", "memory")
        for value in (1, 2, 3):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([value])
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.btn_statistics.setChecked(True)
        self.wait_for_statistics(dialog)
        self.assertEqual(dialog.statistics_strip.summaries[0][2], 6.0)
        dialog.edit_cb.setChecked(True)
        dialog.table.item(0, 0).setText("10")
        deadline = time.monotonic() + 15
        while (dialog.timer.isActive() or dialog.query_task is not None or dialog.statistics_task is not None
               or dialog.statistics_refresh_timer.isActive()) and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.wait_for_results(dialog)
        self.wait_for_statistics(dialog)
        self.assertEqual(dialog.statistics_strip.summaries[0][2], 15.0)
        ids = dialog.all_fids()
        layer.selectByIds(ids[:2])
        dialog.selected_only_cb.setChecked(True)
        self.wait_for_results(dialog)
        self.wait_for_statistics(dialog)
        self.assertEqual(dialog.statistics_strip.summaries[0][0], 2)
        self.assertEqual(dialog.statistics_strip.summaries[0][2], 12.0)

    def test_saved_filter_restores_checked_values(self):
        dialog = self.create_dialog(self.make_layer(4))
        dialog.open_field_filter("name")
        row = dialog.filter_rows[0]
        row.widget.hide()
        row.value.set_selected_values(["1", "2"])
        dialog.refresh_dependent_values()
        self.wait_for_results(dialog)
        with patch.object(self.plugin.QInputDialog, "getText", return_value=("Example", True)):
            dialog.save_current_filter()
        dialog.clear_filters()
        self.wait_for_results(dialog)
        dialog.load_saved_filter("Example")
        self.wait_for_results(dialog)
        self.assertEqual(dialog.filter_rows[0].value.selected_values, ["1", "2"])
        self.assertEqual(len(dialog.result_ids), 2)

    def test_bulk_edit_changes_selected_features_as_one_undo(self):
        layer = self.make_layer(3)
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        dialog.table.selectRow(0)
        selected = dialog.selected_fids()
        def apply_dialog(editor):
            editor.field.setCurrentText("name")
            editor.input.setText("updated")
            self.assertIn("0 → updated", editor.preview.toPlainText())
            self.assertTrue(editor.apply_button.isEnabled())
            return self.plugin.QDialog.Accepted
        with patch.object(self.plugin.BulkEditDialog, "exec_", apply_dialog):
            dialog.bulk_edit()
        self.assertEqual(layer.getFeature(selected[0])["name"], "updated")
        self.assertEqual(layer.undoStack().count(), 1)
        layer.undoStack().undo()
        self.assertEqual(layer.getFeature(selected[0])["name"], "0")

    def test_bulk_edit_dialog_validates_and_cancel_changes_nothing(self):
        layer = self.make_layer(3)
        self.assertTrue(layer.dataProvider().addAttributes([QgsField("value", QVariant.Int)]))
        layer.updateFields()
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        dialog.table.selectRow(0)
        fid = dialog.selected_fids()[0]
        editor = self.plugin.BulkEditDialog(dialog, layer, ["value", "name"], [fid])
        editor.input.setText("not a number")
        self.assertFalse(editor.apply_button.isEnabled())
        self.assertIn("Invalid value", editor.hint.text())
        editor.field.setCurrentText("name")
        self.assertTrue(editor.apply_button.isEnabled())
        editor.input.clear()
        self.assertIn("NULL", editor.preview.toPlainText())
        editor.reject()
        self.assertEqual(layer.getFeature(fid)["name"], "0")

    def test_autofill_patterns_validate_generated_values(self):
        field = QgsField("number", QVariant.Int)
        make = self.plugin.FinderDialog.autofill_values
        self.assertEqual(make(field, "sequence", "10", "-2", 4), [10, 8, 6, 4])
        self.assertEqual(make(field, "repeat", "1\n4", "1", 5), [1, 4, 1, 4, 1])
        self.assertEqual(make(field, "same", "7", "1", 3), [7, 7, 7])
        with self.assertRaises(ValueError):
            make(field, "sequence", "1", "0.5", 3)
        with self.assertRaises(ValueError):
            make(field, "sequence", str(2**31 - 1), "1", 2)

    def test_autofill_input_theme_and_pattern_placeholders(self):
        parent = self.create_dialog(self.make_layer(1))
        parent.show()
        for theme in ("light", "dark"):
            parent.theme = theme
            parent.apply_theme()
            dialog = self.plugin.AutofillDialog(parent, ["name"], 0, 1)
            dialog.show()
            QgsApplication.processEvents()
            self.assertIn("Residential", dialog.values.placeholderText())
            image = dialog.values.viewport().grab().toImage()
            background = image.pixelColor(image.width() - 8, image.height() - 8)
            if theme == "dark":
                self.assertLess(max(background.red(), background.green(), background.blue()), 100)
            else:
                self.assertGreater(min(background.red(), background.green(), background.blue()), 180)
            dialog.mode.setCurrentIndex(dialog.mode.findData("sequence"))
            self.assertIn("1", dialog.values.placeholderText())
            dialog.mode.setCurrentIndex(dialog.mode.findData("repeat"))
            self.assertIn("\n", dialog.values.placeholderText())
            dialog.close()
            dialog.deleteLater()

    def test_number_display_format_preserves_stored_values(self):
        layer = QgsVectorLayer("None?field=value:double", "numbers", "memory")
        feature = QgsFeature(layer.fields())
        feature.setAttributes([1.25])
        layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        fid = dialog.row_fid(0)
        original = dialog.table.item(0, 0).text()
        dialog.set_number_format("value", "whole")
        delegate = dialog.table.itemDelegateForColumn(0)
        self.assertEqual(delegate.displayText(original, QLocale()), "1")
        self.assertEqual(dialog.table.item(0, 0).text(), original)
        self.assertEqual(layer.getFeature(fid)[0], 1.25)
        self.assertEqual(dialog.table_rows(), [["value"], [original]])
        dialog.set_number_format("value", "trim")
        self.assertEqual(delegate.displayText("1.0", QLocale()), "1")
        self.assertEqual(delegate.displayText("1.25", QLocale()), "1.25")
        dialog.run_search()
        self.assertEqual(dialog.number_formats()["value"], "trim")

    def test_autofill_sequence_preview_and_single_undo(self):
        layer = QgsVectorLayer("None?field=number:integer", "autofill", "memory")
        for value in (10, 20, 30):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([value])
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        dialog.select_all()
        ids = dialog.selected_fids()
        previews = []
        def accept_options(options):
            options.mode.setCurrentIndex(options.mode.findData("sequence"))
            options.values.setPlainText("3")
            options.step.setText("2")
            return QDialog.Accepted
        def confirm(parent, title, message, *args):
            previews.append(message)
            return self.plugin.QMessageBox.Yes
        with patch.object(self.plugin.AutofillDialog, "exec_", accept_options), \
             patch.object(self.plugin.QMessageBox, "question", confirm):
            dialog.autofill()
        self.assertEqual([layer.getFeature(fid)[0] for fid in ids], [3, 5, 7])
        self.assertIn("10 → 3", previews[0])
        self.assertEqual(layer.undoStack().count(), 1)
        layer.undoStack().undo()
        self.assertEqual([layer.getFeature(fid)[0] for fid in ids], [10, 20, 30])

    def test_autofill_column_scope_only_changes_current_page(self):
        self.remember_page_size_preference()
        layer = self.make_layer(105)
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        dialog.edit_cb.setChecked(True)
        self.assertTrue(dialog.btn_autofill.isEnabled())
        first_page = dialog.all_fids()
        all_ids = [feature.id() for feature in layer.getFeatures()]
        remaining = [fid for fid in all_ids if fid not in set(first_page)]
        previews = []
        def accept_options(options):
            self.assertEqual(options.scope.currentData(), "page")
            options.mode.setCurrentIndex(options.mode.findData("repeat"))
            options.values.setPlainText("A\nB")
            return QDialog.Accepted
        def confirm(parent, title, message, *args):
            previews.append(message)
            return self.plugin.QMessageBox.Yes
        with patch.object(self.plugin.AutofillDialog, "exec_", accept_options), \
             patch.object(self.plugin.QMessageBox, "question", confirm):
            dialog.autofill()
        self.assertEqual([layer.getFeature(fid)[0] for fid in first_page[:4]], ["A", "B", "A", "B"])
        self.assertTrue(all(layer.getFeature(fid)[0] not in ("A", "B") for fid in remaining))
        self.assertIn("100 rows (all rows on this page)", previews[0])
        layer.undoStack().undo()
        self.assertEqual(layer.getFeature(first_page[0])[0], "0")

    def test_add_field_creates_typed_column_as_one_undo(self):
        for expected_type in (QVariant.LongLong, QVariant.Double):
            with self.subTest(field_type=expected_type):
                layer = self.make_layer(3)
                dialog = self.create_dialog(layer)
                dialog.edit_cb.setChecked(True)
                def accept_options(options):
                    options.field_type.setCurrentIndex(options.field_type.findData(expected_type))
                    options.name.setText("new_number")
                    return QDialog.Accepted
                with patch.object(self.plugin.AddFieldDialog, "exec_", accept_options):
                    dialog.add_field()
                index = layer.fields().indexFromName("new_number")
                self.assertGreaterEqual(index, 0, dialog.status.text())
                self.assertEqual(layer.fields()[index].type(), expected_type)
                self.assertEqual(layer.undoStack().count(), 1)
                layer.undoStack().undo()
                self.assertEqual(layer.fields().indexFromName("new_number"), -1)

    def test_add_decimal_field_retains_length_and_precision(self):
        layer = self.make_layer(1)
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        def accept_options(options):
            options.name.setText("amount")
            options.field_type.setCurrentIndex(options.field_type.findData(QVariant.Double))
            options.length.setValue(12)
            options.precision.setValue(3)
            return QDialog.Accepted
        with patch.object(self.plugin.AddFieldDialog, "exec_", accept_options):
            dialog.add_field()
        index = layer.fields().indexFromName("amount")
        self.assertGreaterEqual(index, 0, dialog.status.text())
        self.assertEqual(layer.fields()[index].length(), 12)
        self.assertEqual(layer.fields()[index].precision(), 3)

    def test_fields_menu_matches_theme_and_actions_remain_available(self):
        dialog = self.create_dialog(self.make_layer(1))
        dialog.show()
        dialog.edit_cb.setChecked(True)
        self.assertTrue(dialog.btn_add_field.isEnabled())
        self.assertTrue(dialog.btn_delete_field.isEnabled())
        for theme in ("light", "dark"):
            dialog.theme = theme
            dialog.apply_theme()
            self.assertFalse(dialog.btn_fields.icon().isNull())
            self.assertFalse(dialog.btn_add_field.icon().isNull())
            self.assertFalse(dialog.btn_delete_field.icon().isNull())
            dialog.btn_fields.click()
            QgsApplication.processEvents()
            self.assertTrue(dialog.fields_menu.isVisible())
            image = dialog.fields_menu.grab().toImage()
            background = image.pixelColor(5, 5)
            if theme == "dark":
                self.assertLess(max(background.red(), background.green(), background.blue()), 100)
            else:
                self.assertGreater(min(background.red(), background.green(), background.blue()), 180)
            dialog.fields_menu.hide()

    def test_delete_field_confirmation_and_undo(self):
        layer = QgsVectorLayer("None?field=keep:string&field=remove:string", "fields", "memory")
        feature = QgsFeature(layer.fields())
        feature.setAttributes(["A", "original"])
        layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        with patch.object(self.plugin.QInputDialog, "getItem", return_value=("remove", True)), \
             patch.object(self.plugin.QMessageBox, "question", return_value=self.plugin.QMessageBox.Cancel):
            dialog.delete_field()
        self.assertGreaterEqual(layer.fields().indexFromName("remove"), 0)
        self.assertEqual(layer.undoStack().count(), 0)
        with patch.object(self.plugin.QInputDialog, "getItem", return_value=("remove", True)), \
             patch.object(self.plugin.QMessageBox, "question", return_value=self.plugin.QMessageBox.Yes):
            dialog.delete_field()
        self.assertEqual(layer.fields().indexFromName("remove"), -1, dialog.status.text())
        self.assertEqual(layer.undoStack().count(), 1)
        layer.undoStack().undo()
        self.assertGreaterEqual(layer.fields().indexFromName("remove"), 0)
        self.assertEqual(next(layer.getFeatures())["remove"], "original")

    def test_attribute_editing_across_geometry_types(self):
        for geometry in ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon", "None"):
            with self.subTest(geometry=geometry):
                layer = QgsVectorLayer(geometry + "?field=name:string", geometry, "memory")
                self.assertTrue(layer.isValid())
                feature = QgsFeature(layer.fields())
                feature.setAttributes(["before"])
                self.assertTrue(layer.dataProvider().addFeatures([feature])[0])
                dialog = self.create_dialog(layer)
                self.assertTrue(dialog.edit_cb.isEnabled())
                self.assertIn("Editable", dialog.edit_status.text())
                dialog.edit_cb.setChecked(True)
                self.assertTrue(layer.isEditable())
                self.assertIn("Editing", dialog.edit_status.text())
                fid = dialog.row_fid(0)
                dialog.table.item(0, 0).setText("after")
                self.assertEqual(layer.getFeature(fid)["name"], "after")
                dialog.save_edits()
                self.assertEqual(layer.getFeature(fid)["name"], "after")

    def test_readonly_indicator_disables_editing(self):
        layer = self.make_layer(1)
        self.assertTrue(layer.setReadOnly(True))
        dialog = self.create_dialog(layer)
        self.assertIn("Read-only", dialog.edit_status.text())
        self.assertFalse(dialog.edit_cb.isEnabled())
        self.assertFalse(dialog.btn_save.isEnabled())
        self.assertIn("disabled", dialog.edit_status.toolTip())

    def test_select_all_and_unselect_synchronize_table_and_map(self):
        layer = self.make_layer(3)
        dialog = self.create_dialog(layer)
        dialog.select_all()
        self.assertEqual(len(dialog.selected_rows()), 3)
        self.assertEqual(set(dialog.selected_fids()), set(layer.selectedFeatureIds()))
        self.assertEqual(dialog.selection_status.text(), "3 selected")
        dialog.run_search()
        self.assertEqual(len(dialog.selected_rows()), 3)
        dialog.unselect_all()
        self.assertEqual(dialog.selected_rows(), [])
        self.assertEqual(layer.selectedFeatureCount(), 0)
        self.assertEqual(dialog.selection_status.text(), "0 selected")

    def test_large_page_selection_and_external_selection_with_hidden_first_column(self):
        self.remember_page_size_preference()
        uri = "None?" + "&".join("field=field{}:string".format(i) for i in range(12))
        layer = QgsVectorLayer(uri, "large selection", "memory")
        features = []
        for row in range(1000):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([str(row)] * 12)
            features.append(feature)
        self.assertTrue(layer.dataProvider().addFeatures(features)[0])
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(1000))
        dialog.table.setColumnHidden(0, True)
        dialog.select_all()
        self.assertEqual(len(dialog.selected_rows()), 1000)
        self.assertEqual(set(dialog.selected_fids()), set(layer.selectedFeatureIds()))
        ids = dialog.all_fids()
        expected = ids[::2]
        layer.selectByIds(expected)
        self.assertEqual(dialog.selected_fids(), expected)
        self.assertEqual(dialog.selection_status.text(), "500 selected")
        dialog.run_search()
        self.assertEqual(dialog.selected_fids(), expected)

    def test_existing_and_external_qgis_selection_is_reflected_without_changing_map(self):
        layer = self.make_layer(3)
        ids = [feature.id() for feature in layer.getFeatures()]
        layer.selectByIds([ids[0], ids[2]])
        dialog = self.create_dialog(layer)
        self.assertEqual(set(dialog.selected_fids()), {ids[0], ids[2]})
        self.assertEqual(set(layer.selectedFeatureIds()), {ids[0], ids[2]})
        layer.selectByIds([ids[1]])
        self.assertEqual(set(dialog.selected_fids()), {ids[1]})
        self.assertEqual(dialog.selection_status.text(), "1 selected")
        layer.removeSelection()
        self.assertEqual(dialog.selected_fids(), [])

    def test_external_selection_outside_page_is_kept_and_shown_on_its_page(self):
        layer = self.make_layer(205)
        ids = [feature.id() for feature in layer.getFeatures()]
        layer.selectByIds([ids[150]])
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        self.assertEqual(dialog.selected_fids(), [])
        self.assertEqual(dialog.selection_status.text(), "1 selected (0 on page)")
        dialog.change_page(1)
        self.assertEqual(dialog.selected_fids(), [ids[150]])
        self.assertEqual(layer.selectedFeatureIds(), [ids[150]])

    def test_active_layer_changes_and_restore_follow_qgis(self):
        first = self.make_layer(2)
        second = self.make_layer(3)
        dialog = self.create_dialog(first)
        dialog.show()
        QgsApplication.processEvents()
        QgsProject.instance().addMapLayer(second)
        self.addCleanup(QgsProject.instance().removeMapLayer, second.id())
        dialog.rebuild_layer_list(first.id())
        current = [first]
        dialog.iface.activeLayer = lambda: current[0]
        dialog.open_field_filter("name")
        row = dialog.filter_rows[0]
        row.widget.hide()
        row.value.set_selected_values(["1"])
        dialog.refresh_dependent_values()
        self.wait_for_results(dialog)
        dialog.sync_active_layer()
        self.assertEqual(dialog.filter_rows[0].value.selected_values, ["1"])
        current[0] = second
        dialog.on_active_layer_changed(second)
        self.wait_for_results(dialog)
        self.assertEqual(dialog.current_layer().id(), second.id())
        self.assertEqual(len(dialog.result_ids), 3)
        dialog.showMinimized()
        QgsApplication.processEvents()
        current[0] = first
        dialog.on_active_layer_changed(first)
        self.assertEqual(dialog.current_layer().id(), second.id())
        dialog.showNormal()
        QgsApplication.processEvents()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.current_layer().id(), first.id())

    def test_unavailable_layer_is_hidden_and_valid_layer_remains_usable(self):
        valid = self.make_layer(2)
        invalid = QgsVectorLayer("D:/quicktable-missing-layer-test.gpkg|layername=missing", "unavailable", "ogr")
        self.assertFalse(invalid.isValid())
        QgsProject.instance().addMapLayer(invalid)
        self.addCleanup(QgsProject.instance().removeMapLayer, invalid.id())
        dialog = self.create_dialog(valid)
        dialog.show()
        QgsApplication.processEvents()
        self.assertEqual(dialog.layer.findData(invalid.id()), -1)
        self.assertGreaterEqual(dialog.layer.findData(valid.id()), 0)
        dialog.on_active_layer_changed(invalid)
        self.assertEqual(dialog.current_layer().id(), valid.id())
        self.assertEqual(len(dialog.result_ids), 2)

    def test_unavailable_layer_list_is_empty_and_recovers_after_validity_changes(self):
        layer = self.make_layer(2)
        dialog = self.create_dialog(layer)
        dialog.show()
        QgsApplication.processEvents()
        layer.setValid(False)
        deadline = time.monotonic() + 5
        while dialog.layer_list_timer.isActive() and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.assertEqual(dialog.layer.findData(layer.id()), -1)
        self.assertIsNone(dialog.current_layer())
        self.assertEqual(dialog.status.text(), "No available vector layers")
        layer.setValid(True)
        deadline = time.monotonic() + 5
        while dialog.layer_list_timer.isActive() and time.monotonic() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.wait_for_results(dialog)
        self.assertGreaterEqual(dialog.layer.findData(layer.id()), 0)
        self.assertEqual(dialog.current_layer().id(), layer.id())
        self.assertEqual(len(dialog.result_ids), 2)

    def test_multi_selection_mode_can_be_toggled(self):
        dialog = self.create_dialog(self.make_layer(3))
        dialog.multi_cb.setChecked(True)
        self.assertEqual(dialog.table.selectionMode(), QAbstractItemView.MultiSelection)
        dialog.multi_cb.setChecked(False)
        self.assertEqual(dialog.table.selectionMode(), QAbstractItemView.ExtendedSelection)

    def test_column_preferences_preserve_feature_ids_and_export_visible_fields(self):
        layer = QgsVectorLayer("None?field=id:integer&field=name:string", "columns", "memory")
        feature = QgsFeature(layer.fields())
        feature.setAttributes([12, "Alice"])
        layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        key = dialog.column_settings_key()
        self.addCleanup(QSettings().remove, key)
        QSettings().setValue(key, ["id"])
        dialog.apply_column_visibility()
        dialog.select_all()
        self.assertEqual(len(dialog.selected_fids()), 1)
        self.assertEqual(set(dialog.selected_fids()), set(layer.selectedFeatureIds()))
        self.assertEqual(dialog.table_rows(), [["name"], ["Alice"]])
        dialog.run_search()
        self.assertTrue(dialog.table.isColumnHidden(0))
        self.assertEqual(dialog.table_rows(), [["name"], ["Alice"]])
        reopened = self.plugin.FinderDialog(dialog.iface)
        self.addCleanup(reopened.shutdown)
        reopened.refresh()
        self.wait_for_results(reopened)
        self.assertTrue(reopened.table.isColumnHidden(0))
        QSettings().setValue(key, ["id", "name"])
        dialog.apply_column_visibility()
        self.assertFalse(dialog.table.isColumnHidden(0))

    def test_operators_match_layer_data(self):
        layer = QgsVectorLayer("None?field=name:string&field=amount:integer", "filters", "memory")
        for name, amount in (("Alpha", 5), ("alpha extra", 15), ("Beta", 25), (None, 35), ("", 45)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([name, amount])
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.open_field_filter("name")
        dialog.filter_rows[0].widget.hide()

        def matches(field, operator, value="", upper=""):
            for widget in (dialog.field1, dialog.op1, dialog.value1, dialog.upper1):
                widget.blockSignals(True)
            dialog.field1.setCurrentText(field)
            dialog.op1.setCurrentText(operator)
            dialog.value1.setEditText(value)
            dialog.upper1.setText(upper)
            for widget in (dialog.field1, dialog.op1, dialog.value1, dialog.upper1):
                widget.blockSignals(False)
            expression = dialog.part_expr(dialog.field1, dialog.value1)
            query = QgsExpression(expression)
            self.assertFalse(query.hasParserError(), query.parserErrorString())
            return [f["amount"] for f in layer.getFeatures(QgsFeatureRequest().setFilterExpression(expression))]

        self.assertEqual(matches("name", "Contains", "ALPHA"), [5, 15])
        self.assertEqual(matches("name", "Equals", "Alpha"), [5])
        self.assertEqual(matches("amount", "Greater than", "25"), [35, 45])
        self.assertEqual(matches("amount", "Between", "15", "35"), [15, 25, 35])
        self.assertEqual(matches("name", "Is empty"), [35, 45])
        self.assertEqual(matches("name", "Is not empty"), [5, 15, 25])

    def test_readonly_field_cannot_be_edited_in_a_writable_layer(self):
        layer = self.make_layer(1)
        form = layer.editFormConfig()
        form.setReadOnly(0, True)
        layer.setEditFormConfig(form)
        dialog = self.create_dialog(layer)
        dialog.edit_cb.setChecked(True)
        self.assertTrue(layer.isEditable())
        self.assertFalse(dialog.table.item(0, 0).flags() & Qt.ItemIsEditable)

    def remember_page_size_preference(self):
        key = "LayerFilter/pageSize"
        settings = QSettings()
        previous = settings.value(key) if settings.contains(key) else None
        self.addCleanup(lambda: settings.remove(key) if previous is None else settings.setValue(key, previous))

    def test_pagination_reaches_every_match_beyond_old_row_limit(self):
        self.remember_page_size_preference()
        layer = self.make_layer(2205)
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        visited = []
        while True:
            visited.extend(dialog.all_fids())
            if not dialog.btn_next.isEnabled():
                break
            dialog.change_page(1)
        self.assertEqual(len(visited), 2205)
        self.assertEqual(len(set(visited)), 2205)
        self.assertEqual(set(visited), {feature.id() for feature in layer.getFeatures()})
        self.assertEqual(dialog.table.rowCount(), 5)
        self.assertIn("2201–2205 of 2205", dialog.page_status.text())
        self.assertTrue(dialog.btn_previous.isEnabled())

    def test_all_results_turns_pagination_off(self):
        self.remember_page_size_preference()
        dialog = self.create_dialog(self.make_layer(2105))
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        dialog.change_page(1)
        self.assertEqual(dialog.page, 1)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(0))
        self.assertEqual(dialog.table.rowCount(), 2105)
        self.assertEqual(dialog.page, 0)
        self.assertFalse(dialog.btn_next.isEnabled())
        self.assertFalse(dialog.btn_previous.isEnabled())
        self.assertEqual(dialog.btn_select.text(), "Select all")

    def test_page_selection_and_exports_are_limited_to_current_page(self):
        self.remember_page_size_preference()
        layer = self.make_layer(205)
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        dialog.select_all()
        self.assertEqual(layer.selectedFeatureCount(), 100)
        self.assertEqual(len(dialog.table_rows()), 101)
        first = set(dialog.selected_fids())
        dialog.change_page(1)
        self.assertEqual(dialog.selected_rows(), [])
        self.assertEqual(layer.selectedFeatureCount(), 100)
        self.assertEqual(dialog.selection_status.text(), "100 selected (0 on page)")
        self.assertTrue(first.isdisjoint(dialog.all_fids()))
        dialog.select_all()
        self.assertEqual(set(layer.selectedFeatureIds()), set(dialog.all_fids()))

    def test_new_filter_resets_to_first_page(self):
        self.remember_page_size_preference()
        dialog = self.create_dialog(self.make_layer(305))
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        dialog.change_page(1)
        dialog.edit.setText("2")
        dialog.run_search()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.page, 0)
        self.assertTrue(all("2" in dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())))

    def test_id_search_respects_filters_and_cancellation(self):
        layer = self.make_layer(10)
        expected = tuple(feature.id() for feature in layer.getFeatures()
                         if feature["name"] == "3")
        ids = self.plugin.collect_feature_ids(SimpleNamespace(isCanceled=lambda: False),
                                              QgsVectorLayerFeatureSource(layer), '"name" = \'3\'')
        self.assertEqual(ids, expected)
        self.assertIsNone(self.plugin.collect_feature_ids(SimpleNamespace(isCanceled=lambda: True),
                                                         QgsVectorLayerFeatureSource(layer), ""))

    def test_obsolete_search_completion_cannot_replace_latest_results(self):
        layer = self.make_layer(3)
        dialog = self.create_dialog(layer)
        tasks = []

        def make_task(description, function, **kwargs):
            task = SimpleNamespace(canceled=False, callback=kwargs["on_finished"])
            task.cancel = lambda: setattr(task, "canceled", True)
            task.setDependentLayers = lambda layers: None
            tasks.append(task)
            return task

        with patch.object(self.plugin, "QgsTask", SimpleNamespace(fromFunction=make_task)), \
             patch.object(self.plugin, "QgsApplication", SimpleNamespace(
                 taskManager=lambda: SimpleNamespace(addTask=lambda task: None))):
            dialog.edit.setText("0")
            dialog.run_search()
            dialog.edit.setText("1")
            dialog.run_search()
            self.assertTrue(tasks[0].canceled)
            tasks[0].callback(None, ((),))
            self.assertIs(dialog.query_task, tasks[1])
            self.assertIsNone(dialog.result_ids)
            latest = tuple(feature.id() for feature in layer.getFeatures() if feature["name"] == "1")
            tasks[1].callback(None, (latest,))
        self.assertEqual(dialog.result_ids, latest)
        self.assertEqual(dialog.table_rows(), [["name"], ["1"]])

    def test_data_refresh_clamps_page_after_records_are_removed(self):
        self.remember_page_size_preference()
        layer = self.make_layer(250)
        dialog = self.create_dialog(layer)
        dialog.page_size.setCurrentIndex(dialog.page_size.findData(100))
        dialog.change_page(1)
        dialog.change_page(1)
        self.assertEqual(dialog.page, 2)
        removed = [feature.id() for feature in layer.getFeatures() if int(feature["name"]) < 200]
        self.assertTrue(layer.dataProvider().deleteFeatures(removed))
        dialog.soft_refresh()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.page, 0)
        self.assertEqual(dialog.table.rowCount(), 50)
        self.assertFalse(dialog.btn_next.isEnabled())

    def test_font_settings_apply_after_save_and_survive_reopening(self):
        settings = QSettings()
        for key in ("LayerFilter/fontFamily", "LayerFilter/fontSize", "LayerFilter/theme", "LayerFilter/pinned"):
            previous = settings.value(key) if settings.contains(key) else None
            self.addCleanup(lambda key=key, previous=previous:
                            settings.remove(key) if previous is None else settings.setValue(key, previous))
        layer = self.make_layer(2)
        dialog = self.create_dialog(layer)
        family = None
        original_size = dialog.font_size
        original_theme, original_pin = dialog.theme, dialog.pinned
        chosen_theme = "dark" if original_theme == "light" else "light"
        self.assertFalse(hasattr(dialog, "font_picker"))
        self.assertFalse(hasattr(dialog, "btn_pin"))
        self.assertFalse(hasattr(dialog, "btn_theme"))

        def save(settings_dialog):
            nonlocal family
            self.assertTrue(settings_dialog.isModal())
            picker = settings_dialog.font_picker
            self.assertGreater(picker.count(), 0, "The offscreen test platform must load installed fonts")
            chosen_index = 0 if picker.currentIndex() != 0 else min(1, picker.count() - 1)
            picker.setCurrentIndex(chosen_index)
            family = picker.currentFont().family()
            settings_dialog.font_size_spin.setValue(14)
            settings_dialog.theme_picker.setCurrentIndex(settings_dialog.theme_picker.findData(chosen_theme))
            settings_dialog.pin_cb.setChecked(not original_pin)
            self.assertEqual(dialog.font_size, original_size)
            self.assertEqual(dialog.theme, original_theme)
            self.assertEqual(dialog.pinned, original_pin)
            self.assertIn("font-size: 14pt", settings_dialog.preview.styleSheet())
            self.assertEqual(settings_dialog.font_delegate.theme, chosen_theme)
            index = settings_dialog.font_picker.model().index(chosen_index, 0)
            self.assertEqual(settings_dialog.font_delegate.preview_font(index).family(), family)
            return QDialog.Accepted

        with patch.object(self.plugin.SettingsDialog, "exec_", save):
            dialog.show_settings()
        self.assertEqual(dialog.font_family, family)
        self.assertEqual(dialog.font_size, 14)
        self.assertEqual(dialog.theme, chosen_theme)
        self.assertEqual(dialog.pinned, not original_pin)
        self.assertEqual(bool(dialog.windowFlags() & Qt.WindowStaysOnTopHint), not original_pin)
        self.assertIn("font-size: 14pt", dialog.styleSheet())
        self.assertIn('font-family: "' + family + '"', dialog.styleSheet())
        self.assertGreaterEqual(dialog.table.verticalHeader().defaultSectionSize(), QFontMetrics(QFont(family, 14)).height() + 10)
        dialog.open_field_filter("name")
        dialog.filter_rows[0].widget.hide()
        self.assertIn("font-size: 14pt", dialog.value1.view().styleSheet())
        self.assertIsNone(dialog.value1.completer())
        reopened = self.plugin.FinderDialog(dialog.iface)
        self.addCleanup(reopened.shutdown)
        self.assertEqual(reopened.font_family, family)
        self.assertEqual(reopened.font_size, 14)
        self.assertEqual(reopened.theme, chosen_theme)
        self.assertEqual(reopened.pinned, not original_pin)

    def test_canceling_font_settings_keeps_previous_preferences(self):
        dialog = self.create_dialog(self.make_layer(1))
        before = (dialog.font_family, dialog.font_size, dialog.theme, dialog.pinned, dialog.styleSheet())
        settings = QSettings()
        keys = ("LayerFilter/fontFamily", "LayerFilter/fontSize", "LayerFilter/theme", "LayerFilter/pinned")
        stored = [settings.value(key) for key in keys]

        def cancel(settings_dialog):
            settings_dialog.font_size_spin.setValue(24 if dialog.font_size != 24 else 8)
            settings_dialog.theme_picker.setCurrentIndex(0 if dialog.theme == "dark" else 1)
            settings_dialog.pin_cb.setChecked(not dialog.pinned)
            return QDialog.Rejected

        with patch.object(self.plugin.SettingsDialog, "exec_", cancel):
            dialog.show_settings()
        self.assertEqual((dialog.font_family, dialog.font_size, dialog.theme, dialog.pinned, dialog.styleSheet()), before)
        self.assertEqual([settings.value(key) for key in keys], stored)

    def test_font_preview_painter_uses_each_rows_font(self):
        from qgis.PyQt.QtCore import QRect
        from qgis.PyQt.QtGui import QImage, QPainter
        from qgis.PyQt.QtWidgets import QStyleOptionViewItem

        class TrackingPainter(QPainter):
            def setFont(self, font):
                self.selected_family = font.family()
                super().setFont(font)

        parent = self.create_dialog(self.make_layer(1))
        settings = self.plugin.SettingsDialog(parent, parent.font_family, parent.font_size, parent.theme, parent.pinned)
        self.addCleanup(settings.deleteLater)
        model = settings.font_picker.model()
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 50)
        for row in range(min(3, model.rowCount())):
            index = model.index(row, 0)
            image = QImage(400, 50, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = TrackingPainter(image)
            try:
                settings.font_delegate.paint(painter, option, index)
                self.assertEqual(painter.selected_family, index.data(Qt.DisplayRole))
            finally:
                painter.end()
            self.assertEqual(settings.font_delegate.preview_font(index).family(), index.data(Qt.DisplayRole))
            self.assertGreater(settings.font_delegate.sizeHint(option, index).height(), 0)

    def test_size_arrows_are_visible_and_clickable_in_both_themes(self):
        from qgis.PyQt.QtTest import QTest
        from qgis.PyQt.QtWidgets import QStyle, QStyleOptionSpinBox
        parent = self.create_dialog(self.make_layer(1))
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                settings = self.plugin.SettingsDialog(parent, parent.font_family, 10, theme, parent.pinned)
                self.addCleanup(settings.deleteLater)
                settings.show()
                QgsApplication.processEvents()
                spin = settings.font_size_spin
                option = QStyleOptionSpinBox()
                spin.initStyleOption(option)
                up = spin.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, spin)
                down = spin.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, spin)
                image = spin.grab().toImage()
                for rect in (up, down):
                    self.assertGreater(rect.width(), 0)
                    self.assertGreater(rect.height(), 0)
                    center = rect.adjusted(3, 2, -3, -2)
                    colors = {image.pixelColor(x, y).rgba() for x in range(center.left(), center.right() + 1)
                              for y in range(center.top(), center.bottom() + 1)}
                    self.assertGreater(len(colors), 1, "Arrow area is blank")
                QTest.mouseClick(spin, Qt.LeftButton, pos=up.center())
                self.assertEqual(spin.value(), 11)
                QTest.mouseClick(spin, Qt.LeftButton, pos=down.center())
                self.assertEqual(spin.value(), 10)
                settings.close()

    def test_multiple_values_match_any_barangay_and_combine_with_second_filter(self):
        layer = QgsVectorLayer("None?field=barangay:integer&field=status:string", "multiple", "memory")
        for barangay, status in ((1, "Open"), (2, "Closed"), (2, "Open"), (3, "Open")):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([barangay, status])
            layer.dataProvider().addFeatures([feature])
        dialog = self.create_dialog(layer)
        dialog.open_field_filter("barangay")
        dialog.filter_rows[0].widget.hide()
        dialog.field1.setCurrentText("barangay")
        dialog.op1.setCurrentText("Equals")

        dialog.value1.set_selected_values(["1", "2"])
        dialog.refresh_dependent_values()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.value1.selected_values, ["1", "2"])
        self.assertEqual(len(dialog.result_ids), 3)
        self.assertIn('"barangay" IN (1, 2)', dialog.build_expr())
        dialog.open_field_filter("status")
        dialog.filter_rows[1].widget.hide()
        dialog.field2.setCurrentText("status")
        dialog.value2.setEditText("Open")
        dialog.run_search()
        self.wait_for_results(dialog)
        self.assertEqual(len(dialog.result_ids), 2)
        self.assertIn(' AND ', dialog.build_expr())
        dialog.soft_refresh()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.value1.selected_values, ["1", "2"])
        self.assertEqual(len(dialog.result_ids), 2)
        dialog.clear_filters()
        self.wait_for_results(dialog)
        self.assertEqual(dialog.filter_rows, [])

    def test_equals_popup_search_and_missing_values(self):
        parent = self.create_dialog(self.make_layer(3))
        parent.open_field_filter("name")
        parent.filter_rows[0].widget.hide()
        parent.field1.setCurrentText("name")
        combo = parent.value1
        combo.showPopup()
        popup = combo.checkbox_popup
        self.assertTrue(popup.isVisible())
        popup.search.setText("99")
        popup.add_typed_value()
        self.assertEqual(combo.selected_values, ["99"])
        self.assertTrue(popup.isVisible())
        self.assertIn("99", popup.items)
        popup.items[None].setCheckState(Qt.Checked)
        self.assertEqual(combo.selected_values, [])
        self.assertEqual(combo.currentText(), self.plugin.ALL_VALUES)
        popup.hide()

    def test_dynamic_filter_rows_apply_all_constraints_and_remove_cleanly(self):
        layer = QgsVectorLayer("None?field=a:integer&field=b:string&field=c:integer&field=d:string", "dynamic", "memory")
        for attrs in ([1, "Open", 20, "Yes"], [2, "Open", 20, "No"], [2, "Open", 5, "Yes"], [3, "Open", 20, "Yes"]):
            feature = QgsFeature(layer.fields())
            feature.setAttributes(attrs)
            layer.dataProvider().addFeatures([feature])
        parent = self.create_dialog(layer)
        parent.add_filter_row()
        parent.add_filter_row()
        third = parent.add_filter_row()
        fourth = parent.add_filter_row()
        parent.filter_rows[0].field.setCurrentText("a")
        parent.filter_rows[0].value.set_selected_values(["1", "2"])
        parent.filter_rows[1].field.setCurrentText("b")
        parent.filter_rows[1].value.set_selected_values(["Open"])
        third.field.setCurrentText("c")
        third.operator.setCurrentText("Greater than")
        third.value.setEditText("10")
        fourth.field.setCurrentText("d")
        fourth.value.set_selected_values(["Yes"])
        parent.refresh_dependent_values()
        self.wait_for_results(parent)
        self.assertEqual(len(parent.filter_rows), 4)
        self.assertEqual(len(parent.result_ids), 1)
        parent.remove_filter_row(fourth)
        self.wait_for_results(parent)
        self.assertEqual(len(parent.result_ids), 2)
        for row in list(parent.filter_rows[1:]):
            parent.remove_filter_row(row)
        self.assertEqual(len(parent.filter_rows), 1)
        parent.remove_filter_row(parent.filter_rows[0])
        self.assertEqual(len(parent.filter_rows), 0)
        for _ in range(8):
            parent.add_filter_row()
        self.assertEqual(len(parent.filter_rows), 8)
        parent.clear_filters()
        self.wait_for_results(parent)
        self.assertEqual(len(parent.result_ids), 4)
        self.assertTrue(all(not row.value.selected_values for row in parent.filter_rows))

    def test_equals_checkboxes_keep_dropdown_open_for_multiple_clicks(self):
        from qgis.PyQt.QtTest import QTest
        from qgis.PyQt.QtCore import QPoint
        parent = self.create_dialog(self.make_layer(3))
        parent.open_field_filter("name")
        parent.filter_rows[0].widget.hide()
        parent.field1.setCurrentText("name")
        combo = parent.value1
        combo.addItem("1")
        combo.addItem("2")
        combo.showPopup()
        popup = combo.checkbox_popup
        QgsApplication.processEvents()
        for value in ("1", "2"):
            item = popup.items[value]
            popup.list.scrollToItem(item)
            QgsApplication.processEvents()
            rect = popup.list.visualItemRect(item)
            QTest.mouseClick(popup.list.viewport(), Qt.LeftButton, pos=QPoint(rect.left() + 8, rect.center().y()))
            self.assertIn(value, combo.selected_values)
            self.assertTrue(popup.isVisible())
        self.assertEqual(set(combo.selected_values), {"1", "2"})
        popup.hide()


if __name__ == "__main__":
    unittest.main()
