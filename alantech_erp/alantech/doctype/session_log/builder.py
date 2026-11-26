# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Creates Session Logs from Employee Checkins, as Session Log Settings > Log Creation Trigger says.

    on_checkin(doc)          Employee Checkin.after_insert. "On Check-out": an OUT punch builds the
                             log of the shift day it belongs to (a night / 24 hour shift's check-out
                             the next morning goes to the previous day).
    build_yesterday_logs()   daily. "Daily Scheduler": one log per employee who punched yesterday.

A Draft log is recalculated and processed again; a log already under HR review (Pending Approval,
Approved, Rejected, Processed) is left alone: HR uses Recalculate / Reopen on it. Exception: a log
held for a missing check-out is recalculated when the missing OUT is added (with either trigger), and
goes on to be processed when the check-out is now complete and Require Log Approval is off.
Building never blocks the check-in: a failure is written to the Error Log.

hooks.py:
    doc_events = {"Employee Checkin": {"after_insert": "...session_log.builder.on_checkin",
                                       "on_update": "...session_log.builder.on_checkin_update"}}
    scheduler_events = {"daily": ["...session_log.builder.build_yesterday_logs"]}
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, today

from alantech_erp.alantech.doctype.session_log.calculation import (
	calculate,
	get_sessions,
	get_shift,
	get_shift_window,
)
from alantech_erp.alantech.doctype.session_log.processing import add_remark, process_log
from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import (
	TRIGGER_DAILY,
	TRIGGER_ON_CHECKOUT,
	get_session_log_settings,
)

DT = "Session Log"
SAVEPOINT = "session_log_build"


def on_checkin(doc, method=None):
	if doc.log_type != "OUT":
		return
	log_date = shift_day(doc.employee, doc.time)
	if get_session_log_settings().log_creation_trigger == TRIGGER_ON_CHECKOUT or held_log(doc.employee, log_date):
		build_log_safely(doc.employee, log_date)


REBUILD_FIELDS = ("employee", "time", "log_type")


def on_checkin_update(doc, method=None):
	"""Employee Checkin.on_update: a punch edited after saving (Log Type set later, time or employee
	corrected) is treated like a new punch, and the day it was moved away from is recalculated.
	New punches are left to on_checkin (after_insert)."""
	before = doc.get_doc_before_save()
	if not before or not any(doc.has_value_changed(f) for f in REBUILD_FIELDS):
		return
	on_checkin(doc)
	rebuild_existing_log(doc)
	if before.employee and before.time and before.log_type in ("IN", "OUT"):
		rebuild_existing_log(before)


def rebuild_existing_log(checkin):
	"""Recalculate the Session Log of the punch's shift day, if there is one (only a Draft or a held
	missing check-out log changes; see build_log)."""
	log_date = shift_day(checkin.employee, checkin.time)
	if frappe.db.exists(DT, {"employee": checkin.employee, "log_date": getdate(log_date)}):
		build_log_safely(checkin.employee, log_date)


def held_log(employee, log_date):
	"""The log of that day waiting for HR because the check-out was missing."""
	return frappe.db.exists(
		DT,
		{"employee": employee, "log_date": getdate(log_date), "status": "Pending Approval", "missing_checkout": 1},
	)


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
	"""One Session Log per IN-OUT pair of the day (session_no 1, 2, ...). Returns Session 1's log.

	Session 1 owns the day's Attendance and Overtime Log; when a later session is processed they are
	rebuilt from the whole day (see processing.process_extra_session)."""
	day = getdate(log_date)
	first = None
	for number in range(1, max(len(get_sessions(employee, day)), 1) + 1):
		log = build_session_log(employee, day, number)
		first = first or log
	return first


def find_log(employee, log_date, session_no):
	"""A log made before sessions existed has no session_no and counts as Session 1."""
	rows = frappe.db.sql_list(
		"""select name from `tabSession Log`
		where employee = %s and log_date = %s and coalesce(nullif(session_no, 0), 1) = %s limit 1""",
		(employee, getdate(log_date), session_no),
	)
	return rows[0] if rows else None


def build_session_log(employee, log_date, session_no):
	name = find_log(employee, log_date, session_no)
	if name:
		log = frappe.get_doc(DT, name)
		if log.status == "Pending Approval" and cint(log.missing_checkout):
			return release_corrected_log(log)
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
				"session_no": session_no,
			}
		)
		log.insert(ignore_permissions=True)  # after_insert processes a Draft log
		return log

	process_log(log)
	return log


def release_corrected_log(log):
	"""A held missing check-out log after the OUT was added (HR correction): recalculate it, and
	process it when nothing else holds it (check-out found, Require Log Approval off)."""
	calculate(log)
	if cint(log.missing_checkout):
		log.save(ignore_permissions=True)
		return log
	add_remark(log, _("Check-out corrected; recalculated."))
	if not get_session_log_settings().require_log_approval:
		log.status = "Draft"
	log.save(ignore_permissions=True)
	if log.status == "Draft":
		process_log(log)
	return log
