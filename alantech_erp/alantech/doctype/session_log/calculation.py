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
	sessions = build_sessions(logs)
	if session_number(doc) > len(sessions) and session_number(doc) > 1:
		return  # this session's punches are gone (deleted / moved): leave the log as it is

	set_checkins_table(doc, logs if len(sessions) <= 1 else sessions[session_number(doc) - 1]["logs"])
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
	if end - start >= timedelta(hours=23, minutes=59):
		end = start + timedelta(days=1)  # 24-hour shift, stored as 09:00-08:59 because HRMS forbids equal times
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


def session_number(doc):
	"""1 for the first IN-OUT pair of the day (and for logs made before sessions existed)."""
	return cint(doc.get("session_no")) or 1


def build_sessions(logs):
	"""The day's IN-OUT pairs in time order: [{"in": datetime, "out": datetime or None, "logs": [...]}].

	Only the last session can be open (IN without OUT). A repeated IN inside an open session and an
	OUT with no open IN are ignored. A device that sends no IN/OUT gives one session: first punch =
	in, last punch = out."""
	typed = [l for l in logs if l.log_type in ("IN", "OUT")]
	if logs and not typed:
		last = get_datetime(logs[-1].time) if len(logs) > 1 else None
		return [{"in": get_datetime(logs[0].time), "out": last, "logs": list(logs)}]

	sessions = []
	for log in typed:
		time = get_datetime(log.time)
		open_session = sessions[-1] if sessions and sessions[-1]["out"] is None else None
		if log.log_type == "IN":
			if open_session:
				open_session["logs"].append(log)
			else:
				sessions.append({"in": time, "out": None, "logs": [log]})
		elif open_session and time > open_session["in"]:
			open_session["out"] = time
			open_session["logs"].append(log)
	return sessions


def get_sessions(employee, log_date):
	shift = get_shift(frappe._dict(employee=employee, log_date=log_date, shift=None))
	return build_sessions(get_checkins(employee, get_shift_window(log_date, shift)))


def day_hours(doc):
	"""Hours worked in the whole day (sum of all sessions). Logs without a day total use working_hours."""
	value = doc.get("total_working_hours")
	return flt(value) if value is not None else flt(doc.working_hours)


def day_first_in(doc):
	return doc.get("day_first_in") or doc.first_in


def day_last_out(doc):
	return doc.get("day_last_out") or doc.last_out


def day_missing_checkout(doc):
	value = doc.get("day_missing_checkout")
	return cint(value) if value is not None else cint(doc.missing_checkout)


def set_times(doc, logs, shift, window):
	"""Session fields (first_in, last_out, working_hours, missing_checkout) are this log's IN-OUT pair.
	Day fields (total_working_hours, day_last_out, late_entry, early_exit) cover all the day's sessions;
	late entry / early exit are kept on Session 1, which owns the day's Attendance."""
	sessions = build_sessions(logs)
	mine = sessions[session_number(doc) - 1] if session_number(doc) <= len(sessions) else None
	closed = [s for s in sessions if s["out"]]
	first_in = sessions[0]["in"] if sessions else None
	last_out = closed[-1]["out"] if closed else None
	open_day = bool(sessions) and sessions[-1]["out"] is None

	doc.first_in = mine["in"] if mine else None
	doc.last_out = mine["out"] if mine else None
	doc.missing_checkout = 1 if mine and not mine["out"] else 0
	doc.working_hours = flt(time_diff_in_hours(mine["out"], mine["in"]), 2) if mine and mine["out"] else 0

	doc.total_working_hours = flt(sum(time_diff_in_hours(s["out"], s["in"]) for s in closed), 2)
	doc.day_last_out = last_out
	doc.day_first_in = first_in  # not saved: used by the status / overtime calculation of this run
	doc.day_missing_checkout = 1 if open_day else 0  # not saved, same

	first = session_number(doc) == 1
	doc.late_entry = int(
		bool(
			first
			and shift
			and first_in
			and cint(shift.enable_late_entry_marking)
			and first_in > window.start + timedelta(minutes=cint(shift.late_entry_grace_period))
		)
	)
	doc.early_exit = int(
		bool(
			first
			and shift
			and last_out
			and not open_day
			and cint(shift.enable_early_exit_marking)
			and last_out < window.end - timedelta(minutes=cint(shift.early_exit_grace_period))
		)
	)


# ---------------------------------------------------------------- holiday / leave
HOLIDAY_LIST_PREFIX = "Alantech Holidays"


def get_holiday_list(employee, log_date, shift):
	"""First list that covers the date: shift's, employee's / company's, then 'Alantech Holidays <year>'."""
	date = getdate(log_date)
	for name in (shift.holiday_list if shift else None, employee_holiday_list(employee, date),
			f"{HOLIDAY_LIST_PREFIX} {date.year}"):
		if name and covers(name, date):
			return name
	return None


def employee_holiday_list(employee, date):
	from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

	try:
		return get_holiday_list_for_employee(employee, raise_exception=False, as_on=date)
	except TypeError:  # older signature without as_on
		return get_holiday_list_for_employee(employee, raise_exception=False)


def covers(name, date):
	r = frappe.db.get_value("Holiday List", name, ["from_date", "to_date"], as_dict=True)
	return bool(r and getdate(r.from_date) <= date <= getdate(r.to_date))


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

	if not day_first_in(doc):
		return "Absent", None
	if day_missing_checkout(doc):
		return MISSING_CHECKOUT_STATUS, None

	hours = day_hours(doc)
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
	if session_number(doc) > 1:  # the day's overtime is kept on Session 1 only
		doc.overtime_rule, doc.overtime_hours = None, 0
		return
	rule = get_overtime_rule(shift)
	doc.overtime_rule = rule.name if rule else None
	doc.overtime_hours = get_overtime_hours(doc, rule, window, shift) if rule else 0


def get_overtime_rule(shift):
	"""The employee's shift (assignment / default, see get_shift) decides the rule:
	Shift Type > Allow Overtime + Overtime Type. No rule = no overtime."""
	if not shift or not cint(shift.get("allow_overtime")) or not shift.get("overtime_type"):
		return None
	return frappe.get_cached_doc(OVERTIME_RULE_DOCTYPE, shift.overtime_type)


def get_overtime_hours(doc, rule, window, shift=None):
	"""Overtime from the shift's Work Mode (setup/shift_ot_fields.py), in this order:

	Weekly off / holiday: all worked hours, if the rule allows overtime on that day type.
	Flexible Threshold:   worked hours beyond the shift's Regular Hours Per Day.
	Fixed Shift:          time before the shift start (Early Checkin Mode = OT) plus time after the
	                      shift end (Late Checkout Mode = OT); Ignore counts nothing.
	Then capped at the rule's Maximum Overtime Hours Allowed, and finally rounded down to the
	shift's Round OT Minutes To."""
	from alantech_erp.setup.shift_ot_fields import FLEXIBLE, shift_settings

	worked = day_hours(doc)
	if worked <= 0:
		return 0

	settings = shift_settings(shift)
	if doc.day_type == "Weekly Off":
		hours = worked if cint(rule.applicable_for_weekend) else 0
	elif doc.day_type == "Holiday":
		hours = worked if cint(rule.applicable_for_public_holiday) else 0
	elif settings.work_mode == FLEXIBLE:
		hours = worked - settings.regular_hours_per_day
	else:
		hours = outside_shift_hours(doc, window, settings)

	hours = max(hours, 0)
	max_allowed = flt(rule.maximum_overtime_hours_allowed)
	if max_allowed:
		hours = min(hours, max_allowed)
	return round_down_hours(hours, settings.round_ot_minutes_to)


def outside_shift_hours(doc, window, settings):
	"""Fixed Shift: early check-in and late checkout time that the shift counts as overtime."""
	if not (window.start and window.end and day_first_in(doc) and day_last_out(doc)):
		return 0
	first_in, last_out = get_datetime(day_first_in(doc)), get_datetime(day_last_out(doc))
	hours = 0
	if settings.early_checkin_ot and first_in < window.start:
		hours += time_diff_in_hours(min(window.start, last_out), first_in)
	if settings.late_checkout_ot and last_out > window.end:
		hours += time_diff_in_hours(last_out, max(window.end, first_in))
	return hours


def round_down_hours(hours, step_minutes):
	"""Round hours down to a multiple of step_minutes; 0 = no rounding."""
	if not step_minutes:
		return flt(hours, 2)
	minutes = int(round(flt(hours) * 60, 6))  # round(): 0.1 h is 5.999999 min in floating point
	return flt((minutes - minutes % step_minutes) / 60, 2)
