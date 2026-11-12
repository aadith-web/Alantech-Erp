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


def auto_create_missing_checkout():
	if not get_session_log_settings().auto_create_missing_checkout:
		return
	now = now_datetime()
	since = add_days(today(), -2)  # yesterday + day before, so night shifts that were still running are caught
	employees = frappe.get_all(
		DT, filters={"time": [">=", f"{since} 00:00:00"]}, pluck="employee", distinct=True
	)
	for employee in employees:
		frappe.db.savepoint(SAVEPOINT)
		try:
			create_checkout(employee, now)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.log_error(title=f"Auto checkout for {employee} failed", reference_doctype=DT)


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
	if not shift:
		frappe.log_error(title=f"Auto checkout skipped: no shift for {employee}",
			message=f"Open IN at {in_time}", reference_doctype=DT)
		return

	window = get_shift_window(day, shift)
	out_time = get_checkout_time(in_time, window, get_approved_leave(employee, day), day)
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