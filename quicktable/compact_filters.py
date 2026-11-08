"""Column-header controls and per-column text presentation."""

import math
from decimal import Decimal, InvalidOperation

from qgis.PyQt.QtCore import Qt, QRect, QSize, QDate, QPoint, QEvent, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen, QTextDocument, QTextOption
from qgis.PyQt.QtWidgets import QHeaderView, QStyledItemDelegate, QStyleOptionViewItem, QComboBox, QDateEdit, QWidget, QToolTip


class StatisticsStrip(QWidget):
    """Paint statistics in the same viewport coordinates as the table headers."""
    def __init__(self, table, parent=None):
        super().__init__(parent)
        self.table = table
        self.summaries = {}
        self.state = "loading"
        self.message = "Calculating…"
        self.background = "#ffffff"
        self.card_background = "#ffffff"
        self.border = "#dedcd1"
        self.foreground = "#4a4943"
        self.title_color = "#1f1e1d"
        self.accent = "#2e7d5b"
        self.setMouseTracking(True)
        table.horizontalScrollBar().valueChanged.connect(self.geometry_changed)
        table.horizontalHeader().sectionResized.connect(self.geometry_changed)
        table.horizontalHeader().geometriesChanged.connect(self.geometry_changed)
        table.viewport().installEventFilter(self)
        self.update_height()

    def geometry_changed(self, *args):
        self.update()

    def update_height(self):
        self.setFixedHeight(max(135, 7 * (self.fontMetrics().height() + 2) + 16))
        self.update()

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            self.update()
        return super().eventFilter(watched, event)

    def viewport_offset(self):
        return self.mapFromGlobal(self.table.viewport().mapToGlobal(QPoint(0, 0))).x()

    def set_state(self, state, summaries=None, message=""):
        self.state = state
        self.summaries = summaries or {}
        self.message = message
        self.update()

    def lines_for(self, index):
        if self.state != "ready":
            return [self.message or "Calculating…"]
        summary = self.summaries.get(index)
        if summary is None:
            return ["No statistics"]
        count, nulls, total, minimum, maximum, numeric = summary[:6]
        info = summary[6] if len(summary) > 6 else {}
        distinct = ">={:,}".format(info["distinct"]) if info.get("capped") else "{:,}".format(info.get("distinct", 0))
        lines = ["Non-null: {}".format(count), "NULL: {}".format(nulls)]
        lines.append("Distinct: {}".format(distinct))
        if numeric:
            numeric_count = info.get("numeric_count", count)
            lines.extend(["Sum: {}".format(format(total, ".12g") if numeric_count else "—"),
                          "Avg: {}".format(format(total / numeric_count, ".12g") if numeric_count else "—"),
                          "Min: {}".format(format(minimum, ".12g") if numeric_count else "—"),
                          "Max: {}".format(format(maximum, ".12g") if numeric_count else "—")])
            if info.get("nonfinite"):
                lines.append("Non-finite values excluded: {}".format(info["nonfinite"]))
        for value, frequency in info.get("top", []):
            lines.append("{}: {}".format(value or "(empty string)", frequency))
        return lines

    @staticmethod
    def percent(value, total):
        if not total:
            return "0%"
        percentage = value * 100.0 / total
        if 0 < percentage < 1:
            return "<1%"
        return "{}%".format(round(percentage))

    def draw_line(self, painter, rect, text, color=None, align=Qt.AlignmentFlag.AlignLeft):
        painter.setPen(QColor(color or self.foreground))
        painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(str(text), Qt.TextElideMode.ElideRight, max(0, rect.width())))

    @staticmethod
    def fit_text(painter, width, choices):
        metrics = painter.fontMetrics()
        return next((text for text in choices if metrics.horizontalAdvance(text) <= width), choices[-1])

    def draw_card(self, painter, index, rect):
        painter.setPen(QPen(QColor(self.border), 1))
        painter.setBrush(QColor(self.card_background))
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 3, 3)
        inner = rect.adjusted(8, 6, -8, -6)
        line_height = self.fontMetrics().height() + 2
        name = self.table.horizontalHeaderItem(index)
        summary = self.summaries.get(index)
        numeric = bool(summary and summary[5])
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        self.draw_line(painter, QRect(inner.left(), inner.top(), inner.width(), line_height),
                       ("123  " if numeric else "abc  ") + (name.text() if name else "Column"), self.title_color)
        font.setBold(False)
        painter.setFont(font)
        if self.state != "ready" or summary is None:
            self.draw_line(painter, QRect(inner.left(), inner.top() + line_height * 2, inner.width(), line_height),
                           self.message or "Calculating…")
            return
        count, nulls, total, minimum, maximum, numeric = summary[:6]
        info = summary[6] if len(summary) > 6 else {}
        all_count = count + nulls
        distinct = info.get("distinct", 0)
        distinct_text = ">={:,}".format(distinct) if info.get("capped") else "{:,}".format(distinct)
        missing = self.fit_text(painter, inner.width(), [
            "Missing {} ({})".format(nulls, self.percent(nulls, all_count)),
            "Missing {}".format(nulls), "∅ {}".format(nulls)])
        unique = self.fit_text(painter, inner.width(), [
            "Distinct {}{}".format(distinct_text, "" if info.get("capped") else
                                   " ({})".format(self.percent(distinct, all_count))),
            "Distinct {}".format(distinct_text), "Unique {}".format(distinct_text), "# {}".format(distinct_text)])
        self.draw_line(painter, QRect(inner.left(), inner.top() + line_height, inner.width(), line_height), missing)
        self.draw_line(painter, QRect(inner.left(), inner.top() + 2 * line_height, inner.width(), line_height), unique)
        y = inner.top() + 3 * line_height + 4
        if numeric and info.get("histogram"):
            bins = info["histogram"]
            max_count = max(bins) or 1
            chart_width = max(0, inner.width())
            chart_height = max(12, min(line_height * 2, inner.bottom() - y - line_height))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.accent))
            for i, amount in enumerate(bins):
                left = inner.left() + i * chart_width // len(bins)
                right = inner.left() + (i + 1) * chart_width // len(bins)
                height = round(chart_height * amount / max_count)
                if height:
                    painter.drawRect(left, y + chart_height - height, max(1, right - left - 1), height)
            self.draw_line(painter, QRect(inner.left(), y + chart_height + 2, inner.width(), line_height),
                           "Min {}  Max {}".format(format(minimum, ".8g"), format(maximum, ".8g")))
        elif not numeric and info.get("top"):
            for i, (value, frequency) in enumerate(info["top"]):
                percent = self.percent(frequency, all_count)
                percentage_width = min(inner.width(), painter.fontMetrics().horizontalAdvance(percent))
                value_width = max(0, inner.width() - percentage_width - 4)
                self.draw_line(painter, QRect(inner.left(), y + i * line_height, value_width, line_height),
                               value or "(empty string)")
                self.draw_line(painter, QRect(inner.right() - percentage_width + 1, y + i * line_height,
                                             percentage_width, line_height), percent, align=Qt.AlignmentFlag.AlignRight)
            other = count - sum(frequency for value, frequency in info["top"])
            if other:
                self.draw_line(painter, QRect(inner.left(), y + len(info["top"]) * line_height, inner.width(), line_height),
                               "Other classes {}".format(self.percent(other, all_count)))
        elif count and not info.get("capped"):
            self.draw_line(painter, QRect(inner.left(), y + line_height // 2, inner.width(), line_height),
                           "{} distinct values".format(distinct_text), self.accent)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.background))
        painter.setFont(self.table.font())
        painter.setPen(QColor(self.foreground))
        header = self.table.horizontalHeader()
        offset = self.viewport_offset()
        painter.setClipRect(QRect(offset, 0, self.table.viewport().width(), self.height()))
        line_height = self.fontMetrics().height() + 2
        if self.table.columnCount() == 0 and self.message:
            painter.drawText(QRect(offset + 6, 4, max(0, self.table.viewport().width() - 12), line_height),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.message)
        for index in range(self.table.columnCount()):
            if self.table.isColumnHidden(index):
                continue
            x = offset + header.sectionViewportPosition(index)
            width = header.sectionSize(index)
            if x + width < offset or x > offset + self.table.viewport().width():
                continue
            self.draw_card(painter, index, QRect(x + 3, 2, max(0, width - 6), self.height() - 4))
        painter.end()

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            x = event.pos().x() - self.viewport_offset()
            index = self.table.horizontalHeader().logicalIndexAt(x)
            if index >= 0 and not self.table.isColumnHidden(index):
                name = self.table.horizontalHeaderItem(index)
                title = name.text() if name else "Column"
                QToolTip.showText(event.globalPos(), title + "\n" + "\n".join(self.lines_for(index)), self)
                return True
        return super().event(event)


class ColumnTextDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.wrapped = False
        self.field_kind = "text"
        self.value_map = []
        self.number_format = "original"

    def displayText(self, value, locale):
        text = super().displayText(value, locale)
        if self.field_kind not in ("integer", "number") or self.number_format == "original" or not text:
            return text
        try:
            number = Decimal(str(value))
            if not number.is_finite():
                return text
            if self.number_format == "trim":
                formatted = format(number, "f")
                return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted
            if self.number_format == "whole":
                return format(number, ".0f")
            if self.number_format in ("1", "2", "3"):
                return format(number, ".{}f".format(self.number_format))
        except (InvalidOperation, ValueError):
            pass
        return text

    def createEditor(self, parent, option, index):
        if self.value_map:
            editor = QComboBox(parent)
            editor.addItem("(NULL)", "")
            for label, value in self.value_map:
                editor.addItem(label, str(value))
            return editor
        if self.field_kind == "boolean":
            editor = QComboBox(parent)
            editor.addItem("(NULL)", "")
            editor.addItem("True", "true")
            editor.addItem("False", "false")
            return editor
        if self.field_kind == "date" and QDate.fromString(str(index.data(Qt.ItemDataRole.EditRole) or ""), Qt.DateFormat.ISODate).isValid():
            editor = QDateEdit(parent)
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd")
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            value = str(index.data(Qt.ItemDataRole.EditRole) or "").lower()
            if self.field_kind == "boolean" and not self.value_map:
                value = {"1": "true", "0": "false"}.get(value, value)
            match = next((i for i in range(editor.count()) if str(editor.itemData(i)).lower() == value), -1)
            if match < 0:
                editor.addItem(str(index.data(Qt.ItemDataRole.EditRole)), str(index.data(Qt.ItemDataRole.EditRole)))
                match = editor.count() - 1
            editor.setCurrentIndex(match)
        elif isinstance(editor, QDateEdit):
            date = QDate.fromString(str(index.data(Qt.ItemDataRole.EditRole)), Qt.DateFormat.ISODate)
            editor.setDate(date if date.isValid() else QDate.currentDate())
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentData(), Qt.ItemDataRole.EditRole)
        elif isinstance(editor, QDateEdit):
            model.setData(index, editor.date().toString(Qt.DateFormat.ISODate), Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if self.wrapped:
            option.features |= QStyleOptionViewItem.ViewItemFeature.WrapText
            option.textElideMode = Qt.TextElideMode.ElideNone
        else:
            option.features &= ~QStyleOptionViewItem.ViewItemFeature.WrapText
            option.textElideMode = Qt.TextElideMode.ElideRight

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if not self.wrapped or option.rect.width() <= 1:
            return size
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(styled.font)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(text_option)
        document.setPlainText(styled.text)
        document.setTextWidth(max(1, option.rect.width() - 18))
        return QSize(size.width(), max(size.height(), math.ceil(document.size().height()) + 8))


class FilterHeader(QHeaderView):
    filterRequested = pyqtSignal(int)
    sortRequested = pyqtSignal(int)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.filtered_columns = set()
        self.filter_labels = {}
        self.icon_color = "#73726c"
        self.active_color = "#2e7d5b"
        self.active_background = "#e7f3ec"
        self.filter_background = "#ffffff"
        self.filter_border = "#dedcd1"
        self.pressed_part = None
        self.setToolTip("Click a column name to sort. Click the filter below it for filtering and column options. Drag a border to resize.")

    def sizeHint(self):
        size = super().sizeHint()
        return QSize(size.width(), max(size.height(), self.fontMetrics().height() + 12) * 2)

    def paintSection(self, painter, rect, logical_index):
        top_height = rect.height() // 2
        top = QRect(rect.left(), rect.top(), rect.width(), top_height)
        painter.save()
        try:
            super().paintSection(painter, top, logical_index)
        finally:
            painter.restore()
        area = QRect(rect.left() + 4, rect.top() + top_height + 3,
                     max(0, rect.width() - 8), max(0, rect.height() - top_height - 6))
        active = logical_index in self.filtered_columns
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(QRect(rect.left(), rect.top() + top_height, rect.width(), rect.height() - top_height),
                             QColor(self.filter_background))
            painter.setPen(QPen(QColor(self.active_color if active else self.filter_border), 1))
            painter.setBrush(QColor(self.active_background if active else self.filter_background))
            painter.drawRoundedRect(area.adjusted(0, 0, -1, -1), 4, 4)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(self.active_color if active else self.icon_color))
            text_area = area.adjusted(8, 0, -22, 0)
            label = self.filter_labels.get(logical_index, "Filter…")
            painter.drawText(text_area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             self.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, max(0, text_area.width())))
            painter.setPen(QPen(QColor(self.active_color if active else self.icon_color), 1.4))
            x, y = area.right() - 15, area.center().y() - 3
            path = QPainterPath()
            path.moveTo(x, y)
            path.lineTo(x + 4, y + 4)
            path.lineTo(x + 8, y)
            painter.drawPath(path)
        finally:
            painter.restore()

    def part_at(self, position):
        column = self.logicalIndexAt(position)
        if column < 0:
            return None
        start = self.sectionViewportPosition(column)
        end = start + self.sectionSize(column)
        # Keep the section edges available for the normal resize interaction.
        if not start + 3 < position.x() < end - 4:
            return None
        return (column, "sort" if position.y() < self.height() // 2 else "filter")

    def mousePressEvent(self, event):
        self.pressed_part = self.part_at(event.pos()) if event.button() == Qt.MouseButton.LeftButton else None
        if self.pressed_part is not None:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        part = self.pressed_part
        self.pressed_part = None
        if part is not None and event.button() == Qt.MouseButton.LeftButton:
            if self.part_at(event.pos()) == part:
                (self.sortRequested if part[1] == "sort" else self.filterRequested).emit(part[0])
            event.accept()
            return
        super().mouseReleaseEvent(event)
