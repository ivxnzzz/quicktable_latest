"""Theme palettes, stylesheet generation, and SVG/PNG icon helpers."""

import os
import re

from qgis.PyQt.QtCore import Qt, QByteArray
from qgis.PyQt.QtGui import QPalette, QColor, QIcon, QPixmap, QPainter
from qgis.PyQt.QtSvg import QSvgRenderer

ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")


def plugin_icon():
    """Return the main QuickTable plugin icon."""
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

SCOPE_ICONS = {
    "selected": (
        '<rect x="2.5" y="2.5" width="17" height="16" rx="3" fill="#ffffff" stroke="#111111" stroke-width="2"/>'
        '<path d="M2.5 5.5a3 3 0 0 1 3-3h11a3 3 0 0 1 3 3V8H2.5V5.5z" fill="#0a84ff" stroke="#111111" stroke-width="2"/>'
        '<rect x="3.5" y="8.8" width="15" height="4.5" fill="#ffd400"/>'
        '<path d="M2.5 13.3h17M8.5 8v10.5M14 8v10.5" fill="none" stroke="#111111" stroke-width="1.6"/>'
        '<circle cx="17.5" cy="17.5" r="4.3" fill="#ffd400" stroke="#111111" stroke-width="1.8"/>'
        '<path d="M15.6 17.5l1.3 1.4 2.7-2.8" fill="none" stroke="#111111" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "visible": (
        '<rect x="2.5" y="2.5" width="17" height="16" rx="3" fill="#ffffff" stroke="#111111" stroke-width="2"/>'
        '<path d="M2.5 5.5a3 3 0 0 1 3-3h11a3 3 0 0 1 3 3V8H2.5V5.5z" fill="#0a84ff" stroke="#111111" stroke-width="2"/>'
        '<path d="M2.5 13.3h17M8.5 8v10.5M14 8v10.5" fill="none" stroke="#111111" stroke-width="1.6"/>'
        '<circle cx="16.5" cy="16.5" r="4.3" fill="#d1fae5" stroke="#111111" stroke-width="1.8"/>'
        '<circle cx="16.5" cy="16.5" r="2.0" fill="#10b981"/>'
        '<path d="M19.7 19.7l2.5 2.5" fill="none" stroke="#111111" stroke-width="2.4" stroke-linecap="round"/>'
    ),
    "edited": (
        '<rect x="2.5" y="2.5" width="17" height="16" rx="3" fill="#ffffff" stroke="#111111" stroke-width="2"/>'
        '<path d="M2.5 5.5a3 3 0 0 1 3-3h11a3 3 0 0 1 3 3V8H2.5V5.5z" fill="#0a84ff" stroke="#111111" stroke-width="2"/>'
        '<rect x="3.5" y="8.8" width="15" height="4.5" fill="#fed7aa"/>'
        '<path d="M2.5 13.3h17M8.5 8v10.5M14 8v10.5" fill="none" stroke="#111111" stroke-width="1.6"/>'
        '<path d="M19.8 9.2l2.3 2.3-7.6 7.6-3.2.9.9-3.2 7.6-7.6z" fill="#f97316" stroke="#111111" '
        'stroke-width="1.7" stroke-linejoin="round"/>'
    ),
}


def scope_launch_icon(scope):
    """Return a QuickTable-styled icon matching a launch scope."""
    body = SCOPE_ICONS.get(scope)
    if body is None:
        return plugin_icon()
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{}</svg>'.format(body)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    icon = QIcon()
    for logical, scale in ((16, 1), (16, 2), (24, 1), (24, 2)):
        pixmap = QPixmap(logical * scale, logical * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        icon.addPixmap(pixmap)
    return icon


def toolbar_icon(name, color):
    """Render a crisp 2x SVG toolbar icon in the given stroke color."""
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


THEMES = {
    "dark": dict(
        bg="#1f1e1d", surface="#262624", alt="#2a2927", border="#3d3d3a", border_hi="#5a5955",
        text="#e8e6dc", text_hi="#faf9f5", text_soft="#c2c0b6", muted="#87867f",
        accent="#73bb98", accent_hi="#88caaa", accent_press="#5aa783", accent_text="#1f1e1d", outside="#e08e36",
        sel_bg="#253c31", sel_fg="#d5efdf", sel_input="#345743", hover_bg="#2f2e2c", press_bg="#2a2927",
        danger="#e0675e", danger_hi="#ff8a80", danger_border="#5a3a37",
        dis_text="#5a5955", dis_border="#2e2d2b", pdis_bg="#293d32", pdis_text="#587965", ddis_text="#5a4442",
        grid="#34332f", scroll="#3d3d3a", scroll_hi="#5a5955",
        preview_halo="#1f1e1d", preview_label_selected="#88caaa", preview_label="#e8e6dc"),
    "light": dict(
        bg="#faf9f5", surface="#ffffff", alt="#f5f4ee", border="#dedcd1", border_hi="#b8b5a8",
        text="#1f1e1d", text_hi="#000000", text_soft="#4a4943", muted="#73726c",
        accent="#2e7d5b", accent_hi="#256649", accent_press="#1c5139", accent_text="#ffffff", outside="#d97706",
        sel_bg="#e7f3ec", sel_fg="#1e4935", sel_input="#e7f3ec", hover_bg="#f0eee6", press_bg="#f0eee6",
        danger="#c0392b", danger_hi="#a52f23", danger_border="#e7b9b3",
        dis_text="#b0aea5", dis_border="#e8e6dc", pdis_bg="#d4e7db", pdis_text="#6f8b7b", ddis_text="#d9a7a1",
        grid="#e6e3d8", scroll="#d4d1c5", scroll_hi="#b8b5a8",
        preview_halo="#ffffff", preview_label_selected="#174d37", preview_label="#454c47"),
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
QFrame#featurePreview, QFrame#tableArea { background: @surface; border: 1px solid @border; border-radius: 6px; }
QLabel#previewTitle { color: @text; font-weight: 700; background: transparent; }
QLabel#previewSecondary { color: @muted; background: transparent; }
QLabel#previewSelectedSwatch { background: @accent; border: none; border-radius: 4px; }
QLabel#previewNearbySwatch { background: @border_hi; border: none; border-radius: 4px; }
QLabel#previewOutsideSwatch { background: @outside; border: none; border-radius: 4px; }
QFrame#previewMapFrame { background: @surface; border: 1px solid @border; border-radius: 2px; }

QLineEdit, QComboBox, QAbstractSpinBox {
    background: @surface; border: 1px solid @border; border-radius: 4px;
    padding: 3px 8px; min-height: 18px; selection-background-color: @sel_input; selection-color: @text_hi;
}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover { border-color: @border_hi; }
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus { border: 1px solid @accent; padding: 3px 8px; }
QPlainTextEdit {
    background: @surface; color: @text; border: 1px solid @border; border-radius: 4px;
    padding: 4px 8px; selection-background-color: @sel_input; selection-color: @text_hi;
}
QPlainTextEdit:hover { border-color: @border_hi; }
QPlainTextEdit:focus { border: 1px solid @accent; }
QComboBox::drop-down { border: none; width: 22px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url(@down_url); width: 10px; height: 10px; }
QAbstractSpinBox, QAbstractSpinBox:focus { padding-right: 28px; }
QAbstractSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 24px;
    border-left: 1px solid @border; border-bottom: 1px solid @border;
    border-top-right-radius: 4px; background: @alt;
}
QAbstractSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right; width: 24px;
    border-left: 1px solid @border; border-bottom-right-radius: 4px; background: @alt;
}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: @hover_bg; }
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed { background: @sel_bg; }
QAbstractSpinBox::up-arrow { image: url(@up_url); width: 10px; height: 10px; }
QAbstractSpinBox::down-arrow { image: url(@down_url); width: 10px; height: 10px; }
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
    """Build the dialog stylesheet for the named theme and font."""
    return _fill(TEMPLATE, name, font_family, font_size)


def dark_palette(widget, name):
    """Apply theme surface/text colors to a widget's QPalette."""
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
    """Style a combo box's popup list view and completer popup."""
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
