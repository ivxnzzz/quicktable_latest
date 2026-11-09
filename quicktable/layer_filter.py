import os
import re
import hashlib
import json
import math
from array import array
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from .filter_utils import clipboard_text
from .editing import convert_attribute, attribute_text, validate_change, validate_pending_changes
from .numeric_statistics import NumericTotal
from .exporting import export_csv_task
from .filter_logic import FILTER_OPERATORS, field_filter
from .filter_widgets import CheckableValueCombo, ValuePopup
from .compact_filters import FilterHeader, ColumnTextDelegate, StatisticsStrip, NULL_ROLE
from .pagination import PAGE_SIZES, normalize_page_size, page_window

from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                                 QComboBox, QLineEdit, QTableWidget,
                                 QTableWidgetItem, QLabel, QPushButton,
                                 QAbstractItemView, QAbstractButton, QFileDialog, QApplication,
                                 QCompleter, QCheckBox, QMessageBox, QFrame,
                                 QListWidget, QListWidgetItem, QDialogButtonBox,
                                 QFontComboBox, QSpinBox, QStyledItemDelegate, QStyle,
                                 QMenu, QInputDialog, QPlainTextEdit, QFormLayout, QGroupBox)
from qgis.PyQt.QtCore import (Qt, QTimer, QSettings, QMetaType, QSize, QPoint, QDate, QByteArray,
                              QItemSelection, QItemSelectionModel)
from qgis.PyQt.QtGui import QAction, QPalette, QColor, QIcon, QFont, QFontDatabase, QFontMetrics, QBrush, QPixmap, QPainter
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.core import (QgsProject, QgsMapLayer, QgsFeatureRequest,
                       QgsExpression, QgsApplication, QgsVectorDataProvider,
                       QgsTask, QgsVectorLayerFeatureSource, QgsRectangle, QgsSpatialIndex, QgsUnitTypes, QgsField, QgsFields, NULL)

NO_FIELD = "(no filter)"
ALL_VALUES = "(all)"
MAX_VALUE_FEATURES = 2000
MAX_STAT_DISTINCT = 25000
MAX_RENDER_ROWS = 10000
MAX_RENDER_CELLS = 250000
STAT_HISTOGRAM_BINS = 16
ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")


def plugin_icon():
    return QIcon(os.path.join(ICONS_DIR, "icon.png"))


TOOL_ICONS = {
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.8h1.6l.5 2.1a7.5 7.5 0 0 1 1.6.7l1.9-1.1 2.2 2.2-1.1 1.9a7.5 7.5 0 0 1 .7 1.6l2.1.5v3.2l-2.1.5a7.5 7.5 0 0 1-.7 1.6l1.1 1.9-2.2 2.2-1.9-1.1a7.5 7.5 0 0 1-1.6.7l-.5 2.1h-3.2l-.5-2.1a7.5 7.5 0 0 1-1.6-.7l-1.9 1.1-2.2-2.2 1.1-1.9a7.5 7.5 0 0 1-.7-1.6l-2.1-.5v-3.2l2.1-.5a7.5 7.5 0 0 1 .7-1.6L4.2 6.7l2.2-2.2 1.9 1.1a7.5 7.5 0 0 1 1.6-.7l.5-2.1z"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14-5L4 8"/><path d="M4 4v4h4M4 13a8 8 0 0 0 14 5l2-2"/><path d="M20 20v-4h-4"/>',
    "undo": '<path d="m9 8-4 4 4 4"/><path d="M5 12h9a5 5 0 0 1 5 5"/>',
    "redo": '<path d="m15 8 4 4-4 4"/><path d="M19 12h-9a5 5 0 0 0-5 5"/>',
    "copy": '<rect x="8" y="8" width="11" height="12" rx="1"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h3"/>',
    "export": '<path d="M12 3v11m-4-4 4 4 4-4M5 16v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3"/>',
    "columns": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>',
    "select": '<path d="m4 4 15 6-6 2-2 6z"/>',
    "nearby": '<path d="M19 10c0 5-7 10-7 10S5 15 5 10a7 7 0 0 1 14 0z"/><circle cx="12" cy="10" r="2"/>',
    "save": '<path d="M5 3h12l3 3v14H4V3z"/><path d="M7 3v6h9V3M7 20v-7h10v7"/>',
    "fields": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16M11 8h7M11 12h7M11 16h7"/>',
    "fieldAdd": '<path d="M4 5h8M4 10h8M4 15h8M17 11v8M13 15h8"/>',
    "fieldDelete": '<path d="M4 5h8M4 10h8M4 15h8M13 15h8"/>',
}


def toolbar_icon(name, color):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
           'fill="none" stroke="{}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{}</svg>'
           .format(color, TOOL_ICONS[name]))
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def field_kind(field):
    if field is None:
        return "text"
    return {QMetaType.Type.Int: "integer", QMetaType.Type.UInt: "integer", QMetaType.Type.LongLong: "integer",
            QMetaType.Type.ULongLong: "integer", QMetaType.Type.Double: "number", QMetaType.Type.Bool: "boolean",
            QMetaType.Type.QDate: "date", QMetaType.Type.QDateTime: "datetime", QMetaType.Type.QTime: "time"}.get(field.type(), "text")




def collect_feature_ids(task, source, expression, sort_field=None, ascending=True):
    """Find all matches off the UI thread, without retaining attributes/geometry."""
    if task.isCanceled():
        return None
    request = QgsFeatureRequest()
    request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
    if not sort_field:
        request.setNoAttributes()
    else:
        request.setSubsetOfAttributes([source.fields().indexFromName(sort_field)])
    if expression:
        request.setFilterExpression(expression)
    if sort_field:
        request.addOrderBy(QgsExpression.quotedColumnRef(sort_field), ascending)
        request.addOrderBy('$id', True)
    features = source.getFeatures(request)
    ids = array('q')
    try:
        for feature in features:
            if task.isCanceled():
                return None
            ids.append(feature.id())
    finally:
        features.close()
    if task.isCanceled():
        return None
    if not sort_field:
        ids = array('q', sorted(ids))
    # Compact storage keeps large result sets from retaining one Python int per ID.
    return ids if len(ids) > 50000 else tuple(ids)


def collect_feature_ids_task(task, source, expression, sort_field=None, ascending=True):
    ids = collect_feature_ids(task, source, expression, sort_field, ascending)
    # QgsTask.fromFunction omits falsy return values from its completion callback.
    return (ids,) if ids is not None else None


def collect_nearby(task, source, selected_ids, distance):
    """Return IDs touching or within a planar distance of the selected features."""
    selected = set(selected_ids)
    request = QgsFeatureRequest().setFilterFids(list(selected))
    request.setNoAttributes()
    features = source.getFeatures(request)
    origins = {}
    spatial_index = QgsSpatialIndex()
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
            origins[feature.id()] = geometry
            spatial_index.addFeature(feature)
            rectangle = QgsRectangle(geometry.boundingBox())
            if distance is not None:
                rectangle.grow(distance)
            if bounds is None:
                bounds = rectangle
            else:
                bounds.combineExtentWith(rectangle)
    finally:
        features.close()
    if not origins:
        raise ValueError("The selected features have no usable geometry.")
    request = QgsFeatureRequest().setFilterRect(bounds)
    request.setNoAttributes()
    features = source.getFeatures(request)
    matches = []
    try:
        for feature in features:
            if task.isCanceled():
                return None
            if feature.id() in selected or not feature.hasGeometry():
                continue
            geometry = feature.geometry()
            if geometry.isEmpty():
                continue
            candidate_bounds = QgsRectangle(geometry.boundingBox())
            if distance is not None:
                candidate_bounds.grow(distance)
            for origin_id in spatial_index.intersects(candidate_bounds):
                if task.isCanceled():
                    return None
                origin = origins[origin_id]
                if distance is None:
                    matched = origin.touches(geometry)
                else:
                    separation = origin.distance(geometry)
                    if separation < 0:
                        raise ValueError("Could not calculate geometry distance; check the layer geometries.")
                    matched = separation <= distance
                if matched:
                    matches.append(feature.id())
                    break
    finally:
        features.close()
    return tuple(matches)


def collect_nearby_task(task, source, selected_ids, distance):
    ids = collect_nearby(task, source, selected_ids, distance)
    return (ids,) if ids is not None else None


def collect_column_statistics(task, source, columns, ids):
    """Collect exact counts and bounded category distributions for filtered IDs."""
    summaries = {index: [0, 0, 0.0, None, None, numeric,
                         {"distinct": 0, "capped": False, "top": [], "histogram": [],
                          "numeric_count": 0, "nonfinite": 0}] for index, numeric in columns}
    frequencies = {index: {} for index, numeric in columns}
    totals = {index: NumericTotal(field_kind(source.fields()[index]) == "integer")
              for index, numeric in columns if numeric}
    if not ids or not columns:
        return {"summaries": summaries}
    request = QgsFeatureRequest().setFilterFids(list(ids))
    request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
    request.setSubsetOfAttributes([index for index, numeric in columns])
    features = source.getFeatures(request)
    try:
        for feature in features:
            if task.isCanceled():
                return None
            for index, numeric in columns:
                value = feature[index]
                summary = summaries[index]
                if value is None or value == NULL:
                    summary[1] += 1
                    continue
                summary[0] += 1
                categories = frequencies[index]
                if categories is not None:
                    label = str(value)
                    if label in categories:
                        categories[label] += 1
                    elif len(categories) < MAX_STAT_DISTINCT:
                        categories[label] = 1
                    else:
                        frequencies[index] = None
                        summary[6]["capped"] = True
                        summary[6]["distinct"] = MAX_STAT_DISTINCT + 1
                if numeric:
                    try:
                        number = int(value) if totals[index].integer else float(value)
                    except (ValueError, TypeError, OverflowError):
                        summary[6]["nonfinite"] += 1
                        continue
                    if not math.isfinite(number):
                        summary[6]["nonfinite"] += 1
                        continue
                    summary[6]["numeric_count"] += 1
                    totals[index].add(number)
                    summary[2] = totals[index].total
                    summary[3] = number if summary[3] is None else min(summary[3], number)
                    summary[4] = number if summary[4] is None else max(summary[4], number)
    finally:
        features.close()
    for index, numeric in columns:
        summary = summaries[index]
        categories = frequencies[index]
        if categories is not None:
            summary[6]["distinct"] = len(categories)
            if not numeric and len(categories) <= 30:
                summary[6]["top"] = sorted(categories.items(), key=lambda item: (-item[1], item[0].casefold()))[:2]
        if numeric and summary[6]["numeric_count"]:
            summary[6]["histogram"] = [0] * STAT_HISTOGRAM_BINS
    histogram_columns = [(index, summaries[index]) for index, numeric in columns
                         if numeric and summaries[index][6]["histogram"]]
    if histogram_columns:
        request.setSubsetOfAttributes([index for index, summary in histogram_columns])
        features = source.getFeatures(request)
        try:
            for feature in features:
                if task.isCanceled():
                    return None
                for index, summary in histogram_columns:
                    value = feature[index]
                    if value is None or value == NULL:
                        continue
                    try:
                        number = int(value) if totals[index].integer else float(value)
                    except (ValueError, TypeError, OverflowError):
                        continue
                    if not math.isfinite(number):
                        continue
                    low, high = summary[3], summary[4]
                    if high > low:
                        span = high - low
                        ratio = ((number - low) / span if math.isfinite(span) else
                                 (number / 2 - low / 2) / (high / 2 - low / 2))
                    else:
                        ratio = 0.5
                    if not math.isfinite(ratio):
                        ratio = 0.0 if number == low else 1.0
                    bucket = max(0, min(STAT_HISTOGRAM_BINS - 1, int(ratio * STAT_HISTOGRAM_BINS)))
                    summary[6]["histogram"][bucket] += 1
        finally:
            features.close()
    return {"summaries": summaries}


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

# signals of a vector layer that mean "the data or fields changed"
LAYER_SIGNALS = ("dataChanged", "updatedFields", "editingStarted", "editingStopped",
                 "afterCommitChanges", "attributeValueChanged",
                 "featureAdded", "featureDeleted", "readOnlyChanged",
                 "supportsEditingChanged")


THEMES = {
    "dark": dict(
        bg="#1f1e1d", surface="#262624", alt="#2a2927", border="#3d3d3a", border_hi="#5a5955",
        text="#e8e6dc", text_hi="#faf9f5", text_soft="#c2c0b6", muted="#87867f",
        accent="#73bb98", accent_hi="#88caaa", accent_press="#5aa783", accent_text="#1f1e1d",
        sel_bg="#253c31", sel_fg="#d5efdf", sel_input="#345743", hover_bg="#2f2e2c", press_bg="#2a2927",
        danger="#e0675e", danger_hi="#ff8a80", danger_border="#5a3a37",
        dis_text="#5a5955", dis_border="#2e2d2b", pdis_bg="#293d32", pdis_text="#587965", ddis_text="#5a4442",
        grid="#34332f", scroll="#3d3d3a", scroll_hi="#5a5955"),
    "light": dict(
        bg="#faf9f5", surface="#ffffff", alt="#f5f4ee", border="#dedcd1", border_hi="#b8b5a8",
        text="#1f1e1d", text_hi="#000000", text_soft="#4a4943", muted="#73726c",
        accent="#2e7d5b", accent_hi="#256649", accent_press="#1c5139", accent_text="#ffffff",
        sel_bg="#e7f3ec", sel_fg="#1e4935", sel_input="#e7f3ec", hover_bg="#f0eee6", press_bg="#f0eee6",
        danger="#c0392b", danger_hi="#a52f23", danger_border="#e7b9b3",
        dis_text="#b0aea5", dis_border="#e8e6dc", pdis_bg="#d4e7db", pdis_text="#6f8b7b", ddis_text="#d9a7a1",
        grid="#e6e3d8", scroll="#d4d1c5", scroll_hi="#b8b5a8"),
}

FONT = '"JetBrains Mono", "Cascadia Mono", "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace'

# @name tokens are replaced with the colors of the chosen theme
TEMPLATE = """
* { font-family: @font; font-size: @font_size; }
QDialog { background: @bg; }
QWidget { color: @text; }
QToolTip { background: @surface; color: @text; border: 1px solid @border; padding: 3px 6px; }

QFrame#banner { background: transparent; border: none; border-bottom: 1px solid @border; }
QLabel#title { color: @text; font-size: @title_size; font-weight: 700; background: transparent; }
QLabel#subtitle { color: @muted; background: transparent; }

QFrame#card { background: transparent; border: none; }
QFrame#card QPushButton { border-radius: 4px; padding: 4px 10px; }
QFrame#card QComboBox#layerPicker, QFrame#card QLineEdit#globalSearch { border-radius: 4px; padding: 4px 10px; }
QFrame#toolSeparator { background: @border; border: none; }
QFrame#fieldFilterPopup { background: @surface; border: 1px solid @border; border-radius: 5px; }
QLabel#fieldlabel { color: @muted; background: transparent; }
QLabel#status { color: @muted; background: transparent; }

QLineEdit, QComboBox, QSpinBox {
    background: @surface; border: 1px solid @border; border-radius: 4px;
    padding: 3px 8px; min-height: 18px; selection-background-color: @sel_input; selection-color: @text_hi;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: @border_hi; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid @accent; padding: 3px 8px; }
QPlainTextEdit {
    background: @surface; color: @text; border: 1px solid @border; border-radius: 4px;
    padding: 4px 8px; selection-background-color: @sel_input; selection-color: @text_hi;
}
QPlainTextEdit:hover { border-color: @border_hi; }
QPlainTextEdit:focus { border: 1px solid @accent; }
QComboBox::drop-down { border: none; width: 22px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url(@down_url); width: 10px; height: 10px; }
QSpinBox, QSpinBox:focus { padding-right: 28px; }
QSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 24px;
    border-left: 1px solid @border; border-bottom: 1px solid @border;
    border-top-right-radius: 4px; background: @alt;
}
QSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right; width: 24px;
    border-left: 1px solid @border; border-bottom-right-radius: 4px; background: @alt;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: @hover_bg; }
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed { background: @sel_bg; }
QSpinBox::up-arrow { image: url(@up_url); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url(@down_url); width: 10px; height: 10px; }
QAbstractItemView {
    background: @surface; color: @text; border: 1px solid @border; outline: 0;
    selection-background-color: @sel_bg; selection-color: @sel_fg;
}

QPushButton {
    background: transparent; border: 1px solid @border; border-radius: 4px;
    padding: 3px 10px; color: @text_soft; font-weight: normal;
}
QPushButton:hover { border-color: @accent; color: @text_hi; }
QPushButton:pressed { background: transparent; border-color: @accent_press; color: @accent_press; }
QPushButton:disabled { color: @dis_text; border-color: @dis_border; }
QPushButton#primary { background: transparent; border: 1px solid @accent; color: @accent; }
QPushButton#primary:hover { background: transparent; border-color: @accent_hi; color: @accent_hi; }
QPushButton#primary:pressed { background: transparent; border-color: @accent_press; color: @accent_press; }
QPushButton#primary:disabled { background: transparent; border-color: @dis_border; color: @dis_text; }
QPushButton#danger { color: @danger; border-color: @danger_border; }
QPushButton#danger:hover { border-color: @danger; color: @danger_hi; }
QPushButton#danger:disabled { color: @ddis_text; border-color: @dis_border; }
QPushButton#theme { padding: 1px 8px; color: @muted; }
QPushButton#sortOption:checked { background: transparent; border: 2px solid @accent; color: @accent; }
QPushButton#statsToggle:checked { background: transparent; border: 2px solid @accent; color: @accent; }

QMenu { background: @surface; color: @text; border: 1px solid @border; padding: 4px; }
QMenu::item { background: transparent; color: @text; padding: 6px 24px 6px 32px; border-radius: 3px; }
QMenu::item:selected { background: @sel_bg; color: @sel_fg; }
QMenu::item:disabled { color: @muted; }
QMenu::separator { height: 1px; background: @border; margin: 4px 8px; }
QMenu::icon { left: 8px; }

QCheckBox { spacing: 6px; background: transparent; color: @text_soft; }
QCheckBox::indicator { width: 13px; height: 13px; border: 1px solid @border_hi; border-radius: 3px; background: transparent; }
QCheckBox::indicator:hover { border-color: @accent; }
QCheckBox::indicator:checked { background: @accent; border-color: @accent; image: url(@check_url); }
QListWidget::indicator { width: 13px; height: 13px; border: 1px solid @border_hi; border-radius: 3px; background: @surface; }
QListWidget::indicator:checked { background: @accent; border-color: @accent; image: url(@check_url); }

QTableWidget {
    background: @surface; alternate-background-color: @alt;
    border: 1px solid @border; border-radius: 0; gridline-color: @grid;
    selection-background-color: @sel_bg; selection-color: @sel_fg;
}
QTableWidget[editing="true"] { border: 1px solid @accent; }
QTableWidget::item { padding: 1px 8px; border: none; border-right: 1px solid @grid; }
QTableWidget::item:hover { background: @hover_bg; }
QHeaderView::section {
    background: @surface; color: @muted; font-weight: 600;
    padding: 4px 8px; border: none; border-right: 1px solid @grid; border-bottom: 1px solid @border;
}
QTableCornerButton::section { background: @surface; border: none; }

QScrollBar:vertical { background: transparent; width: 9px; margin: 1px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 3px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: @scroll_hi; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 1px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 3px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: @scroll_hi; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""

# dropdown lists are separate pop-up windows, so they are styled directly
POPUP_TEMPLATE = """
QListView, QAbstractItemView {
    font-family: @font; font-size: @font_size;
    background-color: @surface; color: @text; border: 1px solid @border; outline: 0;
    selection-background-color: @sel_bg; selection-color: @sel_fg;
}
QListView::item, QAbstractItemView::item {
    min-height: 20px; padding: 1px 8px; color: @text; background-color: @surface;
}
QListView::item:hover, QAbstractItemView::item:hover { background-color: @hover_bg; color: @sel_fg; }
QListView::item:selected, QAbstractItemView::item:selected { background-color: @sel_bg; color: @sel_fg; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 1px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def _fill(template, name, font_family=None, font_size=9):
    t = dict(THEMES[name])
    here = ICONS_DIR
    t["font"] = '"{}"'.format(font_family.replace("\\", "\\\\").replace('"', '\\"')) if font_family else FONT
    t["font_size"] = "{}pt".format(font_size)
    t["title_size"] = "{}pt".format(font_size + 2)
    t["down_url"] = os.path.join(here, "down_%s.svg" % name).replace("\\", "/")
    t["up_url"] = os.path.join(here, "up_%s.svg" % name).replace("\\", "/")
    t["check_url"] = os.path.join(here, "check_%s.svg" % name).replace("\\", "/")
    return re.sub(r"@(\w+)", lambda m: t[m.group(1)], template)


def build_css(name, font_family=None, font_size=9):
    return _fill(TEMPLATE, name, font_family, font_size)


def dark_palette(widget, name):
    t = THEMES[name]
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Base, QColor(t["surface"]))
    pal.setColor(QPalette.ColorRole.Window, QColor(t["surface"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t["sel_bg"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t["sel_fg"]))
    widget.setPalette(pal)


def style_combo_popup(combo, name, font_family=None, font_size=9):
    css = _fill(POPUP_TEMPLATE, name, font_family, font_size)
    view = combo.view()
    view.setStyleSheet(css)
    dark_palette(view, name)
    box = view.parentWidget()  # the frame around the list
    if box is not None:
        dark_palette(box, name)
        box.setAutoFillBackground(True)
    comp = combo.completer()   # typing suggestions of editable boxes
    if comp is not None and comp.popup() is not None:
        comp.popup().setStyleSheet(css)
        dark_palette(comp.popup(), name)


class SortItem(QTableWidgetItem):
    """Sorts numbers as numbers, text as text (like Excel)."""
    def __lt__(self, other):
        a, b = self.text(), other.text()
        try:
            return float(a) < float(b)
        except ValueError:
            return a.lower() < b.lower()


class FontPreviewDelegate(QStyledItemDelegate):
    """Paint each font explicitly, bypassing the interface's stylesheet font."""
    def __init__(self, theme, point_size, parent):
        super().__init__(parent)
        self.theme = theme
        self.point_size = point_size

    def preview_font(self, index):
        return QFont(str(index.data(Qt.ItemDataRole.DisplayRole)), self.point_size)

    def paint(self, painter, option, index):
        colors = THEMES[self.theme]
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        try:
            painter.setClipRect(option.rect)
            painter.fillRect(option.rect, QColor(colors["sel_bg" if selected else "hover_bg" if hover else "surface"]))
            painter.setPen(QColor(colors["sel_fg" if selected else "text"]))
            painter.setFont(self.preview_font(index))
            painter.drawText(option.rect.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             str(index.data(Qt.ItemDataRole.DisplayRole)))
        finally:
            painter.restore()

    def sizeHint(self, option, index):
        metrics = QFontMetrics(self.preview_font(index))
        return QSize(max(280, metrics.horizontalAdvance(str(index.data(Qt.ItemDataRole.DisplayRole))) + 20),
                     max(24, metrics.height() + 8))


class SettingsDialog(QDialog):
    def __init__(self, parent, family, size, theme, pinned=True):
        super().__init__(parent)
        self.setWindowTitle("QuickTable Settings")
        self.setModal(True)
        self.setFont(QFont(family, size))
        self.setStyleSheet(build_css(theme, family, size))
        self.resize(440, 190)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Font"))
        self.font_picker = QFontComboBox()
        self.font_picker.setCurrentFont(QFont(family))
        self.font_picker.setMinimumContentsLength(18)
        self.font_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.font_picker, 1)
        row.addWidget(QLabel("Size"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.setValue(size)
        self.font_size_spin.setKeyboardTracking(False)
        self.font_size_spin.setMinimumWidth(110)
        self.font_size_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        row.addWidget(self.font_size_spin)
        layout.addLayout(row)
        self.preview = QLabel("Aa Bb Cc  0123456789")
        self.preview.setMinimumHeight(32)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme"))
        self.theme_picker = QComboBox()
        self.theme_picker.addItem("Light", "light")
        self.theme_picker.addItem("Dark", "dark")
        self.theme_picker.setCurrentIndex(self.theme_picker.findData(theme))
        self.theme_picker.setMinimumWidth(115)
        row.addWidget(self.theme_picker)
        self.pin_cb = QCheckBox("Keep QuickTable on top")
        self.pin_cb.setChecked(pinned)
        row.addSpacing(12)
        row.addWidget(self.pin_cb)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.font_delegate = FontPreviewDelegate(theme, size, self.font_picker)
        self.font_picker.setItemDelegate(self.font_delegate)
        self.updating_preview = False

        def preview_font(*args):
            if self.updating_preview:
                return
            self.updating_preview = True
            try:
                selected_theme = self.theme_picker.currentData()
                self.setStyleSheet(build_css(selected_theme, family, size))
                self.preview.setStyleSheet(_fill(
                    "font-family: @font; font-size: @font_size; color: @text;", selected_theme,
                    self.font_picker.currentFont().family(), self.font_size_spin.value()))
                self.font_delegate.theme = selected_theme
                self.font_delegate.point_size = self.font_size_spin.value()
                style_combo_popup(self.font_picker, selected_theme, family, size)
                style_combo_popup(self.theme_picker, selected_theme, family, size)
                self.font_picker.view().doItemsLayout()
                self.font_picker.view().viewport().update()
            finally:
                self.updating_preview = False

        self.font_picker.currentFontChanged.connect(preview_font)
        self.font_size_spin.valueChanged.connect(preview_font)
        self.theme_picker.currentIndexChanged.connect(preview_font)
        preview_font()




class AddFieldDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add fields")
        self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        self.resize(640, 480)
        self.queued = []
        group = QGroupBox("New field")
        form = QGridLayout(group)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Field name")
        self.field_type = QComboBox()
        for label, value in (("Text", QMetaType.Type.QString), ("Whole number (32-bit)", QMetaType.Type.Int),
                             ("Whole number (64-bit)", QMetaType.Type.LongLong), ("Decimal number", QMetaType.Type.Double),
                             ("Date", QMetaType.Type.QDate), ("True / False", QMetaType.Type.Bool)):
            self.field_type.addItem(label, value)
        self.length = QSpinBox()
        self.length.setRange(0, 255)
        self.length.setSpecialValueText("Default")
        self.precision = QSpinBox()
        self.precision.setRange(0, 30)
        form.addWidget(QLabel("Name"), 0, 0)
        form.addWidget(self.name, 0, 1, 1, 3)
        form.addWidget(QLabel("Type"), 1, 0)
        form.addWidget(self.field_type, 1, 1, 1, 3)
        form.addWidget(QLabel("Length"), 2, 0)
        form.addWidget(self.length, 2, 1)
        form.addWidget(QLabel("Decimal precision"), 2, 2)
        form.addWidget(self.precision, 2, 3)
        add = QPushButton("Add to fields list")
        add.setObjectName("primary")
        add.clicked.connect(self.add_to_list)
        form.addWidget(add, 3, 1, 1, 3)
        layout.addWidget(group)
        listing = QGroupBox("Fields list")
        list_layout = QVBoxLayout(listing)
        self.fields_list = QTableWidget(0, 4)
        self.fields_list.setHorizontalHeaderLabels(["Name", "Type", "Length", "Precision"])
        self.fields_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fields_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.fields_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fields_list.verticalHeader().hide()
        self.fields_list.horizontalHeader().setStretchLastSection(True)
        list_row = QHBoxLayout()
        list_row.addWidget(self.fields_list, 1)
        order_buttons = QVBoxLayout()
        up = QPushButton("↑")
        up.setToolTip("Move field up")
        up.clicked.connect(lambda: self.move_selected(-1))
        down = QPushButton("↓")
        down.setToolTip("Move field down")
        down.clicked.connect(lambda: self.move_selected(1))
        order_buttons.addWidget(up)
        order_buttons.addWidget(down)
        order_buttons.addStretch(1)
        list_row.addLayout(order_buttons)
        list_layout.addLayout(list_row)
        remove = QPushButton("Remove selected field")
        remove.clicked.connect(self.remove_selected)
        list_layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(listing, 1)
        self.field_type.currentIndexChanged.connect(self.update_type)
        self.update_type()
        note = QLabel("Each field starts empty. Save edits to commit.")
        note.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(note, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add Fields")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    def current_spec(self):
        return (self.name.text().strip(), self.field_type.currentData(),
                self.length.value() if self.length.isEnabled() else 0,
                self.precision.value() if self.precision.isEnabled() else 0)

    def field_specs(self):
        current = self.current_spec()
        return self.queued + ([current] if current[0] else [])

    def add_to_list(self):
        spec = self.current_spec()
        if not spec[0]:
            self.name.setFocus()
            return
        self.queued.append(spec)
        row = self.fields_list.rowCount()
        self.fields_list.insertRow(row)
        for col, text in enumerate((spec[0], self.field_type.currentText(), str(spec[2]) if spec[2] else "Default", str(spec[3]))):
            self.fields_list.setItem(row, col, QTableWidgetItem(text))
        self.name.clear()
        self.name.setFocus()

    def remove_selected(self):
        row = self.fields_list.currentRow()
        if row >= 0:
            self.queued.pop(row)
            self.fields_list.removeRow(row)

    def move_selected(self, direction):
        row = self.fields_list.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= len(self.queued):
            return
        self.queued[row], self.queued[target] = self.queued[target], self.queued[row]
        for column in range(self.fields_list.columnCount()):
            first = self.fields_list.takeItem(row, column)
            second = self.fields_list.takeItem(target, column)
            self.fields_list.setItem(row, column, second)
            self.fields_list.setItem(target, column, first)
        self.fields_list.selectRow(target)

    def update_type(self):
        kind = self.field_type.currentData()
        self.length.setEnabled(kind in (QMetaType.Type.QString, QMetaType.Type.Int, QMetaType.Type.LongLong, QMetaType.Type.Double))
        self.precision.setEnabled(kind == QMetaType.Type.Double)


class DeleteFieldsDialog(QDialog):
    def __init__(self, parent, names):
        super().__init__(parent)
        self.setWindowTitle("Delete fields")
        self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select fields to delete:"))
        self.list = QListWidget()
        for name in names:
            item = QListWidgetItem(name, self.list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        layout.addWidget(self.list)
        layout.addWidget(QLabel("Check the fields you want to delete."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continue")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_names(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class BulkEditDialog(QDialog):
    """Choose a field and value and review the changes in a single window."""

    def __init__(self, parent, layer, field_names, fids):
        super().__init__(parent)
        self.setWindowTitle("Bulk edit")
        self.setStyleSheet(parent.styleSheet())
        self.resize(480, 350)
        self.layer = layer
        self.fids = fids
        request = QgsFeatureRequest().setFilterFids(fids)
        self.features = {feature.id(): feature for feature in layer.getFeatures(request)}
        self.value = None
        self.original_values = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Change {} selected row(s) on this page".format(len(fids))))
        form = QFormLayout()
        self.field = QComboBox()
        self.field.addItems(field_names)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Enter a value; text spaces are preserved")
        self.set_null = QCheckBox("Set NULL")
        self.set_null.toggled.connect(lambda checked: self.input.setEnabled(not checked))
        form.addRow("Column", self.field)
        form.addRow("New value", self.input)
        form.addRow(self.set_null)
        layout.addLayout(form)
        layout.addWidget(QLabel("Preview (first 10 rows)"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        dark_palette(self.preview, parent.theme)
        layout.addWidget(self.preview)
        self.hint = QLabel("Changes are undoable and remain unsaved until Save edits.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Apply changes")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.field.currentIndexChanged.connect(self.update_preview)
        self.input.textChanged.connect(self.update_preview)
        self.set_null.toggled.connect(self.update_preview)
        self.update_preview()

    def update_preview(self):
        index = self.layer.fields().indexFromName(self.field.currentText())
        try:
            if index < 0:
                raise ValueError("The selected field is no longer available.")
            value = FinderDialog.convert(self.layer.fields()[index], None if self.set_null.isChecked() else self.input.text())
            if len(self.features) != len(self.fids):
                raise ValueError("Some selected features are no longer available.")
            self.value = value
            self.original_values = {fid: self.features[fid][index] for fid in self.fids}

            def display(value):
                return "NULL" if value is None or value == NULL else str(value)

            lines = ["{}: {} → {}".format(fid, display(self.original_values[fid]), display(value))
                     for fid in self.fids[:10]]
            if len(self.fids) > 10:
                lines.append("… and {} more".format(len(self.fids) - 10))
            self.preview.setPlainText("\n".join(lines))
            self.hint.setText("Changes are undoable and remain unsaved until Save edits.")
            self.apply_button.setEnabled(True)
        except (ValueError, OverflowError) as exc:
            self.preview.clear()
            self.hint.setText("Invalid value: {}".format(exc))
            self.apply_button.setEnabled(False)


class AutofillDialog(QDialog):
    def __init__(self, parent, field_names, selected_count, page_count):
        super().__init__(parent)
        self.setWindowTitle("Autofill")
        self.setStyleSheet(parent.styleSheet())
        self.resize(420, 260)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Values follow the current table order."))
        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem("Selected rows on this page ({})".format(selected_count), "selected")
        self.scope.addItem("Entire column on this page ({})".format(page_count), "page")
        if not selected_count:
            self.scope.setCurrentIndex(1)
        self.field = QComboBox()
        self.field.addItems(field_names)
        self.mode = QComboBox()
        self.mode.addItem("Same value", "same")
        self.mode.addItem("Number sequence", "sequence")
        self.mode.addItem("Repeat values", "repeat")
        self.mode.addItem("Set NULL", "null")
        self.values = QPlainTextEdit()
        dark_palette(self.values, parent.theme)
        palette = self.values.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(THEMES[parent.theme]["muted"]))
        self.values.setPalette(palette)
        self.step = QLineEdit("1")
        self.step.setPlaceholderText("e.g. 1")
        self.step_label = QLabel("Step")
        form.addRow("Column", self.field)
        form.addRow("Fill", self.scope)
        form.addRow("Pattern", self.mode)
        form.addRow("Value(s)", self.values)
        form.addRow(self.step_label, self.step)
        layout.addLayout(form)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Preview…")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self.update_mode)
        self.update_mode()

    def update_mode(self):
        mode = self.mode.currentData()
        self.values.setFixedHeight(72 if mode == "repeat" else 40)
        self.step.setVisible(mode == "sequence")
        self.step_label.setVisible(mode == "sequence")
        self.values.setEnabled(mode != "null")
        self.hint.setText({"null": "Set every target value to NULL.",
                           "same": "Enter one value. Empty text and spaces are preserved.",
                           "sequence": "Enter the starting number and step; numeric fields only.",
                           "repeat": "Enter one value per line. Values repeat in order."}[mode])
        self.values.setPlaceholderText({"null": "", "same": "e.g. Residential", "sequence": "e.g. 1",
                                        "repeat": "e.g. Residential\nCommercial"}[mode])


class FinderDialog(QDialog):
    def __init__(self, iface):
        super().__init__(None)  # no parent: the window gets its own taskbar button
        self.iface = iface
        self.setWindowTitle("QuickTable")
        raw = str(QSettings().value("LayerFilter/pinned", QSettings().value("ParcelFinder/pinned", "true"))).lower()
        self.pinned = raw in ("true", "1")
        self.setWindowIcon(plugin_icon())
        self.apply_flags()
        self.setModal(False)  # True = blocks the map while open
        self.resize(1040, 620)
        self.fields = []
        self.sort_field = None
        self.sort_order = Qt.SortOrder.AscendingOrder
        self.column_delegates = {}
        self.applying_column_layout = False
        self.layout_settings_key = None
        self.layout_fields = []
        self.pending_column_widths = {}
        self.filter_rows = []
        self.filters_ready = False
        self.pending_cascade_start = None
        self.table_layer_id = None
        self.result_key = None
        self.result_ids = None
        self.query_task = None
        self.csv_task = None
        self.query_version = 0
        self.page = 0
        self.pending_selection = set()
        self.syncing_map_selection = False
        self.selected_scope_ids = None
        self.nearby_scope_ids = None
        self.nearby_task = None
        self.nearby_version = 0
        self.nearby_description = None
        self.statistics_task = None
        self.statistics_version = 0
        self.statistics_key = None
        self.pending_notice = None
        self.pending_added_field = None
        self.hooked_layer = None
        self.hooked_id = None
        self.hooked_undo_stack = None
        self.watched_layer_validity = {}
        self.own_edit = False
        self.edit_failure = None
        saved = str(QSettings().value("LayerFilter/theme", QSettings().value("ParcelFinder/theme", "light")))
        self.theme = saved if saved in THEMES else "light"
        families = set(QFontDatabase().families())
        default_family = next((name for name in ("JetBrains Mono", "Cascadia Mono", "SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono")
                               if name in families), QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family())
        saved_family = str(QSettings().value("LayerFilter/fontFamily", default_family))
        self.font_family = saved_family if saved_family in families else default_family
        try:
            self.font_size = max(8, min(24, int(QSettings().value("LayerFilter/fontSize", 9))))
        except (TypeError, ValueError, OverflowError):
            self.font_size = 9

        # waits a moment after edits so many changes cause one refresh
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.soft_refresh)
        self.column_layout_timer = QTimer(self)
        self.column_layout_timer.setSingleShot(True)
        self.column_layout_timer.setInterval(120)
        self.column_layout_timer.timeout.connect(self.save_column_widths)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.run_search)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(250)
        self.filter_timer.timeout.connect(self.refresh_dependent_values)
        self.selection_filter_timer = QTimer(self)
        self.selection_filter_timer.setSingleShot(True)
        self.selection_filter_timer.setInterval(100)
        self.selection_filter_timer.timeout.connect(self.run_search)
        self.statistics_refresh_timer = QTimer(self)
        self.statistics_refresh_timer.setSingleShot(True)
        self.statistics_refresh_timer.setInterval(120)
        self.statistics_refresh_timer.timeout.connect(self.refresh_statistics)
        self.layer_list_timer = QTimer(self)
        self.layer_list_timer.setSingleShot(True)
        self.layer_list_timer.setInterval(100)
        self.layer_list_timer.timeout.connect(self.refresh_available_layers)
        self.value_tasks = {}
        self.value_versions = {}
        self.closing = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self.btn_settings = QPushButton("Settings")
        self.btn_settings.setObjectName("theme")
        self.btn_settings.setToolTip("Choose font, text size, theme and window pinning")
        self.btn_toolbar = QPushButton()
        self.btn_toolbar.setCheckable(True)
        self.btn_toolbar.setToolTip("Show or hide selection and editing tools")
        self.btn_statistics = QPushButton("Statistics")
        self.btn_statistics.setObjectName("statsToggle")
        self.btn_statistics.setCheckable(True)
        self.btn_statistics.setToolTip("Show statistics for all visible columns across filtered results")

        card = QFrame()
        card.setObjectName("card")
        clay = QGridLayout(card)
        clay.setContentsMargins(0, 0, 0, 0)
        clay.setHorizontalSpacing(8)
        clay.setVerticalSpacing(6)
        clay.setColumnStretch(1, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.layer = QComboBox()
        self.layer.setObjectName("layerPicker")
        self.layer.setMinimumWidth(180)
        self.layer.setMaximumWidth(320)
        row.addWidget(self.layer, 1)
        self.btn_refresh = QPushButton("Refresh lists")
        row.addWidget(self.btn_refresh)
        self.btn_saved_filters = QPushButton("Saved filters")
        self.edit = QLineEdit()
        self.edit.setObjectName("globalSearch")
        self.edit.setPlaceholderText("Search all attributes…")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumWidth(180)
        self.edit.setMaximumWidth(360)
        row.addWidget(self.edit, 1)
        self.btn_clear_filters = QPushButton("Clear filters")
        self.btn_clear_filters.setToolTip("Clear column filters, search, selected-only and nearby views; keep the map selection")
        row.addWidget(self.btn_clear_filters)
        row.addWidget(self.btn_saved_filters)
        row.addStretch(1)
        row.addWidget(self.btn_statistics)
        row.addWidget(self.btn_toolbar)
        row.addWidget(self.btn_settings)
        clay.addWidget(self.field_label("Layer"), 0, 0)
        clay.addLayout(row, 0, 1)
        lay.addWidget(card)

        self.selection_tools = QFrame()
        tools = QHBoxLayout(self.selection_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(6)
        self.btn_columns = QPushButton("Columns…")
        self.btn_select = QPushButton("Select all")
        self.btn_unselect = QPushButton("Unselect")
        self.btn_delete = QPushButton("Delete selected")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.setAutoDefault(False)
        self.btn_delete.setEnabled(False)
        self.multi_cb = QCheckBox("Multi-select")
        self.selected_only_cb = QCheckBox("Selected only")
        self.selected_only_cb.setToolTip("Show the current QGIS selection, updating when the selection changes")
        self.multi_cb.setToolTip("Click rows to toggle selection without holding Ctrl. Turn off to use Ctrl/Shift selection.")
        self.selection_status = QLabel("0 selected")
        self.btn_select.setToolTip("Select all rows on the current page, on the table and map")
        self.btn_unselect.setToolTip("Clear the table selection and the selected layer's map selection")
        self.btn_bulk = QPushButton("Bulk edit…")
        self.btn_autofill = QPushButton("Autofill…")
        self.btn_fields = QPushButton("Fields ▾")
        self.btn_fields.setObjectName("fieldsButton")
        self.fields_menu = QMenu(self.btn_fields)
        self.btn_add_field = self.fields_menu.addAction("Add field…")
        self.btn_delete_field = self.fields_menu.addAction("Delete field…")
        self.btn_fields.setToolTip("Add or delete a layer attribute")
        self.btn_nearby = QPushButton("Nearby…")
        self.btn_nearby.setToolTip("Find features touching or within a distance of the current map selection")
        for widget in (self.btn_columns, self.btn_select, self.btn_unselect, self.btn_nearby):
            tools.addWidget(widget)
        tools.addWidget(self.multi_cb)
        tools.addWidget(self.selected_only_cb)
        tools.addStretch(1)
        tools.addWidget(self.selection_status)
        clay.addWidget(self.selection_tools, 1, 0, 1, 2)

        self.table = QTableWidget()
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.horizontalScrollBar().setSingleStep(20)
        self.table.setHorizontalHeader(FilterHeader(Qt.Orientation.Horizontal, self.table))
        self.table.setWordWrap(True)
        self.table.horizontalHeader().filterRequested.connect(self.open_column_filter)
        self.table.horizontalHeader().sortRequested.connect(self.sort_header_column)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setToolTip("Click a row to select it. Ctrl-click adds/removes rows; Shift-click selects a range.")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setToolTip("Click a column name to sort; click its filter below for filtering and column options. Drag a border to resize.")
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(True)
        self.table.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.verticalHeader().setDefaultSectionSize(23)
        self.table.verticalHeader().setToolTip("Row number in the current filtered and sorted results")
        corner = self.table.findChild(QAbstractButton, "qt_tableview_cornerbutton")
        if corner is not None:
            corner_layout = QHBoxLayout(corner)
            corner_layout.setContentsMargins(0, 0, 0, 0)
            corner_label = QLabel("#", corner)
            corner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            corner_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            corner_layout.addWidget(corner_label)
        self.table.setProperty("editing", "false")
        self.statistics_strip = StatisticsStrip(self.table, self)
        lay.addWidget(self.statistics_strip)
        lay.addWidget(self.table)

        pager = QHBoxLayout()
        pager.addWidget(QLabel("Rows per page"))
        self.page_size = QComboBox()
        for size in PAGE_SIZES:
            self.page_size.addItem(str(size) if size else "All results", size)
        saved_size = normalize_page_size(QSettings().value("LayerFilter/pageSize", 500))
        self.page_size.setCurrentIndex(self.page_size.findData(saved_size))
        self.page_size.setToolTip("All results disables paging for smaller result sets. Large results stay paginated; use Export CSV for the full result set.")
        pager.addWidget(self.page_size)
        pager.addStretch(1)
        self.page_status = QLabel("0 results")
        self.btn_previous = QPushButton("Previous")
        self.btn_next = QPushButton("Next")
        self.btn_previous.setEnabled(False)
        self.btn_next.setEnabled(False)
        pager.addWidget(self.page_status)
        pager.addWidget(self.btn_previous)
        pager.addWidget(self.btn_next)
        lay.addLayout(pager)

        self.edit_tools = QFrame()
        erow = QHBoxLayout(self.edit_tools)
        erow.setContentsMargins(0, 0, 0, 0)
        erow.setSpacing(6)
        self.edit_status = QLabel("No layer")
        self.edit_cb = QCheckBox("Edit mode")
        self.edit_cb.setToolTip("Enable editing, then double-click a cell to change it")
        self.btn_undo = QPushButton("Undo")
        self.btn_redo = QPushButton("Redo")
        self.btn_save = QPushButton("Save edits")
        self.btn_discard = QPushButton("Discard edits")
        self.btn_save.setEnabled(False)
        self.btn_discard.setEnabled(False)
        erow.addWidget(self.edit_cb)
        erow.addWidget(self.edit_status)
        erow.addWidget(self.btn_undo)
        erow.addWidget(self.btn_redo)
        erow.addWidget(self.btn_bulk)
        erow.addWidget(self.btn_autofill)
        erow.addWidget(self.btn_fields)
        erow.addWidget(self.btn_delete)
        erow.addStretch(1)
        clay.addWidget(self.edit_tools, 2, 0, 1, 2)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("status")
        bottom.addWidget(self.status, 1)
        self.btn_zoom = QPushButton("Zoom to all")
        self.btn_copy = QPushButton("Copy (for Excel)")
        self.btn_csv = QPushButton("Export CSV")
        for button in (self.btn_copy, self.btn_csv):
            button.setToolTip("Copy/export selected rows, or all displayed rows, using visible columns. Formula-like text receives an apostrophe.")
        for button, label, tooltip in (
                (self.btn_settings, "Settings", "Settings: font, theme and window pinning"),
                (self.btn_refresh, "Refresh lists", "Refresh layer data and filter choices"),
                (self.btn_undo, "Undo", "Undo the last edit"),
                (self.btn_redo, "Redo", "Redo the last undone edit"),
                (self.btn_copy, "Copy rows", "Copy selected rows, or the current page, for Excel"),
                (self.btn_csv, "Export CSV", "Export selected rows, the current page, or all filtered results to CSV")):
            button.setText("Settings" if button is self.btn_settings else "")
            button.setAccessibleName(label)
            button.setToolTip(tooltip)
            button.setIconSize(QSize(18, 18))
        tools.insertWidget(tools.count() - 2, self.btn_zoom)
        for b in (self.btn_copy, self.btn_csv):
            erow.addWidget(b)
        erow.addWidget(self.btn_discard)
        erow.addWidget(self.btn_save)
        lay.addLayout(bottom)

        self.btn_save.setObjectName("primary")
        self.btn_discard.setObjectName("danger")
        for b in self.findChildren(QPushButton):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self.show_settings)
        self.btn_statistics.toggled.connect(self.set_statistics_visible)
        show_statistics = str(QSettings().value("LayerFilter/statisticsVisible", "false")).lower() in ("true", "1")
        self.btn_statistics.setChecked(show_statistics)
        self.set_statistics_visible(show_statistics)
        self.btn_toolbar.toggled.connect(self.set_toolbar_visible)
        show_toolbar = str(QSettings().value("LayerFilter/toolbarVisible", "true")).lower() in ("true", "1")
        self.btn_toolbar.setChecked(show_toolbar)
        self.set_toolbar_visible(show_toolbar)
        self.apply_theme()

        self.layer.currentIndexChanged.connect(self.on_layer_changed)
        self.filters_ready = True
        self.edit.textChanged.connect(self.schedule_search)
        self.page_size.currentIndexChanged.connect(self.on_page_size_changed)
        self.btn_previous.clicked.connect(lambda: self.change_page(-1))
        self.btn_next.clicked.connect(lambda: self.change_page(1))
        self.btn_refresh.clicked.connect(self.soft_refresh)
        self.table.itemSelectionChanged.connect(self.on_row_selection)
        self.table.horizontalHeader().sectionResized.connect(self.on_column_resized)
        self.table.horizontalHeader().geometriesChanged.connect(self.schedule_statistics_refresh)
        self.btn_zoom.clicked.connect(self.zoom_all)
        self.btn_select.clicked.connect(self.select_all)
        self.btn_unselect.clicked.connect(self.unselect_all)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_columns.clicked.connect(self.choose_columns)
        self.btn_bulk.clicked.connect(self.bulk_edit)
        self.btn_autofill.clicked.connect(self.autofill)
        self.btn_add_field.triggered.connect(self.add_field)
        self.btn_delete_field.triggered.connect(self.delete_field)
        self.btn_fields.clicked.connect(lambda: self.fields_menu.popup(
            self.btn_fields.mapToGlobal(QPoint(0, self.btn_fields.height()))))
        self.btn_nearby.clicked.connect(self.nearby_menu)
        self.selected_only_cb.toggled.connect(self.set_selected_scope)
        self.btn_saved_filters.clicked.connect(self.saved_filters_menu)
        self.btn_clear_filters.clicked.connect(self.clear_filters)
        self.multi_cb.toggled.connect(self.set_multi_selection)
        self.btn_copy.clicked.connect(self.copy_rows)
        self.btn_csv.clicked.connect(self.export_csv)
        self.edit_cb.toggled.connect(self.on_edit_toggled)
        self.table.model().dataChanged.connect(self.on_table_data_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.cell_context_menu)
        self.btn_save.clicked.connect(self.save_edits)
        self.btn_discard.clicked.connect(self.discard_edits)
        self.btn_undo.clicked.connect(lambda: self.change_undo_stack(False))
        self.btn_redo.clicked.connect(lambda: self.change_undo_stack(True))

        # Keep the chosen layer while tracking project layer availability.
        QgsProject.instance().layersAdded.connect(self.on_layers_changed)
        QgsProject.instance().layersRemoved.connect(self.on_layers_changed)

    def apply_flags(self):
        flags = (Qt.WindowType.Window | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowSystemMenuHint |
                 Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowMaximizeButtonHint |
                 Qt.WindowType.WindowCloseButtonHint)
        if self.pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    @staticmethod
    def toolbar_separator():
        separator = QFrame()
        separator.setObjectName("toolSeparator")
        separator.setFixedSize(1, 22)
        return separator

    def set_toolbar_visible(self, visible):
        for widget in (self.selection_tools, self.edit_tools):
            widget.setVisible(visible)
        self.btn_toolbar.setText("Tools ▴" if visible else "Tools ▾")
        self.btn_toolbar.setAccessibleName("Hide tools" if visible else "Show tools")
        QSettings().setValue("LayerFilter/toolbarVisible", visible)

    def cancel_statistics(self):
        self.statistics_version += 1
        task = self.statistics_task
        self.statistics_task = None
        if task is not None:
            task.cancel()
        self.statistics_key = None

    def set_statistics_visible(self, visible):
        self.statistics_strip.setVisible(visible)
        QSettings().setValue("LayerFilter/statisticsVisible", visible)
        if visible:
            self.refresh_statistics()
        else:
            self.statistics_refresh_timer.stop()
            self.cancel_statistics()

    def schedule_statistics_refresh(self, *args):
        if self.btn_statistics.isChecked() and not self.closing:
            self.statistics_refresh_timer.start()

    def refresh_statistics(self):
        if self.closing or not self.btn_statistics.isChecked():
            return
        layer = self.current_layer()
        if layer is None:
            self.cancel_statistics()
            self.statistics_strip.set_state("empty", message="Choose a layer")
            return
        if self.result_ids is None or self.table.columnCount() != len(self.fields):
            self.cancel_statistics()
            self.statistics_strip.set_state("loading", message="Waiting for results…")
            return
        columns = [(index, field_kind(layer.fields()[index]) in ("integer", "number"))
                   for index in range(len(self.fields)) if not self.table.isColumnHidden(index)]
        key = (layer.id(), self.query_version, tuple(columns))
        if key == self.statistics_key:
            self.statistics_strip.update()
            return
        self.cancel_statistics()
        self.statistics_key = key
        self.statistics_strip.set_state("loading", message="Calculating…")
        version = self.statistics_version
        ids = self.result_ids

        def finished(exception, result=None):
            if self.closing or version != self.statistics_version or not self.btn_statistics.isChecked():
                return
            self.statistics_task = None
            if key != self.statistics_key or self.result_ids is not ids:
                return
            if exception is not None:
                self.statistics_key = None
                self.statistics_strip.set_state("error", message="Statistics failed: {}".format(exception))
            elif result is None:
                self.statistics_key = None
                self.statistics_strip.set_state("error", message="Statistics canceled")
            else:
                self.statistics_strip.set_state("ready", summaries=result["summaries"])

        try:
            task = QgsTask.fromFunction("QuickTable: column statistics", collect_column_statistics,
                                        source=QgsVectorLayerFeatureSource(layer), columns=columns,
                                        ids=ids, on_finished=finished)
            task.setDependentLayers([layer])
            self.statistics_task = task
            QgsApplication.taskManager().addTask(task)
        except Exception as exc:
            self.statistics_key = None
            self.statistics_task = None
            self.statistics_strip.set_state("error", message="Statistics failed: {}".format(exc))

    def apply_theme(self):
        self.setFont(QFont(self.font_family, self.font_size))
        self.setStyleSheet(build_css(self.theme, self.font_family, self.font_size))
        for button, name in ((self.btn_settings, "settings"), (self.btn_refresh, "refresh"),
                             (self.btn_undo, "undo"), (self.btn_redo, "redo"),
                             (self.btn_copy, "copy"), (self.btn_csv, "export"),
                             (self.btn_columns, "columns"), (self.btn_select, "select"),
                             (self.btn_nearby, "nearby"), (self.btn_fields, "fields")):
            button.setIcon(toolbar_icon(name, THEMES[self.theme]["text"]))
            button.setIconSize(QSize(16, 16))
        self.btn_save.setIcon(toolbar_icon("save", THEMES[self.theme]["accent"]))
        self.btn_save.setIconSize(QSize(16, 16))
        self.btn_add_field.setIcon(toolbar_icon("fieldAdd", THEMES[self.theme]["text"]))
        self.btn_delete_field.setIcon(toolbar_icon("fieldDelete", THEMES[self.theme]["text"]))
        for cb in self.findChildren(QComboBox):
            style_combo_popup(cb, self.theme, self.font_family, self.font_size)
        for row in self.filter_rows:
            row.value.popup_background = THEMES[self.theme]["surface"]
            row.value.popup_border = THEMES[self.theme]["border"]
        font = QFont(self.font_family, self.font_size)
        metrics = QFontMetrics(font)
        self.table.setFont(font)
        self.statistics_strip.setFont(font)
        self.statistics_strip.background = THEMES[self.theme]["surface"]
        self.statistics_strip.border = THEMES[self.theme]["border"]
        self.statistics_strip.foreground = THEMES[self.theme]["text_soft"]
        self.statistics_strip.card_background = THEMES[self.theme]["surface"]
        self.statistics_strip.accent = THEMES[self.theme]["accent"]
        self.statistics_strip.title_color = THEMES[self.theme]["text"]
        self.statistics_strip.background = THEMES[self.theme]["bg"]
        self.statistics_strip.update_height()
        self.table.horizontalHeader().setFont(font)
        self.table.verticalHeader().setDefaultSectionSize(max(23, metrics.height() + 10))
        self.apply_column_layout()
        for label in self.findChildren(QLabel):
            if label.objectName() == "fieldlabel":
                label.setFixedWidth(max(66, metrics.horizontalAdvance("Selection") + 12))
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(max(90, metrics.horizontalAdvance("Filter…") + 36))
        header.icon_color = THEMES[self.theme]["muted"]
        header.active_color = THEMES[self.theme]["accent"]
        header.active_background = THEMES[self.theme]["sel_bg"]
        header.filter_background = THEMES[self.theme]["surface"]
        header.filter_border = THEMES[self.theme]["border"]
        header.updateGeometry()
        header.viewport().update()
        for row in self.filter_rows:
            row.widget.setFont(font)
            row.widget.setStyleSheet(self.styleSheet())
        self.update_filter_rows_layout()
        self.sync_edit_state()

    def show_settings(self):
        dialog = SettingsDialog(self, self.font_family, self.font_size, self.theme, self.pinned)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pin_changed = self.pinned != dialog.pin_cb.isChecked()
            self.font_family = dialog.font_picker.currentFont().family()
            self.font_size = dialog.font_size_spin.value()
            self.theme = dialog.theme_picker.currentData()
            self.pinned = dialog.pin_cb.isChecked()
            settings = QSettings()
            settings.setValue("LayerFilter/fontFamily", self.font_family)
            settings.setValue("LayerFilter/fontSize", self.font_size)
            settings.setValue("LayerFilter/theme", self.theme)
            settings.setValue("LayerFilter/pinned", "true" if self.pinned else "false")
            self.apply_theme()
            if pin_changed:
                was_visible = self.isVisible()
                state = self.windowState()
                self.apply_flags()  # Changing Qt window flags hides the window.
                self.setWindowState(state)
                if was_visible:
                    self.show()
                    self.raise_()
        dialog.deleteLater()

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        QSettings().setValue("LayerFilter/theme", self.theme)
        self.apply_theme()

    @staticmethod
    def field_label(text):
        lb = QLabel(text)
        lb.setObjectName("fieldlabel")
        lb.setFixedWidth(66)
        return lb

    def add_filter_row(self, *args):
        widget = QFrame(self, Qt.WindowType.Popup)
        widget.setObjectName("fieldFilterPopup")
        widget.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, True)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        label = QLabel("Filter")
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)
        ascending = QPushButton("Ascending")
        descending = QPushButton("Descending")
        for button in (ascending, descending):
            button.setObjectName("sortOption")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setParent(widget)
            button.hide()
        wrap_text = QCheckBox("Wrap text")
        wrap_text.setToolTip("Wrap this column's cells. Drag its border to choose the width; filtering keeps this setting.")
        layout.addWidget(wrap_text)
        number_controls = QFrame()
        number_layout = QHBoxLayout(number_controls)
        number_layout.setContentsMargins(0, 0, 0, 0)
        number_layout.addWidget(QLabel("Number display"))
        number_format = QComboBox()
        for option_label, option_value in (("Original", "original"), ("Hide trailing zeros", "trim"),
                             ("Whole numbers (rounded)", "whole"), ("1 decimal place", "1"),
                             ("2 decimal places", "2"), ("3 decimal places", "3")):
            number_format.addItem(option_label, option_value)
        number_format.setToolTip("Display only. Rounded formats do not change stored values; editing uses the original value.")
        number_layout.addWidget(number_format, 1)
        layout.addWidget(number_controls)
        field = QComboBox(widget)
        field.hide()  # The column/chip chooses the field; keep the existing filter model.
        operator = QComboBox()
        operator.addItems(FILTER_OPERATORS)
        condition = QHBoxLayout()
        condition.addWidget(QLabel("Condition"))
        condition.addWidget(operator, 1)
        layout.addLayout(condition)
        value = CheckableValueCombo()
        layout.addWidget(value)
        upper = QLineEdit()
        upper.setPlaceholderText("To (inclusive)")
        upper.hide()
        layout.addWidget(upper)
        choices = ValuePopup(value, embedded=True)
        choices.done_button.hide()
        choices.list.setMinimumHeight(100)
        choices.list.setMaximumHeight(260)
        layout.addWidget(choices)
        footer = QHBoxLayout()
        remove = QPushButton("Clear filter")
        remove.setAutoDefault(False)
        remove.setObjectName("danger")
        done = QPushButton("Done")
        done.setAutoDefault(False)
        done.clicked.connect(widget.hide)
        footer.addWidget(remove)
        footer.addStretch(1)
        footer.addWidget(done)
        layout.addLayout(footer)
        row = SimpleNamespace(widget=widget, label=label, field=field, operator=operator,
                              value=value, upper=upper, remove=remove, choices=choices,
                              ascending=ascending, descending=descending, wrap_text=wrap_text,
                              number_controls=number_controls, number_format=number_format)
        wrap_text.toggled.connect(lambda checked: self.set_column_wrap(row.field.currentText(), checked))
        number_format.currentIndexChanged.connect(lambda *args: self.set_number_format(row.field.currentText(), number_format.currentData()))
        ascending.clicked.connect(lambda: self.sort_filter_column(row, Qt.SortOrder.AscendingOrder))
        descending.clicked.connect(lambda: self.sort_filter_column(row, Qt.SortOrder.DescendingOrder))
        self.filter_rows.append(row)
        field.currentIndexChanged.connect(lambda *args, row=row: self.on_filter_field_changed(row))
        operator.currentIndexChanged.connect(lambda *args, row=row: self.on_filter_operator_changed(row))
        value.currentTextChanged.connect(lambda *args, row=row: self.queue_filter_change(row))
        value.checkedValuesChanged.connect(lambda row=row: self.queue_filter_change(row))
        upper.textChanged.connect(lambda *args, row=row: self.queue_filter_change(row))
        remove.clicked.connect(lambda *args, row=row: self.remove_filter_row(row))
        if self.filters_ready:
            self.populate_filter_field(row)
            self.sync_filter_inputs()
            self.fill_values(field, value, self.other_filters_expr(row))
        self.update_filter_rows_layout()
        return row

    def open_column_filter(self, column):
        if column < 0 or column >= len(self.fields):
            return
        header = self.table.horizontalHeader()
        position = header.viewport().mapToGlobal(QPoint(header.sectionViewportPosition(column), header.height()))
        self.open_field_filter(self.fields[column], position)

    def open_field_filter(self, name, position=None):
        if name not in self.fields:
            return
        row = next((row for row in self.filter_rows if row.field.currentText() == name), None)
        if row is None:
            row = self.add_filter_row()
            row.field.setCurrentText(name)
        self.show_filter_popup(row, position)

    def show_filter_popup(self, row, position=None):
        if row not in self.filter_rows:
            return
        self.sync_filter_inputs()
        header = self.table.horizontalHeader()
        column = self.fields.index(row.field.currentText()) if row.field.currentText() in self.fields else -1
        sorted_here = bool(self.sort_field and self.sort_field == row.field.currentText())
        order = self.sort_order if self.sort_field else header.sortIndicatorOrder()
        row.ascending.setChecked(sorted_here and order == Qt.SortOrder.AscendingOrder)
        row.descending.setChecked(sorted_here and order == Qt.SortOrder.DescendingOrder)
        blocked = row.wrap_text.blockSignals(True)
        row.wrap_text.setChecked(row.field.currentText() in self.wrapped_fields())
        row.wrap_text.blockSignals(blocked)
        layer = self.current_layer()
        field = layer.fields().field(row.field.currentText()) if layer and column >= 0 else None
        row.number_controls.setVisible(field_kind(field) in ("integer", "number"))
        blocked = row.number_format.blockSignals(True)
        row.number_format.setCurrentIndex(max(0, row.number_format.findData(self.number_formats().get(row.field.currentText(), "original"))))
        row.number_format.blockSignals(blocked)
        row.widget.setFont(QFont(self.font_family, self.font_size))
        row.widget.setStyleSheet(self.styleSheet())
        row.choices.refresh_choices()
        if position is None:
            x = header.sectionViewportPosition(column) if column >= 0 else 0
            position = header.viewport().mapToGlobal(QPoint(x, header.height()))
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        row.choices.list.setMaximumHeight(max(100, min(260, available.height() - 260)))
        row.widget.layout().activate()
        row.widget.adjustSize()
        width = min(max(420, row.widget.sizeHint().width()), available.width() - 16)
        height = min(row.widget.sizeHint().height(), available.height() - 16)
        row.widget.resize(width, height)
        x = max(available.left() + 8, min(position.x(), available.right() - width - 8))
        y = max(available.top() + 8, min(position.y(), available.bottom() - height - 8))
        row.widget.move(x, y)
        row.widget.show()
        if row.operator.currentText() == "Equals":
            row.choices.search.setFocus(Qt.FocusReason.PopupFocusReason)
        else:
            row.value.setFocus(Qt.FocusReason.PopupFocusReason)

    def sort_filter_column(self, row, order):
        name = row.field.currentText()
        if name in self.fields:
            self.sort_field = name
            self.sort_order = order
            self.page = 0
            self.run_search()
        row.widget.hide()

    def sort_header_column(self, column):
        if column < 0 or column >= len(self.fields):
            return
        name = self.fields[column]
        order = Qt.SortOrder.DescendingOrder if self.sort_field == name and self.sort_order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        self.sort_field = name
        self.sort_order = order
        self.page = 0
        self.run_search()


    def remove_filter_row(self, row, refresh=True):
        if row not in self.filter_rows:
            return
        index = self.filter_rows.index(row)
        task = self.value_tasks.pop(row.value, None)
        self.value_versions.pop(row.value, None)
        if task is not None:
            task.cancel()
        row.value.reset_choices()
        self.filter_rows.remove(row)
        row.widget.hide()
        row.widget.deleteLater()
        self.update_filter_rows_layout()
        if refresh:
            self.reload_value_lists()
            self.run_search()

    def clear_filter_rows(self):
        for row in list(self.filter_rows):
            self.remove_filter_row(row, refresh=False)

    def update_filter_rows_layout(self):
        active_columns = set()
        filter_labels = {}
        for row in self.filter_rows:
            name = row.field.currentText()
            row.label.setText(name)
            if name not in self.fields:
                row.remove.setEnabled(False)
                continue
            try:
                has_condition = bool(self.part_expr(row.field, row.value))
            except ValueError:
                has_condition = True
            row.remove.setEnabled(has_condition)
            if has_condition:
                column = self.fields.index(name)
                active_columns.add(column)
                operation = row.operator.currentText()
                if operation in ("Is empty", "Is not empty"):
                    label = operation
                else:
                    value = ", ".join(row.value.selected_values) if operation == "Equals" and row.value.selected_values else row.value.currentText()
                    label = "{} {}".format(operation, value)
                    if operation == "Between":
                        label += " – " + row.upper.text()
                filter_labels[column] = label
        for index in range(2):
            row = self.filter_rows[index] if index < len(self.filter_rows) else None
            for prefix, attribute in (("field", "field"), ("op", "operator"), ("value", "value"), ("upper", "upper")):
                setattr(self, prefix + str(index + 1), getattr(row, attribute) if row else None)
        if hasattr(self, "table"):
            header = self.table.horizontalHeader()
            header.filtered_columns = active_columns
            header.filter_labels = filter_labels
            header.viewport().update()

    def populate_filter_field(self, row, name=None):
        blocked = row.field.blockSignals(True)
        row.field.clear()
        row.field.addItem(NO_FIELD)
        row.field.addItems(self.fields)
        row.field.setCurrentIndex(max(row.field.findText(name or NO_FIELD, Qt.MatchFlag.MatchExactly), 0))
        row.field.blockSignals(blocked)

    def sync_filter_inputs(self):
        layer = self.current_layer()
        for row in self.filter_rows:
            active = row.field.currentText() in self.fields
            operation = row.operator.currentText()
            equals = operation == "Equals"
            row.operator.setEnabled(active)
            row.value.enable_checkboxes(equals)
            row.value.value_kind = field_kind(layer.fields().field(row.field.currentText())) if layer and active else "text"
            row.value.setVisible(not equals and operation not in ("Is empty", "Is not empty"))
            row.value.setEnabled(active)
            row.choices.setVisible(equals)
            row.upper.setVisible(operation == "Between")
            row.upper.setEnabled(active)
            row.value.lineEdit().setPlaceholderText("From (inclusive)" if operation == "Between" else "Type or choose a value")
            style_combo_popup(row.value, self.theme, self.font_family, self.font_size)
        self.update_filter_rows_layout()


    def column_settings_key(self):
        layer = self.current_layer()
        if layer is None:
            return None
        identity = QgsProject.instance().fileName() + "\0" + layer.id()
        return "LayerFilter/columns/" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def apply_column_visibility(self):
        key = self.column_settings_key()
        hidden = QSettings().value(key, []) if key else []
        if isinstance(hidden, str):
            hidden = [hidden]
        hidden = set(hidden or [])
        # Schema changes must never leave a table with no visible columns.
        if self.fields and all(name in hidden for name in self.fields):
            hidden.discard(self.fields[0])
        for column, name in enumerate(self.fields):
            self.table.setColumnHidden(column, name in hidden)
        self.btn_columns.setEnabled(bool(self.fields))

    def wrapped_fields(self):
        key = self.column_settings_key()
        values = QSettings().value(key + "/wrap", []) if key else []
        if isinstance(values, str):
            values = [values]
        return set(values or [])

    def saved_column_widths(self, key):
        if not key:
            return {}
        if key in self.pending_column_widths:
            return dict(self.pending_column_widths[key])
        try:
            widths = json.loads(str(QSettings().value(key + "/widths", "{}")))
        except (TypeError, ValueError):
            return {}
        if not isinstance(widths, dict):
            return {}
        return {name: int(width) for name, width in widths.items()
                if isinstance(width, (int, float)) and 20 <= width <= 10000}

    def on_column_resized(self, column, old_size, new_size):
        if self.applying_column_layout or not self.layout_settings_key or new_size < 20:
            return
        if column >= len(self.layout_fields) or column >= self.table.columnCount():
            return
        widths = self.saved_column_widths(self.layout_settings_key)
        widths[self.layout_fields[column]] = new_size
        self.pending_column_widths[self.layout_settings_key] = widths
        self.column_layout_timer.start()

    def save_column_widths(self):
        pending = self.pending_column_widths
        self.pending_column_widths = {}
        settings = QSettings()
        for key, widths in pending.items():
            settings.setValue(key + "/widths", json.dumps(widths))
        if not self.closing:
            self.resize_wrapped_rows()

    def fit_column_widths_to_names(self):
        key = self.column_settings_key()
        if not key:
            return
        metrics = self.table.horizontalHeader().fontMetrics()
        widths = self.saved_column_widths(key)
        for name in self.fields:
            widths[name] = max(90, metrics.horizontalAdvance(name) + 36)
        self.pending_column_widths[key] = widths
        self.apply_column_layout()
        self.column_layout_timer.start()

    def set_column_wrap(self, name, enabled):
        key = self.column_settings_key()
        if not key or name not in self.fields:
            return
        wrapped = self.wrapped_fields()
        if enabled:
            wrapped.add(name)
        else:
            wrapped.discard(name)
        QSettings().setValue(key + "/wrap", sorted(wrapped))
        widths = self.saved_column_widths(key)
        for column, field_name in enumerate(self.fields):
            if column < self.table.columnCount() and not self.table.isColumnHidden(column):
                widths[field_name] = self.table.columnWidth(column)
        self.pending_column_widths[key] = widths
        self.apply_column_layout()

    def number_formats(self):
        key = self.column_settings_key()
        try:
            result = json.loads(str(QSettings().value(key + "/numberFormats", "{}"))) if key else {}
            return result if isinstance(result, dict) else {}
        except (ValueError, TypeError):
            return {}

    def set_number_format(self, name, value):
        key = self.column_settings_key()
        if not key or name not in self.fields or value not in ("original", "trim", "whole", "1", "2", "3"):
            return
        formats = self.number_formats()
        if value == "original":
            formats.pop(name, None)
        else:
            formats[name] = value
        QSettings().setValue(key + "/numberFormats", json.dumps(formats))
        self.apply_column_layout()
        self.table.viewport().update()

    def apply_column_layout(self):
        key = self.column_settings_key()
        if not key or not self.fields or self.table.columnCount() != len(self.fields):
            return
        previous = self.applying_column_layout
        self.applying_column_layout = True
        try:
            self.layout_settings_key = key
            self.layout_fields = list(self.fields)
            widths = self.saved_column_widths(key)
            wrapped = self.wrapped_fields()
            number_formats = self.number_formats()
            visible = [column for column in range(len(self.fields)) if not self.table.isColumnHidden(column)]
            # Keep viewport expansion from being saved as an explicit field width.
            self.table.horizontalHeader().setStretchLastSection(False)
            for column, name in enumerate(self.fields):
                if name not in self.column_delegates:
                    self.column_delegates[name] = ColumnTextDelegate(self.table)
                delegate = self.column_delegates[name]
                layer = self.current_layer()
                delegate.field_kind = field_kind(layer.fields().field(name)) if layer else "text"
                delegate.number_format = number_formats.get(name, "original")
                delegate.value_map = []
                if layer:
                    setup = layer.editorWidgetSetup(column)
                    if setup.type() == "ValueMap":
                        mapping = setup.config().get("map", [])
                        if isinstance(mapping, dict):
                            mapping = [mapping]
                        if isinstance(mapping, list):
                            for entry in mapping:
                                if isinstance(entry, dict):
                                    delegate.value_map.extend((str(label), value) for label, value in entry.items()
                                                              if value is not None and value != NULL
                                                              and str(value) != "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}")
                delegate.wrapped = name in wrapped
                self.table.setItemDelegateForColumn(column, delegate)
                if name in widths:
                    self.table.setColumnWidth(column, widths[name])
                elif name in wrapped:
                    self.table.setColumnWidth(column, 280)
                else:
                    header = self.table.horizontalHeader()
                    width = header.fontMetrics().horizontalAdvance(name) + 36
                    self.table.setColumnWidth(column, max(90, width))
            self.resize_wrapped_rows()
        finally:
            self.applying_column_layout = previous

    def resize_wrapped_rows(self):
        if self.layout_settings_key != self.column_settings_key():
            return
        if self.table.columnCount() != len(self.fields):
            return
        wrapped = self.wrapped_fields()
        if any(name in wrapped and not self.table.isColumnHidden(column)
               for column, name in enumerate(self.fields)):
            self.table.resizeRowsToContents()
        else:
            height = max(23, QFontMetrics(QFont(self.font_family, self.font_size)).height() + 10)
            for row in range(self.table.rowCount()):
                self.table.setRowHeight(row, height)
        self.table.viewport().update()

    def choose_columns(self):
        if not self.fields:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Visible columns")
        dialog.setStyleSheet(self.styleSheet())
        dialog.resize(340, 440)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Choose columns to display, copy and export."))
        columns = QListWidget()
        for index, name in enumerate(self.fields):
            item = QListWidgetItem(name, columns)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if self.table.isColumnHidden(index) else Qt.CheckState.Checked)
        layout.addWidget(columns)
        show_all = QPushButton("Show all columns")
        show_all.clicked.connect(lambda: [columns.item(i).setCheckState(Qt.CheckState.Checked)
                                         for i in range(columns.count())])
        layout.addWidget(show_all)
        fit_widths = QPushButton("Fit widths to column names")
        fit_widths.setToolTip("Immediately resize all columns to fit their names")
        fit_widths.clicked.connect(self.fit_column_widths_to_names)
        layout.addWidget(fit_widths)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        layout.addWidget(buttons)

        def accept():
            if not any(columns.item(i).checkState() == Qt.CheckState.Checked for i in range(columns.count())):
                QMessageBox.information(dialog, "Visible columns", "Keep at least one column visible.")
                return
            dialog.accept()

        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            hidden = [columns.item(i).text() for i in range(columns.count())
                      if columns.item(i).checkState() != Qt.CheckState.Checked]
            key = self.column_settings_key()
            if key:
                QSettings().setValue(key, hidden)
            self.apply_column_visibility()
            self.apply_column_layout()
            self.refresh_statistics()

    def shutdown(self):
        self.closing = True
        if self.csv_task is not None:
            self.csv_task.cancel()
            self.csv_task = None
        self.layer_list_timer.stop()
        self.update_validity_watchers([])
        self.statistics_refresh_timer.stop()
        self.cancel_statistics()
        self.selection_filter_timer.stop()
        self.cancel_nearby()
        self.column_layout_timer.stop()
        self.save_column_widths()
        self.invalidate_results()
        self.search_timer.stop()
        self.filter_timer.stop()
        for task in self.value_tasks.values():
            task.cancel()
        self.value_tasks.clear()
        for sig, slot in ((QgsProject.instance().layersAdded, self.on_layers_changed),
                          (QgsProject.instance().layersRemoved, self.on_layers_changed)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self.unhook_layer()
        self.timer.stop()
        self.close()
        self.deleteLater()

    # ---------- layer list / active layer ----------
    def refresh(self):
        """Use QGIS's current vector layer only to initialize the layer choice."""
        current = self.current_layer()
        active = self.iface.activeLayer()
        prefer = current.id() if current is not None else (
            active.id() if active is not None and active.type() == QgsMapLayer.LayerType.VectorLayer and active.isValid() else None)
        self.rebuild_layer_list(prefer)
        self.edit.setFocus()

    def rebuild_layer_list(self, prefer_id=None, refresh_current=True):
        keep = prefer_id or self.layer.currentData()
        previous = self.hooked_id
        vectors = [layer for layer in QgsProject.instance().mapLayers().values()
                   if layer.type() == QgsMapLayer.LayerType.VectorLayer]
        self.update_validity_watchers(vectors)
        layers = [layer for layer in vectors if layer.isValid()]
        layers.sort(key=lambda layer: layer.name().lower())
        self.layer.blockSignals(True)
        self.layer.clear()
        for layer in layers:
            self.layer.addItem(layer.name(), layer.id())
        i = self.layer.findData(keep)
        if i < 0:
            i = 0 if self.layer.count() else -1
        self.layer.setCurrentIndex(i)
        self.layer.blockSignals(False)
        if self.layer.currentData() == previous and previous is not None:
            if refresh_current:
                self.soft_refresh()
        else:
            self.on_layer_changed()

    def update_validity_watchers(self, layers):
        current = {layer.id(): layer for layer in layers}
        for layer_id, layer in list(self.watched_layer_validity.items()):
            if layer_id not in current or current[layer_id] is not layer:
                for signal_name in ("isValidChanged", "dataSourceChanged"):
                    try:
                        getattr(layer, signal_name).disconnect(self.schedule_layer_list_refresh)
                    except (AttributeError, TypeError, RuntimeError):
                        pass
                self.watched_layer_validity.pop(layer_id, None)
        for layer_id, layer in current.items():
            if layer_id not in self.watched_layer_validity:
                for signal_name in ("isValidChanged", "dataSourceChanged"):
                    try:
                        getattr(layer, signal_name).connect(self.schedule_layer_list_refresh)
                    except (AttributeError, TypeError, RuntimeError):
                        pass
                self.watched_layer_validity[layer_id] = layer

    def schedule_layer_list_refresh(self, *args):
        if not self.closing:
            self.layer_list_timer.start()

    def refresh_available_layers(self):
        if not self.closing:
            self.rebuild_layer_list(refresh_current=False)

    def on_layers_changed(self, *args):
        if self.isVisible():
            self.rebuild_layer_list()

    def current_layer(self):
        lid = self.layer.currentData()
        layer = QgsProject.instance().mapLayer(lid) if lid else None
        return layer if layer is not None and layer.type() == QgsMapLayer.LayerType.VectorLayer and layer.isValid() else None

    def on_layer_changed(self, *args):
        self.selection_filter_timer.stop()
        self.cancel_nearby()
        self.nearby_scope_ids = None
        self.nearby_description = None
        self.btn_nearby.setText("Nearby…")
        self.selected_only_cb.blockSignals(True)
        self.selected_only_cb.setChecked(False)
        self.selected_only_cb.blockSignals(False)
        self.selected_scope_ids = None
        self.filter_timer.stop()
        self.pending_cascade_start = None
        self.search_timer.stop()
        self.hook_layer()
        self.load_fields(keep=False)

    # ---------- watch the layer for edits ----------
    def unhook_layer(self):
        if self.hooked_undo_stack is not None:
            try:
                self.hooked_undo_stack.indexChanged.disconnect(self.on_undo_stack_changed)
            except (TypeError, RuntimeError):
                pass
            self.hooked_undo_stack = None
        if self.hooked_layer is not None:
            try:
                self.hooked_layer.selectionChanged.disconnect(self.on_layer_selection_changed)
            except (TypeError, RuntimeError, AttributeError):
                pass
            for name in LAYER_SIGNALS:
                try:
                    getattr(self.hooked_layer, name).disconnect(self.schedule_refresh)
                except (TypeError, RuntimeError, AttributeError):
                    pass
        self.hooked_layer = None
        self.hooked_id = None

    def hook_layer(self):
        self.unhook_layer()
        layer = self.current_layer()
        if layer is None:
            return
        for name in LAYER_SIGNALS:
            try:
                getattr(layer, name).connect(self.schedule_refresh)
            except (TypeError, RuntimeError, AttributeError):
                pass
        self.hooked_layer = layer
        self.hooked_id = layer.id()
        layer.selectionChanged.connect(self.on_layer_selection_changed)
        self.hooked_undo_stack = layer.undoStack()
        self.hooked_undo_stack.indexChanged.connect(self.on_undo_stack_changed)

    def on_undo_stack_changed(self, *args):
        self.update_undo_buttons()
        if not self.own_edit:
            self.schedule_refresh()

    def update_undo_buttons(self):
        layer = self.current_layer()
        stack = layer.undoStack() if layer and layer.isEditable() else None
        self.btn_undo.setEnabled(bool(stack and stack.canUndo()))
        self.btn_redo.setEnabled(bool(stack and stack.canRedo()))
        self.btn_undo.setToolTip("Undo: " + stack.undoText() if stack and stack.canUndo() else "Nothing to undo")
        self.btn_redo.setToolTip("Redo: " + stack.redoText() if stack and stack.canRedo() else "Nothing to redo")

    def change_undo_stack(self, redo):
        layer = self.current_layer()
        if layer and layer.isEditable():
            stack = layer.undoStack()
            if redo and stack.canRedo():
                stack.redo()
            elif not redo and stack.canUndo():
                stack.undo()

    def schedule_refresh(self, *args):
        if self.own_edit:
            return
        self.invalidate_results()
        if self.isVisible():
            self.timer.start()

    def soft_refresh(self, *args):
        """Re-read fields and value lists, keeping the current choices if they still exist."""
        self.edit_failure = None
        self.invalidate_results()
        if self.current_layer() is None:
            self.hook_layer()
            self.load_fields(keep=False)
            return
        self.load_fields(keep=True)

    # ---------- fields and value lists ----------
    def load_fields(self, keep=False):
        layer = self.current_layer()
        self.fields = list(layer.fields().names()) if layer else []
        if not keep:
            self.clear_filter_rows()
        for row in list(self.filter_rows):
            name = row.field.currentText()
            if name not in self.fields:
                self.remove_filter_row(row, refresh=False)
                continue
            self.populate_filter_field(row, name)
        self.sync_filter_inputs()
        self.reload_value_lists()
        self.run_search()
        self.sync_edit_state()

    def reload_value_lists(self, start=0, preserve=True):
        for index in range(start, len(self.filter_rows)):
            row = self.filter_rows[index]
            text = row.value.currentText()
            self.fill_values(row.field, row.value, self.other_filters_expr(row))
            if preserve:
                self.restore_value(row.value, text)

    @staticmethod
    def restore_value(combo, text):
        blocked = combo.blockSignals(True)
        try:
            if isinstance(combo, CheckableValueCombo) and combo.checkable and combo.selected_values:
                combo.update_checked_text()
            else:
                index = combo.findText(text, Qt.MatchFlag.MatchExactly)
                if index >= 0:
                    combo.setCurrentIndex(index)
                else:
                    combo.setEditText(text)
        finally:
            combo.blockSignals(blocked)

    @staticmethod
    def natural_key(text):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]

    def fill_values(self, field_combo, value_combo, base_expr):
        version = self.value_versions.get(value_combo, 0) + 1
        self.value_versions[value_combo] = version
        previous = self.value_tasks.pop(value_combo, None)
        if previous is not None:
            previous.cancel()
        value_combo.blockSignals(True)
        value_combo.clear()
        value_combo.addItem(ALL_VALUES, None)
        value_combo.setCurrentIndex(0)
        value_combo.blockSignals(False)
        if isinstance(value_combo, CheckableValueCombo):
            value_combo.update_checked_text()
        value_combo.setToolTip("")
        layer = self.current_layer()
        name = field_combo.currentText()
        idx = layer.fields().lookupField(name) if layer else -1
        if not layer or name == NO_FIELD or idx < 0:
            return

        def finished(exception, result=None):
            if self.closing or self.value_versions.get(value_combo) != version:
                return
            self.value_tasks.pop(value_combo, None)
            if exception is not None:
                value_combo.setToolTip("Could not list values: {}. You can still type a filter.".format(exception))
                return
            if result is None:
                value_combo.setToolTip("Suggestions canceled. You can still type a filter.")
                return
            values, truncated = result
            value_combo.setToolTip("")
            current = value_combo.currentText()
            value_combo.blockSignals(True)
            value_combo.clear()
            value_combo.addItem(ALL_VALUES, None)
            for text in sorted(values, key=self.natural_key):
                value_combo.addItem(text, values[text])
            self.restore_value(value_combo, current)
            value_combo.blockSignals(False)
            if truncated:
                value_combo.setToolTip(
                    "Suggestions from the first {} matching features. Type to search the full layer."
                    .format(MAX_VALUE_FEATURES))

        try:
            # Snapshot on the main thread; workers never access the live layer or UI.
            source = QgsVectorLayerFeatureSource(layer)
            task = QgsTask.fromFunction("QuickTable: suggestions", collect_values,
                                        source=source, index=idx, expression=base_expr,
                                        on_finished=finished)
            task.setDependentLayers([layer])
            self.value_tasks[value_combo] = task
            value_combo.setToolTip("Loading suggestions; you can type a filter while waiting.")
            QgsApplication.taskManager().addTask(task)
        except Exception as e:
            self.value_tasks.pop(value_combo, None)
            value_combo.setToolTip("Could not list values: {}. You can still type a filter.".format(e))

    def part_expr(self, field_combo, value_combo):
        name = field_combo.currentText()
        if name == NO_FIELD or name not in self.fields:
            return None
        row = next(row for row in self.filter_rows if row.field is field_combo)
        operation = row.operator.currentText()
        values = getattr(value_combo, "selected_values", ()) if operation == "Equals" else ()
        text = value_combo.currentText()
        if not values and operation not in ("Is empty", "Is not empty") and value_combo.currentIndex() == 0 and text == ALL_VALUES:
            if operation != "Between" or not row.upper.text().strip():
                return None
            text = ""
        layer = self.current_layer()
        field = layer.fields().field(name) if layer else None
        return field_filter(QgsExpression.quotedColumnRef(name), operation, text, row.upper.text(),
                            field_kind(field), QgsExpression.quotedString, values)

    def prefix_expr(self, stop):
        try:
            expressions = [self.part_expr(row.field, row.value) for row in self.filter_rows[:stop]]
            return " AND ".join(expression for expression in expressions if expression) or None
        except ValueError:
            return "FALSE"

    def other_filters_expr(self, current):
        """Suggest values consistent with every other active column filter."""
        try:
            expressions = [self.part_expr(row.field, row.value) for row in self.filter_rows if row is not current]
            return " AND ".join(expression for expression in expressions if expression) or None
        except ValueError:
            return "FALSE"





    def schedule_search(self, *args):
        self.search_timer.start()




    def on_filter_field_changed(self, row):
        if row not in self.filter_rows or not self.filters_ready:
            return
        row.value.reset_choices()
        row.choices.list.blockSignals(True)
        row.choices.list.clear()
        row.choices.items.clear()
        row.choices.list.blockSignals(False)
        self.sync_filter_inputs()
        self.fill_values(row.field, row.value, self.other_filters_expr(row))
        self.queue_filter_change(row)

    def on_filter_operator_changed(self, row):
        self.sync_filter_inputs()
        if row.widget.isVisible():
            self.show_filter_popup(row, row.widget.pos())
        self.queue_filter_change(row)

    def queue_filter_change(self, row):
        if row not in self.filter_rows or not self.filters_ready:
            return
        self.pending_cascade_start = 0
        for other in self.filter_rows:
            if other is row:
                continue
            self.value_versions[other.value] = self.value_versions.get(other.value, 0) + 1
            task = self.value_tasks.pop(other.value, None)
            if task is not None:
                task.cancel()
        self.update_filter_rows_layout()
        self.filter_timer.start()

    def refresh_dependent_values(self):
        self.filter_timer.stop()
        start = self.pending_cascade_start
        self.pending_cascade_start = None
        if start is not None:
            self.reload_value_lists(start)
        self.run_search()

    def clear_filters(self):
        self.page = 0
        self.search_timer.stop()
        self.filter_timer.stop()
        self.selection_filter_timer.stop()
        self.pending_cascade_start = None
        self.cancel_nearby()
        self.nearby_scope_ids = None
        self.nearby_description = None
        self.btn_nearby.setText("Nearby…")
        self.selected_only_cb.blockSignals(True)
        self.selected_only_cb.setChecked(False)
        self.selected_only_cb.blockSignals(False)
        self.selected_scope_ids = None
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self.clear_filter_rows()
        self.run_search()

    def set_selected_scope(self, enabled):
        layer = self.current_layer()
        self.selection_filter_timer.stop()
        if enabled:
            self.cancel_nearby()
            self.nearby_scope_ids = None
            self.nearby_description = None
            self.btn_nearby.setText("Nearby…")
        self.selected_scope_ids = tuple(sorted(layer.selectedFeatureIds())) if enabled and layer else None
        self.page = 0
        self.run_search()

    def cancel_nearby(self):
        self.nearby_version += 1
        if self.nearby_task is not None:
            self.nearby_task.cancel()
            self.nearby_task = None

    def nearby_menu(self):
        menu = QMenu(self)
        touching = menu.addAction("Touching selected features")
        distance = menu.addAction("Within distance of selection…")
        menu.addSeparator()
        clear = menu.addAction("Clear nearby results")
        clear.setEnabled(self.nearby_scope_ids is not None or self.nearby_task is not None)
        action = menu.exec(self.btn_nearby.mapToGlobal(QPoint(0, self.btn_nearby.height())))
        if action == touching:
            self.find_nearby(None)
        elif action == distance:
            self.ask_nearby_distance()
        elif action == clear:
            self.clear_nearby()

    def ask_nearby_distance(self):
        layer = self.current_layer()
        if not layer or not layer.isSpatial():
            self.status.setText("Choose a spatial layer and select features first.")
            return
        if not layer.selectedFeatureIds():
            self.status.setText("Select one or more features on the map or in the table first.")
            return
        crs = layer.crs()
        units = QgsUnitTypes.toString(crs.mapUnits()) if crs.isValid() else "layer units (CRS unknown)"
        prompt = "Distance in {} (straight-line, layer coordinates):".format(units)
        if crs.isValid() and crs.isGeographic():
            prompt += "\nThis layer uses geographic coordinates; distance is in degrees, not metres."
        distance, ok = QInputDialog.getDouble(self, "Find nearby", prompt, 0.0, 0.0, 1000000000.0, 4)
        if ok:
            self.find_nearby(distance, units)

    def find_nearby(self, distance=None, units=None):
        layer = self.current_layer()
        if not layer or not layer.isSpatial():
            self.status.setText("Choose a spatial layer and select features first.")
            return
        ids = tuple(layer.selectedFeatureIds())
        if not ids:
            self.status.setText("Select one or more features on the map or in the table first.")
            return
        self.cancel_nearby()
        version = self.nearby_version
        layer_id = layer.id()
        description = "touching selection" if distance is None else "within {:g} {}".format(distance, units or "layer units")

        def finished(exception, result=None):
            if self.closing or version != self.nearby_version:
                return
            self.nearby_task = None
            current = self.current_layer()
            if current is None or current.id() != layer_id:
                return
            if exception is not None:
                self.status.setText("Nearby search failed: {}".format(exception))
                return
            if result is None:
                self.status.setText("Nearby search canceled.")
                return
            self.nearby_scope_ids = result[0]
            self.nearby_description = description
            self.btn_nearby.setText("Nearby ✓")
            self.selected_only_cb.blockSignals(True)
            self.selected_only_cb.setChecked(False)
            self.selected_only_cb.blockSignals(False)
            self.selected_scope_ids = None
            self.page = 0
            self.run_search()

        try:
            task = QgsTask.fromFunction("QuickTable: find nearby features", collect_nearby_task,
                                        source=QgsVectorLayerFeatureSource(layer), selected_ids=ids,
                                        distance=distance, on_finished=finished)
            task.setDependentLayers([layer])
            self.nearby_task = task
            self.status.setText("Finding nearby features…")
            QgsApplication.taskManager().addTask(task)
        except Exception as exc:
            self.nearby_task = None
            self.status.setText("Nearby search failed: {}".format(exc))

    def clear_nearby(self):
        self.cancel_nearby()
        self.nearby_scope_ids = None
        self.nearby_description = None
        self.btn_nearby.setText("Nearby…")
        self.page = 0
        self.run_search()

    def saved_filters_key(self):
        key = self.column_settings_key()
        return key + "/savedFilters" if key else None

    def saved_filters(self):
        key = self.saved_filters_key()
        try:
            result = json.loads(str(QSettings().value(key, "{}"))) if key else {}
            return result if isinstance(result, dict) else {}
        except (ValueError, TypeError):
            return {}

    def saved_filters_menu(self):
        if not self.current_layer():
            return
        menu = QMenu(self)
        save = menu.addAction("Save current filters…")
        entries = self.saved_filters()
        load_menu = menu.addMenu("Load")
        delete_menu = menu.addMenu("Delete")
        load_menu.setEnabled(bool(entries))
        delete_menu.setEnabled(bool(entries))
        for name in sorted(entries):
            load_menu.addAction(name, lambda checked=False, n=name: self.load_saved_filter(n))
            delete_menu.addAction(name, lambda checked=False, n=name: self.delete_saved_filter(n))
        save.triggered.connect(self.save_current_filter)
        menu.exec(self.btn_saved_filters.mapToGlobal(QPoint(0, self.btn_saved_filters.height())))

    def save_current_filter(self):
        key = self.saved_filters_key()
        if not key:
            return
        name, ok = QInputDialog.getText(self, "Save filters", "Name for these filters:")
        name = name.strip()
        if not ok or not name:
            return
        entries = self.saved_filters()
        if name in entries and QMessageBox.question(self, "Replace saved filters", "Replace '{}'?".format(name),
                                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        entries[name] = {"search": self.edit.text(), "filters": [
            {"field": row.field.currentText(), "operator": row.operator.currentText(),
             "value": row.value.currentText(), "values": list(row.value.selected_values),
             "upper": row.upper.text()}
            for row in self.filter_rows if row.field.currentText() in self.fields]}
        QSettings().setValue(key, json.dumps(entries))
        self.status.setText("Saved filters: " + name)

    def delete_saved_filter(self, name):
        entries = self.saved_filters()
        if name in entries and QMessageBox.question(self, "Delete saved filters", "Delete '{}'?".format(name),
                                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            del entries[name]
            QSettings().setValue(self.saved_filters_key(), json.dumps(entries))

    def load_saved_filter(self, name):
        saved = self.saved_filters().get(name)
        if not isinstance(saved, dict) or not isinstance(saved.get("filters"), list):
            return
        self.filter_timer.stop()
        self.filters_ready = False
        try:
            self.clear_filter_rows()
            self.edit.setText(str(saved.get("search", "")))
            for spec in saved["filters"]:
                if not isinstance(spec, dict) or spec.get("field") not in self.fields or spec.get("operator") not in FILTER_OPERATORS:
                    continue
                row = self.add_filter_row()
                self.populate_filter_field(row, spec["field"])
                row.operator.setCurrentText(spec["operator"])
                self.sync_filter_inputs()
                row.value.setEditText(str(spec.get("value", ALL_VALUES)))
                row.value.set_selected_values([str(v) for v in spec.get("values", [])], notify=False)
                if not row.value.selected_values:
                    row.value.setEditText(str(spec.get("value", ALL_VALUES)))
                row.upper.setText(str(spec.get("upper", "")))
        finally:
            self.filters_ready = True
        self.search_timer.stop()
        self.pending_cascade_start = None
        self.sync_filter_inputs()
        self.reload_value_lists()
        self.page = 0
        self.run_search()

    # ---------- filtering ----------
    def build_expr(self):
        parts = [self.part_expr(row.field, row.value) for row in self.filter_rows]
        nearby = getattr(self, "nearby_scope_ids", None)
        if nearby is not None:
            parts.append("$id IN ({})".format(",".join(str(int(fid)) for fid in nearby)) if nearby else "FALSE")
        if self.selected_scope_ids is not None:
            parts.append("$id IN ({})".format(",".join(str(int(fid)) for fid in self.selected_scope_ids)) if self.selected_scope_ids else "FALSE")
        text = self.edit.text().strip()
        if text and self.fields:
            pattern = QgsExpression.quotedString(text)
            parts.append("(" + " OR ".join(
                "strpos(lower(to_string({})), lower({})) > 0".format(QgsExpression.quotedColumnRef(name), pattern)
                for name in self.fields) + ")")
        return " AND ".join(part for part in parts if part)

    def clear_table(self):
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)

    def invalidate_results(self):
        self.query_version += 1
        if hasattr(self, "statistics_strip"):
            self.cancel_statistics()
            if self.btn_statistics.isChecked():
                self.statistics_strip.set_state("loading", message="Waiting for results…")
        task = self.query_task
        self.query_task = None
        if task is not None:
            task.cancel()
        self.result_ids = None

    def update_pager(self):
        size = self.page_size.currentData()
        self.btn_select.setText("Select page" if size else "Select all")
        self.btn_zoom.setText("Zoom to page" if size else "Zoom to all")
        self.btn_select.setToolTip("Select every row on this page on the table and map" if size else
                                   "Select all matching results on the table and map")
        if self.result_ids is None:
            self.btn_previous.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.page_status.setText("Finding matches…" if self.query_task is not None else "0 results")
            return
        window = page_window(len(self.result_ids), self.page, size)
        self.page = window.page
        start = window.start + 1 if self.result_ids else 0
        self.page_status.setText("{}–{} of {}  |  Page {} of {}".format(
            start, window.stop, len(self.result_ids), window.page + 1, window.pages))
        self.btn_previous.setEnabled(window.page > 0)
        self.btn_next.setEnabled(window.page + 1 < window.pages)

    def on_page_size_changed(self, *args):
        QSettings().setValue("LayerFilter/pageSize", self.page_size.currentData())
        self.page = 0
        self.run_search()
        self.update_pager()

    def change_page(self, direction):
        if self.result_ids is None:
            return
        window = page_window(len(self.result_ids), self.page + direction, self.page_size.currentData())
        if window.page != self.page:
            self.page = window.page
            self.render_page()

    def clear_results(self, message):
        self.table.blockSignals(True)
        try:
            self.clear_table()
        finally:
            self.table.blockSignals(False)
        self.status.setText(message)
        if self.btn_statistics.isChecked() and self.query_task is None:
            self.statistics_strip.set_state("empty" if self.current_layer() is None else "error", message=message)
        self.update_selection_status()
        self.update_pager()

    def run_search(self, *args):
        self.search_timer.stop()
        layer = self.current_layer()
        if layer is None:
            self.invalidate_results()
            self.result_key = None
            self.table_layer_id = None
            self.pending_selection.clear()
            self.clear_results("No available vector layers" if self.layer.count() == 0 else "No available vector layer selected")
            return
        try:
            expression = self.build_expr()
            query = QgsExpression(expression) if expression else None
            if query is not None and query.hasParserError():
                raise ValueError(query.parserErrorString())
        except Exception as e:
            self.invalidate_results()
            self.result_key = None
            self.pending_selection.clear()
            self.clear_results("Filter problem: {}".format(e))
            return
        sort_field = self.sort_field if self.sort_field in self.fields else None
        key = (layer.id(), expression, sort_field, self.sort_order)
        if key == self.result_key:
            if self.result_ids is not None:
                self.render_page()
                return
            if self.query_task is not None:
                return

        previous_selection = set(self.selected_fids()) | self.pending_selection if self.table_layer_id == layer.id() else set()
        self.invalidate_results()
        if key != self.result_key:
            self.page = 0
        self.result_key = key
        self.table_layer_id = layer.id()
        self.pending_selection = previous_selection
        version = self.query_version

        def finished(exception, result=None):
            if self.closing or version != self.query_version:
                return
            self.query_task = None
            current = self.current_layer()
            if current is None or current.id() != key[0]:
                return
            if exception is not None:
                self.clear_results("Could not search: {}".format(exception))
                return
            if result is None:
                self.clear_results("Search canceled. Use Refresh lists to retry.")
                return
            self.result_ids = result[0]
            self.render_page()

        try:
            source = QgsVectorLayerFeatureSource(layer)
            task = QgsTask.fromFunction("QuickTable: find matches", collect_feature_ids_task,
                                        source=source, expression=expression, sort_field=sort_field,
                                        ascending=self.sort_order == Qt.SortOrder.AscendingOrder, on_finished=finished)
            task.setDependentLayers([layer])
            self.query_task = task
            self.clear_results("Finding matching records…")
            QgsApplication.taskManager().addTask(task)
        except Exception as e:
            self.invalidate_results()
            self.clear_results("Could not search: {}".format(e))

    def render_page(self):
        layer = self.current_layer()
        if layer is None or self.result_ids is None:
            return
        render_notice = ""
        limit = min(MAX_RENDER_ROWS, max(100, MAX_RENDER_CELLS // max(1, len(self.fields))))
        if not self.page_size.currentData() and len(self.result_ids) > limit:
            self.page_size.blockSignals(True)
            self.page_size.setCurrentIndex(self.page_size.findData(500))
            self.page_size.blockSignals(False)
            QSettings().setValue("LayerFilter/pageSize", 500)
            self.page = 0
            render_notice = "All results exceeds the display limit; showing pages of 500. "
        window = page_window(len(self.result_ids), self.page, self.page_size.currentData())
        self.page = window.page
        page_ids = self.result_ids[window.start:window.stop]
        previous_selection = set(layer.selectedFeatureIds())
        self.pending_selection.clear()
        self.table_layer_id = layer.id() if layer else None
        previous_column_layout = self.applying_column_layout
        self.applying_column_layout = True
        self.table.blockSignals(True)
        try:
            self.clear_table()
            if not layer:
                self.status.setText("No vector layer selected")
                return

            self.table.setColumnCount(len(self.fields))
            self.table.setHorizontalHeaderLabels(self.fields)
            self.table.verticalHeader().setMinimumWidth(
                max(42, self.table.fontMetrics().horizontalAdvance(str(len(self.result_ids))) + 20))
            self.apply_column_visibility()
            form = layer.editFormConfig()
            layer_fields = layer.fields()
            edit_buffer = layer.editBuffer() if layer.isEditable() else None
            changed_attributes = edit_buffer.changedAttributeValues() if edit_buffer else {}
            readonly_columns = {c for c in range(len(self.fields))
                                if form.readOnly(c) or (hasattr(layer_fields[c], "isReadOnly")
                                                        and layer_fields[c].isReadOnly())}

            req = QgsFeatureRequest().setFilterFids(list(page_ids))
            req.setFlags(QgsFeatureRequest.Flag.NoGeometry)
            features = {feature.id(): feature for feature in layer.getFeatures(req)} if page_ids else {}

            r = 0
            for fid in page_ids:
                feat = features.get(fid)
                if feat is None:
                    continue
                attrs = feat.attributes()
                self.table.insertRow(r)
                self.table.setVerticalHeaderItem(r, QTableWidgetItem(str(window.start + r + 1)))
                for c in range(len(self.fields)):
                    v = attrs[c] if c < len(attrs) else None
                    s = attribute_text(v)
                    item = SortItem(s)
                    item.setData(NULL_ROLE, v is None or v == NULL)
                    if c in changed_attributes.get(fid, {}):
                        item.setBackground(QColor("#365345" if self.theme == "dark" else "#d8efdf"))
                        item.setToolTip("Unsaved attribute change")
                    if c in readonly_columns:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setToolTip("This field is read-only in the layer configuration or data source")
                    if c == 0:
                        item.setData(Qt.ItemDataRole.UserRole, feat.id())
                    self.table.setItem(r, c, item)
                r += 1

            if self.sort_field in self.fields:
                self.table.horizontalHeader().setSortIndicator(self.fields.index(self.sort_field), self.sort_order)
            self.table.horizontalHeader().setSortIndicatorShown(self.sort_field in self.fields)
            self.apply_column_layout()
            pending = self.pending_added_field
            self.pending_added_field = None
            if pending and pending[0] == layer.id() and pending[1] in self.fields:
                column = self.fields.index(pending[1])
                if self.table.rowCount():
                    self.table.scrollToItem(self.table.item(0, column), QAbstractItemView.ScrollHint.EnsureVisible)
                else:
                    self.table.horizontalScrollBar().setValue(self.table.horizontalScrollBar().maximum())
            self.select_table_fids(previous_selection)
            message = ("No matching records. Adjust a column filter or search to see results."
                       if not self.result_ids else
                       "{} record(s)  |  click a column name to sort or its filter below".format(r))
            if self.nearby_description:
                message = "Nearby: {}  |  {} record(s) on this page".format(self.nearby_description, r)
            if self.pending_notice and layer.isModified():
                message = self.pending_notice
            self.pending_notice = None
            self.status.setText(render_notice + message)
        except Exception as e:
            self.clear_table()
            self.status.setText("Filter problem: {}  (try Refresh lists or Clear filters)".format(e))
        finally:
            self.table.blockSignals(False)
            self.applying_column_layout = previous_column_layout
            self.update_selection_status()
            self.update_pager()
            self.btn_columns.setEnabled(bool(self.fields))
        if self.table.columnCount() == len(self.fields):
            self.refresh_statistics()
        elif self.btn_statistics.isChecked():
            self.cancel_statistics()
            self.statistics_strip.set_state("error", message=self.status.text())

    # ---------- editing ----------
    convert = staticmethod(convert_attribute)

    def apply_edit_state(self, on):
        self.table.setProperty("editing", "true" if on else "false")
        sty = self.table.style()
        sty.unpolish(self.table)
        sty.polish(self.table)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
            if on else QAbstractItemView.EditTrigger.NoEditTriggers)
        self.btn_save.setEnabled(on)
        self.btn_discard.setEnabled(on)
        self.update_undo_buttons()
        self.update_delete_button()

    def sync_edit_state(self):
        """Mirror QGIS: checkbox is on when the layer is in edit mode."""
        layer = self.current_layer()
        can_edit, reason = self.attribute_editability()
        on = bool(layer and layer.isEditable() and can_edit)
        self.edit_cb.blockSignals(True)
        self.edit_cb.setChecked(on)
        self.edit_cb.blockSignals(False)
        self.edit_cb.setEnabled(can_edit)
        self.edit_cb.setToolTip(reason)
        text = "Editing" if on else "Editable" if can_edit else "Read-only" if layer else "No layer"
        color = THEMES[self.theme]["accent" if can_edit else "muted"]
        self.edit_status.setText("<b style='color:{}'>{}</b>".format(color, text))
        self.edit_status.setToolTip(reason)
        self.apply_edit_state(on)

    def attribute_editability(self):
        layer = self.current_layer()
        if layer is None:
            return False, "Choose a vector layer to edit its attributes."
        if self.edit_failure and self.edit_failure[0] == layer.id():
            return False, self.edit_failure[1]
        if not layer.isValid():
            return False, "The layer's data source is unavailable."
        if layer.readOnly():
            return False, "Editing is disabled for this layer in QGIS."
        provider = layer.dataProvider()
        if provider is None or not (provider.capabilities() & QgsVectorDataProvider.Capability.ChangeAttributeValues):
            return False, "This data source does not allow attribute editing. Export to GeoPackage to edit a copy."
        return True, "Attributes can be edited. Enable edit mode, then double-click a writable cell."

    def uncheck_edit(self, checked=False):
        self.edit_cb.blockSignals(True)
        self.edit_cb.setChecked(checked)
        self.edit_cb.blockSignals(False)
        self.apply_edit_state(checked)

    def on_edit_toggled(self, checked):
        layer = self.current_layer()
        if layer is None:
            self.uncheck_edit(False)
            return
        if checked:
            can_edit, reason = self.attribute_editability()
            if not can_edit:
                self.sync_edit_state()
                self.status.setText(reason)
                return
            if not layer.isEditable() and not layer.startEditing():
                reason = "QGIS could not start editing. Check file permissions, connection permissions or source locks, then Refresh lists to retry."
                self.edit_failure = (layer.id(), reason)
                self.sync_edit_state()
                self.status.setText(reason)
                return
            self.sync_edit_state()
            self.status.setText("Edit mode ON. Double-click a cell, then Save edits when done.")
        else:
            if layer.isEditable():
                if layer.isModified():
                    ans = QMessageBox.question(
                        self, "QuickTable", "Save your edits to this layer?",
                        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
                    if ans == QMessageBox.StandardButton.Cancel:
                        self.uncheck_edit(True)
                        return
                    if ans == QMessageBox.StandardButton.Save:
                        try:
                            validate_pending_changes(layer)
                        except ValueError as exc:
                            self.status.setText("Could not save: {}".format(exc))
                            self.uncheck_edit(True)
                            return
                        if not layer.commitChanges():
                            self.status.setText("Could not save: " + "; ".join(layer.commitErrors()))
                            self.uncheck_edit(True)
                            return
                    else:
                        if not layer.rollBack():
                            self.status.setText("Could not discard edits; pending changes were retained.")
                            self.sync_edit_state()
                            return
                else:
                    if not layer.commitChanges():
                        self.status.setText("Could not stop editing: " + "; ".join(layer.commitErrors()))
                        self.sync_edit_state()
                        return
            self.sync_edit_state()
            self.status.setText("Edit mode OFF")

    def on_table_data_changed(self, first, last, roles):
        if self.table.signalsBlocked() or (roles and not any(
                role in roles for role in (Qt.ItemDataRole.EditRole, Qt.ItemDataRole.DisplayRole))):
            return
        for row in range(first.row(), last.row() + 1):
            for column in range(first.column(), last.column() + 1):
                item = self.table.item(row, column)
                if item is not None:
                    self.on_cell_edited(item)

    def cell_context_menu(self, position):
        item = self.table.itemAt(position)
        if item is None or not self.edit_cb.isChecked() or not item.flags() & Qt.ItemFlag.ItemIsEditable:
            return
        menu = QMenu(self)
        null_action = menu.addAction("Set cell to NULL")
        empty_action = menu.addAction("Set cell to empty text")
        layer = self.current_layer()
        empty_action.setEnabled(bool(layer and field_kind(layer.fields()[item.column()]) == "text"))
        layer_id = layer.id() if layer else None
        fid = self.row_fid(item.row())
        field_name = self.fields[item.column()]
        action = menu.exec(self.table.viewport().mapToGlobal(position))
        if action in (null_action, empty_action):
            current = self.current_layer()
            if current is None or current.id() != layer_id or field_name not in self.fields:
                self.status.setText("The layer or field changed; the cell was not changed.")
                return
            row = next((row for row in range(self.table.rowCount()) if self.row_fid(row) == fid), None)
            if row is None:
                self.status.setText("The cell is no longer visible; it was not changed.")
                return
            self.set_cell_null(row, self.fields.index(field_name), action == null_action)

    def set_cell_null(self, row, column, null=True):
        item = self.table.item(row, column)
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEditable or not self.edit_cb.isChecked():
            return
        self.table.blockSignals(True)
        try:
            item.setData(NULL_ROLE, null)
            item.setText("")
        finally:
            self.table.blockSignals(False)
        self.on_cell_edited(item)

    def on_cell_edited(self, item):
        if not self.edit_cb.isChecked():
            return
        layer = self.current_layer()
        if layer is None or not layer.isEditable():
            return
        row, col = item.row(), item.column()
        fid = self.row_fid(row)
        if fid is None or col >= len(self.fields):
            return
        fld = layer.fields()[col]
        feat = layer.getFeature(fid)
        old = feat.attributes()[col] if feat.isValid() and col < len(feat.attributes()) else None
        old_text = attribute_text(old)
        ok, err = False, ""
        command_started = False
        try:
            if layer.readOnly() or layer.editFormConfig().readOnly(col) or (
                    hasattr(fld, "isReadOnly") and fld.isReadOnly()):
                raise ValueError("This field or layer is read-only")
            new = self.convert(fld, None if item.data(NULL_ROLE) and not item.text() else item.text())
            validate_change(layer, fid, col, new)
            self.own_edit = True
            layer.beginEditCommand("Change {}".format(fld.name()))
            command_started = True
            ok = layer.changeAttributeValue(fid, col, new)
            if not ok:
                err = "layer refused the change"
            if ok:
                layer.endEditCommand()
            else:
                layer.destroyEditCommand()
            command_started = False
        except ValueError as e:
            err = "Invalid value for {}: {}".format(fld.name(), e)
        except Exception as e:
            err = str(e)
        finally:
            if command_started:
                layer.destroyEditCommand()
            self.own_edit = False
            self.update_undo_buttons()
        if ok:
            changed = layer.editBuffer().changedAttributeValues().get(fid, {}) if layer.editBuffer() else {}
            self.table.blockSignals(True)
            try:
                item.setBackground(QBrush(QColor("#365345" if self.theme == "dark" else "#d8efdf")) if col in changed else QBrush())
                item.setToolTip("Unsaved attribute change" if col in changed else "")
                item.setData(NULL_ROLE, new is None or new == NULL)
            finally:
                self.table.blockSignals(False)
            self.status.setText("Changed {} (not saved yet, click Save edits)".format(fld.name()))
            self.refresh_lists_only()
            self.resize_wrapped_rows()
            # The edited value may change filter membership or sort order even
            # when statistics are hidden. Rebuild after this signal returns.
            self.invalidate_results()
            self.timer.start()
        else:
            self.table.blockSignals(True)
            item.setText(old_text)
            item.setData(NULL_ROLE, old is None or old == NULL)
            self.table.blockSignals(False)
            self.status.setText("Not changed: " + err)

    def refresh_lists_only(self):
        """Refresh choices without replacing a cell currently being edited."""
        self.reload_value_lists()

    def save_edits(self):
        layer = self.current_layer()
        if layer is None or not layer.isEditable():
            return
        if not layer.isModified():
            self.status.setText("Nothing to save")
            return
        try:
            validate_pending_changes(layer)
        except ValueError as exc:
            self.status.setText("Could not save: {}".format(exc))
            return
        if layer.commitChanges(False):  # False = stay in edit mode
            self.soft_refresh()
            self.status.setText("Saved to the layer.")
        else:
            self.status.setText("Could not save: " + "; ".join(layer.commitErrors()))

    def discard_edits(self):
        layer = self.current_layer()
        if layer is None or not layer.isEditable():
            return
        if not layer.isModified():
            self.status.setText("Nothing to discard")
            return
        ans = QMessageBox.question(self, "QuickTable",
                                   "Discard all unsaved edits on this layer?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        if not layer.rollBack():
            self.status.setText("Could not discard edits; pending changes were retained.")
            return
        if not layer.startEditing():
            self.sync_edit_state()
            self.status.setText("Edits discarded, but QGIS could not restart editing.")
            return
        self.status.setText("Unsaved edits discarded.")
        self.soft_refresh()

    # ---------- helpers ----------
    def row_fid(self, row):
        # fid lives on column 0 of each row (items move with the row when sorting)
        it = self.table.item(row, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def all_fids(self):
        return [self.row_fid(r) for r in range(self.table.rowCount())
                if self.row_fid(r) is not None]

    def selected_rows(self):
        return sorted(index.row() for index in self.table.selectionModel().selectedRows(0))

    def selected_fids(self):
        return [self.row_fid(r) for r in self.selected_rows()
                if self.row_fid(r) is not None]

    def deletion_availability(self, selection=None):
        layer = self.current_layer()
        if layer is None or not layer.isValid():
            return False, "Choose a valid vector layer."
        provider = layer.dataProvider()
        if layer.readOnly() or provider is None or not (provider.capabilities() & QgsVectorDataProvider.Capability.DeleteFeatures):
            return False, "This layer does not allow deleting features."
        if not layer.isEditable():
            return False, "Enable edit mode before deleting selected features."
        if not (self.selected_fids() if selection is None else selection):
            return False, "Select the rows you want to delete."
        return True, "Delete only the selected features after confirmation. Changes remain unsaved until Save edits."

    def update_delete_button(self):
        enabled, reason = self.deletion_availability()
        self.btn_delete.setEnabled(enabled)
        self.btn_delete.setToolTip(reason)
        can_edit, reason = self.attribute_editability()
        layer = self.current_layer()
        self.btn_bulk.setEnabled(bool(can_edit and layer and layer.isEditable() and self.selected_fids()))
        self.btn_bulk.setToolTip("Change one writable field for selected table rows" if can_edit else reason)
        self.btn_autofill.setEnabled(bool(can_edit and layer and layer.isEditable() and self.table.rowCount()))
        self.btn_autofill.setToolTip("Fill a column on selected rows or the current page")
        provider = layer.dataProvider() if layer else None
        can_add = bool(layer and layer.isEditable() and not layer.readOnly() and provider
                       and provider.capabilities() & QgsVectorDataProvider.Capability.AddAttributes)
        self.btn_add_field.setEnabled(can_add)
        self.btn_add_field.setToolTip("Add an empty field to the layer" if can_add else
                                      "Enable edit mode on a layer that supports adding fields")
        can_delete_field = bool(layer and layer.isEditable() and not layer.readOnly() and provider
                                and provider.capabilities() & QgsVectorDataProvider.Capability.DeleteAttributes)
        self.btn_delete_field.setEnabled(can_delete_field)
        self.btn_delete_field.setToolTip("Delete a field and its values after confirmation" if can_delete_field else
                                         "Enable edit mode on a layer that supports deleting fields")
        self.btn_fields.setEnabled(can_add or can_delete_field)

    def add_field(self):
        layer = self.current_layer()
        if not layer or not layer.isEditable() or layer.readOnly():
            return
        provider = layer.dataProvider()
        if not provider or not provider.capabilities() & QgsVectorDataProvider.Capability.AddAttributes:
            self.status.setText("This layer does not support adding fields.")
            return
        dialog = AddFieldDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        specs = dialog.field_specs()
        dialog.deleteLater()
        names = [spec[0] for spec in specs]
        if not names or any(not name for name in names):
            QMessageBox.warning(self, "Add field", "Enter a name for each field.")
            return
        if self.current_layer() != layer or not layer.isEditable():
            self.status.setText("Layer or edit mode changed. Field was not added.")
            return
        if len({item.casefold() for item in names}) != len(names) or any(layer.fields().lookupField(item) >= 0 for item in names):
            QMessageBox.warning(self, "Add field", "Field names must be unique and must not already exist.")
            return
        if any(length and precision >= length for _, _, length, precision in specs):
            QMessageBox.warning(self, "Add field", "Decimal precision must be smaller than the field length.")
            return
        command_open = False
        error = None
        self.own_edit = True
        try:
            layer.beginEditCommand("QuickTable: add {} field(s)".format(len(names)))
            command_open = True
            for field_name, field_type, length, precision in specs:
                type_name = ""
                if layer.providerType() == "postgres":
                    type_name = {
                        QMetaType.Type.QString: "varchar" if length else "text",
                        QMetaType.Type.Int: "int4",
                        QMetaType.Type.LongLong: "int8",
                        QMetaType.Type.Double: "numeric" if length else "float8",
                        QMetaType.Type.QDate: "date",
                        QMetaType.Type.Bool: "bool",
                    }[field_type]
                if not layer.addAttribute(QgsField(field_name, field_type, type_name, len=length, prec=precision)):
                    raise RuntimeError("The data source rejected field '{}' or its type.".format(field_name))
            layer.updateFields()
            layer.endEditCommand()
            command_open = False
        except Exception as exc:
            error = str(exc)
            if command_open:
                layer.destroyEditCommand()
        finally:
            self.own_edit = False
        if error is None:
            key = self.column_settings_key()
            hidden = QSettings().value(key, []) if key else []
            if isinstance(hidden, str):
                hidden = [hidden]
            if key and any(item in (hidden or []) for item in names):
                QSettings().setValue(key, [item for item in hidden if item not in names])
            if key:
                # Refit regular columns when the schema grows, including widths
                # saved by older versions which stretched the last column.
                wrapped = self.wrapped_fields()
                widths = self.saved_column_widths(key)
                for field_name in list(widths):
                    if field_name not in wrapped:
                        del widths[field_name]
                self.pending_column_widths[key] = widths
                self.column_layout_timer.start()
            self.pending_added_field = (layer.id(), names[0])
        self.soft_refresh()
        self.status.setText("Could not add field: " + error if error else
                            "Added {} field(s); save edits to commit.".format(len(names)))

    @staticmethod
    def deletable_field_indices(layer):
        fields = layer.fields()
        primary_keys = set(layer.primaryKeyAttributes())
        form = layer.editFormConfig()
        return [index for index in range(fields.count())
                if index not in primary_keys and fields.fieldOrigin(index) in (QgsFields.FieldOrigin.OriginProvider, QgsFields.FieldOrigin.OriginEdit)
                and not form.readOnly(index)
                and not (hasattr(fields[index], "isReadOnly") and fields[index].isReadOnly())]

    def delete_field(self):
        layer = self.current_layer()
        provider = layer.dataProvider() if layer else None
        if (not layer or not layer.isEditable() or layer.readOnly() or not provider
                or not provider.capabilities() & QgsVectorDataProvider.Capability.DeleteAttributes):
            self.status.setText("This layer does not allow deleting fields in the current edit mode.")
            return
        indices = self.deletable_field_indices(layer)
        if not indices:
            self.status.setText("No deletable fields are available.")
            return
        names = [layer.fields()[i].name() for i in indices]
        dialog = DeleteFieldsDialog(self, names)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        selected = dialog.selected_names()
        dialog.deleteLater()
        if not selected:
            self.status.setText("No fields selected.")
            return
        question = ("Delete {} field(s) from '{}'?\n\n{}\n\nThis removes their values from every feature. "
                    "The deletion remains pending until Save edits; you can undo it before saving.").format(
                        len(selected), layer.name(), "\n".join(selected))
        if QMessageBox.question(self, "Delete fields", question, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        indices = [layer.fields().indexFromName(name) for name in selected]
        allowed = set(self.deletable_field_indices(layer))
        if (self.current_layer() != layer or not layer.isEditable() or layer.readOnly()
                or any(index < 0 or index not in allowed for index in indices)
                or not layer.dataProvider().capabilities() & QgsVectorDataProvider.Capability.DeleteAttributes):
            self.status.setText("The layer or fields changed. Field deletion canceled.")
            return
        command_open = False
        error = None
        self.own_edit = True
        try:
            layer.beginEditCommand("QuickTable: delete {} field(s)".format(len(selected)))
            command_open = True
            for index in sorted(indices, reverse=True):
                if not layer.deleteAttribute(index):
                    raise RuntimeError("The data source refused to delete a field.")
            layer.updateFields()
            layer.endEditCommand()
            command_open = False
        except Exception as exc:
            error = str(exc)
            if command_open:
                layer.destroyEditCommand()
        finally:
            self.own_edit = False
        self.soft_refresh()
        self.status.setText("Could not delete fields: " + error if error else
                            "Deleted {} field(s); save edits to commit.".format(len(selected)))

    def bulk_edit(self):
        layer = self.current_layer()
        fids = list(dict.fromkeys(self.selected_fids()))
        if not layer or not layer.isEditable() or not fids:
            return
        fields = layer.fields()
        form = layer.editFormConfig()
        names = [field.name() for i, field in enumerate(fields)
                 if not form.readOnly(i) and not (hasattr(field, "isReadOnly") and field.isReadOnly())]
        if not names:
            self.status.setText("No writable fields available.")
            return
        dialog = BulkEditDialog(self, layer, names, fids)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.field.currentText()
        index = layer.fields().indexFromName(name)
        value = dialog.value
        dialog.deleteLater()
        if (self.current_layer() != layer or not layer.isEditable() or set(self.selected_fids()) != set(fids)
                or index < 0 or layer.editFormConfig().readOnly(index)
                or (hasattr(layer.fields()[index], "isReadOnly") and layer.fields()[index].isReadOnly())):
            self.status.setText("Layer or selection changed. Bulk edit canceled.")
            return
        request = QgsFeatureRequest().setFilterFids(fids)
        current = {feature.id(): feature[index] for feature in layer.getFeatures(request)}
        if current != dialog.original_values:
            self.status.setText("Values changed after the preview. Bulk edit canceled.")
            return
        error = None
        command_open = False
        self.own_edit = True
        try:
            layer.beginEditCommand("QuickTable: bulk edit {}".format(name))
            command_open = True
            for fid in fids:
                validate_change(layer, fid, index, value)
                if not layer.changeAttributeValue(fid, index, value):
                    raise RuntimeError("The layer refused a change to feature {}".format(fid))
            layer.endEditCommand()
            command_open = False
        except Exception as exc:
            error = str(exc)
            if command_open:
                layer.destroyEditCommand()
        finally:
            self.own_edit = False
        self.soft_refresh()
        self.status.setText("Bulk edit failed: " + error if error else
                            "Changed {} feature(s); save to commit.".format(len(fids)))

    @staticmethod
    def autofill_values(field, mode, text, step_text, count):
        if mode == "null":
            return [NULL] * count
        if mode == "same":
            return [FinderDialog.convert(field, text)] * count
        if mode == "repeat":
            if not text:
                raise ValueError("Enter at least one value to repeat.")
            values = [FinderDialog.convert(field, value) for value in text.split("\n")]
            return [values[i % len(values)] for i in range(count)]
        if mode != "sequence" or field_kind(field) not in ("integer", "number"):
            raise ValueError("Number sequences require a numeric field.")
        try:
            start, step = Decimal(text.strip()), Decimal(step_text.strip())
            if not start.is_finite() or not step.is_finite():
                raise ValueError("Start and step must be finite numbers.")
            output = []
            limits = {QMetaType.Type.Int: (-(2**31), 2**31 - 1), QMetaType.Type.UInt: (0, 2**32 - 1),
                      QMetaType.Type.LongLong: (-(2**63), 2**63 - 1), QMetaType.Type.ULongLong: (0, 2**64 - 1)}
            for i in range(count):
                number = start + step * i
                if field.type() in limits:
                    if number != number.to_integral_value():
                        raise ValueError("A whole-number field requires whole-number values.")
                    low, high = limits[field.type()]
                    if not low <= number <= high:
                        raise ValueError("A generated number is outside the field's range.")
                    output.append(int(number))
                else:
                    output.append(FinderDialog.convert(field, format(number, "f")))
            return output
        except (InvalidOperation, OverflowError):
            raise ValueError("Enter valid start and step numbers.")

    def autofill(self):
        layer = self.current_layer()
        selected_fids = list(dict.fromkeys(self.selected_fids()))
        page_fids = list(dict.fromkeys(self.all_fids()))
        if not layer or not layer.isEditable() or not page_fids:
            return
        fields = layer.fields()
        form = layer.editFormConfig()
        names = [field.name() for i, field in enumerate(fields)
                 if not form.readOnly(i) and not (hasattr(field, "isReadOnly") and field.isReadOnly())]
        if not names:
            self.status.setText("No writable fields available.")
            return
        dialog = AutofillDialog(self, names, len(selected_fids), len(page_fids))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        name = dialog.field.currentText()
        scope = dialog.scope.currentData()
        fids = selected_fids if scope == "selected" else page_fids
        mode = dialog.mode.currentData()
        text = dialog.values.toPlainText()
        step = dialog.step.text()
        dialog.deleteLater()
        if not fids:
            self.status.setText("Select rows or choose the entire current page for autofill.")
            return
        index = fields.indexFromName(name)
        field = fields[index]
        try:
            values = self.autofill_values(field, mode, text, step, len(fids))
        except (ValueError, OverflowError) as exc:
            QMessageBox.warning(self, "Autofill", "Invalid values: {}".format(exc))
            return
        features = {feature.id(): feature for feature in layer.getFeatures(QgsFeatureRequest().setFilterFids(fids))}
        if len(features) != len(fids):
            self.status.setText("A selected feature is unavailable. Autofill canceled.")
            return
        preview = []
        for fid, value in list(zip(fids, values))[:10]:
            old = features[fid][index]
            preview.append("{}: {} → {}".format(fid, "NULL" if old is None or old == NULL else str(old),
                                               "NULL" if value is None or value == NULL else str(value)))
        if len(fids) > 10:
            preview.append("… and {} more".format(len(fids) - 10))
        scope_label = "selected rows" if scope == "selected" else "all rows on this page"
        message = "Fill column '{}' for {} rows ({}), in table order?\n\n{}\n\nChanges remain unsaved until Save edits.".format(
            name, len(fids), scope_label, "\n".join(preview))
        if QMessageBox.question(self, "Confirm autofill", message,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        current_fids = self.selected_fids() if scope == "selected" else self.all_fids()
        if (self.current_layer() != layer or not layer.isEditable() or current_fids != fids
                or index >= layer.fields().count() or layer.fields()[index].name() != name
                or layer.editFormConfig().readOnly(index)
                or (hasattr(layer.fields()[index], "isReadOnly") and layer.fields()[index].isReadOnly())):
            self.status.setText("Layer, field or row order changed. Autofill canceled.")
            return
        current = {feature.id(): feature for feature in layer.getFeatures(QgsFeatureRequest().setFilterFids(fids))}
        if len(current) != len(fids) or any(current[fid][index] != features[fid][index] for fid in fids):
            self.status.setText("Values changed after the preview. Autofill canceled.")
            return
        error, command_open = None, False
        self.own_edit = True
        try:
            layer.beginEditCommand("QuickTable: autofill {}".format(name))
            command_open = True
            for fid, value in zip(fids, values):
                validate_change(layer, fid, index, value)
                if not layer.changeAttributeValue(fid, index, value):
                    raise RuntimeError("The layer refused a change to feature {}".format(fid))
            layer.endEditCommand()
            command_open = False
        except Exception as exc:
            error = str(exc)
            if command_open:
                layer.destroyEditCommand()
        finally:
            self.own_edit = False
        self.soft_refresh()
        self.status.setText("Autofill failed: " + error if error else
                            "Filled {} row(s); save to commit.".format(len(fids)))

    def delete_selected(self):
        allowed, reason = self.deletion_availability()
        if not allowed:
            self.status.setText(reason)
            return
        layer = self.current_layer()
        layer_id = layer.id()
        fids = list(dict.fromkeys(self.selected_fids()))
        question = QMessageBox(self)
        question.setWindowTitle("Delete selected features")
        question.setIcon(QMessageBox.Icon.Warning)
        question.setTextFormat(Qt.TextFormat.PlainText)
        question.setText("Delete {} selected feature(s) from '{}'?".format(len(fids), layer.name()))
        question.setInformativeText(
            "This deletes the full features, including their geometry.\n"
            "The deletion stays unsaved until you click Save edits. Discard edits rolls back all unsaved changes.")
        delete = question.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        cancel = question.addButton(QMessageBox.StandardButton.Cancel)
        question.setDefaultButton(cancel)
        question.setEscapeButton(cancel)
        question.exec()
        confirmed = question.clickedButton() == delete
        question.deleteLater()
        if not confirmed:
            return
        layer = self.current_layer()
        if layer is None or layer.id() != layer_id:
            self.status.setText("The current layer changed. Deletion canceled.")
            return
        allowed, reason = self.deletion_availability(fids)
        if not allowed:
            self.status.setText(reason)
            return
        self.timer.stop()
        self.search_timer.stop()
        self.filter_timer.stop()
        self.pending_cascade_start = None
        command_open = False
        error = None
        self.own_edit = True
        try:
            layer.beginEditCommand("QuickTable: delete selected features")
            command_open = True
            if not layer.deleteFeatures(fids):
                raise RuntimeError("The layer refused the deletion")
            layer.endEditCommand()
            command_open = False
        except Exception as exc:
            error = str(exc)
            if command_open:
                try:
                    layer.destroyEditCommand()
                except Exception as undo_error:
                    error += "; could not undo this operation: " + str(undo_error)
        finally:
            self.own_edit = False
        if error:
            self.soft_refresh()
            self.status.setText("Could not delete: " + error)
            return
        self.unselect_all()
        self.pending_notice = "Deleted {} feature(s). Not saved yet — click Save edits to commit.".format(len(fids))
        self.soft_refresh()
        self.status.setText(self.pending_notice)

    # ---------- map actions ----------
    def select_table_fids(self, fids):
        """Apply selected rows in contiguous ranges, without selecting every cell separately."""
        selection_model = self.table.selectionModel()
        model = self.table.model()
        last_column = self.table.columnCount() - 1
        ranges = QItemSelection()
        start = None
        for row in range(self.table.rowCount()):
            selected = last_column >= 0 and self.row_fid(row) in fids
            if selected and start is None:
                start = row
            if start is not None and (not selected or row == self.table.rowCount() - 1):
                end = row if selected else row - 1
                ranges.select(model.index(start, 0), model.index(end, last_column))
                start = None
        selection_model.select(ranges, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)

    def set_map_selection(self, layer, fids):
        self.syncing_map_selection = True
        try:
            layer.selectByIds(fids)
        finally:
            self.syncing_map_selection = False

    def on_layer_selection_changed(self, *args):
        layer = self.current_layer()
        if layer is None or layer.id() != self.table_layer_id:
            return
        selected = set(layer.selectedFeatureIds())
        self.pending_selection = selected
        if self.selected_only_cb.isChecked():
            self.selected_scope_ids = tuple(sorted(selected))
            self.page = 0
            self.selection_filter_timer.start()
        if not self.syncing_map_selection:
            blocked = self.table.blockSignals(True)
            try:
                self.select_table_fids(selected)
            finally:
                self.table.blockSignals(blocked)
        self.update_selection_status()

    def on_row_selection(self):
        layer = self.current_layer()
        fids = self.selected_fids()
        self.update_selection_status()
        if not layer:
            return
        self.set_map_selection(layer, fids)
        if not fids or not layer.isSpatial():
            return
        canvas = self.iface.mapCanvas()
        canvas.zoomToSelected(layer)
        canvas.flashFeatureIds(layer, fids[:50])

    def select_all(self):
        layer = self.current_layer()
        self.table.blockSignals(True)
        try:
            self.table.selectAll()
        finally:
            self.table.blockSignals(False)
        if layer:
            self.set_map_selection(layer, self.all_fids())
        self.update_selection_status()

    def unselect_all(self):
        self.pending_selection.clear()
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
        finally:
            self.table.blockSignals(False)
        layer = self.current_layer()
        if layer:
            self.set_map_selection(layer, [])
        self.update_selection_status()

    def set_multi_selection(self, enabled):
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection if enabled
                                    else QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setToolTip("Click rows to add or remove them from the selection." if enabled else
                             "Ctrl-click adds/removes rows; Shift-click selects a range.")

    def update_selection_status(self):
        layer = self.current_layer()
        self.btn_clear_filters.setEnabled(layer is not None)
        on_page = len(self.selected_rows())
        total = layer.selectedFeatureCount() if layer else 0
        self.selection_status.setText("{} selected".format(total) if total == on_page else
                                      "{} selected ({} on page)".format(total, on_page))
        self.btn_select.setEnabled(self.table.rowCount() > 0)
        self.btn_copy.setEnabled(self.table.rowCount() > 0)
        self.btn_csv.setEnabled(self.table.rowCount() > 0)
        self.btn_unselect.setEnabled(layer is not None)
        self.btn_zoom.setEnabled(bool(layer and layer.isSpatial() and self.table.rowCount()))
        self.update_delete_button()

    def zoom_all(self):
        layer = self.current_layer()
        fids = self.all_fids()
        if layer and layer.isSpatial() and fids:
            self.select_all()
            self.iface.mapCanvas().zoomToSelected(layer)

    # ---------- export ----------
    def table_rows(self):
        rows = self.selected_rows() or range(self.table.rowCount())
        columns = [c for c in range(len(self.fields)) if not self.table.isColumnHidden(c)]
        out = [[self.fields[c] for c in columns]]
        for r in rows:
            out.append([self.table.item(r, c).text() for c in columns])
        return out

    def copy_rows(self):
        data = self.table_rows()
        layer = self.current_layer()
        columns = [c for c in range(len(self.fields)) if not self.table.isColumnHidden(c)]
        numeric = [i for i, column in enumerate(columns)
                   if layer and field_kind(layer.fields()[column]) in ("integer", "number")]
        QApplication.clipboard().setText(clipboard_text(data, numeric))
        self.status.setText("Copied {} row(s). Paste into Excel.".format(len(data) - 1))

    def export_csv(self):
        layer = self.current_layer()
        if layer is None or self.result_ids is None:
            self.status.setText("Wait for matching results before exporting.")
            return
        if self.csv_task is not None:
            self.status.setText("A CSV export is already running; cancel it in the QGIS task manager to retry.")
            return
        scopes = ["Current page", "All filtered results"]
        selected = self.selected_fids()
        if selected:
            scopes.insert(0, "Selected rows on this page")
        scope, accepted = QInputDialog.getItem(self, "Export CSV", "Rows to export", scopes, 0, False)
        if not accepted:
            return
        ids = tuple(selected if scope == "Selected rows on this page" else
                    self.result_ids if scope == "All filtered results" else self.all_fids())
        columns = [c for c in range(len(self.fields)) if not self.table.isColumnHidden(c)]
        names = [self.fields[c] for c in columns]
        source = QgsVectorLayerFeatureSource(layer)
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "features.csv", "CSV (*.csv)")
        if not path:
            return

        def finished(exception, result=None):
            if self.closing:
                return
            self.csv_task = None
            if exception is not None:
                self.status.setText("Could not export CSV: {}".format(exception))
            elif result is None:
                self.status.setText("CSV export canceled; the destination was not replaced.")
            else:
                self.status.setText("Exported {} row(s) to {}".format(result['rows'], result['path']))

        try:
            task = QgsTask.fromFunction("QuickTable: export CSV", export_csv_task,
                source=source, ids=ids, columns=columns, names=names, path=path, on_finished=finished)
            task.setDependentLayers([layer])
            self.csv_task = task
            self.status.setText("Exporting {} row(s)…".format(len(ids)))
            QgsApplication.taskManager().addTask(task)
        except Exception as exc:
            self.csv_task = None
            self.status.setText("Could not export CSV: {}".format(exc))


class QuickFilter:
    def __init__(self, iface):
        self.iface = iface
        self.dlg = None
        self.action = None

    def initGui(self):
        icon = plugin_icon()
        self.action = QAction(icon, "QuickTable", self.iface.mainWindow())
        self.action.triggered.connect(self.show)
        self.iface.addPluginToMenu("&QuickTable", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginMenu("&QuickTable", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dlg:
            self.dlg.shutdown()
            self.dlg = None

    def show(self):
        created = self.dlg is None
        if self.dlg is None:
            self.dlg = FinderDialog(self.iface)
            QgsApplication.instance().aboutToQuit.connect(self.dlg.close)
        # Restoring/raising the existing window must not reload its filter controls.
        if created or self.dlg.current_layer() is None:
            self.dlg.refresh()
        if self.dlg.isMinimized():
            self.dlg.showNormal()
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
