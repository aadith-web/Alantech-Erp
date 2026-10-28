"""Alantech yearly holiday lists and shift types.

execute() runs on every migrate (hooks.py after_migrate) and ensure_holiday_lists() runs monthly
(hooks.py scheduler_events). Both only CREATE what is missing, so changes made later in the UI
(shift times, thresholds, overtime, public holidays) are never overwritten.

Holiday lists: one per year, "Alantech Holidays <year>", with every Sunday and the 2nd and 4th
Saturday as Weekly Off. This year's and next year's lists are kept ready; HR adds public holidays
(rows without Weekly Off) to each year's list.

Create a year by hand:
    bench --site <site> execute alantech_erp.setup.shifts.add_year --kwargs "{'year': 2028}"
"""

import calendar
import datetime

import frappe
from frappe.utils import getdate

COMPANY = "Alantech Industries India Pvt Ltd"
HOLIDAY_LIST_PREFIX = "Alantech Holidays"
DEFAULT_SHIFT = "General Shift"

SHIFT_BASE = {
	"enable_auto_attendance": 0,  # attendance comes from Session Log, not HRMS auto attendance
	"allow_overtime": 0,  # overtime only on General Shift, ticked by hand with its Overtime Type
	"enable_late_entry_marking": 1,
	"late_entry_grace_period": 15,
	"enable_early_exit_marking": 1,
	"early_exit_grace_period": 15,
}

# Starting values only: edit them later in Shift Type, they won't be reset.
# HRMS rule: shift length + check-in before + check-out after must stay under 1440 minutes.
SHIFTS = {
	# name: start, end, check-in before (min), check-out after (min), half-day below (h), absent below (h)
	"General Shift": ("09:00:00", "17:00:00", 60, 300, 4, 2),
	"12 Hour Shift": ("09:00:00", "21:00:00", 60, 180, 6, 3),
	# 09:00 to 09:00 next day; stored as 08:59 because HRMS forbids equal start/end and >= 24 h.
	# calculation.py treats it as a full 24 hours.
	"24 Hour Shift": ("09:00:00", "08:59:00", 0, 0, 12, 6),
}


def execute():
	if not frappe.db.exists("Company", COMPANY):
		return  # fresh site before the setup wizard: the next migrate will do it
	ensure_holiday_lists()
	create_shift_types()
	set_default_shift()
	hide_unused_overtime()
	lock_employee_holiday_list()
	sync_employee_holiday_lists()
	allow_employees_to_read_holiday_list()
	add_assignment_status()


# ---------------------------------------------------------------- holiday lists
def holiday_list_name(year):
	return f"{HOLIDAY_LIST_PREFIX} {year}"


def weekly_offs(year):
	"""Every Sunday plus the 2nd and 4th Saturday of each month."""
	rows = []
	for month in range(1, 13):
		saturdays = 0
		for day in range(1, calendar.monthrange(year, month)[1] + 1):
			date = datetime.date(year, month, day)
			if date.weekday() == 6:
				rows.append({"holiday_date": date, "description": "Sunday", "weekly_off": 1})
			elif date.weekday() == 5:
				saturdays += 1
				if saturdays in (2, 4):
					label = "Second Saturday" if saturdays == 2 else "Fourth Saturday"
					rows.append({"holiday_date": date, "description": label, "weekly_off": 1})
	return rows


def create_year(year):
	"""Create 'Alantech Holidays <year>' if it doesn't exist. Returns its name."""
	name = holiday_list_name(year)
	if frappe.db.exists("Holiday List", name):
		return name
	frappe.get_doc(
		{
			"doctype": "Holiday List",
			"holiday_list_name": name,
			"from_date": f"{year}-01-01",
			"to_date": f"{year}-12-31",
			"holidays": weekly_offs(year),
		}
	).insert(ignore_permissions=True)
	return name


def ensure_holiday_lists():
	"""This year's and next year's lists, so next year's exists well before January."""
	if not frappe.db.exists("Company", COMPANY):
		return
	this_year = datetime.date.today().year
	for year in (this_year, this_year + 1):
		create_year(year)
		assign_to_company(year)
	if not frappe.db.get_value("Company", COMPANY, "default_holiday_list"):
		frappe.db.set_value("Company", COMPANY, "default_holiday_list", holiday_list_name(this_year))


def assign_to_company(year):
	"""HRMS v16 finds an employee's holidays through a Holiday List Assignment, not the Company's
	default list; without one, leave approval fails ("No Holiday List was found")."""
	name = holiday_list_name(year)
	if not frappe.db.exists("Holiday List", name) or frappe.db.exists(
		"Holiday List Assignment",
		{"applicable_for": "Company", "assigned_to": COMPANY, "holiday_list": name, "docstatus": 1},
	):
		return
	frappe.get_doc(
		{
			"doctype": "Holiday List Assignment",
			"applicable_for": "Company",
			"assigned_to": COMPANY,
			"holiday_list": name,
			"from_date": f"{year}-01-01",
		}
	).submit()


# ---------------------------------------------------------------- holiday list on the Employee
# HRMS v16 reads holidays only from Holiday List Assignments (here one per year, for the Company);
# the Employee's own Holiday List field is no longer used and stayed empty. It is kept filled,
# read-only, with the list that applies today so it can be seen on the employee: on save, when an
# assignment is submitted or cancelled, and monthly (the 1st of January moves everyone to the new
# year's list).
EMPLOYEE_HOLIDAY_LIST_HELP = "Set from Holiday List Assignment (the company's list for the current year)."


def current_holiday_list(employee, company, as_on=None, assignments=None):
	from hrms.utils.holiday_list import get_holiday_list_assignments, resolve_holiday_list_assignment

	if assignments is None:
		assignments = get_holiday_list_assignments([employee, company])
	found = resolve_holiday_list_assignment(
		assignments.get(employee, []), assignments.get(company, []), getdate(as_on)
	)
	return found.holiday_list if found else None


def employee_holiday_list(doc, method=None):
	"""Employee.validate"""
	doc.holiday_list = current_holiday_list(doc.name, doc.company)


def sync_employee_holiday_lists(doc=None, method=None):
	"""Monthly, after_migrate, and Holiday List Assignment on_submit / on_cancel."""
	from hrms.utils.holiday_list import get_holiday_list_assignments

	employees = frappe.get_all("Employee", fields=["name", "company", "holiday_list"])
	companies = {e.company for e in employees}
	assignments = get_holiday_list_assignments([e.name for e in employees] + list(companies))
	for emp in employees:
		holiday_list = current_holiday_list(emp.name, emp.company, assignments=assignments)
		if emp.holiday_list != holiday_list:
			frappe.db.set_value("Employee", emp.name, "holiday_list", holiday_list, update_modified=False)


def lock_employee_holiday_list():
	"""Create-only, like the shifts."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if frappe.db.exists(
		"Property Setter", {"doc_type": "Employee", "field_name": "holiday_list", "property": "read_only"}
	):
		return
	make_property_setter("Employee", "holiday_list", "read_only", 1, "Check", validate_fields_for_doctype=False)
	make_property_setter(
		"Employee", "holiday_list", "description", EMPLOYEE_HOLIDAY_LIST_HELP, "Text",
		validate_fields_for_doctype=False,
	)


# Employees see only their own current list (Employee > Holiday List, kept in sync above), so the
# next year's list stays out of sight until it applies. HR (FULL_ACCESS_ROLES) sees every list.
# hooks.py: permission_query_conditions / has_permission for "Holiday List".
def _holiday_list_unrestricted(user):
	from alantech_erp.setup.access import FULL_ACCESS_ROLES

	return user == "Administrator" or bool(FULL_ACCESS_ROLES & set(frappe.get_roles(user)))


def _own_holiday_lists(user):
	return frappe.get_all(
		"Employee", filters={"user_id": user, "holiday_list": ["is", "set"]}, pluck="holiday_list", distinct=True
	)


def holiday_list_query_conditions(user=None):
	"""Filters the list view, reports and search."""
	user = user or frappe.session.user
	if _holiday_list_unrestricted(user):
		return ""
	lists = _own_holiday_lists(user)
	if not lists:
		return "1=0"
	values = ", ".join(frappe.db.escape(name) for name in lists)
	return f"`tabHoliday List`.`name` in ({values})"


def holiday_list_has_permission(doc, ptype=None, user=None):
	"""Checks a single record (opening by URL, API)."""
	user = user or frappe.session.user
	if _holiday_list_unrestricted(user):
		return True
	return doc.name in _own_holiday_lists(user)


def allow_employees_to_read_holiday_list():
	"""Employees see the holiday calendar (read only; HR keeps create / write). Create-only: a rule
	for the Employee role changed later in Role Permissions Manager is left alone."""
	from frappe.permissions import add_permission

	if frappe.db.exists("Custom DocPerm", {"parent": "Holiday List", "role": "Employee", "permlevel": 0}):
		return
	add_permission("Holiday List", "Employee", 0, "read")


# ---------------------------------------------------------------- Holiday List Assignment status
# Draft until submitted, Active once submitted, Cancelled when cancelled (Active does not depend on
# the date: the 2027 assignment is Active before 2027 starts). The list / form badge shows it
# (public/js/holiday_list_assignment_list.js).
ASSIGNMENT_STATUS = {0: "Draft", 1: "Active", 2: "Cancelled"}


def add_assignment_status():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Holiday List Assignment": [
				{
					"fieldname": "alt_status",
					"label": "Status",
					"fieldtype": "Select",
					"options": "\n".join(ASSIGNMENT_STATUS.values()),
					"default": "Draft",
					"insert_after": "holiday_list",
					"read_only": 1,
					"allow_on_submit": 1,
					"no_copy": 1,
					"in_list_view": 1,
					"in_standard_filter": 1,
				}
			]
		},
		update=True,
	)
	for docstatus, status in ASSIGNMENT_STATUS.items():
		frappe.db.set_value(
			"Holiday List Assignment",
			{"docstatus": docstatus, "alt_status": ["!=", status]},
			"alt_status",
			status,
			update_modified=False,
		)


def set_assignment_status(doc, method=None):
	"""Holiday List Assignment.validate (save, submit) and before_cancel"""
	doc.alt_status = ASSIGNMENT_STATUS[doc.docstatus]


def add_year(year):
	"""Manual: bench --site <site> execute alantech_erp.setup.shifts.add_year --kwargs "{'year': 2028}" """
	name = create_year(int(year))
	frappe.db.commit()
	print(f"{name} ready")


# ---------------------------------------------------------------- shift types
def create_shift_types():
	meta = frappe.get_meta("Shift Type")
	for name, (start, end, before, after, half, absent) in SHIFTS.items():
		if frappe.db.exists("Shift Type", name):
			continue
		values = {
			**SHIFT_BASE,
			"start_time": start,
			"end_time": end,
			"begin_check_in_before_shift_start_time": before,
			"allow_check_out_after_shift_end_time": after,
			"working_hours_threshold_for_half_day": half,
			"working_hours_threshold_for_absent": absent,
		}
		values = {k: v for k, v in values.items() if meta.has_field(k)}
		frappe.get_doc({"doctype": "Shift Type", "name": name, "__newname": name, **values}).insert(
			ignore_permissions=True
		)

def set_default_shift():
	"""New employees get General Shift unless HR picks another. Create-only, like the shifts."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if not frappe.db.exists("Shift Type", DEFAULT_SHIFT):
		return
	if frappe.db.exists(
		"Property Setter", {"doc_type": "Employee", "field_name": "default_shift", "property": "default"}
	):
		return  # already set (or changed by HR in Customize Form): leave it
	make_property_setter(
		"Employee", "default_shift", "default", DEFAULT_SHIFT, "Text", validate_fields_for_doctype=False
	)


# ---------------------------------------------------------------- overtime
# Overtime is paid through Overtime Log -> Salary Slip (overtime_utils.py). HRMS Overtime Slip and
# the Overtime Type on Shift Assignment are not used. Shift Type > Allow Overtime + Overtime Type
# stay: Session Log reads the overtime rule from there (session_log/calculation.py).
SHIFT_MODULE = "Shift and Attendance"
HIDDEN_SIDEBAR_ITEMS = {("Section Break", "Overtime"), ("Link", "Overtime Type"), ("Link", "Overtime Slip")}


def hide_unused_overtime():
	"""Create-only, like the shifts: a sidebar or field changed later by hand is left alone."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter
	from frappe.desk.doctype.custom_sidebar.custom_sidebar import (
		_save_customization,
		get_customization,
		layer_arrangement,
	)

	if not frappe.db.exists(
		"Property Setter", {"doc_type": "Shift Assignment", "field_name": "overtime_type", "property": "hidden"}
	):
		make_property_setter(
			"Shift Assignment", "overtime_type", "hidden", 1, "Check", validate_fields_for_doctype=False
		)

	# site-wide layer, the same one the sidebar editor's "for everyone" saves
	if get_customization(SHIFT_MODULE, None):
		return
	rows = layer_arrangement(SHIFT_MODULE, None)
	for row in rows:
		if (row.get("type"), row.get("label")) in HIDDEN_SIDEBAR_ITEMS:
			row["hidden"] = 1
	_save_customization(SHIFT_MODULE, rows, user=None)


def fill_missing_shifts():
	"""One-off for existing active employees without a shift."""
	frappe.db.set_value(
		"Employee", {"status": "Active", "default_shift": ["is", "not set"]}, "default_shift", DEFAULT_SHIFT
	)
	frappe.db.commit()