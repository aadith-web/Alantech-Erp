# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Turns a Session Log into an Attendance (HRMS) and, when there is overtime, an Overtime Log.

    initial_status(log)  status for a new log: Draft (will be processed) or Pending Approval
    process_log(log)     creates and links the records, sets Processed; on failure fills error_log
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_last_day, getdate

from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import (
	get_session_log_settings,
)

DT = "Session Log"
OVERTIME_DOCTYPE = "Overtime Log"
OT_TYPE_BY_DAY = {"Working Day": "Normal", "Weekly Off": "Holiday", "Holiday": "Holiday"}
PROCESSABLE = ("Draft", "Approved")
SAVEPOINT = "session_log_process"


def initial_status(log):
	"""Approval OFF -> Draft (processed right after insert). Approval ON, or a held
	missing check-out -> Pending Approval."""
	settings = get_session_log_settings()
	if cint(log.missing_checkout) and settings.hold_missing_checkout:
		add_remark(log, _("Held for review: missing check-out."))
		return "Pending Approval"
	return "Pending Approval" if settings.require_log_approval else "Draft"


def process_log(log):
	"""Create Attendance (+ Overtime Log) for one Session Log. Returns True when Processed."""
	if isinstance(log, str):
		log = frappe.get_doc(DT, log)
	if log.status == "Processed":
		return True
	if log.status not in PROCESSABLE:
		frappe.throw(
			_("Session Log {0} is {1}. Only Draft or Approved logs can be processed.").format(
				log.name, _(log.status)
			)
		)

	settings = get_session_log_settings()
	frappe.db.savepoint(SAVEPOINT)
	try:
		existing = get_existing_attendance(log)
		if existing and existing.attendance_log != log.name:
			# attendance made elsewhere (by hand, HRMS auto attendance, ...): skip, do not duplicate
			add_remark(log, _("Attendance {0} already exists for this date; nothing was created.").format(existing.name))
			if log.status == "Draft":
				log.status = "Pending Approval"
			log.error_log = None
			log.save(ignore_permissions=True)
			return False

		log.attendance = existing.name if existing else make_attendance(log, settings)
		log.overtime = make_overtime(log, settings) if flt(log.overtime_hours) > 0 else None
		log.status = "Processed"
		log.error_log = None
		log.save(ignore_permissions=True)
		return True

	except Exception as e:
		traceback = frappe.get_traceback()
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.clear_messages()
		log.reload()
		log.db_set("error_log", f"{frappe.utils.now()}: {e}", update_modified=False)
		frappe.log_error(
			title=f"Session Log {log.name}: processing failed",
			message=traceback,
			reference_doctype=DT,
			reference_name=log.name,
		)
		return False


# ---------------------------------------------------------------- attendance
def get_existing_attendance(log):
	return frappe.db.get_value(
		"Attendance",
		{"employee": log.employee, "attendance_date": log.log_date, "docstatus": ["!=", 2]},
		["name", "attendance_log"],
		as_dict=True,
	)


def make_attendance(log, settings):
	# weekly off / holiday with no check-ins and no leave: nothing to record
	if log.day_type != "Working Day" and not log.first_in and log.attendance_status != "On Leave":
		add_remark(log, _("{0} without check-ins: no attendance needed.").format(_(log.day_type)))
		return None

	att = frappe.new_doc("Attendance")
	att.update(
		{
			"employee": log.employee,
			"attendance_date": log.log_date,
			"company": log.company,
			"status": log.attendance_status,
			"leave_type": log.leave_type if log.attendance_status in ("On Leave", "Half Day") else None,
			"shift": log.shift,
			"late_entry": cint(log.late_entry),
			"early_exit": cint(log.early_exit),
			"working_hours": flt(log.working_hours),
			"in_time": log.first_in,
			"out_time": log.last_out,
			"attendance_log": log.name,
		}
	)
	att.insert(ignore_permissions=True)
	if settings.auto_submit_attendance:
		att.submit()
	return att.name


# ---------------------------------------------------------------- overtime
def make_overtime(log, settings):
	existing = frappe.db.get_value(
		OVERTIME_DOCTYPE,
		{"employee": log.employee, "overtime_date": log.log_date, "docstatus": ["!=", 2]},
		["name", "attendance_log"],
		as_dict=True,
	)
	if existing:
		if existing.attendance_log == log.name:
			return existing.name
		add_remark(log, _("Overtime Log {0} already exists for this date; overtime was not created.").format(existing.name))
		return None

	ot_type = OT_TYPE_BY_DAY.get(log.day_type, "Normal")
	ot = frappe.new_doc(OVERTIME_DOCTYPE)
	ot.update(
		{
			"employee": log.employee,
			"employee_name": log.employee_name,
			"overtime_date": log.log_date,
			"ot_type": ot_type,
			"overtime_hours": flt(log.overtime_hours),
			"overtime_rate": get_overtime_rate(log, ot_type),
			"attendance_log": log.name,
                        "project": log.project,
		}
	)
	ot.insert(ignore_permissions=True)
	if settings.auto_submit_overtime:
		ot.submit()
	return ot.name


def get_overtime_rate(log, ot_type):
	"""Hourly overtime rate from Overtime Settings > Overtime Type Rules.

	Fixed Rate:      fixed_hourly_rate x rate_multiplier
	Salary Derived:  monthly base / working days / working_hours_per_day x rate_multiplier
	                 e.g. (gross - fixed allowances) / days in month / 8 x 1.5
	                 base = Full Salary (all earnings) or Component Wise (Applicable Overtime Components)
	Multiple OT off: the Normal rule is used for every day type.
	"""
	settings = frappe.get_cached_doc("Overtime Settings")
	wanted = ot_type if cint(settings.enable_multiple_ot) else "Normal"
	rule = next((r for r in settings.overtime_type_rules if r.ot_type == wanted), None)
	if not rule:
		frappe.throw(_("Overtime Settings has no rule for OT type {0}.").format(frappe.bold(wanted)))

	multiplier = flt(rule.rate_multiplier) or 1
	if rule.calculation_method == "Fixed Rate":
		rate = flt(rule.fixed_hourly_rate) * multiplier
	else:
		hours_per_day = flt(settings.working_hours_per_day)
		days = get_working_days(settings.working_days_base, log.log_date)
		rate = get_monthly_base(log, settings, rule) / days / hours_per_day * multiplier

	if flt(rate) <= 0:
		frappe.throw(_("Overtime rate for OT type {0} is zero; check Overtime Settings.").format(frappe.bold(wanted)))
	return flt(rate, 2)


def get_monthly_base(log, settings, rule):
	"""Full salary = all earnings (gross). Otherwise only the Applicable Overtime Components,
	so leaving fixed allowances out of that list gives gross - fixed allowances."""
	earnings = get_monthly_earnings(log.employee, log.log_date)
	if rule.component_method == "Full Salary" or settings.base_component_method == "All":
		return sum(earnings.values())
	applicable = {row.salary_component for row in settings.applicable_overtime_component}
	if not applicable:
		frappe.throw(_("Overtime Settings: add the Applicable Overtime Components (earnings that count for overtime)."))
	return sum(amount for component, amount in earnings.items() if component in applicable)


def get_monthly_earnings(employee, date):
	"""{component: full monthly amount}. From the latest submitted Salary Slip (default_amount is
	the amount before leave-without-pay deductions); if there is none yet, a preview slip
	from the employee's Salary Structure Assignment."""
	slip = frappe.db.get_value(
		"Salary Slip",
		{"employee": employee, "docstatus": 1, "start_date": ["<=", date]},
		"name",
		order_by="start_date desc",
	)
	if slip:
		rows = frappe.get_all(
			"Salary Detail",
			filters={"parent": slip, "parenttype": "Salary Slip", "parentfield": "earnings"},
			fields=["salary_component", "default_amount", "amount"],
		)
	else:
		structure = frappe.db.get_value(
			"Salary Structure Assignment",
			{"employee": employee, "docstatus": 1, "from_date": ["<=", date]},
			"salary_structure",
			order_by="from_date desc",
		)
		if not structure:
			frappe.throw(_("No salary slip or Salary Structure Assignment for {0} on {1}.").format(employee, date))
		from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

		rows = make_salary_slip(structure, employee=employee, posting_date=date, for_preview=1).earnings

	earnings = {}
	for row in rows:
		earnings[row.salary_component] = earnings.get(row.salary_component, 0) + (
			flt(row.default_amount) or flt(row.amount)
		)
	return earnings


def get_working_days(basis, date):
	if basis == "Month Days":
		return getdate(get_last_day(date)).day
	if basis == "Fixed 30":
		return 30
	return 365 / 12  # Year Average


# ---------------------------------------------------------------- helpers
def add_remark(log, text):
	if text not in (log.remarks or ""):
		log.remarks = f"{log.remarks}\n{text}" if log.remarks else text
