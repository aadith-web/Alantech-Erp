# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Attendance Log Review: one month of Session Logs, with a per-employee summary."""

import calendar

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt, getdate

MONTHS = list(calendar.month_name)[1:]  # January ... December
STATUS_COUNTS = {"Present": "present", "Absent": "absent", "Half Day": "half_day", "On Leave": "on_leave"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	start, end = get_period(filters)
	data = get_data(filters, start, end)
	summary = get_employee_summary(data)
	return get_columns(), data, get_summary_html(summary, start), None, get_report_summary(data)


# ---------------------------------------------------------------- filters / data
def get_period(filters):
	if not filters.month or not filters.year:
		frappe.throw(_("Select a Month and Year."))
	month = MONTHS.index(filters.month) + 1
	year = cint(filters.year)
	return getdate(f"{year}-{month:02d}-01"), getdate(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}")


def get_data(filters, start, end):
	conditions = {"company": filters.company, "log_date": ["between", [start, end]]}
	for field in ("employee", "department", "project", "status"):
		if filters.get(field):
			conditions[field] = filters.get(field)

	or_conditions = None
	if cint(filters.show_flagged_only):
		or_conditions = {
			"late_entry": 1,
			"early_exit": 1,
			"missing_checkout": 1,
			"error_log": ["is", "set"],
		}

	# get_list (not get_all): respects permissions, so an employee only sees their own logs
	return frappe.get_list(
		"Session Log",
		filters=conditions,
		or_filters=or_conditions,
		fields=[
			"name", "employee", "employee_name", "department", "branch", "log_date", "day_type",
			"first_in", "last_out", "working_hours", "attendance_status", "late_entry", "early_exit",
			"missing_checkout", "overtime_rule", "overtime_hours", "status", "remarks", "error_log",
		],
		order_by="employee_name asc, log_date asc",
		limit_page_length=0,
	)


def get_columns():
	return [
		{"fieldname": "name", "label": _("Log ID"), "fieldtype": "Link", "options": "Session Log", "width": 140},
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "log_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "day_type", "label": _("Day Type"), "fieldtype": "Data", "width": 100},
		{"fieldname": "first_in", "label": _("First In"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "last_out", "label": _("Last Out"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "working_hours", "label": _("Working Hours"), "fieldtype": "Float", "precision": 2, "width": 110},
		{"fieldname": "attendance_status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{"fieldname": "late_entry", "label": _("Late"), "fieldtype": "Check", "width": 60},
		{"fieldname": "early_exit", "label": _("Early Exit"), "fieldtype": "Check", "width": 80},
		{"fieldname": "missing_checkout", "label": _("Missing Check-out"), "fieldtype": "Check", "width": 120},
		{"fieldname": "overtime_rule", "label": _("OT Rule"), "fieldtype": "Link", "options": "Overtime Type", "width": 120},
		{"fieldname": "overtime_hours", "label": _("OT Hours"), "fieldtype": "Float", "precision": 2, "width": 90},
		{"fieldname": "status", "label": _("Log Status"), "fieldtype": "Data", "width": 130},
		{"fieldname": "remarks", "label": _("Remarks"), "fieldtype": "Data", "width": 220},
	]


# ---------------------------------------------------------------- summary
def get_employee_summary(data):
	summary = {}
	for row in data:
		emp = summary.setdefault(
			row.employee,
			frappe._dict(employee=row.employee, employee_name=row.employee_name, present=0, absent=0,
				half_day=0, on_leave=0, off_days=0, ot_hours=0.0, logs=0),
		)
		emp.logs += 1
		if is_off_day(row):
			emp.off_days += 1  # weekly off / holiday without work: not an absence
		else:
			key = STATUS_COUNTS.get(row.attendance_status)
			if key:
				emp[key] += 1
		emp.ot_hours += flt(row.overtime_hours)
		if row.error_log and not row.remarks:  # show processing errors in the Remarks column
			row.remarks = row.error_log
	return list(summary.values())


def is_off_day(row):
	return row.day_type in ("Weekly Off", "Holiday") and not row.first_in and row.attendance_status != "On Leave"


def get_summary_html(summary, start):
	if not summary:
		return ""
	head = "".join(
		f"<th style='text-align:{'left' if i < 2 else 'right'}'>{escape_html(h)}</th>"
		for i, h in enumerate([_("Employee"), _("Name"), _("Present"), _("Absent"), _("Half Day"),
			_("Leave"), _("Off Days"), _("OT Hours"), _("Logs")])
	)
	body = "".join(
		"<tr>"
		f"<td>{escape_html(s.employee)}</td><td>{escape_html(s.employee_name or '')}</td>"
		f"<td style='text-align:right'>{s.present}</td><td style='text-align:right'>{s.absent}</td>"
		f"<td style='text-align:right'>{s.half_day}</td><td style='text-align:right'>{s.on_leave}</td>"
		f"<td style='text-align:right'>{s.off_days}</td>"
		f"<td style='text-align:right'>{flt(s.ot_hours, 2)}</td><td style='text-align:right'>{s.logs}</td>"
		"</tr>"
		for s in summary
	)
	title = _("Monthly summary per employee: {0}").format(start.strftime("%B %Y"))
	return (
		f"<h6 style='margin: var(--margin-sm) 0'>{escape_html(title)}</h6>"
		f"<table class='table table-bordered table-sm' style='font-size: var(--text-sm)'>"
		f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
	)


def get_report_summary(data):
	flagged = sum(1 for r in data if r.late_entry or r.early_exit or r.missing_checkout or r.error_log)
	pending = sum(1 for r in data if r.status == "Pending Approval")
	return [
		{"value": len(data), "label": _("Logs"), "datatype": "Int"},
		{"value": len({r.employee for r in data}), "label": _("Employees"), "datatype": "Int"},
		{"value": pending, "label": _("Pending Approval"), "datatype": "Int",
			"indicator": "Orange" if pending else "Green"},
		{"value": flagged, "label": _("Flagged"), "datatype": "Int", "indicator": "Red" if flagged else "Green"},
		{"value": flt(sum(flt(r.overtime_hours) for r in data), 2), "label": _("Total OT Hours"),
			"datatype": "Float"},
	]
