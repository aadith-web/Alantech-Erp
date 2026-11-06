# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Checkin sequence rules: IN and OUT must alternate, and a missed check-out must be corrected.

ClickUp: https://app.clickup.com/t/14yr2e57879

    validate(doc)   Employee Checkin.validate (hooks.py doc_events), so it runs for desk, mobile app,
                    REST API and data import alike.

Rules, checked against the employee's last log before the log's own time (so a back-dated log is
checked where it falls in the sequence, not against the latest log). Later logs are not checked, so a
missing IN + OUT pair can be added one log at a time:
    IN    the previous log must not be an IN.
    OUT   the previous log must be an IN.
    Missed check-out: an IN or OUT that comes more than (shift hours + Overtime Type > Maximum
          Overtime Hours Allowed) after an open IN is refused with the "check-out for <date> is
          missing" message. Without a shift or an overtime maximum, Session Log Settings >
          Missing Check-out Block After (Hours) is the limit (default 16).

HR Manager / System Manager are not held by the missed check-out limit, so they can add the missing
OUT at its real (back-dated) time; the IN/OUT alternation still applies to them.

Biometric device logs (Location / Device ID set) and data imports are never refused, because the
device would retry or the import would stop: they are saved with the problem written to
"Sequence Warning", for HR to correct.
"""

import frappe
from frappe import _
from frappe.utils import flt, format_datetime, formatdate, get_datetime, time_diff_in_hours

from alantech_erp.alantech.doctype.session_log.calculation import (
	get_overtime_rule,
	get_shift,
	get_shift_window,
)
from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import (
	DEFAULT_MISSING_CHECKOUT_HOURS,
	get_session_log_settings,
)

DT = "Employee Checkin"
LOG_TYPES = ("IN", "OUT")
CORRECTION_ROLES = {"HR Manager", "System Manager"}
WARNING_FIELD = "sequence_warning"


class CheckinSequenceError(frappe.ValidationError):
	pass


class MissingCheckoutError(CheckinSequenceError):
	pass


def validate(doc, method=None):
	if doc.log_type not in LOG_TYPES or not doc.employee or not doc.time:
		return
	if not doc.is_new() and not any(doc.has_value_changed(f) for f in ("employee", "time", "log_type")):
		return

	problem = get_sequence_problem(doc)
	if not problem:
		set_warning(doc, None)
		return

	message, exc = problem
	if is_unattended(doc):
		set_warning(doc, message)
		return
	frappe.throw(message, exc, title=_("Check-in Not Allowed"))


def is_unattended(doc):
	"""Biometric device punches and data imports are saved and flagged, never refused."""
	return bool(doc.device_id or frappe.flags.in_import)


def set_warning(doc, message):
	if doc.meta.has_field(WARNING_FIELD):
		doc.set(WARNING_FIELD, message)


def get_sequence_problem(doc):
	"""(message, exception class) when the log breaks the IN/OUT sequence, else None."""
	time = get_datetime(doc.time)
	previous = previous_log(doc)

	if previous and previous.log_type == "IN" and not can_skip_missing_checkout_limit():
		limit, shift_date = missing_checkout_limit(doc.employee, previous.time)
		if time_diff_in_hours(time, previous.time) > limit:
			return (
				_(
					"Your check-out for {0} is missing. Please request correction of the previous day's "
					"check-out before checking in."
				).format(formatdate(shift_date)),
				MissingCheckoutError,
			)

	if doc.log_type == "IN":
		if previous and previous.log_type == "IN":
			return (
				_("You have an open check-in at {0}. Please check out before checking in again.").format(
					format_datetime(previous.time)
				),
				CheckinSequenceError,
			)
	elif not previous or previous.log_type != "IN":
		return (_("No open check-in found. Please check in before checking out."), CheckinSequenceError)
	return None


def previous_log(doc):
	"""The employee's IN/OUT log just before this one (a log at the same second counts as before)."""
	filters = {
		"employee": doc.employee,
		"log_type": ["in", LOG_TYPES],
		"docstatus": ["<", 2],
		"time": ["<=", get_datetime(doc.time)],
	}
	if not doc.is_new():
		filters["name"] = ["!=", doc.name]
	rows = frappe.get_all(
		DT,
		filters=filters,
		fields=["name", "time", "log_type"],
		order_by="time desc, creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def can_skip_missing_checkout_limit():
	return bool(CORRECTION_ROLES.intersection(frappe.get_roles()))


def missing_checkout_limit(employee, in_time):
	"""(hours, shift date) after which an open IN counts as a missed check-out.

	Shift length + the Overtime Type's maximum overtime hours, for the shift the IN belongs to.
	Without an overtime maximum: Session Log Settings > Missing Check-out Block After, but never less
	than the shift length (a 24 hour shift is not cut at 16 hours).
	"""
	from alantech_erp.alantech.doctype.session_log.builder import shift_day

	day = shift_day(employee, in_time)
	shift = get_shift(frappe._dict(employee=employee, log_date=day, shift=None))
	shift_hours = 0
	if shift:
		window = get_shift_window(day, shift)
		shift_hours = time_diff_in_hours(window.end, window.start)
	rule = get_overtime_rule(shift)
	max_overtime = flt(rule.maximum_overtime_hours_allowed) if rule else 0
	if shift and max_overtime:
		return shift_hours + max_overtime, day
	fallback = flt(get_session_log_settings().missing_checkout_block_hours) or DEFAULT_MISSING_CHECKOUT_HOURS
	return max(shift_hours, fallback), day
