"""Employee Grade: Level, Band and a Sub Bands table with the gross amount of each sub band.

ClickUp 14yr2e586v1 (parent 14yr2e586v0, "Employee Grade, Sub Band & Salary Structure creation
from Employee form"). A grade such as L3-B3 has Level L3, Band B3 and five rows, Sub Band A to E,
each with its Gross Amount. The standard Default Salary Structure / Default Base Pay stay as they are.

Rules (Employee Grade.validate, so the form, Data Import and the API all obey them):
- Level and Band are trimmed; no two grades have the same Level + Band.
- A sub band appears once per grade, and every row has a Gross Amount above zero.
- Minimum Gross is not above Maximum Gross; a sub band outside the range only warns.

Grade data L1-B1 to L10-B10 from the PDF "Employee Grade, Level & Salary Band" Ver1 (ClickUp
14yr2e586v3): setup/data/employee_grades.csv, a Data Import file, loaded by the patch
patches/v16/employee_grades_from_pdf.py.

Sub Band master (ClickUp 14yr2e586v2): A to E, listed in the HR Setup sidebar > Masters after
Employee Grade (`add_sub_band_to_sidebar`).

Hooked in hooks.py: after_migrate `execute` (custom fields, Sub Band A to E on a site without sub
bands, sidebar) and doc_events Employee Grade validate. `get_gross_amount` is for the Create Salary Structure popup.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

LEVEL, BAND, SUB_BANDS = "alt_level", "alt_band", "alt_sub_bands"
CATEGORY, MIN_GROSS, MAX_GROSS = "alt_employee_category", "alt_min_gross", "alt_max_gross"
DEFAULT_SUB_BANDS = ("A", "B", "C", "D", "E")

CUSTOM_FIELDS = {
	"Employee Grade": [
		{
			"fieldname": "alt_band_section",
			"fieldtype": "Section Break",
			"label": "Level & Band",
			"insert_after": "default_base_pay",
		},
		{
			"fieldname": LEVEL,
			"fieldtype": "Data",
			"label": "Level",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"insert_after": "alt_band_section",
			"description": "e.g. L3",
		},
		{
			"fieldname": CATEGORY,
			"fieldtype": "Data",
			"label": "Employee Category",
			"insert_after": LEVEL,
			"description": "e.g. Junior Executive / Junior Engineer",
		},
		{"fieldname": "alt_band_column", "fieldtype": "Column Break", "insert_after": CATEGORY},
		{
			"fieldname": BAND,
			"fieldtype": "Data",
			"label": "Band",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"insert_after": "alt_band_column",
			"description": "e.g. B3",
		},
		{
			"fieldname": MIN_GROSS,
			"fieldtype": "Currency",
			"label": "Minimum Gross",
			"non_negative": 1,
			"insert_after": BAND,
			"description": "Monthly gross salary range of the grade.",
		},
		{
			"fieldname": MAX_GROSS,
			"fieldtype": "Currency",
			"label": "Maximum Gross",
			"non_negative": 1,
			"insert_after": MIN_GROSS,
			"description": "Leave blank for no upper limit (e.g. L10: 1,20,000 onwards).",
		},
		{
			"fieldname": "alt_sub_bands_section",
			"fieldtype": "Section Break",
			"label": "Sub Bands",
			"insert_after": MAX_GROSS,
		},
		{
			"fieldname": SUB_BANDS,
			"fieldtype": "Table",
			"label": "Sub Bands",
			"options": "Employee Grade Sub Band",
			"insert_after": "alt_sub_bands_section",
			"description": "Gross Amount of each sub band of this grade (e.g. A to E).",
		},
	]
}


class DuplicateGradeLevelError(frappe.ValidationError):
	pass


class DuplicateSubBandError(frappe.ValidationError):
	pass


class InvalidGrossAmountError(frappe.ValidationError):
	pass


def validate(doc, method=None):
	"""Employee Grade.validate."""
	doc.set(LEVEL, (doc.get(LEVEL) or "").strip())
	doc.set(BAND, (doc.get(BAND) or "").strip())
	validate_unique_level_band(doc)
	validate_sub_bands(doc)
	validate_gross_range(doc)


def validate_unique_level_band(doc):
	level, band = doc.get(LEVEL), doc.get(BAND)
	if not level and not band:
		return
	other = frappe.db.get_value(
		"Employee Grade", {LEVEL: level, BAND: band, "name": ["!=", doc.name or ""]}, "name"
	)
	if other:
		frappe.throw(
			_("Level {0} and Band {1} are already used by grade {2}.").format(
				frappe.bold(level or "-"), frappe.bold(band or "-"), frappe.bold(other)
			),
			DuplicateGradeLevelError,
			title=_("Duplicate Level and Band"),
		)


def validate_sub_bands(doc):
	seen = {}
	for row in doc.get(SUB_BANDS) or []:
		if row.sub_band in seen:
			frappe.throw(
				_("Sub Band {0} is in rows {1} and {2}. Keep one row per sub band.").format(
					frappe.bold(row.sub_band), seen[row.sub_band], row.idx
				),
				DuplicateSubBandError,
				title=_("Duplicate Sub Band"),
			)
		seen[row.sub_band] = row.idx
		if flt(row.gross_amount) <= 0:
			frappe.throw(
				_("Row {0}: enter a Gross Amount above zero for Sub Band {1}.").format(
					row.idx, frappe.bold(row.sub_band)
				),
				InvalidGrossAmountError,
				title=_("Invalid Gross Amount"),
			)


class InvalidGrossRangeError(frappe.ValidationError):
	pass


def validate_gross_range(doc):
	"""Minimum Gross not above Maximum Gross; a sub band outside the range is only a warning
	(HR may pay a sub band above the published range, e.g. L10 E 2,00,000+)."""
	low, high = flt(doc.get(MIN_GROSS)), flt(doc.get(MAX_GROSS))
	if low and high and low > high:
		frappe.throw(
			_("Minimum Gross {0} is above Maximum Gross {1}.").format(
				frappe.bold(frappe.format_value(low, "Currency")), frappe.bold(frappe.format_value(high, "Currency"))
			),
			InvalidGrossRangeError,
			title=_("Invalid Gross Range"),
		)
	outside = [
		row.sub_band
		for row in doc.get(SUB_BANDS) or []
		if (low and flt(row.gross_amount) < low) or (high and flt(row.gross_amount) > high)
	]
	if outside:
		frappe.msgprint(
			_("Gross Amount of Sub Band {0} is outside the grade range.").format(", ".join(outside)),
			title=_("Check Gross Amounts"),
			indicator="orange",
		)


@frappe.whitelist()
def get_gross_amount(grade, sub_band):
	"""Gross Amount of `sub_band` on `grade`, or None when the grade has no such row."""
	frappe.has_permission("Employee Grade", "read", doc=grade, throw=True)
	return frappe.db.get_value(
		"Employee Grade Sub Band",
		{"parenttype": "Employee Grade", "parent": grade, "parentfield": SUB_BANDS, "sub_band": sub_band},
		"gross_amount",
	)


# ---------------------------------------------------------------------- after_migrate
def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)
	# only on a site with no sub bands yet: HR may rename, disable, delete or add them later
	if not frappe.db.count("Sub Band"):
		for sub_band in DEFAULT_SUB_BANDS:
			frappe.get_doc({"doctype": "Sub Band", "sub_band": sub_band}).insert(ignore_permissions=True)
	add_sub_band_to_sidebar()


# HR Setup sidebar > Masters: Sub Band right after Employee Grade (ClickUp 14yr2e586v2)
SIDEBAR_MODULE = "HR Setup"
SUB_BAND_ITEM = {"type": "Link", "link_type": "DocType", "link_to": "Sub Band", "label": "Sub Band", "child": 1}


def add_sub_band_to_sidebar():
	"""Site layer (Custom Sidebar) of HR Setup. With no site layer yet, one is written that keeps
	the HRMS order and puts Sub Band after Employee Grade. A site layer HR already arranged is
	left as it is, and Sub Band is only appended to it; one that already names Sub Band (also
	hidden by HR) is not touched."""
	from frappe.desk.doctype.custom_sidebar.custom_sidebar import (
		_save_customization,
		add_site_sidebar_item,
		get_customization,
	)
	from frappe.desk.doctype.sidebar.sidebar import LINKED_IDENTITY_FIELDS, is_linked, item_key

	if not frappe.db.exists("Sidebar", SIDEBAR_MODULE):
		return
	layer = get_customization(SIDEBAR_MODULE, None)
	if layer:
		add_site_sidebar_item(SIDEBAR_MODULE, SUB_BAND_ITEM)  # skips an item already there
		return

	rows, placed = [], False
	for item in frappe.get_doc("Sidebar", SIDEBAR_MODULE).items:
		if is_linked(item):
			row = {field: item.get(field) for field in LINKED_IDENTITY_FIELDS}
		else:
			row = {"key": item_key(item)}
		rows.append({**row, "child": item.child})
		if item.link_type == "DocType" and item.link_to == "Employee Grade":
			rows.append({**SUB_BAND_ITEM, "added": 1})
			placed = True
	if not placed:
		rows.append({**SUB_BAND_ITEM, "added": 1})
	_save_customization(SIDEBAR_MODULE, rows, user=None)
