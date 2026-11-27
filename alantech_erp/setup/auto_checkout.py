import frappe
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime, today

from alantech_erp.alantech.doctype.session_log.builder import shift_day
from alantech_erp.alantech.doctype.session_log.calculation import (
	get_approved_leave, get_shift, get_shift_window,
)
from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import (
	get_session_log_settings,
)

DT = "Employee Checkin"
SAVEPOINT = "auto_checkout"
NOTE = "Auto checkout by scheduler"
LOOKBACK_DAYS = 31


def auto_create_missing_checkout():
	if not get_session_log_settings().auto_create_missing_checkout:
		return
	now = now_datetime()
	employees = get_employees_with_open_checkin(now)
	for employee in employees:
		frappe.db.savepoint(SAVEPOINT)
		try:
			create_checkout(employee, now)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.log_error(title=f"Auto checkout for {employee} failed", reference_doctype=DT)



def set_auto_checkout_default_on():
	"""One time: existing sites hold a saved 0, which overrides the doctype default of 1."""
	key = "alt_auto_checkout_default_on"
	if frappe.db.get_default(key):
		return
	frappe.db.set_single_value("Session Log Settings", "auto_create_missing_checkout", 1)
	frappe.db.set_default(key, "1")
	
def get_employees_with_open_checkin(now):
	"""Employees whose latest IN/OUT log is an IN, looking back LOOKBACK_DAYS.

	Not limited to the last 2 days: if the scheduler was off or a run failed, the open IN is still
	picked up by the next run instead of being left for HR.
	"""
	since = add_days(getdate(now), -LOOKBACK_DAYS)
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT ec.employee
		FROM `tabEmployee Checkin` ec
		JOIN (
			SELECT employee, MAX(time) AS last_time
			FROM `tabEmployee Checkin`
			WHERE log_type IN ('IN', 'OUT')
			GROUP BY employee
		) last ON last.employee = ec.employee AND last.last_time = ec.time
		WHERE ec.log_type = 'IN' AND ec.time >= %s
		""",
		(f"{since} 00:00:00",),
	)


def create_checkout(employee, now):
	rows = frappe.get_all(
		DT,
		filters={"employee": employee, "log_type": ["in", ["IN", "OUT"]]},
		fields=["time", "log_type"],
		order_by="time desc, creation desc",
		limit=1,
	)
	if not rows or rows[0].log_type != "IN":
		return  # no log, or last log already OUT

	in_time = get_datetime(rows[0].time)
	day = shift_day(employee, in_time)
	shift = get_shift(frappe._dict(employee=employee, log_date=day, shift=None))
	window = get_shift_window(day, shift)
	leave = get_approved_leave(employee, day)
	if not shift:
		frappe.logger("auto_checkout").info(f"skipped {employee}: no shift assigned")
		return
	out_time = get_checkout_time(in_time, window, leave, day)
	if out_time is None or out_time <= in_time:
		return  # full-day leave, or IN after the checkout time: HR corrects
	if now < out_time:
		return  # shift still running (night shift): next run picks it up
	if frappe.db.exists(DT, {"employee": employee, "alt_auto_created": 1,
			"time": ["between", [window.actual_start, window.actual_end]]}):
		return  # already auto-checked-out for this shift day

	doc = frappe.get_doc({"doctype": DT, "employee": employee, "log_type": "OUT",
		"time": out_time, "alt_auto_created": 1}).insert(ignore_permissions=True)
	doc.add_comment("Comment", NOTE)


def is_half_day(leave, day):
	# same rule as calculation.get_status
	return bool(cint(leave.half_day) and (not leave.half_day_date or getdate(leave.half_day_date) == getdate(day)))


def get_checkout_time(in_time, window, leave, day):
	if not leave:
		return window.end
	if not is_half_day(leave, day):
		return None  # full-day approved leave
	mid = window.start + (window.end - window.start) / 2
	# HRMS doesn't record which half is the leave, so infer it from the IN time
	return window.end if in_time >= mid else mid