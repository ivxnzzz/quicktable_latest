"""Schema management and batch attribute/feature editing actions for FinderDialog."""

from decimal import Decimal, InvalidOperation
import sys

from qgis.PyQt.QtCore import QMetaType, QSettings, Qt
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.core import NULL, QgsField, QgsFields, QgsVectorDataProvider

from .editing import convert_attribute, validate_change, validation_request
from .tasks import field_kind


def _ui(owner):
    """Resolve UI dialog/messagebox classes on the owner's module so test patches still apply."""
    return sys.modules[owner.__class__.__module__]


def is_field_read_only(layer, index):
    """Return True when a layer field is marked read-only by form config or provider flags."""
    field = layer.fields()[index]
    return bool(
        layer.editFormConfig().readOnly(index)
        or (hasattr(field, "isReadOnly") and field.isReadOnly())
    )


def writable_field_names(layer, text_only=False):
    """Return names of editable layer fields, optionally restricted to text columns."""
    form = layer.editFormConfig()
    names = []
    for index, field in enumerate(layer.fields()):
        if text_only and field.type() != QMetaType.Type.QString:
            continue
        if not form.readOnly(index) and not (hasattr(field, "isReadOnly") and field.isReadOnly()):
            names.append(field.name())
    return names


def deletable_field_indices(layer):
    """Return field indices on layer that can be safely deleted in an edit session."""
    fields = layer.fields()
    primary_keys = set(layer.primaryKeyAttributes())
    form = layer.editFormConfig()
    return [
        index for index in range(fields.count())
        if index not in primary_keys
        and fields.fieldOrigin(index) in (QgsFields.FieldOrigin.OriginProvider, QgsFields.FieldOrigin.OriginEdit)
        and not form.readOnly(index)
        and not (hasattr(fields[index], "isReadOnly") and fields[index].isReadOnly())
    ]


def autofill_values(field, mode, text, step_text, count, converter=convert_attribute):
    """Compute validated typed replacement values for autofill modes."""
    if mode == "null":
        return [NULL] * count
    if mode == "same":
        return [converter(field, text)] * count
    if mode == "repeat":
        if not text:
            raise ValueError("Enter at least one value to repeat.")
        values = [converter(field, value) for value in text.split("\n")]
        return [values[i % len(values)] for i in range(count)]
    if mode != "sequence" or field_kind(field) not in ("integer", "number"):
        raise ValueError("Number sequences require a numeric field.")
    try:
        start, step = Decimal(text.strip()), Decimal(step_text.strip())
        if not start.is_finite() or not step.is_finite():
            raise ValueError("Start and step must be finite numbers.")
        output = []
        limits = {
            QMetaType.Type.Int: (-(2**31), 2**31 - 1),
            QMetaType.Type.UInt: (0, 2**32 - 1),
            QMetaType.Type.LongLong: (-(2**63), 2**63 - 1),
            QMetaType.Type.ULongLong: (0, 2**64 - 1),
        }
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
                output.append(converter(field, format(number, "f")))
        return output
    except (InvalidOperation, OverflowError):
        raise ValueError("Enter valid start and step numbers.")


def add_field(owner, ui=None):
    """Prompt for and create one or more new attributes as a single undo command."""
    ui = ui or _ui(owner)
    layer = owner.current_layer()
    if not layer or not layer.isEditable() or layer.readOnly():
        return
    provider = layer.dataProvider()
    if not provider or not provider.capabilities() & QgsVectorDataProvider.Capability.AddAttributes:
        owner.status.setText("This layer does not support adding fields.")
        return
    dialog = ui.AddFieldDialog(owner)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        dialog.deleteLater()
        return
    specs = dialog.field_specs()
    dialog.deleteLater()
    names = [spec[0] for spec in specs]
    if not names or any(not name for name in names):
        ui.QMessageBox.warning(owner, "Add field", "Enter a name for each field.")
        return
    if owner.current_layer() != layer or not layer.isEditable():
        owner.status.setText("Layer or edit mode changed. Field was not added.")
        return
    if len({item.casefold() for item in names}) != len(names) or any(layer.fields().lookupField(item) >= 0 for item in names):
        ui.QMessageBox.warning(owner, "Add field", "Field names must be unique and must not already exist.")
        return
    if any(length and precision >= length for _, _, length, precision in specs):
        ui.QMessageBox.warning(owner, "Add field", "Decimal precision must be smaller than the field length.")
        return
    command_open = False
    error = None
    owner.own_edit = True
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
                if type_name == "text":
                    # PostgreSQL reports unbounded text with typmod -1.
                    length = -1
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
        owner.own_edit = False
    if error is None:
        key = owner.column_settings_key()
        hidden = QSettings().value(key, []) if key else []
        if isinstance(hidden, str):
            hidden = [hidden]
        if key and any(item in (hidden or []) for item in names):
            QSettings().setValue(key, [item for item in hidden if item not in names])
        if key:
            # Refit regular columns when the schema grows, including widths
            # saved by older versions which stretched the last column.
            wrapped = owner.wrapped_fields()
            widths = owner.saved_column_widths(key)
            for field_name in list(widths):
                if field_name not in wrapped:
                    del widths[field_name]
            owner.pending_column_widths[key] = widths
            owner.column_layout_timer.start()
        owner.pending_added_field = (layer.id(), names[0])
    owner.soft_refresh()
    owner.status.setText(
        "Could not add field: " + error if error else
        "Added {} field(s); save edits to commit.".format(len(names))
    )


def delete_field(owner, ui=None):
    """Prompt for and remove selected layer fields as one undo command."""
    ui = ui or _ui(owner)
    layer = owner.current_layer()
    provider = layer.dataProvider() if layer else None
    if (not layer or not layer.isEditable() or layer.readOnly() or not provider
            or not provider.capabilities() & QgsVectorDataProvider.Capability.DeleteAttributes):
        owner.status.setText("This layer does not allow deleting fields in the current edit mode.")
        return
    indices = deletable_field_indices(layer)
    if not indices:
        owner.status.setText("No deletable fields are available.")
        return
    names = [layer.fields()[i].name() for i in indices]
    dialog = ui.DeleteFieldsDialog(owner, names)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        dialog.deleteLater()
        return
    selected = dialog.selected_names()
    dialog.deleteLater()
    if not selected:
        owner.status.setText("No fields selected.")
        return
    question = (
        "Delete {} field(s) from '{}'?\n\n{}\n\nThis removes their values from every feature. "
        "The deletion remains pending until Save edits; you can undo it before saving."
    ).format(len(selected), layer.name(), "\n".join(selected))
    if ui.QMessageBox.question(
            owner, "Delete fields", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
        return
    indices = [layer.fields().indexFromName(name) for name in selected]
    allowed = set(deletable_field_indices(layer))
    if (owner.current_layer() != layer or not layer.isEditable() or layer.readOnly()
            or any(index < 0 or index not in allowed for index in indices)
            or not layer.dataProvider().capabilities() & QgsVectorDataProvider.Capability.DeleteAttributes):
        owner.status.setText("The layer or fields changed. Field deletion canceled.")
        return
    command_open = False
    error = None
    owner.own_edit = True
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
        owner.own_edit = False
    owner.soft_refresh()
    owner.status.setText(
        "Could not delete fields: " + error if error else
        "Deleted {} field(s); save edits to commit.".format(len(selected))
    )


def bulk_edit(owner, attribute_request_fn, ui=None):
    """Apply a uniform validated attribute edit across selected rows."""
    ui = ui or _ui(owner)
    layer = owner.current_layer()
    fids = list(dict.fromkeys(owner.selected_fids()))
    if not layer or not layer.isEditable() or not fids:
        return
    names = writable_field_names(layer)
    if not names:
        owner.status.setText("No writable fields available.")
        return
    dialog = ui.BulkEditDialog(owner, layer, names, fids)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    name = dialog.field.currentText()
    index = layer.fields().indexFromName(name)
    value = dialog.value
    dialog.deleteLater()
    if (owner.current_layer() != layer or not layer.isEditable() or set(owner.selected_fids()) != set(fids)
            or index < 0 or is_field_read_only(layer, index)):
        owner.status.setText("Layer or selection changed. Bulk edit canceled.")
        return
    current_features = {feature.id(): feature for feature in layer.getFeatures(validation_request(layer, fids))}
    current = {fid: current_features[fid][index] for fid in current_features}
    if current != dialog.original_values:
        owner.status.setText("Values changed after the preview. Bulk edit canceled.")
        return
    error = None
    command_open = False
    owner.own_edit = True
    try:
        layer.beginEditCommand("QuickTable: bulk edit {}".format(name))
        command_open = True
        for fid in fids:
            validate_change(layer, fid, index, value, feature=current_features.get(fid))
            if not layer.changeAttributeValue(fid, index, value):
                raise RuntimeError("The layer refused a change to feature {}".format(fid))
        layer.endEditCommand()
        command_open = False
    except Exception as exc:
        error = str(exc)
        if command_open:
            layer.destroyEditCommand()
    finally:
        owner.own_edit = False
    owner.soft_refresh()
    owner.status.setText(
        "Bulk edit failed: " + error if error else
        "Changed {} feature(s); save to commit.".format(len(fids))
    )


def apply_multi_replacements(owner, layer, names, originals, changes, attribute_request_fn, entire_layer=False):
    """Apply and constraint-check text replacements across multiple columns in one undo command."""
    indices = [layer.fields().indexFromName(name) for name in names]
    if (owner.current_layer() != layer or not layer.isEditable() or layer.readOnly()
            or any(index < 0 or layer.fields()[index].type() != QMetaType.Type.QString
                   or is_field_read_only(layer, index)
                   for index in indices)):
        owner.status.setText("The layer or columns changed. Replace canceled.")
        return False
    request = attribute_request_fn(list(originals) if not entire_layer else None, indices)
    current = {
        feature.id(): {index: feature[index] for index in indices}
        for feature in layer.getFeatures(request)
    }
    if current != originals:
        owner.status.setText("Values or features changed after the preview. Replace canceled.")
        return False
    opened = False
    owner.own_edit = True
    try:
        layer.beginEditCommand("QuickTable: find and replace")
        opened = True
        for fid, values in changes.items():
            for index, value in values.items():
                converted = convert_attribute(layer.fields()[index], value)
                if not layer.changeAttributeValue(fid, index, converted):
                    raise ValueError("The layer refused feature {}".format(fid))
        # Validate complete records after every proposed change has been
        # staged, so cross-field constraints see the final values.
        updated = {feature.id(): feature for feature in layer.getFeatures(validation_request(layer, list(changes)))}
        for fid, values in changes.items():
            index = next(iter(values))
            feat = updated.get(fid)
            value = feat[index] if feat is not None and feat.isValid() else None
            validate_change(layer, fid, index, value, feature=feat)
        layer.endEditCommand()
        opened = False
    except Exception as exc:
        if opened:
            layer.destroyEditCommand()
        owner.status.setText("Replace failed: {}".format(exc))
        return False
    finally:
        owner.own_edit = False
    owner.soft_refresh()
    owner.status.setText("Changed {} feature(s); save edits to commit.".format(len(changes)))
    return True


def apply_replacements(owner, layer, name, originals, changes):
    """Apply and constraint-check text replacements in one column as a single undo command."""
    index = layer.fields().indexFromName(name)
    if (owner.current_layer() != layer or not layer.isEditable() or layer.readOnly() or index < 0
            or field_kind(layer.fields()[index]) != "text" or is_field_read_only(layer, index)):
        owner.status.setText("The layer or field changed. Replace canceled.")
        return False
    current_features = {feature.id(): feature for feature in layer.getFeatures(validation_request(layer, list(originals)))}
    current = {fid: current_features[fid][index] for fid in current_features}
    if current != originals:
        owner.status.setText("Values changed after the preview. Replace canceled.")
        return False
    command_open = False
    owner.own_edit = True
    try:
        layer.beginEditCommand("QuickTable: find and replace {}".format(name))
        command_open = True
        for fid, value in changes.items():
            converted = convert_attribute(layer.fields()[index], value)
            validate_change(layer, fid, index, converted, feature=current_features.get(fid))
            if not layer.changeAttributeValue(fid, index, converted):
                raise ValueError("The layer refused feature {}".format(fid))
        layer.endEditCommand()
        command_open = False
    except Exception as exc:
        if command_open:
            layer.destroyEditCommand()
        owner.status.setText("Replace failed: {}".format(exc))
        return False
    finally:
        owner.own_edit = False
    owner.soft_refresh()
    owner.status.setText("Changed {} feature(s); save edits to commit.".format(len(changes)))
    return True


def find_replace(owner, ui=None):
    """Open Find and Replace for writable text columns on the current layer."""
    ui = ui or _ui(owner)
    layer = owner.current_layer()
    if layer is None or not layer.isEditable():
        owner.status.setText("Enable edit mode before replacing.")
        return
    names = writable_field_names(layer, text_only=True)
    if not names:
        owner.status.setText("No writable text fields are available.")
        return
    dialog = ui.FindReplaceDialog(owner, layer, names)
    dialog.exec()
    dialog.deleteLater()


def autofill(owner, attribute_request_fn, ui=None):
    """Preview and apply column autofill edits across selected or page features."""
    ui = ui or _ui(owner)
    layer = owner.current_layer()
    selected_fids = list(dict.fromkeys(owner.selected_fids()))
    page_fids = list(dict.fromkeys(owner.all_fids()))
    if not layer or not layer.isEditable() or not page_fids:
        return
    names = writable_field_names(layer)
    if not names:
        owner.status.setText("No writable fields available.")
        return
    dialog = ui.AutofillDialog(owner, names, len(selected_fids), len(page_fids))
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
        owner.status.setText("Select rows or choose the entire current page for autofill.")
        return
    fields = layer.fields()
    index = fields.indexFromName(name)
    field = fields[index]
    try:
        values = owner.autofill_values(field, mode, text, step, len(fids))
    except (ValueError, OverflowError) as exc:
        ui.QMessageBox.warning(owner, "Autofill", "Invalid values: {}".format(exc))
        return
    features = {feature.id(): feature for feature in layer.getFeatures(attribute_request_fn(fids, [index]))}
    if len(features) != len(fids):
        owner.status.setText("A selected feature is unavailable. Autofill canceled.")
        return
    preview = []
    for fid, value in list(zip(fids, values))[:10]:
        old = features[fid][index]
        preview.append("{}: {} → {}".format(
            fid,
            "NULL" if old is None or old == NULL else str(old),
            "NULL" if value is None or value == NULL else str(value),
        ))
    if len(fids) > 10:
        preview.append("… and {} more".format(len(fids) - 10))
    scope_label = "selected rows" if scope == "selected" else "all rows on this page"
    message = (
        "Fill column '{}' for {} rows ({}), in table order?\n\n{}\n\n"
        "Changes remain unsaved until Save edits."
    ).format(name, len(fids), scope_label, "\n".join(preview))
    if ui.QMessageBox.question(
            owner, "Confirm autofill", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
        return
    current_fids = owner.selected_fids() if scope == "selected" else owner.all_fids()
    if (owner.current_layer() != layer or not layer.isEditable() or current_fids != fids
            or index >= layer.fields().count() or layer.fields()[index].name() != name
            or is_field_read_only(layer, index)):
        owner.status.setText("Layer, field or row order changed. Autofill canceled.")
        return
    current = {feature.id(): feature for feature in layer.getFeatures(validation_request(layer, fids))}
    if len(current) != len(fids) or any(current[fid][index] != features[fid][index] for fid in fids):
        owner.status.setText("Values changed after the preview. Autofill canceled.")
        return
    error, command_open = None, False
    owner.own_edit = True
    try:
        layer.beginEditCommand("QuickTable: autofill {}".format(name))
        command_open = True
        for fid, value in zip(fids, values):
            validate_change(layer, fid, index, value, feature=current.get(fid))
            if not layer.changeAttributeValue(fid, index, value):
                raise RuntimeError("The layer refused a change to feature {}".format(fid))
        layer.endEditCommand()
        command_open = False
    except Exception as exc:
        error = str(exc)
        if command_open:
            layer.destroyEditCommand()
    finally:
        owner.own_edit = False
    owner.soft_refresh()
    owner.status.setText(
        "Autofill failed: " + error if error else
        "Filled {} row(s); save to commit.".format(len(fids))
    )


def delete_selected(owner, ui=None):
    """Confirm and delete selected features as one undoable edit command."""
    ui = ui or _ui(owner)
    allowed, reason = owner.deletion_availability()
    if not allowed:
        owner.status.setText(reason)
        return
    layer = owner.current_layer()
    layer_id = layer.id()
    fids = list(dict.fromkeys(owner.selected_fids()))
    question = ui.QMessageBox(owner)
    question.setWindowTitle("Delete selected features")
    question.setIcon(QMessageBox.Icon.Warning)
    question.setTextFormat(Qt.TextFormat.PlainText)
    question.setText("Delete {} selected feature(s) from '{}'?".format(len(fids), layer.name()))
    question.setInformativeText(
        "This deletes the full features, including their geometry.\n"
        "The deletion stays unsaved until you click Save edits. Discard edits rolls back all unsaved changes."
    )
    delete_btn = question.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
    cancel_btn = question.addButton(QMessageBox.StandardButton.Cancel)
    question.setDefaultButton(cancel_btn)
    question.setEscapeButton(cancel_btn)
    question.exec()
    confirmed = question.clickedButton() == delete_btn
    question.deleteLater()
    if not confirmed:
        return
    layer = owner.current_layer()
    if layer is None or layer.id() != layer_id:
        owner.status.setText("The current layer changed. Deletion canceled.")
        return
    allowed, reason = owner.deletion_availability(fids)
    if not allowed:
        owner.status.setText(reason)
        return
    owner.timer.stop()
    owner.search_timer.stop()
    owner.filter_timer.stop()
    owner.pending_cascade_start = None
    command_open = False
    error = None
    owner.own_edit = True
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
        owner.own_edit = False
    if error:
        owner.soft_refresh()
        owner.status.setText("Could not delete: " + error)
        return
    owner.unselect_all()
    owner.pending_notice = "Deleted {} feature(s). Not saved yet — click Save edits to commit.".format(len(fids))
    owner.soft_refresh()
    owner.status.setText(owner.pending_notice)
