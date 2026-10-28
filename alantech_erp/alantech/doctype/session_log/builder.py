# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Creates Session Logs from Employee Checkins, as Session Log Settings > Log Creation Trigger says.

    on_checkin(doc)          Employee Checkin.after_insert. "On Check-out": an OUT punch builds the
                             log of the shift day it belongs to (a night / 24 hour shift's check-out
                             the next morning goes to the previous day).
    build_yesterday_logs()   daily. "Daily Scheduler": one log per employee who punched yesterday.

A Draft log is recalculated and processed again; a log already under HR review (Pending Approval,
Approved, Rejected, Processed) is left alone: HR uses Recalculate / Reopen on it.
Building never blocks the check-in: a failure is written to the Error Log.

hooks.py:
    doc_events = {"Employee Checkin": {"after_insert": "...session_log.builder.on_checkin"}}
    scheduler_events = {"daily": ["...session_log.builder.build_yesterday_logs"]}
"""

import frappe
from frappe.utils import add_days, get_datetime, getdate, today

from alantech_erp.alantech.doctype.session_log.calculation import get_shift, get_shift_window
from alantech_erp.alantech.doctype.session_log.processing import process_log
from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import (
	TRIGGER_DAILY,
	TRIGGER_ON_CHECKOUT,
	get_session_log_settings,
)

DT = "Session Log"
SAVEPOINT = "session_log_build"


def on_checkin(doc, method=None):
	if doc.log_type != "OUT" or get_session_log_settings().log_creation_trigger != TRIGGER_ON_CHECKOUT:
		return
	build_log_safely(doc.employee, shift_day(doc.employee, doc.time))


def build_yesterday_logs():
	if get_session_log_settings().log_creation_trigger != TRIGGER_DAILY:
		return
	yesterday = add_days(today(), -1)
	employees = frappe.get_all(
		"Employee Checkin",
		filters={"time": ["between", [f"{yesterday} 00:00:00", f"{yesterday} 23:59:59"]]},
		pluck="employee",
		distinct=True,
	)
	for employee in employees:
		build_log_safely(employee, yesterday)
		frappe.db.commit()


def shift_day(employee, time):
	"""The date whose shift window (check-in before start .. check-out after end) holds the punch."""
	time = get_datetime(time)
	for day in (getdate(time), add_days(getdate(time), -1)):
		window = get_shift_window(day, get_shift(frappe._dict(employee=employee, log_date=day, shift=None)))
		if window.actual_start <= time <= window.actual_end:
			return getdate(day)
	return getdate(time)


def build_log_safely(employee, log_date):
	frappe.db.savepoint(SAVEPOINT)
	try:
		return build_log(employee, log_date)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.clear_messages()
		frappe.log_error(title=f"Session Log for {employee} on {log_date}: build failed", reference_doctype=DT)


def build_log(employee, log_date):
	name = frappe.db.exists(DT, {"employee": employee, "log_date": getdate(log_date)})
	if name:
		log = frappe.get_doc(DT, name)
		if log.status != "Draft":
			return log
		log.save(ignore_permissions=True)  # validate recalculates Draft logs
	else:
		log = frappe.get_doc(
			{
				"doctype": DT,
				"employee": employee,
				"company": frappe.db.get_value("Employee", employee, "company"),
				"log_date": getdate(log_date),
			}
		)
		log.insert(ignore_permissions=True)  # after_insert processes a Draft log
		return log

	process_log(log)
	return log
