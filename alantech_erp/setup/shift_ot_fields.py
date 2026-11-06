# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Shift Type: Work Mode, Early Check-in / Late Checkout handling and OT rounding.

ClickUp: https://app.clickup.com/t/14yr2e5785z

Custom fields on HRMS Shift Type (never edit its JSON), after the existing Overtime section
(Allow Overtime + Overtime Type). The Session Log reads them from the employee's shift
(session_log/calculation.py get_overtime_hours); there are no global equivalents.

    execute()        after_migrate (hooks.py): creates / updates the fields. Safe to re-run.
    validate(doc)    Shift Type.validate (hooks.py doc_events): defaults, Regular Hours Per Day > 0.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt

FIXED = "Fixed Shift"
FLEXIBLE = "Flexible Threshold"
IGNORE = "Ignore"
OT = "OT"
ROUNDING_OPTIONS = ("0", "15", "30", "60")

# fieldname: value for shifts saved before the fields existed (and for new shifts)
DEFAULTS = {
	"work_mode": FIXED,
	"early_checkin_mode": IGNORE,
	"late_checkout_mode": IGNORE,
	"round_ot_minutes_to": "0",
}

IS_FIXED = f"eval:doc.work_mode != '{FLEXIBLE}'"
IS_FLEXIBLE = f"eval:doc.work_mode == '{FLEXIBLE}'"

CUSTOM_FIELDS = {
	"Shift Type": [
		{
			"fieldname": "work_mode_section",
			"label": "Work Mode",
			"fieldtype": "Section Break",
			"insert_after": "overtime_type",
		},
		{
			"fieldname": "work_mode",
			"label": "Work Mode",
			"fieldtype": "Select",
			"options": f"{FIXED}\n{FLEXIBLE}",
			"default": FIXED,
			"reqd": 1,
			"insert_after": "work_mode_section",
			"description": "Fixed Shift: overtime is time outside the shift start-end, as set below. "
			"Flexible Threshold: shift start/end are not used; hours worked in the day beyond "
			"Regular Hours Per Day are overtime.",
		},
		{
			"fieldname": "regular_hours_per_day",
			"label": "Regular Hours Per Day",
			"fieldtype": "Float",
			"non_negative": 1,
			"insert_after": "work_mode",
			"depends_on": IS_FLEXIBLE,
			"mandatory_depends_on": IS_FLEXIBLE,
			"description": "Hours worked beyond this value in a day are considered overtime.",
		},
		{
			"fieldname": "early_checkin_section",
			"label": "Early Check-in",
			"fieldtype": "Section Break",
			"insert_after": "regular_hours_per_day",
			"depends_on": IS_FIXED,
		},
		{
			"fieldname": "early_checkin_mode",
			"label": "Early Checkin Mode",
			"fieldtype": "Select",
			"options": f"{IGNORE}\n{OT}",
			"default": IGNORE,
			"reqd": 1,
			"insert_after": "early_checkin_section",
			"depends_on": IS_FIXED,
			"description": "Ignore: time before the shift start is not counted. "
			"OT: time before the shift start is counted as overtime.",
		},
		{
			"fieldname": "late_checkout_section",
			"label": "Late Checkout",
			"fieldtype": "Section Break",
			"insert_after": "early_checkin_mode",
			"depends_on": IS_FIXED,
		},
		{
			"fieldname": "late_checkout_mode",
			"label": "Late Checkout Mode",
			"fieldtype": "Select",
			"options": f"{IGNORE}\n{OT}",
			"default": IGNORE,
			"reqd": 1,
			"insert_after": "late_checkout_section",
			"depends_on": IS_FIXED,
			"description": "Ignore: time after the shift end is not counted. "
			"OT: time after the shift end is counted as overtime.",
		},
		{
			"fieldname": "ot_rounding_section",
			"label": "OT Rounding",
			"fieldtype": "Section Break",
			"insert_after": "late_checkout_mode",
		},
		{
			"fieldname": "round_ot_minutes_to",
			"label": "Round OT Minutes To",
			"fieldtype": "Select",
			"options": "\n".join(ROUNDING_OPTIONS),
			"default": "0",
			"reqd": 1,
			"insert_after": "ot_rounding_section",
			"description": "Overtime minutes are rounded down to a multiple of this value, after every "
			"other rule. 0 = no rounding. Example: 52 min with 30 gives 30 min.",
		},
	],
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)
	fill_defaults()


def fill_defaults():
	"""Shifts saved before the fields existed: Fixed Shift / Ignore / Ignore / 0 (empty values only)."""
	for fieldname, value in DEFAULTS.items():
		frappe.db.sql(
			f"update `tabShift Type` set `{fieldname}` = %s where ifnull(`{fieldname}`, '') = ''", value
		)


def count_outside_shift_as_ot(shift):
	"""Early Checkin Mode and Late Checkout Mode = OT: the overtime a shift with Allow Overtime gave
	before these fields existed (every hour beyond the shift length)."""
	if frappe.get_meta("Shift Type").has_field("late_checkout_mode"):
		frappe.db.set_value("Shift Type", shift, {"early_checkin_mode": OT, "late_checkout_mode": OT})
		frappe.clear_document_cache("Shift Type", shift)


def validate(doc, method=None):
	for fieldname, value in DEFAULTS.items():
		if doc.meta.has_field(fieldname) and not doc.get(fieldname):
			doc.set(fieldname, value)
	if doc.get("work_mode") == FLEXIBLE and flt(doc.get("regular_hours_per_day")) <= 0:
		frappe.throw(
			_("Regular Hours Per Day must be greater than 0 for a Flexible Threshold shift."),
			title=_("Work Mode"),
		)


def shift_settings(shift):
	"""The shift's OT handling with defaults filled in (for shifts read from cache or older rows)."""
	shift = shift or {}
	rounding = str(shift.get("round_ot_minutes_to") or "0")
	return frappe._dict(
		work_mode=shift.get("work_mode") or FIXED,
		regular_hours_per_day=flt(shift.get("regular_hours_per_day")),
		early_checkin_ot=shift.get("early_checkin_mode") == OT,
		late_checkout_ot=shift.get("late_checkout_mode") == OT,
		round_ot_minutes_to=cint(rounding) if rounding in ROUNDING_OPTIONS else 0,
	)
