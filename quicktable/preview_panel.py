"""Interactive Features Preview sidebar, pan/select tool, and map-anchored labels."""

from qgis.PyQt.QtCore import Qt, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import (QApplication, QComboBox, QFrame,
                                 QHBoxLayout, QLabel, QPushButton, QVBoxLayout)
from qgis.core import QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsRectangle
from qgis.gui import QgsMapCanvas, QgsMapCanvasItem, QgsMapToolPan, QgsRubberBand

from .editing import attribute_text
from .tasks import preview_label_angle, preview_label_placement
from .themes import THEMES


def _decode_snapshot_geometries(snapshot):
    """Decode preview WKB blobs once into QgsGeometry objects."""
    decoded = {"selected": {}, "nearby": {}}
    if snapshot is None:
        return decoded
    for group in ("selected", "nearby"):
        for fid, wkb in snapshot[group].items():
            geometry = QgsGeometry()
            geometry.fromWkb(wkb)
            if not geometry.isEmpty():
                decoded[group][fid] = geometry
    return decoded


class PreviewPanSelectTool(QgsMapToolPan):
    """Pan by dragging; select a displayed feature with a click."""

    def __init__(self, canvas, layer, snapshot, on_selected, can_select=None, geometries=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.on_selected = on_selected
        self.can_select = can_select
        self.press_pos = None
        self.set_snapshot_data(layer, snapshot, geometries)

    def set_snapshot_data(self, layer, snapshot, geometries=None):
        """Update selectable geometries in place without replacing the active map tool."""
        self.layer = layer
        decoded = geometries if geometries is not None else _decode_snapshot_geometries(snapshot)
        self.selected_ids = set(decoded['selected'])
        self.geometries = [
            (fid, geometry)
            for group in ('selected', 'nearby')
            for fid, geometry in decoded[group].items()
        ]
        self.press_pos = None

    def canvasPressEvent(self, event):
        self.press_pos = event.pos() if event.button() == Qt.MouseButton.LeftButton else None
        super().canvasPressEvent(event)

    def canvasReleaseEvent(self, event):
        click = (self.press_pos is not None and event.button() == Qt.MouseButton.LeftButton
                 and (event.pos() - self.press_pos).manhattanLength() < QApplication.startDragDistance())
        self.press_pos = None
        super().canvasReleaseEvent(event)
        if not click:
            return
        map_point = event.mapPoint()
        point = QgsGeometry.fromPointXY(map_point)
        tolerance = self.canvas.mapUnitsPerPixel() * 5
        matches = []
        for fid, geometry in self.geometries:
            bounds = geometry.boundingBox()
            bounds.grow(tolerance)
            if not bounds.contains(map_point):
                continue
            distance = geometry.distance(point)
            if 0 <= distance <= tolerance:
                matches.append((distance, fid in self.selected_ids, fid))
        if matches:
            fid = min(matches)[2]
            if self.can_select is not None and not self.can_select(self.layer, fid):
                return
            self.layer.selectByIds([fid])
            self.on_selected(self.layer, fid)


class PreviewLabel(QgsMapCanvasItem):
    """A map-anchored, readable label that follows pan and zoom."""

    def __init__(self, canvas, point, text, selected=True, angle=0, theme="light"):
        super().__init__(canvas)
        self.point = point
        self.text = text
        self.selected = selected
        self.theme = theme if theme in THEMES else "light"
        self.font = QFont(QApplication.font())
        self.font.setBold(True)
        metrics = QFontMetrics(self.font)
        display_text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, 208)
        self.text_path = QPainterPath()
        self.text_path.addText(3, metrics.ascent() + 3, self.font, display_text)
        self.box = QRectF(0, 0, metrics.horizontalAdvance(display_text) + 6, metrics.height() + 6)
        self.setTransformOriginPoint(self.box.center())
        self.setRotation(angle)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(100)
        self.updatePosition()

    def boundingRect(self):
        return self.box

    def updatePosition(self):
        pos = self.toCanvasCoordinates(self.point)
        self.setPos(pos.x() - self.box.width() / 2, pos.y() - self.box.height() / 2)

    def paint(self, painter, option, widget=None):
        palette = THEMES[self.theme]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(palette['preview_halo']), 3)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.text_path)
        fill = palette['preview_label_selected'] if self.selected else palette['preview_label']
        painter.fillPath(self.text_path, QColor(fill))


class EmptyPreviewPanel(QFrame):
    """Show a helpful prompt when the layer has no selection."""

    def __init__(self, parent, layer):
        super().__init__(parent)
        self.layer = layer
        self.setObjectName('featurePreview')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)
        title = QHBoxLayout()
        heading = QLabel('Features Preview')
        heading.setObjectName('previewTitle')
        title.addWidget(heading, 1)
        self.close_button = QPushButton('Close')
        self.close_button.setToolTip('Hide Features Preview')
        self.close_button.clicked.connect(parent.hide_nearby_preview)
        title.addWidget(self.close_button)
        layout.addLayout(title)
        self.message = QLabel('Select a feature to see its nearby features.')
        self.message.setObjectName('previewSecondary')
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message, 1)
        self.setMinimumWidth(264)


class NearbyPreviewPanel(QFrame):
    """Display copied nearby geometry without changing the source layer."""

    def __init__(self, parent, layer, snapshot, nearby_count, extent=None, recenter=True,
                 nearby_limited=False):
        super().__init__(parent)
        self.owner = parent
        self.layer = layer
        self.layer_id = layer.id()
        self.snapshot = snapshot
        self.nearby_count = nearby_count
        self.nearby_limited = bool(nearby_limited)
        self.label_items = {}
        self.setObjectName('featurePreview')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)
        title = QHBoxLayout()
        title.setSpacing(8)
        heading = QLabel("Features Preview")
        heading.setObjectName('previewTitle')
        title.addWidget(heading, 1)
        self.close_button = QPushButton("Close")
        self.close_button.setToolTip("Hide Features Preview")
        self.close_button.clicked.connect(parent.hide_nearby_preview)
        title.addWidget(self.close_button)
        layout.addLayout(title)
        legend = QHBoxLayout()
        legend.setSpacing(6)
        self.outside_swatch = None
        self.outside_label = None
        for label, name in (('Selected', 'previewSelectedSwatch'),
                            ('Touching', 'previewNearbySwatch'),
                            ('Outside', 'previewOutsideSwatch')):
            marker = QLabel()
            marker.setObjectName(name)
            marker.setFixedSize(8, 8)
            legend.addWidget(marker)
            caption = QLabel(label)
            caption.setObjectName('previewSecondary')
            legend.addWidget(caption)
            if name == 'previewOutsideSwatch':
                marker.setToolTip('Touching features outside the current table or visible map extent')
                caption.setToolTip('Touching features outside the current table or visible map extent')
                self.outside_swatch = marker
                self.outside_label = caption
                marker.hide()
                caption.hide()
            else:
                legend.addSpacing(10)
        legend.addStretch(1)
        layout.addLayout(legend)
        label_row = QHBoxLayout()
        label_row.setSpacing(8)
        label_title = QLabel('Labels')
        label_title.setObjectName('previewSecondary')
        label_row.addWidget(label_title)
        self.label_field = QComboBox()
        self.label_field.addItem('No label', None)
        for field in layer.fields():
            self.label_field.addItem(field.name(), field.name())
        saved_field = parent.preview_label_fields.get(layer.id())
        saved_index = self.label_field.findData(saved_field) if saved_field else 0
        self.label_field.setCurrentIndex(max(0, saved_index))
        label_row.addWidget(self.label_field, 1)
        layout.addLayout(label_row)
        self.canvas = QgsMapCanvas(self)
        self.canvas.setCanvasColor(QColor(THEMES[parent.theme]["surface"]))
        if layer.crs().isValid():
            self.canvas.setDestinationCrs(layer.crs())
        self.canvas.setLayers([])
        self.canvas.setMinimumSize(240, 180)
        self.canvas.setToolTip("Drag to pan, scroll to zoom, or click a feature to select it")
        self.map_tool = None
        map_frame = QFrame()
        map_frame.setObjectName('previewMapFrame')
        map_layout = QVBoxLayout(map_frame)
        map_layout.setContentsMargins(1, 1, 1, 1)
        map_layout.addWidget(self.canvas)
        layout.addWidget(map_frame, 1)
        self.outside_band = QgsRubberBand(self.canvas, layer.geometryType())
        self.nearby_band = QgsRubberBand(self.canvas, layer.geometryType())
        self.selected_band = QgsRubberBand(self.canvas, layer.geometryType())
        self.message = QLabel()
        self.message.setObjectName('previewSecondary')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.label_field.currentIndexChanged.connect(lambda *args: self.update_labels())
        self._decoded_snapshot = {"selected": {}, "nearby": {}}
        self._label_placements = {}
        self._band_result_token = None
        self.update_snapshot(snapshot, nearby_count, extent, recenter, nearby_limited=self.nearby_limited)

    def refresh_feature_bands(self, refresh=True):
        """Color selected, in-table nearby, and outside-table nearby features."""
        layer = self.layer
        snapshot = self.snapshot
        if snapshot is None:
            return [], [], 0
        decoded = self._decoded_snapshot
        if hasattr(self.owner, "result_id_set"):
            table_ids = self.owner.result_id_set()
        elif self.owner.result_ids is not None:
            table_ids = set(self.owner.result_ids)
        else:
            table_ids = None
        self._band_result_token = (getattr(self.owner, "query_version", None), id(self.owner.result_ids))
        outside_color = QColor(THEMES.get(self.owner.theme, THEMES["light"])["outside"])
        outside_fill = QColor(outside_color)
        outside_fill.setAlpha(45)

        self.outside_band.reset(layer.geometryType())
        self.outside_band.setStrokeColor(outside_color)
        self.outside_band.setFillColor(outside_fill)
        self.outside_band.setLineStyle(Qt.PenStyle.DashLine)
        self.outside_band.setWidth(1)
        self.outside_band.setIconSize(8)

        self.nearby_band.reset(layer.geometryType())
        self.nearby_band.setStrokeColor(QColor("#a7aea9"))
        self.nearby_band.setFillColor(QColor(150, 160, 153, 35))
        self.nearby_band.setWidth(1)
        self.nearby_band.setIconSize(8)

        self.selected_band.reset(layer.geometryType())
        self.selected_band.setStrokeColor(QColor("#26805b"))
        self.selected_band.setFillColor(QColor(46, 125, 91, 55))
        self.selected_band.setWidth(3)
        self.selected_band.setIconSize(10)

        bounds = []
        selected_bounds = []
        outside_count = 0
        for fid, geometry in decoded["nearby"].items():
            if table_ids is not None and fid not in table_ids:
                self.outside_band.addGeometry(geometry, None, False)
                outside_count += 1
            else:
                self.nearby_band.addGeometry(geometry, None, False)
            bounds.append(geometry.boundingBox())
        for geometry in decoded["selected"].values():
            self.selected_band.addGeometry(geometry, None, False)
            rect = geometry.boundingBox()
            bounds.append(rect)
            selected_bounds.append(rect)
        for band in (self.outside_band, self.nearby_band, self.selected_band):
            band.show()
        self.outside_swatch.setVisible(outside_count > 0)
        self.outside_label.setVisible(outside_count > 0)
        if refresh:
            self.canvas.refresh()
        self.update_message(outside_count)
        return bounds, selected_bounds, outside_count

    def update_message(self, outside_count=0):
        if not self.nearby_count:
            text = "No touching features found."
        else:
            count_text = "{}+".format(self.nearby_count) if self.nearby_limited else str(self.nearby_count)
            text = "{} touching feature(s) found.".format(count_text)
            if outside_count:
                text += " ({} outside table)".format(outside_count)
        if self.nearby_limited or self.snapshot["truncated"]:
            text += " Map preview is limited; the table is unchanged."
        self.message.setText(text)

    def update_snapshot(self, snapshot, nearby_count, extent=None, recenter=True, nearby_limited=False):
        """Refresh preview geometries, map tool, extent, message, and labels in place."""
        self.snapshot = snapshot
        self._decoded_snapshot = _decode_snapshot_geometries(snapshot)
        self._label_placements = dict(snapshot.get("label_placements") or {})
        self.nearby_count = nearby_count
        self.nearby_limited = bool(nearby_limited)
        layer = self.layer
        if self.map_tool is None:
            self.map_tool = PreviewPanSelectTool(
                self.canvas, layer, snapshot, self.owner.focus_preview_feature,
                can_select=self.owner.can_select_preview_feature,
                geometries=self._decoded_snapshot,
            )
            self.canvas.setMapTool(self.map_tool)
        else:
            self.map_tool.set_snapshot_data(layer, snapshot, self._decoded_snapshot)
            if self.canvas.mapTool() is not self.map_tool:
                self.canvas.setMapTool(self.map_tool)
        bounds, selected_bounds, _ = self.refresh_feature_bands(refresh=False)
        if extent is not None and recenter and selected_bounds:
            xmin_sel = min(r.xMinimum() for r in selected_bounds)
            xmax_sel = max(r.xMaximum() for r in selected_bounds)
            ymin_sel = min(r.yMinimum() for r in selected_bounds)
            ymax_sel = max(r.yMaximum() for r in selected_bounds)
            x = (xmin_sel + xmax_sel) / 2
            y = (ymin_sel + ymax_sel) / 2
            recentered = QgsRectangle(x - extent.width() / 2, y - extent.height() / 2,
                                      x + extent.width() / 2, y + extent.height() / 2)
            view_geom = QgsGeometry.fromRect(recentered)
            too_zoomed_in = ((xmax_sel - xmin_sel) > extent.width() * 2.5
                             or (ymax_sel - ymin_sel) > extent.height() * 2.5)
            if not too_zoomed_in and any(geom.intersects(view_geom) for geom in self._decoded_snapshot["selected"].values()):
                extent = recentered
            else:
                extent = None
        if extent is None and bounds:
            xmin = min(rect.xMinimum() for rect in bounds)
            xmax = max(rect.xMaximum() for rect in bounds)
            ymin = min(rect.yMinimum() for rect in bounds)
            ymax = max(rect.yMaximum() for rect in bounds)
            coordinate_scale = max(abs(xmin), abs(xmax), abs(ymin), abs(ymax), 1.0)
            span = max(xmax - xmin, ymax - ymin, coordinate_scale * 1e-9)
            margin = span * 0.12
            if selected_bounds:
                x = (min(r.xMinimum() for r in selected_bounds) + max(r.xMaximum() for r in selected_bounds)) / 2
                y = (min(r.yMinimum() for r in selected_bounds) + max(r.yMaximum() for r in selected_bounds)) / 2
                half_width = max(x - xmin, xmax - x) + margin
                half_height = max(y - ymin, ymax - y) + margin
                extent = QgsRectangle(x - half_width, y - half_height, x + half_width, y + half_height)
            else:
                extent = QgsRectangle(xmin - margin, ymin - margin, xmax + margin, ymax + margin)
        if extent is not None:
            self.canvas.setExtent(extent)
        self.canvas.refresh()
        self.update_labels()

    def update_labels(self, refresh_values=False):
        for item in self.label_items.values():
            self.canvas.scene().removeItem(item)
        self.label_items = {}
        field = self.label_field.currentData()
        self.owner.preview_label_fields[self.layer.id()] = field
        if field is None:
            return
        geometries = dict(self._decoded_snapshot['nearby'])
        geometries.update(self._decoded_snapshot['selected'])
        if not geometries:
            return
        if not refresh_values and self.snapshot.get('label_field') == field and 'labels' in self.snapshot:
            labels_map = self.snapshot['labels']
        else:
            index = self.layer.fields().indexFromName(field)
            if index < 0:
                return
            labels_map = {}
            request = QgsFeatureRequest().setFilterFids(list(geometries))
            request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
            request.setSubsetOfAttributes([index])
            for feature in self.layer.getFeatures(request):
                value = attribute_text(feature.attribute(index))
                if value:
                    labels_map[feature.id()] = value
            self.snapshot['label_field'] = field
            self.snapshot['labels'] = labels_map
        for fid, value in labels_map.items():
            if not value or fid not in geometries:
                continue
            placement = self._label_placements.get(fid)
            if placement is None:
                placement = preview_label_placement(geometries[fid])
                if placement is None:
                    continue
                self._label_placements[fid] = placement
            x, y, angle = placement
            self.label_items[fid] = PreviewLabel(
                self.canvas, QgsPointXY(x, y), value, fid in self.snapshot['selected'], angle,
                theme=getattr(self.owner, "theme", "light"),
            )
