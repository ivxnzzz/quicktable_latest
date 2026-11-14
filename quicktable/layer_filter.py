import re
import hashlib
import json
from types import SimpleNamespace

from . import table_actions
from .filter_utils import clipboard_text
from .editing import (convert_attribute, attribute_text, validate_change,
                      validate_pending_changes, validation_request)
from .exporting import export_csv_task
from .filter_logic import FILTER_OPERATORS, field_filter
from .filter_widgets import CheckableValueCombo, ValuePopup
from .compact_filters import FilterHeader, ColumnTextDelegate, StatisticsStrip, NULL_ROLE
from .pagination import PAGE_SIZES, normalize_page_size, page_window
from .themes import (
    ICONS_DIR,
    THEMES,
    _fill,
    build_css,
    dark_palette,
    plugin_icon,
    scope_launch_icon,
    style_combo_popup,
    toolbar_icon,
)
from .tasks import (
    MAX_NEARBY_CANDIDATES,
    MAX_NEARBY_PREVIEW,
    MAX_STAT_DISTINCT,
    MAX_VALUE_FEATURES,
    STAT_HISTOGRAM_BINS,
    collect_column_statistics as _collect_column_statistics,
    collect_feature_ids,
    collect_feature_ids_task,
    collect_nearby,
    collect_nearby_preview,
    collect_nearby_task,
    collect_values,
    field_kind,
    replace_columns_snapshot,
    replace_feature_snapshot,
    replace_suggestions,
)
from .dialogs import (
    AddFieldDialog,
    AutofillDialog,
    BulkEditDialog,
    DeleteFieldsDialog,
    FindReplaceDialog,
    FontPreviewDelegate,
    SettingsDialog,
)
from .preview_panel import (
    EmptyPreviewPanel,
    NearbyPreviewPanel,
    PreviewLabel,
    PreviewPanSelectTool,
    preview_label_angle,
)

from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                                 QComboBox, QLineEdit, QTableWidget,
                                 QTableWidgetItem, QLabel, QPushButton, QToolButton,
                                 QAbstractItemView, QAbstractButton, QFileDialog, QApplication,
                                 QCheckBox, QMessageBox, QFrame,
                                 QListWidget, QListWidgetItem, QDialogButtonBox,
                                 QMenu, QInputDialog, QSplitter)
from qgis.PyQt.QtCore import (Qt, QTimer, QSettings, QMetaType, QSize, QPoint,
                              QItemSelection, QItemSelectionModel)
from qgis.PyQt.QtGui import QAction, QColor, QIcon, QFont, QFontDatabase, QFontMetrics, QBrush
from qgis.core import (QgsProject, QgsMapLayer, QgsFeatureRequest,
                       QgsExpression, QgsApplication, QgsVectorDataProvider,
                       QgsTask, QgsVectorLayerFeatureSource, QgsRectangle,
                       QgsCoordinateTransform, QgsCsException,
                       Qgis, NULL)

NO_FIELD = "(no filter)"
ALL_VALUES = "(all)"
MAX_RENDER_ROWS = 10000
MAX_RENDER_CELLS = 250000
SCOPE_LAUNCH_OPTIONS = (
    ("all", "Open All Features", "Open QuickTable showing all features"),
    ("selected", "Open Selected Features", "Open QuickTable filtered to selected features"),
    ("visible", "Open Visible on Map", "Open QuickTable filtered to features inside the map view"),
    ("edited", "Open Edited and New", "Open QuickTable filtered to unsaved edits and new features"),
)

# signals of a vector layer that mean "the data or fields changed"
LAYER_SIGNALS = ("dataChanged", "updatedFields",
                 "afterCommitChanges", "attributeValueChanged",
                 "featureAdded", "featureDeleted", "geometryChanged")
EDIT_STATE_SIGNALS = ("editingStarted", "editingStopped",
                      "readOnlyChanged", "supportsEditingChanged")


def collect_column_statistics(task, source, columns, ids, max_distinct=None, full_layer=False):
    """Forward to tasks.collect_column_statistics while honoring patched MAX_STAT_DISTINCT."""
    limit = MAX_STAT_DISTINCT if max_distinct is None else max_distinct
    return _collect_column_statistics(task, source, columns, ids, max_distinct=limit, full_layer=full_layer)


def _attribute_request(fids=None, attributes=None):
    """Build a NoGeometry attribute-only feature request."""
    request = QgsFeatureRequest()
    request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
    if fids is not None:
        request.setFilterFids(list(fids))
    if attributes is not None:
        request.setSubsetOfAttributes(list(attributes))
    return request


def edited_feature_ids(layer):
    """Return sorted IDs of modified or newly added features in the active edit buffer."""
    buf = layer.editBuffer() if layer is not None and layer.isEditable() else None
    if buf is None:
        return ()
    fids = set(buf.addedFeatures()) | set(buf.changedAttributeValues()) | set(buf.changedGeometries())
    fids.difference_update(buf.deletedFeatureIds())
    return tuple(sorted(fids))


class SortItem(QTableWidgetItem):
    """Sorts numbers as numbers, text as text (like Excel)."""

    def __lt__(self, other):
        a, b = self.text(), other.text()
        try:
            return float(a) < float(b)
        except ValueError:
            return a.lower() < b.lower()


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
        self._column_layout_dirty = True
        self._rows_were_wrapped = False
        self.pending_column_widths = {}
        self.filter_rows = []
        self.filters_ready = False
        self.pending_cascade_start = None
        self._stale_value_rows = set()
        self._populated_columns = set()
        self.table_layer_id = None
        self.result_key = None
        self.result_ids = None
        self._result_id_set = None
        self._result_ids_token = None
        self.query_task = None
        self.csv_task = None
        self.query_version = 0
        self.page = 0
        self.pending_selection = set()
        self.syncing_map_selection = False
        self.selected_scope_ids = None
        self._pending_initial_scope = None
        self.nearby_origin_ids = None
        self.nearby_match_ids = None
        self.nearby_task = None
        self.nearby_preview_dialog = None
        self.nearby_version = 0
        self.nearby_enabled = False
        self.preview_label_fields = {}
        self.preview_extents = {}
        self.preview_selection = {}
        self.preview_width = 320
        self.pending_preview_focus = None
        self.statistics_task = None
        self.replace_task = None
        self.statistics_version = 0
        self.statistics_key = None
        self.pending_notice = None
        self.pending_added_field = None
        self.hooked_layer = None
        self.hooked_id = None
        self.hooked_undo_stack = None
        self.hooked_canvas = None
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
        self.canvas_extent_timer = QTimer(self)
        self.canvas_extent_timer.setSingleShot(True)
        self.canvas_extent_timer.setInterval(250)
        self.canvas_extent_timer.timeout.connect(self.on_canvas_extent_timeout)
        self.nearby_update_timer = QTimer(self)
        self.nearby_update_timer.setSingleShot(True)
        self.nearby_update_timer.setInterval(25)
        self.nearby_update_timer.timeout.connect(self.start_nearby_preview)
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
        self.btn_clear_filters.setToolTip("Clear column filters, search and feature scope; keep the map selection")
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
        self.scope_combo = QComboBox()
        self.scope_combo.setObjectName("scopePicker")
        self.scope_combo.addItem("All features", "all")
        self.scope_combo.addItem("Selected features", "selected")
        self.scope_combo.addItem("Visible on map", "visible")
        self.scope_combo.addItem("Edited and new", "edited")
        self.scope_combo.setToolTip("Show all features, the QGIS selection, features in the map extent, or unsaved edits")
        self.multi_cb.setToolTip("Click rows to toggle selection without holding Ctrl. Turn off to use Ctrl/Shift selection.")
        self.selection_status = QLabel("0 selected")
        self.btn_select.setToolTip("Select all rows on the current page, on the table and map")
        self.btn_unselect.setToolTip("Clear the table selection and the selected layer's map selection")
        self.btn_bulk = QPushButton("Bulk edit…")
        self.btn_autofill = QPushButton("Autofill…")
        self.btn_replace = QPushButton("Find and replace…")
        self.btn_fields = QPushButton("Fields ▾")
        self.btn_fields.setObjectName("fieldsButton")
        self.fields_menu = QMenu(self.btn_fields)
        self.btn_add_field = self.fields_menu.addAction("Add field…")
        self.btn_delete_field = self.fields_menu.addAction("Delete field…")
        self.btn_fields.setToolTip("Add or delete a layer attribute")
        self.btn_nearby = QPushButton("Features Preview")
        self.btn_nearby.setObjectName("statsToggle")
        self.btn_nearby.setCheckable(True)
        self.btn_nearby.setChecked(False)
        self.btn_nearby.setToolTip("Show or hide the layer and selected-feature preview")
        for widget in (self.btn_columns, self.btn_select, self.btn_unselect):
            tools.addWidget(widget)
        tools.addWidget(self.multi_cb)
        tools.addWidget(self.scope_combo)
        tools.addStretch(1)
        tools.addWidget(self.selection_status)
        tools.addSpacing(6)
        tools.addWidget(self.btn_nearby)
        clay.addWidget(self.selection_tools, 1, 0, 1, 2)

        self.table = QTableWidget()
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
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
        table_area = QFrame()
        table_area.setObjectName('tableArea')
        table_layout = QVBoxLayout(table_area)
        table_layout.setContentsMargins(10, 10, 10, 10)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.statistics_strip)
        table_layout.addWidget(self.table)
        self.nearby_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.nearby_splitter.setChildrenCollapsible(False)
        self.nearby_splitter.addWidget(table_area)
        self.nearby_splitter.setStretchFactor(0, 1)
        lay.addWidget(self.nearby_splitter, 1)

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
        erow.addWidget(self.btn_replace)
        erow.addWidget(self.btn_fields)
        erow.addWidget(self.btn_delete)
        erow.addStretch(1)
        clay.addWidget(self.edit_tools, 2, 0, 1, 2)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("status")
        bottom.addWidget(self.status, 1)
        self.btn_zoom = QPushButton("Zoom to selected")
        self.btn_zoom.setEnabled(False)
        self.btn_zoom.setToolTip("Select one or more features in the table or map to zoom")
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
        self.btn_zoom.clicked.connect(self.zoom_selected)
        self.btn_select.clicked.connect(self.select_all)
        self.btn_unselect.clicked.connect(self.unselect_all)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_columns.clicked.connect(self.choose_columns)
        self.btn_bulk.clicked.connect(self.bulk_edit)
        self.btn_autofill.clicked.connect(self.autofill)
        self.btn_replace.clicked.connect(self.find_replace)
        self.btn_add_field.triggered.connect(self.add_field)
        self.btn_delete_field.triggered.connect(self.delete_field)
        self.btn_fields.clicked.connect(lambda: self.fields_menu.popup(
            self.btn_fields.mapToGlobal(QPoint(0, self.btn_fields.height()))))
        self.btn_nearby.toggled.connect(self.set_nearby_preview_enabled)
        self.scope_combo.currentIndexChanged.connect(self.on_scope_changed)
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
        canvas = self.iface.mapCanvas() if self.iface and hasattr(self.iface, "mapCanvas") else None
        if canvas is not None and hasattr(canvas, "extentsChanged"):
            self.hooked_canvas = canvas
            canvas.extentsChanged.connect(self.on_canvas_extents_changed)

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

        full_layer = (
            not layer.isEditable()
            and self.result_key is not None
            and self.result_key[0] == layer.id()
            and not self.result_key[1]
            and self.result_key[2] == "all"
            and self.result_key[3] is None
            and self.result_key[4] is None
        )
        try:
            task = QgsTask.fromFunction("QuickTable: column statistics", collect_column_statistics,
                                        source=QgsVectorLayerFeatureSource(layer), columns=columns,
                                        ids=ids, full_layer=full_layer, on_finished=finished)
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
        if self.nearby_preview_dialog is not None and hasattr(self.nearby_preview_dialog, 'canvas'):
            self.nearby_preview_dialog.canvas.setCanvasColor(QColor(THEMES[self.theme]["surface"]))
            if isinstance(self.nearby_preview_dialog, NearbyPreviewPanel):
                self.nearby_preview_dialog.refresh_feature_bands()
                self.nearby_preview_dialog.update_labels()
            else:
                self.nearby_preview_dialog.canvas.refresh()
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
        style_combo_popup(value, self.theme, self.font_family, self.font_size)
        style_combo_popup(operator, self.theme, self.font_family, self.font_size)
        style_combo_popup(number_format, self.theme, self.font_family, self.font_size)
        field.currentIndexChanged.connect(lambda *args, row=row: self.on_filter_field_changed(row))
        operator.currentIndexChanged.connect(lambda *args, row=row: self.on_filter_operator_changed(row))
        value.currentTextChanged.connect(lambda *args, row=row: self.queue_filter_change(row))
        value.checkedValuesChanged.connect(lambda row=row: self.queue_filter_change(row))
        upper.textChanged.connect(lambda *args, row=row: self.queue_filter_change(row))
        remove.clicked.connect(lambda *args, row=row: self.remove_filter_row(row))
        if self.filters_ready:
            self.populate_filter_field(row)
            self.sync_filter_inputs()
            FinderDialog._init_value_combo(value)
            self._stale_value_rows.add(id(row))
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
        if id(row) in self._stale_value_rows:
            self._reload_filter_row_values(row)
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
        self._stale_value_rows.discard(id(row))
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
        self._stale_value_rows.clear()

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
        visible_unpopulated = False
        for column, name in enumerate(self.fields):
            is_hidden = name in hidden
            self.table.setColumnHidden(column, is_hidden)
            if not is_hidden and column not in self._populated_columns:
                visible_unpopulated = True
        self.btn_columns.setEnabled(bool(self.fields))
        if (
            visible_unpopulated
            and not self.applying_column_layout
            and self.result_ids is not None
            and self.table.columnCount() == len(self.fields)
            and self.table.rowCount() > 0
        ):
            self.render_page()

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
        header = self.table.horizontalHeader()
        metrics = header.fontMetrics()
        widths = self.saved_column_widths(key)
        for name in self.fields:
            widths[name] = max(90, header.minimumSectionSize(), metrics.horizontalAdvance(name) + 36)
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
            self._column_layout_dirty = False
            widths = self.saved_column_widths(key)
            wrapped = self.wrapped_fields()
            number_formats = self.number_formats()
            layer = self.current_layer()
            # Keep viewport expansion from being saved as an explicit field width.
            self.table.horizontalHeader().setStretchLastSection(False)
            for column, name in enumerate(self.fields):
                if name not in self.column_delegates:
                    self.column_delegates[name] = ColumnTextDelegate(self.table)
                delegate = self.column_delegates[name]
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
        has_wrapped = any(name in wrapped and not self.table.isColumnHidden(column)
                          for column, name in enumerate(self.fields))
        if has_wrapped:
            self.table.resizeRowsToContents()
            self._rows_were_wrapped = True
        else:
            height = max(23, QFontMetrics(QFont(self.font_family, self.font_size)).height() + 10)
            self.table.verticalHeader().setDefaultSectionSize(height)
            if self._rows_were_wrapped:
                for row in range(self.table.rowCount()):
                    self.table.setRowHeight(row, height)
            self._rows_were_wrapped = False
        self.table.viewport().update()

    def resize_table_row(self, row, column=None):
        """Resize one edited row when wrapping is enabled on a visible column."""
        if self.layout_settings_key != self.column_settings_key() or self.table.columnCount() != len(self.fields):
            return
        wrapped = self.wrapped_fields()
        if any(name in wrapped and not self.table.isColumnHidden(c) for c, name in enumerate(self.fields)):
            if column is None or (column < len(self.fields) and self.fields[column] in wrapped and not self.table.isColumnHidden(column)):
                self.table.resizeRowToContents(row)
                self._rows_were_wrapped = True
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
        if self.replace_task is not None:
            self.replace_task.cancel()
            self.replace_task = None
        if self.csv_task is not None:
            self.csv_task.cancel()
            self.csv_task = None
        self.layer_list_timer.stop()
        self.update_validity_watchers([])
        self.statistics_refresh_timer.stop()
        self.cancel_statistics()
        self.selection_filter_timer.stop()
        self.canvas_extent_timer.stop()
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
        if self.hooked_canvas is not None and hasattr(self.hooked_canvas, "extentsChanged"):
            try:
                self.hooked_canvas.extentsChanged.disconnect(self.on_canvas_extents_changed)
            except (TypeError, RuntimeError):
                pass
            self.hooked_canvas = None
        self.unhook_layer()
        self.timer.stop()
        self.close()
        self.deleteLater()

    # ---------- layer list / active layer ----------
    def refresh(self, initial_scope=None):
        """Use QGIS's current vector layer only to initialize the layer choice."""
        self._pending_initial_scope = initial_scope
        try:
            current = self.current_layer()
            active = self.iface.activeLayer()
            prefer = current.id() if current is not None else (
                active.id() if active is not None and active.type() == QgsMapLayer.LayerType.VectorLayer and active.isValid() else None)
            self.rebuild_layer_list(prefer)
            self.edit.setFocus()
        finally:
            self._pending_initial_scope = None

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
        self.pending_preview_focus = None
        self._column_layout_dirty = True
        self.selection_filter_timer.stop()
        self.canvas_extent_timer.stop()
        self.cancel_nearby()
        if self._pending_initial_scope:
            self.set_scope(self._pending_initial_scope, run=False)
        else:
            self.reset_scope_control()
        self.filter_timer.stop()
        self.pending_cascade_start = None
        self.search_timer.stop()
        self.hook_layer()
        self.load_fields(keep=False)
        self.schedule_nearby_preview()

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
            for name in EDIT_STATE_SIGNALS:
                try:
                    getattr(self.hooked_layer, name).disconnect(self.sync_edit_state)
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
        for name in EDIT_STATE_SIGNALS:
            try:
                getattr(layer, name).connect(self.sync_edit_state)
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
        self.invalidate_nearby_after_layer_change()
        self.invalidate_results()
        if self.isVisible():
            self.timer.start()

    def soft_refresh(self, *args):
        """Re-read fields and value lists, keeping the current choices if they still exist."""
        self.edit_failure = None
        self._column_layout_dirty = True
        self.invalidate_nearby_after_layer_change()
        self.invalidate_results()
        if self.current_layer() is None:
            self.hook_layer()
            self.load_fields(keep=False)
            return
        if self._pending_initial_scope:
            self.set_scope(self._pending_initial_scope, run=False)
        self.load_fields(keep=True)

    # ---------- fields and value lists ----------
    def load_fields(self, keep=False):
        layer = self.current_layer()
        self.fields = list(layer.fields().names()) if layer else []
        self.update_scope_options()
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

    def _reload_filter_row_values(self, row, preserve=True):
        """Reload unique value suggestions for a single filter row."""
        self._stale_value_rows.discard(id(row))
        text = row.value.currentText()
        self.fill_values(row.field, row.value, self.other_filters_expr(row))
        if preserve:
            self.restore_value(row.value, text)

    def reload_value_lists(self, start=0, preserve=True):
        for index in range(start, len(self.filter_rows)):
            filter_row = self.filter_rows[index]
            if filter_row.widget.isVisible():
                self._reload_filter_row_values(filter_row, preserve=preserve)
            else:
                self.value_versions[filter_row.value] = self.value_versions.get(filter_row.value, 0) + 1
                task = self.value_tasks.pop(filter_row.value, None)
                if task is not None:
                    task.cancel()
                self._stale_value_rows.add(id(filter_row))

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

    @staticmethod
    def _init_value_combo(value_combo):
        """Reset combo items to the unloaded ALL_VALUES placeholder without scanning."""
        blocked = value_combo.blockSignals(True)
        try:
            value_combo.clear()
            value_combo.addItem(ALL_VALUES, None)
            value_combo.setCurrentIndex(0)
        finally:
            value_combo.blockSignals(blocked)
        if isinstance(value_combo, CheckableValueCombo):
            value_combo.update_checked_text()

    def fill_values(self, field_combo, value_combo, base_expr):
        version = self.value_versions.get(value_combo, 0) + 1
        self.value_versions[value_combo] = version
        previous = self.value_tasks.pop(value_combo, None)
        if previous is not None:
            previous.cancel()
        FinderDialog._init_value_combo(value_combo)
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
            value_combo.setUpdatesEnabled(False)
            try:
                value_combo.clear()
                value_combo.addItem(ALL_VALUES, None)
                for text in sorted(values, key=self.natural_key):
                    value_combo.addItem(text, values[text])
                self.restore_value(value_combo, current)
            finally:
                value_combo.setUpdatesEnabled(True)
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
        if row.widget.isVisible():
            self._stale_value_rows.discard(id(row))
            self.fill_values(row.field, row.value, self.other_filters_expr(row))
        else:
            self.value_versions[row.value] = self.value_versions.get(row.value, 0) + 1
            task = self.value_tasks.pop(row.value, None)
            if task is not None:
                task.cancel()
            FinderDialog._init_value_combo(row.value)
            self._stale_value_rows.add(id(row))
        try:
            expr_changed = self.result_key is None or self.build_expr() != self.result_key[1]
        except ValueError:
            expr_changed = True
        if expr_changed:
            self.queue_filter_change(row)
        else:
            self.update_filter_rows_layout()

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
        self.canvas_extent_timer.stop()
        self.pending_cascade_start = None
        self.reset_scope_control()
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self.clear_filter_rows()
        self.run_search()

    def current_scope(self):
        """Return the active table scope key ('all', 'selected', 'visible', or 'edited')."""
        return self.scope_combo.currentData() or "all"

    def reset_scope_control(self):
        """Reset the scope selector to All features without emitting a search."""
        self.scope_combo.blockSignals(True)
        index = self.scope_combo.findData("all")
        self.scope_combo.setCurrentIndex(index if index >= 0 else 0)
        self.scope_combo.blockSignals(False)
        self.selected_scope_ids = None

    def update_scope_options(self):
        """Enable map-extent filtering only for spatial layers."""
        layer = self.current_layer()
        spatial = bool(layer is not None and layer.isSpatial())
        idx = self.scope_combo.findData("visible")
        model = self.scope_combo.model()
        if idx >= 0 and hasattr(model, "item"):
            item = model.item(idx)
            if item is not None:
                flags = item.flags()
                if spatial:
                    item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                else:
                    item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
        if not spatial and self.current_scope() == "visible":
            self.reset_scope_control()

    def set_scope(self, scope, run=True):
        """Set the active scope ('all', 'selected', 'visible', or 'edited')."""
        layer = self.current_layer()
        self.selection_filter_timer.stop()
        self.canvas_extent_timer.stop()
        if scope == "visible" and (layer is None or not layer.isSpatial()):
            scope = "all"
        idx = self.scope_combo.findData(scope)
        if idx < 0:
            idx = self.scope_combo.findData("all")
            scope = "all"
        self.scope_combo.blockSignals(True)
        self.scope_combo.setCurrentIndex(max(0, idx))
        self.scope_combo.blockSignals(False)
        self.selected_scope_ids = tuple(sorted(layer.selectedFeatureIds())) if scope == "selected" and layer else None
        self.page = 0
        if run:
            self.run_search()

    def on_scope_changed(self, *args):
        self.set_scope(self.current_scope(), run=True)

    def set_selected_scope(self, enabled):
        """Compatibility helper for toggling the Selected features scope."""
        self.set_scope("selected" if enabled else "all")

    def canvas_layer_extent(self, layer):
        """Return the active QGIS map canvas extent transformed into the layer's CRS."""
        if layer is None or not layer.isSpatial():
            return ()
        canvas = self.iface.mapCanvas() if self.iface and hasattr(self.iface, "mapCanvas") else None
        if canvas is None or not hasattr(canvas, "extent"):
            return ()
        extent = canvas.extent()
        if extent is None or extent.isNull() or extent.isEmpty():
            return ()
        if hasattr(canvas, "mapSettings"):
            canvas_crs = canvas.mapSettings().destinationCrs()
            layer_crs = layer.crs()
            if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
                extent = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance()).transformBoundingBox(extent)
        if extent.isNull() or extent.isEmpty():
            return ()
        return (float(extent.xMinimum()), float(extent.yMinimum()),
                float(extent.xMaximum()), float(extent.yMaximum()))

    def active_scope_filter(self, layer):
        """Return (filter_fids, filter_rect) for the currently selected scope."""
        scope = self.current_scope()
        if scope == "selected":
            self.selected_scope_ids = tuple(sorted(layer.selectedFeatureIds())) if layer else ()
            return self.selected_scope_ids, None
        self.selected_scope_ids = None
        if scope == "edited":
            return edited_feature_ids(layer), None
        if scope == "visible":
            return None, self.canvas_layer_extent(layer)
        return None, None

    def on_canvas_extents_changed(self, *args):
        if not self.closing and self.isVisible() and self.current_scope() == "visible":
            self.canvas_extent_timer.start()

    def on_canvas_extent_timeout(self):
        if not self.closing and self.isVisible() and self.current_scope() == "visible":
            self.run_search()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.closing and (self.current_scope() == "visible"
                                 or (self.result_ids is None and self.current_layer() is not None
                                     and self.query_task is None and not self.timer.isActive())):
            self.run_search()

    def invalidate_nearby_after_layer_change(self):
        self.schedule_nearby_preview()

    def invalidate_nearby_after_attribute_edit(self, field_name):
        """Keep existing touching geometry intact after attribute-only edits."""
        had_pending = self.nearby_task is not None or self.nearby_update_timer.isActive()
        keep_preview = (not self.closing and self.nearby_enabled
                        and isinstance(self.nearby_preview_dialog, (EmptyPreviewPanel, NearbyPreviewPanel))
                        and self.nearby_preview_dialog.layer == self.current_layer())
        self.cancel_nearby(keep_preview=keep_preview)
        if had_pending and not self.closing and self.nearby_enabled:
            self.schedule_nearby_preview()
            return
        preview = self.nearby_preview_dialog
        if isinstance(preview, NearbyPreviewPanel) and preview.layer == self.current_layer():
            if preview.label_field.currentData() == field_name:
                preview.update_labels(refresh_values=True)

    def cancel_nearby(self, keep_preview=False):
        self.nearby_version += 1
        self.nearby_update_timer.stop()
        if self.nearby_task is not None:
            self.nearby_task.cancel()
            self.nearby_task = None
        if not keep_preview:
            self.close_nearby_preview()
        self.nearby_origin_ids = None
        self.nearby_match_ids = None

    def close_nearby_preview(self):
        if self.nearby_preview_dialog is not None:
            preview = self.nearby_preview_dialog
            self.nearby_preview_dialog = None
            if isinstance(preview, NearbyPreviewPanel):
                self.preview_extents[preview.layer_id] = QgsRectangle(preview.canvas.extent())
            self.preview_width = preview.width()
            preview.hide()
            preview.setParent(None)
            preview.deleteLater()

    def apply_nearby_preview_snapshot(self, layer, selected_ids, nearby_ids, snapshot, nearby_limited=False):
        """Render a completed nearby-preview WKB snapshot on the sidebar canvas."""
        current_selection = frozenset(selected_ids)
        recenter = self.preview_selection.get(layer.id()) != current_selection
        self.preview_selection[layer.id()] = current_selection
        existing = self.nearby_preview_dialog
        if isinstance(existing, NearbyPreviewPanel) and existing.layer == layer:
            extent = QgsRectangle(existing.canvas.extent())
            self.preview_extents[layer.id()] = extent
            existing.update_snapshot(snapshot, len(nearby_ids), extent, recenter,
                                     nearby_limited=nearby_limited)
        else:
            self.close_nearby_preview()
            preview = NearbyPreviewPanel(self, layer, snapshot, len(nearby_ids),
                                         self.preview_extents.get(layer.id()), recenter,
                                         nearby_limited=nearby_limited)
            self.display_preview_panel(preview)
        self.nearby_origin_ids = selected_ids
        self.nearby_match_ids = nearby_ids

    def set_nearby_preview_enabled(self, enabled):
        self.nearby_enabled = bool(enabled)
        self.schedule_nearby_preview()

    def display_preview_panel(self, preview):
        self.nearby_preview_dialog = preview
        self.nearby_splitter.addWidget(preview)
        self.nearby_splitter.setStretchFactor(1, 0)
        preview.show()
        width = self.nearby_splitter.width() - self.nearby_splitter.handleWidth()
        self.nearby_splitter.setSizes([max(1, width - self.preview_width), self.preview_width])

    def hide_nearby_preview(self):
        self.btn_nearby.setChecked(False)

    def schedule_nearby_preview(self, *args):
        layer = self.current_layer()
        keep_preview = (not self.closing and self.nearby_enabled and layer is not None
                        and bool(layer.selectedFeatureIds())
                        and isinstance(self.nearby_preview_dialog, (EmptyPreviewPanel, NearbyPreviewPanel))
                        and self.nearby_preview_dialog.layer == layer)
        self.cancel_nearby(keep_preview=keep_preview)
        if (not self.closing and self.nearby_enabled and layer is not None and layer.isSpatial()):
            self.nearby_update_timer.start()

    def start_nearby_preview(self):
        layer = self.current_layer()
        if self.closing or not self.nearby_enabled or layer is None or not layer.isSpatial():
            return
        ids = tuple(layer.selectedFeatureIds())
        if not ids:
            self.display_preview_panel(EmptyPreviewPanel(self, layer))
            return
        version = self.nearby_version

        def finished(exception, result=None):
            if self.nearby_task is not task:
                return
            self.nearby_task = None
            if (self.closing or not self.nearby_enabled or version != self.nearby_version
                    or self.current_layer() != layer or set(layer.selectedFeatureIds()) != set(ids)):
                return
            if exception is not None:
                self.status.setText("Map preview failed: {}".format(exception))
                return
            if result is None:
                return
            raw_matches, scan_limited, snapshot = result
            raw_matches = tuple(raw_matches)
            nearby_limited = bool(scan_limited) or len(raw_matches) > MAX_NEARBY_PREVIEW
            matches = raw_matches[:MAX_NEARBY_PREVIEW]
            self.apply_nearby_preview_snapshot(layer, ids, matches, snapshot, nearby_limited=nearby_limited)

        try:
            task = QgsTask.fromFunction("QuickTable: find nearby features", collect_nearby_task,
                source=QgsVectorLayerFeatureSource(layer), selected_ids=ids, distance=None,
                max_matches=MAX_NEARBY_PREVIEW + 1, max_candidates=MAX_NEARBY_CANDIDATES,
                preview_limit=MAX_NEARBY_PREVIEW, label_field=self.preview_label_fields.get(layer.id()),
                on_finished=finished)
            task.setDependentLayers([layer])
            self.nearby_task = task
            QgsApplication.taskManager().addTask(task)
        except Exception as exc:
            self.nearby_task = None
            self.status.setText("Map preview failed: {}".format(exc))

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
        entries[name] = {"search": self.edit.text(),
            "hidden_columns": [field for i, field in enumerate(self.fields) if self.table.isColumnHidden(i)],
            "sort_field": self.sort_field, "sort_descending": self.sort_order == Qt.SortOrder.DescendingOrder,
            "filters": [
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
        missing = []
        if "hidden_columns" in saved and isinstance(saved["hidden_columns"], list):
            hidden = [field for field in saved["hidden_columns"] if field in self.fields]
            missing.extend(str(field) for field in saved["hidden_columns"] if field not in self.fields)
            QSettings().setValue(self.column_settings_key(), hidden)
            self._column_layout_dirty = True
            self.apply_column_visibility()
        if "sort_field" in saved:
            sort_field = saved.get("sort_field")
            if sort_field and sort_field not in self.fields:
                missing.append(str(sort_field))
            self.sort_field = sort_field if sort_field in self.fields else None
            self.sort_order = Qt.SortOrder.DescendingOrder if saved.get("sort_descending") else Qt.SortOrder.AscendingOrder
        self.filter_timer.stop()
        self.filters_ready = False
        try:
            self.clear_filter_rows()
            self.edit.setText(str(saved.get("search", "")))
            for spec in saved["filters"]:
                if not isinstance(spec, dict) or spec.get("field") not in self.fields or spec.get("operator") not in FILTER_OPERATORS:
                    if isinstance(spec, dict) and spec.get("field") not in self.fields:
                        missing.append(str(spec.get("field", "unknown")))
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
        notices = []
        if missing:
            notices.append("Preset skipped missing fields: " + ", ".join(sorted(set(missing))))
        if saved.get("advanced"):
            notices.append("Preset's advanced filter is no longer supported and was not applied")
        self.run_search()
        if notices:
            QMessageBox.information(self, "Saved filters", "; ".join(notices))

    # ---------- filtering ----------
    def build_expr(self):
        parts = [self.part_expr(row.field, row.value) for row in self.filter_rows]
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
        self._populated_columns.clear()

    def result_id_set(self):
        """Return a cached set of current result_ids for O(1) membership checks."""
        if self.result_ids is None:
            return None
        token = (self.query_version, id(self.result_ids), len(self.result_ids))
        if self._result_id_set is None or self._result_ids_token != token:
            self._result_id_set = set(self.result_ids)
            self._result_ids_token = token
        return self._result_id_set

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
        self._result_id_set = None
        self._result_ids_token = None

    def update_pager(self):
        size = self.page_size.currentData()
        self.btn_select.setText("Select page" if size else "Select all")
        self.btn_select.setToolTip("Select every row on this page on the table and map" if size else
                                   "Select all matching results on the table and map")
        self.update_zoom_button()
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
            filter_fids, filter_rect = self.active_scope_filter(layer)
        except Exception as e:
            self.invalidate_results()
            self.result_key = None
            self.pending_selection.clear()
            self.clear_results("Filter problem: {}".format(e))
            return
        sort_field = self.sort_field if self.sort_field in self.fields else None
        key = (layer.id(), expression, self.current_scope(), filter_fids, filter_rect, sort_field, self.sort_order)
        if key == self.result_key:
            if self.result_ids is not None:
                self.render_page()
                return
            if self.query_task is not None:
                return

        previous_selection = set(self.selected_fids()) | self.pending_selection if self.table_layer_id == layer.id() else set()
        preserve_table = (
            self.table_layer_id == layer.id()
            and self.layout_fields == list(self.fields)
            and self.table.columnCount() == len(self.fields)
            and len(self.fields) > 0
        )
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
            self._result_id_set = None
            self._result_ids_token = None
            self.render_page()

        try:
            source = QgsVectorLayerFeatureSource(layer)
            task = QgsTask.fromFunction("QuickTable: find matches", collect_feature_ids_task,
                                        source=source, expression=expression, sort_field=sort_field,
                                        ascending=self.sort_order == Qt.SortOrder.AscendingOrder,
                                        filter_fids=filter_fids, filter_rect=filter_rect, on_finished=finished)
            task.setDependentLayers([layer])
            self.query_task = task
            if preserve_table:
                self.status.setText("Finding matching records…")
                self.update_pager()
            else:
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
        same_schema = (
            not self._column_layout_dirty
            and self.table.columnCount() == len(self.fields)
            and self.layout_fields == list(self.fields)
            and self.layout_settings_key == self.column_settings_key()
        )
        previous_column_layout = self.applying_column_layout
        self.applying_column_layout = True
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        try:
            if not layer:
                self.clear_table()
                self.status.setText("No vector layer selected")
                return

            if same_schema:
                self.table.setSortingEnabled(False)
            else:
                self.clear_table()
                self.table.setColumnCount(len(self.fields))
                self.table.setHorizontalHeaderLabels(self.fields)
                self.apply_column_visibility()

            num_fields = len(self.fields)
            visible_columns = [c for c in range(num_fields) if not self.table.isColumnHidden(c)]
            visible_set = set(visible_columns)

            req = QgsFeatureRequest().setFilterFids(list(page_ids))
            req.setFlags(QgsFeatureRequest.Flag.NoGeometry)
            req.setSubsetOfAttributes(visible_columns)
            if page_ids:
                iterator = layer.getFeatures(req)
                try:
                    features = {feature.id(): feature for feature in iterator}
                finally:
                    iterator.close()
            else:
                features = {}
            page_features = [(fid, features[fid]) for fid in page_ids if fid in features]

            self.table.verticalHeader().setMinimumWidth(
                max(42, self.table.fontMetrics().horizontalAdvance(str(len(self.result_ids))) + 20))
            self.table.setRowCount(len(page_features))

            form = layer.editFormConfig()
            layer_fields = layer.fields()
            edit_buffer = layer.editBuffer() if layer.isEditable() else None
            changed_attributes = edit_buffer.changedAttributeValues() if edit_buffer else {}
            readonly_columns = {c for c in visible_columns
                                if form.readOnly(c) or (hasattr(layer_fields[c], "isReadOnly")
                                                        and layer_fields[c].isReadOnly())}
            edited_bg = QBrush(QColor("#365345" if self.theme == "dark" else "#d8efdf"))
            clear_bg = QBrush()
            base_flags = QTableWidgetItem().flags()

            for r, (fid, feat) in enumerate(page_features):
                attrs = feat.attributes()
                row_label = str(window.start + r + 1)
                vitem = self.table.verticalHeaderItem(r) if same_schema else None
                if vitem is not None:
                    vitem.setText(row_label)
                else:
                    self.table.setVerticalHeaderItem(r, QTableWidgetItem(row_label))
                feat_changed = changed_attributes.get(fid, {})
                for c in range(num_fields):
                    if c not in visible_set:
                        if c == 0:
                            # Column 0 item carries the row's FID in UserRole even when hidden.
                            existing = self.table.item(r, 0) if same_schema else None
                            reused = isinstance(existing, SortItem)
                            item = existing if reused else SortItem("")
                            if reused and item.text():
                                item.setText("")
                            item.setData(Qt.ItemDataRole.UserRole, fid)
                            if not reused:
                                self.table.setItem(r, 0, item)
                        continue
                    v = attrs[c] if c < len(attrs) else None
                    text = attribute_text(v)
                    existing = self.table.item(r, c) if same_schema else None
                    reused = isinstance(existing, SortItem)
                    item = existing if reused else SortItem(text)
                    if reused:
                        item.setText(text)
                    item.setData(NULL_ROLE, v is None or v == NULL)
                    if c in feat_changed:
                        item.setBackground(edited_bg)
                        tooltip = "Unsaved attribute change"
                    else:
                        if reused:
                            item.setBackground(clear_bg)
                        tooltip = ""
                    flags = base_flags & ~Qt.ItemFlag.ItemIsEditable if c in readonly_columns else base_flags
                    if c in readonly_columns:
                        tooltip = "This field is read-only in the layer configuration or data source"
                    if reused or c in readonly_columns:
                        item.setFlags(flags)
                    if reused or tooltip:
                        item.setToolTip(tooltip)
                    if c == 0:
                        item.setData(Qt.ItemDataRole.UserRole, fid)
                    elif reused:
                        item.setData(Qt.ItemDataRole.UserRole, None)
                    if not reused:
                        self.table.setItem(r, c, item)
            self._populated_columns = visible_set
            r = len(page_features)

            if self.sort_field in self.fields:
                self.table.horizontalHeader().setSortIndicator(self.fields.index(self.sort_field), self.sort_order)
            self.table.horizontalHeader().setSortIndicatorShown(self.sort_field in self.fields)
            if same_schema:
                self.resize_wrapped_rows()
            else:
                self.apply_column_layout()
            pending = self.pending_added_field
            self.pending_added_field = None
            if pending and pending[0] == layer.id() and pending[1] in self.fields:
                column = self.fields.index(pending[1])
                if self.table.rowCount():
                    target = self.table.item(0, column)
                    if target is not None:
                        self.table.scrollToItem(target, QAbstractItemView.ScrollHint.EnsureVisible)
                else:
                    self.table.horizontalScrollBar().setValue(self.table.horizontalScrollBar().maximum())
            self.select_table_fids(previous_selection)
            message = ("No matching records. Adjust a column filter or search to see results."
                       if not self.result_ids else
                       "{} record(s)  |  click a column name to sort or its filter below".format(r))
            if self.pending_notice and layer.isModified():
                message = self.pending_notice
            self.pending_notice = None
            self.status.setText(render_notice + message)
        except Exception as e:
            self.clear_table()
            self.status.setText("Filter problem: {}  (try Refresh lists or Clear filters)".format(e))
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(False)
            self.applying_column_layout = previous_column_layout
            self.update_selection_status()
            self.update_pager()
            self.btn_columns.setEnabled(bool(self.fields))
        if self.table.columnCount() == len(self.fields):
            # Defer queueing statistics_task until query_task finishes retiring in QgsTaskManager.
            self.schedule_statistics_refresh()
        elif self.btn_statistics.isChecked():
            self.statistics_refresh_timer.stop()
            self.cancel_statistics()
            self.statistics_strip.set_state("error", message=self.status.text())
        if isinstance(self.nearby_preview_dialog, NearbyPreviewPanel) and self.nearby_preview_dialog.layer == layer:
            band_token = (self.query_version, id(self.result_ids))
            if getattr(self.nearby_preview_dialog, "_band_result_token", None) != band_token:
                self.nearby_preview_dialog.refresh_feature_bands()
        if self.pending_preview_focus and not self.selection_filter_timer.isActive():
            layer_id, fid = self.pending_preview_focus
            self.pending_preview_focus = None
            if layer.id() == layer_id and fid in layer.selectedFeatureIds():
                self.focus_preview_feature(layer, fid)

    def can_select_preview_feature(self, layer, fid):
        """Restrict preview clicks to features in the table while Scope is Visible on map."""
        if self.current_layer() != layer:
            return False
        if self.current_scope() != "visible":
            return True
        id_set = self.result_id_set()
        if id_set is None:
            self.status.setText("Wait for Visible on map results to finish loading before selecting from the preview.")
            return False
        if fid not in id_set:
            self.status.setText("Only features in the current Visible on map table can be selected from Features Preview.")
            return False
        return True

    def focus_preview_feature(self, layer, fid):
        """Show the clicked preview feature without changing active filters."""
        if self.current_layer() != layer:
            return
        id_set = self.result_id_set()
        if id_set is None or self.selection_filter_timer.isActive():
            self.pending_preview_focus = (layer.id(), fid)
            return
        if fid not in id_set:
            self.status.setText('Selected feature is outside the current table filters.')
            return
        position = self.result_ids.index(fid)
        size = self.page_size.currentData()
        page = position // size if size else 0
        if page != self.page:
            self.page = page
            self.render_page()
        for row in range(self.table.rowCount()):
            if self.row_fid(row) != fid:
                continue
            column = next((c for c in range(self.table.columnCount())
                           if not self.table.isColumnHidden(c)), None)
            if column is not None:
                index = self.table.model().index(row, column)
                self.table.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
            break

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

    def sync_edit_state(self, *args):
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
        feat = next(layer.getFeatures(_attribute_request([fid], [col])), None)
        old = feat.attributes()[col] if feat is not None and feat.isValid() and col < len(feat.attributes()) else None
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
            field_name = fld.name()
            self.invalidate_nearby_after_attribute_edit(field_name)
            changed = layer.editBuffer().changedAttributeValues().get(fid, {}) if layer.editBuffer() else {}
            self.table.blockSignals(True)
            try:
                item.setBackground(QBrush(QColor("#365345" if self.theme == "dark" else "#d8efdf")) if col in changed else QBrush())
                item.setToolTip("Unsaved attribute change" if col in changed else "")
                item.setData(NULL_ROLE, new is None or new == NULL)
            finally:
                self.table.blockSignals(False)
            self.status.setText("Changed {} (not saved yet, click Save edits)".format(field_name))
            self.refresh_lists_only(edited_field=field_name)
            self.resize_table_row(row, col)
            if self._edit_requires_requery(field_name):
                self.invalidate_results()
                self.timer.start()
            elif self.btn_statistics.isChecked():
                self.statistics_key = None
                self.schedule_statistics_refresh()
        else:
            self.table.blockSignals(True)
            item.setText(old_text)
            item.setData(NULL_ROLE, old is None or old == NULL)
            self.table.blockSignals(False)
            self.status.setText("Not changed: " + err)

    def _edit_requires_requery(self, field_name):
        """Return True when editing field_name may change matching FIDs or sort order."""
        if self.result_ids is None or self.query_task is not None or self.timer.isActive():
            return True
        if self.edit.text().strip() or self.sort_field == field_name or self.current_scope() == "edited":
            return True
        for filter_row in self.filter_rows:
            if filter_row.field.currentText() != field_name:
                continue
            try:
                if self.part_expr(filter_row.field, filter_row.value):
                    return True
            except ValueError:
                return True
        return False

    def refresh_lists_only(self, edited_field=None):
        """Refresh relevant filter choices without launching tasks for unrelated closed popups."""
        if edited_field is None:
            self.reload_value_lists()
            return
        for filter_row in self.filter_rows:
            if filter_row.field.currentText() == edited_field and filter_row.widget.isVisible():
                self._reload_filter_row_values(filter_row)
            else:
                self._stale_value_rows.add(id(filter_row))

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
        self.btn_replace.setEnabled(bool(can_edit and layer and layer.isEditable()))
        self.btn_replace.setToolTip("Find and replace text in writable columns" if can_edit and layer and layer.isEditable()
                                    else "Enable edit mode to find and replace text")
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
        table_actions.add_field(self)

    deletable_field_indices = staticmethod(table_actions.deletable_field_indices)

    def delete_field(self):
        table_actions.delete_field(self)

    def bulk_edit(self):
        table_actions.bulk_edit(self, _attribute_request)

    def apply_multi_replacements(self, layer, names, originals, changes, entire_layer=False):
        return table_actions.apply_multi_replacements(
            self, layer, names, originals, changes, _attribute_request, entire_layer=entire_layer)

    def apply_replacements(self, layer, name, originals, changes):
        return table_actions.apply_replacements(self, layer, name, originals, changes)

    def find_replace(self):
        table_actions.find_replace(self)

    autofill_values = staticmethod(table_actions.autofill_values)

    def autofill(self):
        table_actions.autofill(self, _attribute_request)

    def delete_selected(self):
        table_actions.delete_selected(self)

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
        if layer is None:
            return
        self.schedule_nearby_preview()
        if layer.id() != self.table_layer_id:
            return
        selected = set(layer.selectedFeatureIds())
        self.pending_selection = selected
        if self.current_scope() == "selected":
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
        if layer:
            self.set_map_selection(layer, self.selected_fids())
        self.update_selection_status()

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

    def update_zoom_button(self):
        layer = self.current_layer()
        spatial = bool(layer and layer.isSpatial())
        selected = layer.selectedFeatureCount() if layer else 0
        self.btn_zoom.setText("Zoom to selected")
        self.btn_zoom.setEnabled(spatial and selected > 0)
        if not spatial:
            self.btn_zoom.setToolTip("Zooming requires a layer with geometry")
        elif selected > 0:
            self.btn_zoom.setToolTip("Zoom the map to the selected features")
        else:
            self.btn_zoom.setToolTip("Select one or more features in the table or map to zoom")

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
        self.update_zoom_button()
        self.update_delete_button()

    def zoom_selected(self):
        """Zoom the active QGIS map canvas to the currently selected features."""
        layer = self.current_layer()
        if not (layer and layer.isSpatial() and layer.selectedFeatureCount() > 0):
            return
        self.iface.mapCanvas().zoomToSelected(layer)

    # ---------- export ----------
    def table_rows(self):
        rows = self.selected_rows() or range(self.table.rowCount())
        columns = [c for c in range(len(self.fields)) if not self.table.isColumnHidden(c)]
        out = [[self.fields[c] for c in columns]]
        for r in rows:
            out.append([self.table.item(r, c).text() if self.table.item(r, c) is not None else "" for c in columns])
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
        self.scope_menu = None
        self.scope_actions = {}
        self.menu_actions = {}

    def _build_scope_actions(self, parent):
        actions = {}
        for scope, label, tooltip in SCOPE_LAUNCH_OPTIONS:
            action = QAction(scope_launch_icon(scope), label, parent)
            action.setToolTip(tooltip)
            action.setData(scope)
            action.triggered.connect(lambda _checked=False, target=scope: self.show(scope=target))
            actions[scope] = action
        return actions

    def initGui(self):
        icon = plugin_icon()
        main_window = self.iface.mainWindow()
        self.action = QAction(icon, "QuickTable", main_window)
        self.action.setToolTip("QuickTable — Open table (use arrow to choose scope)")
        self.action.triggered.connect(lambda _checked=False: self.show())

        self.scope_menu = QMenu(main_window)
        self.scope_actions = self._build_scope_actions(self.scope_menu)
        for action in self.scope_actions.values():
            self.scope_menu.addAction(action)
        self.scope_menu.aboutToShow.connect(self.update_scope_menu_state)
        self.action.setMenu(self.scope_menu)

        self.menu_actions = self._build_scope_actions(main_window)
        for action in self.menu_actions.values():
            self.iface.addPluginToMenu("&QuickTable", action)

        self.iface.addToolBarIcon(self.action)
        toolbar = self.iface.pluginToolBar() if hasattr(self.iface, "pluginToolBar") else None
        button = toolbar.widgetForAction(self.action) if toolbar is not None and hasattr(toolbar, "widgetForAction") else None
        if isinstance(button, QToolButton):
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

    def update_scope_menu_state(self):
        visible_action = self.scope_actions.get("visible")
        if visible_action is None:
            return
        layer = self.dlg.current_layer() if self.dlg is not None else None
        if layer is None and hasattr(self.iface, "activeLayer"):
            layer = self.iface.activeLayer()
        non_spatial_vector = (
            layer is not None
            and hasattr(layer, "type")
            and layer.type() == QgsMapLayer.LayerType.VectorLayer
            and hasattr(layer, "isSpatial")
            and not layer.isSpatial()
        )
        visible_action.setEnabled(not non_spatial_vector)

    def unload(self):
        for action in self.menu_actions.values():
            self.iface.removePluginMenu("&QuickTable", action)
        self.menu_actions.clear()
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.action.setMenu(None)
        self.scope_actions.clear()
        if self.scope_menu is not None:
            self.scope_menu.deleteLater()
            self.scope_menu = None
        self.action = None
        if self.dlg:
            self.dlg.shutdown()
            self.dlg = None

    def show(self, scope=None):
        if isinstance(scope, bool):
            scope = None
        created = self.dlg is None
        if self.dlg is None:
            self.dlg = FinderDialog(self.iface)
            QgsApplication.instance().aboutToQuit.connect(self.dlg.close)
        # Restoring/raising the existing window must not reload its filter controls.
        if created or self.dlg.current_layer() is None:
            self.dlg.refresh(initial_scope=scope)
        elif scope is not None:
            self.dlg.set_scope(scope, run=True)
        if self.dlg.isMinimized():
            self.dlg.showNormal()
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
