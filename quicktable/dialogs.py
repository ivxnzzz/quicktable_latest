"""Secondary QuickTable dialogs for settings, schema changes, bulk edits, find/replace, and autofill."""

from qgis.PyQt.QtCore import Qt, QTimer, QMetaType, QSize, QStringListModel
from qgis.PyQt.QtGui import QPalette, QColor, QFont, QFontMetrics
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                                 QComboBox, QLineEdit, QTableWidget, QTableWidgetItem,
                                 QLabel, QPushButton, QAbstractItemView, QCompleter,
                                 QCheckBox, QListWidget, QListWidgetItem, QDialogButtonBox,
                                 QFontComboBox, QSpinBox, QStyledItemDelegate, QStyle,
                                 QPlainTextEdit, QFormLayout, QGroupBox)
from qgis.core import QgsFeatureRequest, QgsApplication, QgsTask, QgsVectorLayerFeatureSource, NULL

from .editing import convert_attribute
from .tasks import replace_suggestions, replace_columns_snapshot
from .themes import THEMES, _fill, build_css, dark_palette, style_combo_popup


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
    """Dialog for configuring font family, size, theme, and window pinning."""

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
    """Dialog for queuing one or more new typed attributes to add to the layer."""

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
    """Dialog for selecting deletable layer attributes."""

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
        request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
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
            value = convert_attribute(self.layer.fields()[index], None if self.set_null.isChecked() else self.input.text())
            if len(self.features) != len(self.fids):
                raise ValueError("Some selected features are no longer available.")
            self.value = value
            self.original_values = {fid: self.features[fid][index] for fid in self.fids}

            def display(item_value):
                return "NULL" if item_value is None or item_value == NULL else str(item_value)

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


class FindReplaceDialog(QDialog):
    """Background-previewed find and replace dialog for writable text columns."""

    def __init__(self, parent, layer, names):
        super().__init__(parent)
        self.setWindowTitle("Find and replace")
        self.setStyleSheet(parent.styleSheet())
        self.resize(560, 480)
        self.layer = layer
        self.task = None
        self.suggestion_task = None
        self.preview_result = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.find = QLineEdit()
        self.find.setToolTip("Suggestions come from up to 2,000 features in the selected scope.")
        self.suggestion_model = QStringListModel(self)
        self.completer = QCompleter(self.suggestion_model, self.find)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.find.setCompleter(self.completer)
        self.replacement = QLineEdit()
        self.field = QComboBox()
        self.field.addItem("All writable text columns", None)
        for name in names:
            self.field.addItem(name, name)
        self.scope = QComboBox()
        self.scope.addItem("Filtered results", "filtered")
        self.scope.addItem("Entire layer", "layer")
        if parent.selected_fids():
            self.scope.addItem("Selected rows", "selected")
        self.case = QCheckBox("Match case")
        form.addRow("Find", self.find)
        form.addRow("Replace with", self.replacement)
        form.addRow("Columns", self.field)
        form.addRow("Search in", self.scope)
        form.addRow(self.case)
        layout.addLayout(form)
        self.preview_button = QPushButton("Preview")
        self.preview_button.clicked.connect(self.start_preview)
        layout.addWidget(self.preview_button)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Preview matches before applying changes.")
        layout.addWidget(self.preview)
        self.notice = QLabel("Changes are undoable until saved.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.addButton("Replace all", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_preview)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(350)
        self.preview_timer.timeout.connect(self.start_preview)
        self.suggestion_timer = QTimer(self)
        self.suggestion_timer.setSingleShot(True)
        self.suggestion_timer.setInterval(300)
        self.suggestion_timer.timeout.connect(self.update_suggestions)
        self.find.textChanged.connect(self.schedule_preview)
        self.replacement.textChanged.connect(self.schedule_preview)
        self.field.currentIndexChanged.connect(self.schedule_preview)
        self.scope.currentIndexChanged.connect(self.schedule_preview)
        self.case.toggled.connect(self.schedule_preview)
        self.find.textChanged.connect(self.schedule_suggestions)
        self.field.currentIndexChanged.connect(self.schedule_suggestions)
        self.scope.currentIndexChanged.connect(self.schedule_suggestions)
        self.case.toggled.connect(self.schedule_suggestions)

    def schedule_preview(self, *args):
        self.invalidate_preview()
        if self.find.text():
            self.notice.setText("Updating preview…")
            self.preview_timer.start()
        else:
            self.notice.setText("Enter text to find.")

    def schedule_suggestions(self, *args):
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive if self.case.isChecked()
                                          else Qt.CaseSensitivity.CaseInsensitive)
        self.suggestion_timer.stop()
        if self.suggestion_task is not None:
            self.suggestion_task.cancel()
            self.suggestion_task = None
        self.suggestion_model.setStringList([])
        if self.find.text():
            self.suggestion_timer.start()

    def update_suggestions(self):
        parent = self.parent()
        if parent.closing or parent.current_layer() != self.layer:
            return
        names = ([self.field.currentData()] if self.field.currentData() else
                 [self.field.itemData(i) for i in range(1, self.field.count())])
        columns = [self.layer.fields().indexFromName(name) for name in names]
        if any(index < 0 for index in columns):
            return
        scope = self.scope.currentData()
        if scope == "filtered" and parent.result_ids is None:
            return
        ids = (None if scope == "layer" else tuple(parent.selected_fids()) if scope == "selected"
               else tuple(parent.result_ids))
        selected = set(ids) if scope == "selected" else None
        needle, version = self.find.text(), parent.query_version

        def finished(exception, result=None):
            if self.suggestion_task is not task:
                return
            self.suggestion_task = None
            if (exception or result is None or parent.closing or parent.current_layer() != self.layer
                    or parent.query_version != version or self.find.text() != needle
                    or (selected is not None and set(parent.selected_fids()) != selected)):
                return
            self.suggestion_model.setStringList(result)
            if result and self.find.hasFocus() and self.isVisible():
                self.completer.complete()

        task = QgsTask.fromFunction("QuickTable: find suggestions", replace_suggestions,
                                    source=QgsVectorLayerFeatureSource(self.layer), ids=ids,
                                    columns=columns, needle=needle, case_sensitive=self.case.isChecked(),
                                    on_finished=finished)
        task.setDependentLayers([self.layer])
        self.suggestion_task = task
        QgsApplication.taskManager().addTask(task)

    def invalidate_preview(self, *args):
        self.preview_timer.stop()
        if self.task is not None:
            self.task.cancel()
            self.task = None
        self.preview_result = None
        self.apply_button.setEnabled(False)
        self.preview_button.setEnabled(True)
        self.preview.clear()

    def reject(self):
        self.invalidate_preview()
        self.suggestion_timer.stop()
        if self.suggestion_task is not None:
            self.suggestion_task.cancel()
            self.suggestion_task = None
        super().reject()

    def start_preview(self):
        self.invalidate_preview()
        parent = self.parent()
        if not self.find.text():
            self.notice.setText("Enter text to find.")
            return
        if parent.current_layer() != self.layer or not self.layer.isEditable():
            self.notice.setText("The layer or edit mode changed.")
            return
        names = ([self.field.currentData()] if self.field.currentData() else
                 [self.field.itemData(i) for i in range(1, self.field.count())])
        columns = [self.layer.fields().indexFromName(name) for name in names]
        if any(index < 0 for index in columns):
            self.notice.setText("A column is no longer available.")
            return
        scope = self.scope.currentData()
        if scope == "filtered" and parent.result_ids is None:
            self.notice.setText("Wait for filtered results.")
            return
        ids = (None if scope == "layer" else tuple(parent.selected_fids()) if scope == "selected"
               else tuple(parent.result_ids))
        version = parent.query_version
        selected = set(parent.selected_fids()) if scope == "selected" else None
        self.notice.setText("Preparing preview…")
        self.preview_button.setEnabled(False)

        def finished(exception, result=None):
            if self.task is not task:
                return
            self.task = None
            self.preview_button.setEnabled(True)
            if parent.closing or parent.current_layer() != self.layer or parent.query_version != version:
                self.notice.setText("The layer or results changed. Preview again.")
                return
            if exception or result is None:
                self.notice.setText("Preview failed: {}".format(exception) if exception else "Preview canceled.")
                return
            originals, changes = result
            if not changes:
                self.notice.setText("No matching values found.")
                return
            lines = []
            for fid, values in changes.items():
                for column, value in values.items():
                    lines.append("{} · {}: {} → {}".format(fid, self.layer.fields()[column].name(),
                                 str(originals[fid][column])[:100], str(value)[:100]))
                    if len(lines) >= 20:
                        break
                if len(lines) >= 20:
                    break
            self.preview.setPlainText("\n".join(lines))
            count = sum(len(values) for values in changes.values())
            self.notice.setText("{} cell(s) in {} feature(s) will change. Showing up to 20.".format(count, len(changes)))
            self.preview_result = (originals, changes, names, scope, version, selected)
            self.apply_button.setEnabled(True)

        task = QgsTask.fromFunction("QuickTable: preview replacements", replace_columns_snapshot,
                 source=QgsVectorLayerFeatureSource(self.layer), ids=ids, columns=columns,
                 needle=self.find.text(), replacement=self.replacement.text(), case_sensitive=self.case.isChecked(),
                 on_finished=finished)
        task.setDependentLayers([self.layer])
        self.task = task
        QgsApplication.taskManager().addTask(task)

    def apply_preview(self):
        if self.preview_result is None:
            return
        originals, changes, names, scope, version, selected = self.preview_result
        parent = self.parent()
        if (parent.current_layer() != self.layer or parent.query_version != version
                or (scope == "selected" and set(parent.selected_fids()) != selected)):
            self.invalidate_preview()
            self.notice.setText("The layer or selection changed. Preview again.")
            return
        if parent.apply_multi_replacements(self.layer, names, originals, changes, scope == "layer"):
            self.suggestion_timer.stop()
            if self.suggestion_task is not None:
                self.suggestion_task.cancel()
                self.suggestion_task = None
            self.accept()
        else:
            self.invalidate_preview()
            self.notice.setText(parent.status.text())


class AutofillDialog(QDialog):
    """Dialog for filling selected rows or the current page with values or sequences."""

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
        self.values.ensurePolished()
        lines = 2 if mode == "repeat" else 1
        self.values.setFixedHeight(max(72 if mode == "repeat" else 40,
                                       lines * self.values.fontMetrics().lineSpacing() + 20))
        self.step.setVisible(mode == "sequence")
        self.step_label.setVisible(mode == "sequence")
        self.values.setEnabled(mode != "null")
        self.hint.setText({"null": "Set every target value to NULL.",
                           "same": "Enter one value. Empty text and spaces are preserved.",
                           "sequence": "Enter the starting number and step; numeric fields only.",
                           "repeat": "Enter one value per line. Values repeat in order."}[mode])
        self.values.setPlaceholderText({"null": "", "same": "e.g. Residential", "sequence": "e.g. 1",
                                        "repeat": "e.g. Residential\nCommercial"}[mode])
