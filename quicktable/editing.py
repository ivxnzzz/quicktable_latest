"""Typed attribute conversion and layer-constraint validation."""

import re

from qgis.PyQt.QtCore import QDate, QDateTime, QTime, QMetaType, Qt
from qgis.core import NULL, QgsExpression, QgsFeature, QgsFeatureRequest, QgsFieldConstraints, QgsVectorLayerUtils

from .filter_utils import checked_float


INTEGER_LIMITS = {
    QMetaType.Type.Int: (-(2**31), 2**31 - 1),
    QMetaType.Type.UInt: (0, 2**32 - 1),
    QMetaType.Type.LongLong: (-(2**63), 2**63 - 1),
    QMetaType.Type.ULongLong: (0, 2**64 - 1),
}


def convert_attribute(field, text):
    if text is None:
        return NULL
    kind = field.type()
    if kind == QMetaType.Type.QString:
        if field.length() > 0 and len(text) > field.length():
            raise ValueError("Text exceeds the field length ({})".format(field.length()))
        return text
    value = text.strip()
    if not value:
        raise ValueError("Enter a value or explicitly set NULL")
    if kind in INTEGER_LIMITS:
        if not re.fullmatch(r"[+-]?\d+", value):
            raise ValueError("Enter a whole number")
        number = int(value)
        low, high = INTEGER_LIMITS[kind]
        if not low <= number <= high:
            raise ValueError("Number is outside the field's range")
        return number
    if kind == QMetaType.Type.Double:
        return checked_float(value)
    if kind == QMetaType.Type.Bool:
        if value.lower() not in ("true", "false", "1", "0"):
            raise ValueError("Enter true or false")
        return value.lower() in ("true", "1")
    temporal = {QMetaType.Type.QDate: QDate, QMetaType.Type.QDateTime: QDateTime,
                QMetaType.Type.QTime: QTime}
    if kind in temporal:
        parsed = temporal[kind].fromString(value, Qt.DateFormat.ISODate)
        if not parsed.isValid():
            raise ValueError("Enter a valid ISO date/time (YYYY-MM-DD, HH:mm:ss, or YYYY-MM-DDTHH:mm:ss)")
        return parsed
    return text


def attribute_text(value):
    if value is None or value == NULL:
        return ""
    if isinstance(value, (QDateTime, QTime)):
        return value.toString(Qt.DateFormat.ISODateWithMs)
    if isinstance(value, QDate):
        return value.toString(Qt.DateFormat.ISODate)
    return str(value)


def _needs_geometry_for_validation(layer):
    if not layer.isSpatial():
        return False
    for field in layer.fields():
        constraints = field.constraints()
        if (constraints.constraintStrength(QgsFieldConstraints.Constraint.ConstraintExpression)
                != QgsFieldConstraints.ConstraintStrength.ConstraintStrengthHard):
            continue
        expr = constraints.constraintExpression()
        if expr and QgsExpression(expr).needsGeometry():
            return True
    return False


def validation_request(layer, fids):
    """Build a batched feature request omitting geometry unless a hard constraint expression needs it."""
    request = QgsFeatureRequest().setFilterFids(list(fids))
    if not _needs_geometry_for_validation(layer):
        request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
    return request


def validate_change(layer, fid, index, value, feature=None):
    if feature is None:
        features = layer.getFeatures(validation_request(layer, [fid]))
        try:
            feature = next(features, QgsFeature())
        finally:
            features.close()
    else:
        feature = QgsFeature(feature)
    if not feature.isValid():
        raise ValueError("Feature {} is no longer available".format(fid))
    feature.setAttribute(index, value)
    # Expressions on another field can depend on the changed attribute.
    _validate_feature(layer, feature)


def _validate_feature(layer, feature):
    for field_index, field in enumerate(layer.fields()):
        valid, errors = QgsVectorLayerUtils.validateAttribute(
            layer, feature, field_index, QgsFieldConstraints.ConstraintStrength.ConstraintStrengthHard)
        if not valid:
            raise ValueError("{} (feature {}): {}".format(field.name(), feature.id(), "; ".join(errors)))


def validate_pending_changes(layer):
    buffer = layer.editBuffer()
    if buffer is None:
        return
    ids = list(set(buffer.changedAttributeValues()) | set(buffer.addedFeatures()))
    if not ids:
        return
    features = layer.getFeatures(validation_request(layer, ids))
    try:
        for feature in features:
            if feature.isValid():
                _validate_feature(layer, feature)
    finally:
        features.close()
