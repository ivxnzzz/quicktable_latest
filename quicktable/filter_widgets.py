"""An Equals dropdown whose values can be checked without closing it."""

from qgis.PyQt.QtCore import Qt, QTimer, QPoint, pyqtSignal
from qgis.PyQt.QtWidgets import (QApplication, QComboBox, QCompleter, QFrame,
                                 QVBoxLayout, QHBoxLayout, QLineEdit,
                                 QListWidget, QListWidgetItem, QPushButton, QLabel)
from qgis.core import QgsExpression

from .filter_logic import comparison_value

ALL_VALUES = "(all)"


class ClickableCheckList(QListWidget):
    """Toggle a checkbox once when any part of its row is clicked."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pressed_item = None

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if event.button() == Qt.MouseButton.LeftButton and item is not None and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            self.pressed_item = item
            self.setCurrentItem(item)
            event.accept()
            return
        self.pressed_item = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.pos())
        pressed = self.pressed_item
        self.pressed_item = None
        if event.button() == Qt.MouseButton.LeftButton and pressed is not None:
            if item is pressed and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.mousePressEvent(event)


class CheckableValueCombo(QComboBox):
    checkedValuesChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.selected_values = []
        self.checkable = False
        self.value_kind = "text"
        self.checkbox_popup = None
        self.normal_completer = QCompleter(self.model(), self)
        self.normal_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.normal_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.normal_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.lineEdit().textEdited.connect(self.clear_checks_for_typing)

    def enable_checkboxes(self, enabled):
        if enabled == self.checkable:
            return
        self.checkable = enabled
        self.setCompleter(None if enabled else self.normal_completer)
        if not enabled and self.selected_values:
            blocked = self.blockSignals(True)
            self.setEditText(self.selected_values[0])
            self.blockSignals(blocked)
        elif enabled:
            self.update_checked_text()

    def reset_choices(self):
        self.selected_values = []
        if self.checkbox_popup is not None:
            self.checkbox_popup.hide()
            self.checkbox_popup.deleteLater()
            self.checkbox_popup = None

    def set_selected_values(self, values, notify=True):
        self.selected_values = list(dict.fromkeys(values))
        self.update_checked_text(clear_empty=True)
        if notify:
            self.checkedValuesChanged.emit()

    def update_checked_text(self, clear_empty=False):
        if self.checkable and (self.selected_values or clear_empty):
            blocked = self.blockSignals(True)
            self.setEditText(", ".join(self.selected_values) if self.selected_values else ALL_VALUES)
            self.blockSignals(blocked)

    def clear_checks_for_typing(self, *args):
        if self.selected_values:
            self.selected_values = []
            self.checkedValuesChanged.emit()

    def showPopup(self):
        if not self.checkable:
            super().showPopup()
            return
        if not self.selected_values and self.currentText() != ALL_VALUES:
            self.set_selected_values([self.currentText()], notify=False)
        if self.checkbox_popup is None:
            self.checkbox_popup = ValuePopup(self)
        self.checkbox_popup.open_below()

    def hidePopup(self):
        if self.checkbox_popup is not None:
            self.checkbox_popup.hide()
        super().hidePopup()


class ValuePopup(QFrame):
    def __init__(self, combo, embedded=False):
        super().__init__(combo, Qt.WindowType.Widget if embedded else Qt.WindowType.Popup)
        self.setObjectName("valuePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, True)
        self.combo = combo
        self.items = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a value")
        layout.addWidget(self.search)
        self.list = ClickableCheckList()
        self.list.setObjectName("checkValues")
        layout.addWidget(self.list)
        self.count = QLabel()
        layout.addWidget(self.count)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        self.use_typed = QPushButton("Use typed value")
        self.done_button = QPushButton("Done")
        buttons.addWidget(self.use_typed)
        buttons.addStretch(1)
        buttons.addWidget(self.done_button)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self.filter_items)
        self.search.returnPressed.connect(self.add_typed_value)
        self.use_typed.clicked.connect(self.add_typed_value)
        self.done_button.clicked.connect(self.hide)
        self.list.itemChanged.connect(self.item_changed)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh_choices)
        combo.model().rowsInserted.connect(self.schedule_refresh)

    def schedule_refresh(self, *args):
        if self.isVisible():
            self.refresh_timer.start(25)

    def refresh_choices(self):
        blocked = self.list.blockSignals(True)
        self.list.setUpdatesEnabled(False)
        try:
            selected = list(self.combo.selected_values)
            selected_set = set(selected)
            values = [None] + [self.combo.itemText(i) for i in range(1, self.combo.count())] + selected
            available = set(values)
            stale = [value for value in self.items if value not in available]
            if stale and len(stale) > len(self.items) // 2:
                self.list.clear()
                self.items.clear()
            else:
                for value in stale:
                    item = self.items.pop(value)
                    self.list.takeItem(self.list.row(item))
            for value in values:
                if value not in self.items:
                    text = ALL_VALUES if value is None else value if value else "(empty string)"
                    item = QListWidgetItem(text, self.list)
                    item.setData(Qt.ItemDataRole.UserRole, value)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    self.items[value] = item
            for value, item in self.items.items():
                checked = not selected_set if value is None else value in selected_set
                state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                if item.checkState() != state:
                    item.setCheckState(state)
        finally:
            self.list.setUpdatesEnabled(True)
            self.list.blockSignals(blocked)
        self.filter_items()
        self.count.setText("{} checked — matches any (OR)".format(len(self.combo.selected_values)))

    def filter_items(self, *args):
        search_text = self.search.text()
        text = search_text.casefold()
        self.list.setUpdatesEnabled(False)
        try:
            for value, item in self.items.items():
                item.setHidden(value is not None and text not in item.text().casefold())
        finally:
            self.list.setUpdatesEnabled(True)
        self.use_typed.setVisible(bool(search_text) and search_text not in self.items)

    def item_changed(self, item):
        clicked_value = item.data(Qt.ItemDataRole.UserRole)
        if clicked_value is None:
            values = []
        elif item.checkState() == Qt.CheckState.Checked:
            values = list(self.combo.selected_values) + [clicked_value]
        else:
            values = [v for v in self.combo.selected_values if v != clicked_value]
        self.combo.set_selected_values(values)
        blocked = self.list.blockSignals(True)
        try:
            all_item = self.items.get(None)
            if all_item is not None:
                all_item.setCheckState(Qt.CheckState.Checked if not values else Qt.CheckState.Unchecked)
            if clicked_value is None:
                for value, choice in self.items.items():
                    if value is not None and choice.checkState() == Qt.CheckState.Checked:
                        choice.setCheckState(Qt.CheckState.Unchecked)
        finally:
            self.list.blockSignals(blocked)
        self.count.setText("{} checked — matches any (OR)".format(len(self.combo.selected_values)))

    def add_typed_value(self):
        text = self.search.text()
        if not text:
            return
        try:
            comparison_value(text, self.combo.value_kind, QgsExpression.quotedString)
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.error.clear()
        self.combo.set_selected_values(self.combo.selected_values + [text])
        self.search.clear()
        self.refresh_choices()

    def open_below(self):
        owner = self.combo.window()
        self.setFont(owner.font())
        background = getattr(self.combo, "popup_background", "#ffffff")
        border = getattr(self.combo, "popup_border", "#dedcd1")
        self.setStyleSheet(owner.styleSheet() + "\nQFrame#valuePopup { background: " + background + "; border: 1px solid " + border + "; }"
                          + "\nQListWidget#checkValues::item { min-height: 22px; padding: 2px 4px; }")
        self.search.clear()
        self.error.clear()
        self.refresh_choices()
        position = self.combo.mapToGlobal(QPoint(0, self.combo.height()))
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        width = min(max(320, self.combo.width()), available.width() - 16)
        row_height = max(22, self.list.sizeHintForRow(0))
        height = min(360, max(180, len(self.items) * row_height + 120), available.height() - 16)
        x = max(available.left() + 8, min(position.x(), available.right() - width - 8))
        y = position.y()
        if y + height > available.bottom():
            y = self.combo.mapToGlobal(QPoint(0, 0)).y() - height
        y = max(available.top() + 8, min(y, available.bottom() - height - 8))
        self.resize(width, height)
        self.move(x, y)
        self.show()
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)
