# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Fills a Session Log from the employee's check-ins, shift, holiday list and approved leave.

Fields filled: shift (if empty), checkins, first_in, last_out, working_hours, late_entry,
early_exit, missing_checkout, day_type, attendance_status, leave_type, overtime_rule, overtime_hours.
"""

from datetime import timedelta

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, time_diff_in_hours, to_timedelta

# Status when the employee checked in but never checked out (hours unknown).
# HR can correct it while the log is Pending Approval.
MISSING_CHECKOUT_STATUS = "Half Day"

# The overtime rule is the HRMS Overtime Type set on the Shift Type (Allow Overtime + Overtime Type)
OVERTIME_RULE_DOCTYPE = "Overtime Type"


def calculate(doc):
	shift = get_shift(doc)
	if shift:
		doc.shift = shift.name
	window = get_shift_window(doc.log_date, shift)
	logs = get_checkins(doc.employee, window)

	set_checkins_table(doc, logs)
	set_times(doc, logs, shift, window)
	doc.day_type = get_day_type(doc.employee, doc.log_date, shift)
	doc.attendance_status, doc.leave_type = get_status(doc, shift, get_approved_leave(doc.employee, doc.log_date))
	set_overtime(doc, shift, window)


# ---------------------------------------------------------------- shift
def get_shift(doc):
	"""Shift on the log, else the active Shift Assignment for the date, else the employee's default shift."""
	name = (
		doc.shift
		or get_assigned_shift(doc.employee, doc.log_date)
		or frappe.db.get_value("Employee", doc.employee, "default_shift")
	)
	return frappe.get_cached_doc("Shift Type", name) if name else None


def get_assigned_shift(employee, log_date):
	rows = frappe.db.sql(
		"""select shift_type from `tabShift Assignment`
		where employee = %(employee)s and docstatus = 1 and status = 'Active'
			and start_date <= %(date)s and (end_date is null or end_date >= %(date)s)
		order by start_date desc limit 1""",
		{"employee": employee, "date": getdate(log_date)},
	)
	return rows[0][0] if rows else None


def get_shift_window(log_date, shift):
	"""Shift start/end, and the wider window in which check-ins count for this shift.
	Handles night shifts (end time earlier than start time)."""
	day = get_datetime(getdate(log_date))
	if not shift:
		return frappe._dict(start=None, end=None, actual_start=day, actual_end=day + timedelta(days=1, seconds=-1))

	start = day + to_timedelta(shift.start_time)
	end = day + to_timedelta(shift.end_time)
	if end <= start:
		end += timedelta(days=1)
	return frappe._dict(
		start=start,
		end=end,
		actual_start=start - timedelta(minutes=cint(shift.begin_check_in_before_shift_start_time)),
		actual_end=end + timedelta(minutes=cint(shift.allow_check_out_after_shift_end_time)),
	)


# ---------------------------------------------------------------- check-ins
def get_checkins(employee, window):
	return frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["between", [window.actual_start, window.actual_end]]},
		fields=["name", "time", "log_type"],
		order_by="time asc",
	)


def set_checkins_table(doc, logs):
	doc.set("checkins", [])
	for log in logs:
		doc.append("checkins", {"checkin": log.name, "time": log.time, "log_type": log.log_type})


def set_times(doc, logs, shift, window):
	ins = [get_datetime(l.time) for l in logs if l.log_type == "IN"]
	outs = [get_datetime(l.time) for l in logs if l.log_type == "OUT"]
	if logs and not ins and not outs:  # device sends no IN/OUT: first punch = in, last = out
		ins = [get_datetime(logs[0].time)]
		outs = [get_datetime(logs[-1].time)] if len(logs) > 1 else []

	first_in = min(ins) if ins else None
	last_out = max(outs) if outs else None
	if first_in and last_out and last_out <= first_in:
		last_out = None

	doc.first_in = first_in
	doc.last_out = last_out
	doc.missing_checkout = 1 if first_in and not last_out else 0
	doc.working_hours = flt(time_diff_in_hours(last_out, first_in), 2) if first_in and last_out else 0

	doc.late_entry = int(
		bool(
			shift
			and first_in
			and cint(shift.enable_late_entry_marking)
			and first_in > window.start + timedelta(minutes=cint(shift.late_entry_grace_period))
		)
	)
	doc.early_exit = int(
		bool(
			shift
			and last_out
			and cint(shift.enable_early_exit_marking)
			and last_out < window.end - timedelta(minutes=cint(shift.early_exit_grace_period))
		)
	)


# ---------------------------------------------------------------- holiday / leave
def get_holiday_list(employee, log_date, shift):
	"""Shift's holiday list first, then the employee's (Employee, else Company default)."""
	if shift and shift.holiday_list:
		return shift.holiday_list
	from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

	try:
		return get_holiday_list_for_employee(employee, raise_exception=False, as_on=getdate(log_date))
	except TypeError:  # older signature without as_on
		return get_holiday_list_for_employee(employee, raise_exception=False)


def get_day_type(employee, log_date, shift):
	"""Working Day, Weekly Off (holiday row with Weekly Off ticked) or Holiday."""
	holiday_list = get_holiday_list(employee, log_date, shift)
	if not holiday_list:
		return "Working Day"
	weekly_off = frappe.db.get_value(
		"Holiday", {"parent": holiday_list, "holiday_date": getdate(log_date)}, "weekly_off"
	)
	if weekly_off is None:
		return "Working Day"
	return "Weekly Off" if cint(weekly_off) else "Holiday"


def get_approved_leave(employee, log_date):
	rows = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			"from_date": ["<=", getdate(log_date)],
			"to_date": [">=", getdate(log_date)],
		},
		fields=["leave_type", "half_day", "half_day_date"],
		limit=1,
	)
	return rows[0] if rows else None


# ---------------------------------------------------------------- status
def get_status(doc, shift, leave):
	"""Returns (attendance_status, leave_type)."""
	if leave:
		half = cint(leave.half_day) and (
			not leave.half_day_date or getdate(leave.half_day_date) == getdate(doc.log_date)
		)
		return ("Half Day" if half else "On Leave"), leave.leave_type

	if not doc.first_in:
		return "Absent", None
	if doc.missing_checkout:
		return MISSING_CHECKOUT_STATUS, None

	hours = flt(doc.working_hours)
	if shift:
		absent_below = flt(shift.working_hours_threshold_for_absent)
		half_below = flt(shift.working_hours_threshold_for_half_day)
		if absent_below and hours < absent_below:
			return "Absent", None
		if half_below and hours < half_below:
			return "Half Day", None
	return "Present", None


# ---------------------------------------------------------------- overtime
def set_overtime(doc, shift, window):
	rule = get_overtime_rule(shift)
	doc.overtime_rule = rule.name if rule else None
	doc.overtime_hours = get_overtime_hours(doc, rule, window) if rule else 0


def get_overtime_rule(shift):
	"""The employee's shift (assignment / default, see get_shift) decides the rule:
	Shift Type > Allow Overtime + Overtime Type."""
	if not shift or not cint(shift.get("allow_overtime")) or not shift.get("overtime_type"):
		return None
	return frappe.get_cached_doc(OVERTIME_RULE_DOCTYPE, shift.overtime_type)


def get_overtime_hours(doc, rule, window):
	"""Working day: hours beyond the shift length. Weekly off / holiday: all worked hours,
	if the rule allows overtime on that day type. Capped at the rule's maximum."""
	worked = flt(doc.working_hours)
	if worked <= 0:
		return 0

	if doc.day_type == "Weekly Off":
		hours = worked if cint(rule.applicable_for_weekend) else 0
	elif doc.day_type == "Holiday":
		hours = worked if cint(rule.applicable_for_public_holiday) else 0
	else:
		hours = worked - time_diff_in_hours(window.end, window.start)

	max_allowed = flt(rule.maximum_overtime_hours_allowed)
	if max_allowed:
		hours = min(hours, max_allowed)
	return flt(max(hours, 0), 2)
