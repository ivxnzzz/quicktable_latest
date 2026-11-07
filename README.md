# QuickTable

A QGIS 3 plugin for searching and filtering vector layers, including tables
without geometry. Open **QuickTable** from the plugin menu or toolbar, or
press **Ctrl+Shift+F**.

Choose a layer, add field filters, or search across every field.
QuickTable follows the active vector layer in QGIS, including when restored
after changing layers. Switching layers clears the previous column filters;
returning to the same layer preserves them.
Unavailable vector layers are omitted from the layer list; they reappear when
QGIS reports them as valid again.
Select rows to select and zoom to their features. Enable edit mode to change
attributes; Save and Discard apply to all pending edits on the selected layer.

Light mode is the default; an explicitly saved theme preference is retained.
Both filters start with **Equals** and return to it when filters are cleared.
Both themes use muted green accents; light mode pairs forest-green buttons
with pale-green selections, and dark mode uses lighter green accents.
Errors and Discard retain their red styling.

Open **Settings** in the header to choose an installed font, a text size
from 8 to 24 points, Light/Dark theme, and **Keep QuickTable on top**.
Each font name in the dropdown is drawn in its own family. The size control
has visible up/down arrow buttons. Preview your font and theme in the modal,
then **Save** to apply the choices; **Cancel** keeps your previous settings.
Table rows adjust to fit larger text. Settings are remembered across sessions.

Each filter offers **Equals**, **Contains**, **Greater than**, **Less than**,
**Between** (inclusive), **Is empty**, and **Is not empty**. Contains matches
literal text without case sensitivity. Equals uses exact values, including
case for text fields. Numeric comparisons use the field's numeric type.
Use ISO dates such as `2026-11-06` for date comparisons. Is empty matches NULL
values and empty strings. All filter rows are combined with AND.

Click a **column name** to sort all matching records before pagination; click
it again to reverse the order. Click the **filter below the name** to open that
column's filter and options. Drag a column border to resize it. With
**Equals**, click anywhere on a value row to toggle its checkbox. You can
check one or more values; use the search box to find values and **Done** to
close the popup. For example, checking Barangay 1, 2 and 3 means
`Barangay = 1 OR Barangay = 2 OR Barangay = 3`. Select **(all)** to remove that
value constraint. Use **Use typed value** to include a value not listed, or
type one exact value into the field. Checked values survive list refreshes;
changing the field or clearing filters clears them.

Green filter controls identify columns with an active condition and show a
summary of it. Reopen a column's filter to edit or clear the condition.

The toolbar groups the layer and search controls, selection and map actions,
and editing and export actions into three rows. Hover over icon buttons for
their names and actions; copy and CSV export use selected rows when available,
otherwise the current page. Use **Tools** to hide or show the lower rows; the choice is
remembered, while layer, search and settings remain available.

Enable **Wrap text** in a column's header dropdown to wrap its cell values.
Drag the column border to choose its width; row heights adjust to show the
wrapped text. Wrapping and column widths are saved per layer and field, and
are restored after filtering another column, refreshing, sorting or paging.
Clearing a filter does not turn wrapping off. Disable Wrap text in that
column's header to return to single-line cells.

Numeric column menus include **Number display**. Hide trailing zeros shows
`1.0` as `1` without rounding; the whole-number and decimal-place options
round the displayed text. These are display preferences only: editing, filters,
copy and export continue to use the original values.

Filtering starts from the column headers. Use **Columns…** to show a hidden
field if you want to filter it. Operators such as Contains and Between are
inside the filter dropdown. **Clear filter** removes that column's
condition. Clear search text using the search box's ×. Conditions across
fields still use AND, while checked values within one Equals filter use OR.
Value suggestions respect the other active column conditions regardless of
the order in which filters were added. Checked values are retained when the
conditions change, even if the combination currently has no matching records.
**Clear filters** clears column conditions, search, Selected only and nearby
results; it keeps the layer's map selection.

**Columns…** chooses which fields appear in the table and exports. At least
one column stays visible. The choice is remembered for each layer in its
project; hidden fields remain searchable and available in filter controls.

**Select page** selects every row on the current page on the table and map.
With pagination off, it becomes **Select all** and selects all matching rows. **Unselect**
clears both selections for the current layer. Ctrl-click toggles individual
rows and Shift-click selects a range. Enable **Multi-select** to toggle rows
with ordinary clicks, without holding Ctrl. The selected count appears above
the table. Background list refreshes preserve selected features still present
in the results. QuickTable reflects selections made in QGIS, including those
made before opening the plugin. Changing pages preserves the map selection;
only selected features on the current page are highlighted in the table.
The selection count shows the total and, when different, the count on the page.
Copy, export and zoom also apply to the current page (or all
matching rows with pagination off).

To delete features, enable **edit mode**, select rows and click **Delete selected**.
The confirmation shows the selected count and layer name; **Cancel** is the
default. Deletion removes full features, including their geometry, from the
layer's pending edits. Use **Save edits** to commit, **Discard edits** to roll
back all unsaved changes, or QGIS Undo to undo the deletion command. The action
is unavailable for sources that do not support deleting features and never
defaults to deleting unselected rows.

The edit indicator shows **Editable**, **Editing**, or **Read-only**. Hover
over it for the reason; sources that cannot change attributes have edit mode
disabled. Read-only fields are protected even inside writable layers. If
editing cannot start because of source permissions or a lock, correct the
cause and use **Refresh lists** to retry. Attribute editing applies equally
to points, lines, polygons, multipart features and tables without geometry.

**Undo** and **Redo** use the current layer's QGIS editing history, including
deletions and other layer edits. Cells with unsaved attribute changes have a
green background; the highlight clears after saving or discarding changes.
Selection colors may temporarily cover the highlight.

**Selected only** shows the layer's current QGIS selection, intersected with
the filters. It updates when the map or table selection changes.

**Nearby…** finds features in the same layer that touch the current selection,
or lie within a chosen straight-line distance of it. The selected starting
features are excluded; results are intersected with other column and search
filters. The nearby results are a snapshot: run the search again after changing
the selection or geometry. Use **Nearby… → Clear nearby results** to return to
the normal table. Turning on Selected only also clears the nearby view.
Distances use the layer CRS's coordinate units, not necessarily metres. For
geographic CRS layers these are degrees; use an appropriate projected layer
for meaningful local distance measurements. Touching depends on valid geometry
and exact shared boundaries or corners.

**Bulk edit…** changes one writable field on selected table rows. Choose the
field and value and review the preview in one dialog before applying; the whole
operation is one undo command and remains unsaved until committed. Empty input
sets NULL. Date fields with existing ISO dates offer a calendar, boolean
fields offer a true/false dropdown, and configured QGIS Value Map fields offer
their mapped choices. Other cells use text editing.

**Autofill…** fills a chosen column for selected rows or all rows on the current
page in their displayed order:
use one value, a numeric sequence with a start and step, or a repeating list
of values (one per line). It previews changes and applies them as one undoable
edit. Save commits them; canceling the preview changes nothing. These actions
check value types but do not perform full QGIS form-constraint validation.
An existing column retains its original storage type. **Fields → Add field…** adds a new,
empty attribute with a chosen type when the data source supports adding fields.
The field is a pending edit until saved and can be undone before saving.
The field dialog offers a declared length and decimal precision where relevant;
actual support and limits depend on the data source. **Fields → Delete field…** removes
the selected attribute and all its values across the layer after confirmation.
Primary-key, joined, virtual and configured read-only fields are excluded.
The deletion remains pending until saved and can be undone before saving.

**Saved filters** saves, loads or deletes named column conditions and search
text per layer and project. Selected-only scope is not saved. Use the
**Statistics** button to show or hide a strip above the table. Each visible
column shows missing and distinct counts across all matching records. Numeric
fields include a histogram; low-cardinality text fields show common values.
The strip follows column widths and scrolling; hover for non-null counts and
numeric sum, average, minimum and maximum. Statistics update after filtering
or editing and use floating-point arithmetic. Distinct counts above 25,000 per
column are shown as a lower bound to limit memory use.

**Rows per page** offers 100, 250, 500, 1,000 or 2,000 rows, plus **All results**
to turn pagination off. The default is 500 and your choice is remembered.
**Previous** and **Next** navigate the results, with the current range, total
matches and page count shown beside them. All matching results are accessible;
there is no longer a 2,000-result cutoff. Matching records are found in the
background. All results may take longer to display on large layers.
Changing a filter or page size returns to the first page. Refreshing data keeps
the current page when it still exists. Changing the sort returns to the first page.

Dropdown suggestions load in the background from up to 2,000 matching features;
typed filters still search the full layer. Partial filters survive list
refreshes even when absent from the suggestions.

Copy and CSV export use spreadsheet-safe text: formula-like cells receive a
leading apostrophe. Tabs, quotes and line breaks inside cells are quoted so
they remain in their original cells when imported as delimited text.

Numeric edits use the QGIS field type. Integer fields keep exact integers;
double fields reject non-finite numbers and decimal inputs whose digits would
be lost during conversion, instead of silently rounding the entered value.

Version 1.3 renames Parcel Finder to Layer Filter. Existing theme and pin
preferences are retained. When installing the renamed ZIP beside an existing
Parcel Finder installation, disable the old plugin to avoid duplicate actions.
Version 1.4 adds the edit indicator, filter operators, saved column visibility
and selection controls. Version 1.4.1 defaults to light mode and Equals filters.
Version 1.4.2 updates both themes to muted green accents.
Version 1.5 renames the plugin to Quick Filter and adds a green funnel-and-speed
logo to the toolbar, dialog and plugin listing. Theme, pin and column
preferences carry over from Layer Filter.
Version 1.5.1 simplifies the logo to a green outline funnel with a transparent
background.
Version 1.5.2 changes the outline icon to black, keeping its background transparent.
Version 1.6 replaces the duplicate icon inside the dialog header with a green
dot and adds optional pagination. The toolbar and title bar keep the black icon.
Version 1.6.1 fixes blank pages caused by passing a tuple of feature IDs to
QGIS bindings that require a list.
Version 1.7 adds saved font selection and text size controls.
Version 1.7.1 moves font controls into a Settings modal with preview, Save and Cancel.
Version 1.7.2 fixes font-family previews and size arrows and moves theme and
pinning into Settings.
Version 1.8 adds multi-value filtering through Equals any of and a Values picker.
Version 1.9 puts checkboxes directly into Equals dropdowns and adds dynamic
filter rows with Add filter and Remove controls.
Version 1.9.1 fixes delayed display of newly added filters and scrolls the new
row into view without refreshing the whole dialog.
Version 1.10 moves Add filter beside Clear filters, adds confirmed deletion of
selected features in edit mode, and makes whole value rows clickable.
Version 1.10.1 preserves the chosen layer, filters and current page when
minimizing/restoring or raising the window. QGIS active-layer changes are
ignored while Quick Filter is minimized.
Version 1.11 replaces numbered filter rows with compact chips, column-header
funnels and filter popups. The filter expressions and section behavior are unchanged.
Version 1.12 combines sorting and filtering in each column header and removes
the separate + Filter entry point. Sort choices persist across refreshes and pages.
Version 1.13 removes the chip bar and top Clear button; filters are managed
entirely through the column-header dropdowns.
Version 1.14 adds per-column Wrap text in the header dropdown, with saved
wrapping and widths independent of filter state.
Install `quick_filter-1.14.zip` through QGIS's
**Plugins → Manage and Install Plugins → Install from ZIP** and restart QGIS
to load the updated code.

Run the regression suite with `python -m unittest discover -s tests -v`.
QGIS integration tests run in a QGIS Python environment and are skipped when
QGIS is unavailable.
For the full suite with isolated settings and offscreen rendering, run
`python tests/run_qgis_tests.py` using QGIS's Python launcher. Version 1.9 was
validated with QGIS 3.44.
