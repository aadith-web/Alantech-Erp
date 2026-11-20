"""View Salary Structure popup on the Employee form: earnings and deductions of the active assignment,
and Edit (a revision from a new From Date) for the HR Manager.

ClickUp: https://app.clickup.com/t/14yr2e586v8 (parent 14yr2e586v0). Button: ClickUp 14yr2e586v5
(setup/salary_structure_button.py); popup: public/js/employee.js.

- Shows the active assignment (setup/salary_structure_button.get_active_assignment, read with the
  user's permissions: employees see only their own): structure, From Date, Grade, Sub Band, Base
  (gross), then Earnings and Deductions with component, basis (e.g. "25% of Basic", the formula,
  or a fixed amount) and the monthly amount, and the totals.
- Amounts come from HRMS's own Preview Salary Slip (full month, before payment-day proration), so
  they are what payroll works out; previewed for a month the assignment covers from its 1st
  (`preview_date`).
- Edit: HR Manager only, checked on the server too. A submitted assignment is not changed (that
  would mean cancelling it, and the salary slips made from it): Edit makes a new assignment from a
  later From Date with the chosen Sub Band (Gross Amount from the grade), the same way as the
  Create popup (setup/salary_structure_popup.py). From that date it is the active assignment; the
  old one stays for the months before.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate, today

from alantech_erp.setup.default_salary_structure import PERCENT, PERCENT_OF
from alantech_erp.setup.salary_structure_button import get_active_assignment
from alantech_erp.setup.salary_structure_popup import SUB_BAND, SalaryStructurePopupError

EDIT_ROLE = "HR Manager"


def can_edit(user=None):
	return EDIT_ROLE in frappe.get_roles(user or frappe.session.user)


@frappe.whitelist()
def get_salary_structure_view(employee):
	"""Everything the View popup shows. Refused when the user may not see an active assignment."""
	frappe.has_permission("Employee", "read", doc=employee, throw=True)
	active = get_active_assignment(employee)
	if not active:
		frappe.throw(
			_("{0} has no active Salary Structure Assignment.").format(
				frappe.bold(frappe.db.get_value("Employee", employee, "employee_name") or employee)
			),
			frappe.DoesNotExistError,
			title=_("No Salary Structure"),
		)
	assignment = frappe.get_doc("Salary Structure Assignment", active.name)
	structure = frappe.get_doc("Salary Structure", assignment.salary_structure)
	amounts, error = preview_amounts(assignment)

	def rows(table):
		return [
			{
				"component": row.salary_component,
				"abbr": row.abbr,
				"basis": basis(row),
				"amount": amounts.get((table, row.salary_component)) if amounts is not None else None,
			}
			for row in structure.get(table)
		]

	earnings, deductions = rows("earnings"), rows("deductions")
	total = lambda items: sum(flt(i["amount"]) for i in items) if amounts is not None else None  # noqa: E731
	return {
		"assignment": assignment.name,
		"salary_structure": structure.name,
		"from_date": assignment.from_date,
		"grade": assignment.get("grade"),
		"sub_band": assignment.get(SUB_BAND),
		"base": assignment.base,
		"currency": assignment.currency,
		"earnings": earnings,
		"deductions": deductions,
		"total_earnings": total(earnings),
		"total_deductions": total(deductions),
		"net": (total(earnings) - total(deductions)) if amounts is not None else None,
		"amount_error": error,
		"can_edit": can_edit(),
	}


def basis(row):
	"""How the row's amount is worked out, in words."""
	if row.get(PERCENT) not in (None, ""):
		percent = flt(row.get(PERCENT))
		percent = int(percent) if percent == int(percent) else percent
		return _("{0}% of {1}").format(percent, row.get(PERCENT_OF) or _("Gross"))
	if row.amount_based_on_formula and row.formula:
		return row.formula
	return _("Fixed amount")


def preview_date(from_date):
	"""A posting date whose whole pay period the assignment covers. HRMS previews the month of the
	posting date and needs an assignment applying on its first day, so an assignment from the 19th
	is previewed for next month (the amounts are full-month amounts either way)."""
	from_date = getdate(from_date)
	posting_date = max(getdate(today()), from_date)
	if get_first_day(posting_date) < from_date:
		posting_date = add_months(get_first_day(from_date), 1)
	return posting_date


def preview_amounts(assignment):
	"""({(table, component): full-month amount}, None) from HRMS's Preview Salary Slip, or (None,
	message) when HRMS cannot work it out. The caller has already checked that the user may see
	this assignment, so the slip is built without the user's own permissions on Salary Structure."""
	from hrms.payroll.doctype.salary_structure.salary_structure import _make_salary_slip

	posting_date = preview_date(assignment.from_date)
	messages = list(frappe.local.message_log)
	try:
		slip = _make_salary_slip(
			assignment.salary_structure,
			employee=assignment.employee,
			posting_date=posting_date,
			for_preview=1,
			ignore_permissions=True,
		)
	except frappe.ValidationError as e:
		return None, frappe.utils.strip_html(str(e))
	finally:
		frappe.local.message_log = messages
	return {
		(table, row.salary_component): flt(row.default_amount)
		for table in ("earnings", "deductions")
		for row in slip.get(table)
	}, None


@frappe.whitelist()
def revise_salary_structure(employee, sub_band, from_date, submit=1):
	"""Edit (HR Manager): a new assignment from a later From Date with `sub_band` of the employee's
	grade. Returns what create_salary_structure_assignment returns."""
	from alantech_erp.setup.salary_structure_popup import create_salary_structure_assignment

	if not can_edit():
		frappe.throw(
			_("Only the {0} can edit a salary structure.").format(_(EDIT_ROLE)),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	active = get_active_assignment(employee)
	if not active:
		frappe.throw(_("There is no active assignment to edit."), SalaryStructurePopupError)
	if not from_date or getdate(from_date) <= getdate(active.from_date):
		frappe.throw(
			_("The new From Date must be after {0}, the From Date of the current assignment {1}.").format(
				frappe.bold(frappe.format_value(getdate(active.from_date), "Date")), active.name
			),
			SalaryStructurePopupError,
			title=_("Cannot Edit Salary Structure"),
		)
	grade = frappe.db.get_value("Employee", employee, "grade")
	return create_salary_structure_assignment(employee, grade, sub_band, from_date, submit=submit)
