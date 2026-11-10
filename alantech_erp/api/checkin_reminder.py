# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Home page check-in reminder (HR-F02 Attendance Management).

    get_current_employee()   the Active Employee linked to the session user, and the Log Type to prefill
    get_checkin_status()     whether the home page should show the reminder popup

Users without a linked Active Employee (Administrator, system users) get nothing, so they never see it.
The sequence rules stay in setup/checkin_validation.py; this only picks a sensible default so the
popup does not send the employee into a check-in the validation would refuse.
"""

import frappe
from frappe.utils import add_days, formatdate, get_datetime, now_datetime, time_diff_in_hours, today

from alantech_erp.setup.checkin_validation import CORRECTION_ROLES, missing_checkout_limit

DT = "Employee Checkin"


def _employee(user=None):
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return None
	return frappe.db.get_value(
		"Employee", {"user_id": user, "status": "Active"}, ["name", "employee_name"], as_dict=True
	)


def _last_log(employee):
	rows = frappe.get_all(
		DT,
		filters={"employee": employee, "log_type": ["in", ["IN", "OUT"]], "docstatus": ["<", 2]},
		fields=["time", "log_type"],
		order_by="time desc, creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def _next_log(employee):
	"""(log type to prefill, missing check-out date or None)."""
	last = _last_log(employee)
	if not last or last.log_type != "IN":
		return "IN", None
	limit, shift_date = missing_checkout_limit(employee, last.time)
	if time_diff_in_hours(now_datetime(), last.time) > limit and not CORRECTION_ROLES.intersection(frappe.get_roles()):
		return "OUT", shift_date  # earlier check-out must be corrected first
	return "OUT", None  # open IN still valid: the next punch is the check-out


@frappe.whitelist()
def get_current_employee():
	emp = _employee()
	if not emp:
		return None
	log_type, _missing = _next_log(emp.name)
	return {"employee": emp.name, "employee_name": emp.employee_name, "log_type": log_type}


@frappe.whitelist()
def get_checkin_status():
	emp = _employee()
	if not emp:
		return {"show_popup": 0}

	start, end = get_datetime(today()), get_datetime(add_days(today(), 1))
	if frappe.db.exists(DT, {"employee": emp.name, "time": ["between", [start, end]]}):
		return {"show_popup": 0}

	log_type, missing_date = _next_log(emp.name)
	return {
		"show_popup": 1,
		"employee": emp.name,
		"employee_name": emp.employee_name,
		"date": formatdate(today()),
		"log_type": log_type,
		"missing_checkout": formatdate(missing_date) if missing_date else None,
	}