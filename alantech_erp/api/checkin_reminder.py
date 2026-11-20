# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Home page check-in reminder (HR-F02 Attendance Management).

    get_current_employee()   Active Employee linked to the session user + the Log Type to prefill
    get_checkin_status()     whether the home page should show the daily reminder popup
    get_checkout_status()    the check-out popup: shift is over and the employee is still checked in
    get_reminder()           one call for the desk script: the popup to show now (re-entry / check-out / check-in)
    get_reentry_status()     the check-in popup that stays on until the shift ends after an in-shift check-out
    notify_reentry()         doc event: pushes that popup right away when the employee checks out inside their shift

Users without a linked Active Employee (system users) get nothing; HR and Administrator included once an Employee is linked.
Sequence rules stay in setup/checkin_validation.py; this module only picks sensible defaults.
"""

import frappe
from frappe.utils import (
	format_datetime,
	formatdate,
	get_datetime,
	now_datetime,
	time_diff_in_hours,
	today,
)

from alantech_erp.setup.checkin_validation import CORRECTION_ROLES, missing_checkout_limit

DT = "Employee Checkin"


def _employee(user=None):
	user = user or frappe.session.user
	if user == "Guest":
		return None  # Administrator / HR work too, as long as an Active Employee is linked to the user
	return frappe.db.get_value(
		"Employee", {"user_id": user, "status": "Active"}, ["name", "employee_name"], as_dict=True
	)


def _last_log(employee):
	rows = frappe.get_all(
		DT,
		filters={"employee": employee, "log_type": ["in", ["IN", "OUT"]], "docstatus": ["<", 2]},
		fields=["time", "log_type"],
		order_by="time desc, creation desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _next_log(employee):
	"""Return (log type to prefill, date of the missing check-out or None)."""
	last = _last_log(employee)
	if not last or last.log_type != "IN":
		return "IN", None

	limit, shift_date = missing_checkout_limit(employee, last.time)
	overdue = time_diff_in_hours(now_datetime(), last.time) > limit
	if overdue and not CORRECTION_ROLES.intersection(frappe.get_roles()):
		return "OUT", shift_date  # the earlier check-out must be corrected first
	return "OUT", None  # open IN is still valid: the next punch is the check-out


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

	if frappe.db.exists(DT, {"employee": emp.name, "time": ["between", [today(), today()]]}):
		return {"show_popup": 0}

	_log_type, missing_date = _next_log(emp.name)
	return {
		"show_popup": 1,
		"employee": emp.name,
		"employee_name": emp.employee_name,
		"date": formatdate(today()),
		"missing_checkout": formatdate(missing_date) if missing_date else None,
	}


def _reentry_info(employee, user_id, employee_name, punch_time, now=None):
	"""Payload for the re-entry popup, or None.

	The check-out (by anyone: the employee, HR, Administrator) must be inside the shift window.
	With `now` given (page load / refresh) the shift must also still be running.
	"""
	if not user_id:
		return None

	# imported here to avoid a circular import
	from alantech_erp.alantech.doctype.session_log.builder import shift_day
	from alantech_erp.alantech.doctype.session_log.calculation import get_shift, get_shift_window

	punch_time = get_datetime(punch_time)
	day = shift_day(employee, punch_time)
	shift = get_shift(frappe._dict(employee=employee, log_date=day, shift=None))
	if not shift:
		return None

	window = get_shift_window(day, shift)
	if not (window.start <= punch_time < window.end):
		return None  # shift was already over at check-out: no prompt
	if now is not None and get_datetime(now) >= window.end:
		return None  # shift has ended since: stop prompting

	return {
		"employee": employee,
		"employee_name": employee_name,
		"shift_end": format_datetime(window.end, "hh:mm a"),
	}


@frappe.whitelist()
def get_reentry_status():
	"""Called on every page load / refresh: keep prompting while the last punch is an in-shift OUT."""
	emp = _employee()
	if not emp:
		return {"show_popup": 0}

	rows = frappe.get_all(
		DT,
		filters={"employee": emp.name, "log_type": ["in", ["IN", "OUT"]], "docstatus": ["<", 2]},
		fields=["time", "log_type"],
		order_by="time desc, creation desc",
		limit_page_length=1,
	)
	last = rows[0] if rows else None
	if not last or last.log_type != "OUT":
		return {"show_popup": 0}  # not checked out (or never punched)

	info = _reentry_info(emp.name, frappe.session.user, emp.employee_name, last.time, now=now_datetime())
	return {"show_popup": 1, **info} if info else {"show_popup": 0}


def notify_reentry(doc, method=None):
	"""Employee is checked out before the shift ends: push the check-in popup right away.

	Hook (hooks.py):
		doc_events = {"Employee Checkin": {"after_insert": "alantech_erp.api.checkin_reminder.notify_reentry"}}
	"""
	if doc.log_type != "OUT":
		return

	emp = frappe.db.get_value("Employee", doc.employee, ["user_id", "employee_name"], as_dict=True)
	if not emp:
		return
	info = _reentry_info(doc.employee, emp.user_id, emp.employee_name, doc.time)
	if not info:
		return

	frappe.publish_realtime("checkin_reentry_prompt", info, user=emp.user_id, after_commit=True)


def _shift_window_for(employee, punch_time):
	"""Shift window of the shift the punch belongs to, or None when the employee has no shift."""
	# imported here to avoid a circular import
	from alantech_erp.alantech.doctype.session_log.builder import shift_day
	from alantech_erp.alantech.doctype.session_log.calculation import get_shift, get_shift_window

	day = shift_day(employee, get_datetime(punch_time))
	shift = get_shift(frappe._dict(employee=employee, log_date=day, shift=None))
	return get_shift_window(day, shift) if shift else None


@frappe.whitelist()
def get_checkout_status():
	"""Last punch is an IN and its shift is over: keep asking for the check-out until it is applied."""
	emp = _employee()
	last = _last_log(emp.name) if emp else None
	if not last or last.log_type != "IN":
		return {"show_popup": 0}

	window = _shift_window_for(emp.name, last.time)
	if not window or not window.end:
		return {"show_popup": 0}
	if get_datetime(last.time) >= window.end or now_datetime() < window.end:
		return {"show_popup": 0}  # IN after the shift, or the shift is still running

	_log_type, missing_date = _next_log(emp.name)  # set when the check-out has to be corrected by HR
	return {
		"show_popup": 1,
		"employee": emp.name,
		"employee_name": emp.employee_name,
		"shift_end": format_datetime(window.end, "hh:mm a"),
		"missing_checkout": formatdate(missing_date) if missing_date else None,
	}


@frappe.whitelist()
def get_reminder():
	"""The one popup to show now: {"kind": "reentry" | "checkout" | "checkin", ...} or {"show_popup": 0}.

	Called on every page load / refresh; the popup keeps coming back until the punch is applied.
	"""
	for kind, status in (("reentry", get_reentry_status), ("checkout", get_checkout_status)):
		result = status()
		if result.get("show_popup"):
			return {"kind": kind, **result}

	emp = _employee()
	last = _last_log(emp.name) if emp else None
	if last and last.log_type == "IN":
		return {"show_popup": 0}  # still checked in: never ask for a check-in

	result = get_checkin_status()
	return {"kind": "checkin", **result} if result.get("show_popup") else {"show_popup": 0}