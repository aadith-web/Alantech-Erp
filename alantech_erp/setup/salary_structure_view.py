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
- Cost Centers (ClickUp 14yr2e589er): the View shows the assignment's split; Edit starts from it and
  passes the rows on like the Create popup (salary_structure_popup.clean_cost_centers).
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate, today

from alantech_erp.setup.default_salary_structure import PERCENT, PERCENT_OF
from alantech_erp.setup.salary_structure_button import get_active_assignment
from alantech_erp.setup.salary_structure_popup import SUB_BAND, SalaryStructurePopupError, get_grade_details

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
		# India Payroll's field; the Edit popup starts from it (ClickUp 14yr2e58ft2)
		"employment_state": assignment.get("employment_state"),
		# filled on save by setup/income_tax_slab.py (ClickUp 14yr2e589ev)
		"income_tax_slab": assignment.income_tax_slab,
		"base": assignment.base,
		"cost_centers": [
			{"cost_center": r.cost_center, "percentage": r.percentage} for r in assignment.payroll_cost_centers
		],
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


# Edit modes (ClickUp 14yr2e586vb sign-off point): HR chooses per edit
NEW_ASSIGNMENT, AMEND = "new", "amend"


@frappe.whitelist()
def revise_salary_structure(
	employee, sub_band, from_date=None, submit=1, cost_centers=None, employment_state=None, mode=NEW_ASSIGNMENT
):
	"""Edit (HR Manager only). `mode`:
	- "new" (default): a new assignment from a later From Date with `sub_band` of the employee's
	  grade; the current one stays for the months before (salary history kept).
	- "amend": correct the current assignment: it is cancelled and an amended copy (same From Date,
	  amended_from = it) is made with the new sub band, gross, state and cost centers. Refused once a
	  submitted salary slip covers its period, so payroll history never changes.
	Returns what create_salary_structure_assignment returns."""
	from alantech_erp.setup.salary_structure_popup import (
		DOCTYPE,
		EMPLOYMENT_STATE,
		create_salary_structure_assignment,
	)

	if not can_edit():
		frappe.throw(
			_("Only the {0} can edit a salary structure.").format(_(EDIT_ROLE)),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	active = get_active_assignment(employee)
	if not active:
		frappe.throw(_("There is no active assignment to edit."), SalaryStructurePopupError)

	# Employment State (ClickUp 14yr2e58ft2): the one chosen in the Edit popup; none sent (API): the
	# current assignment's, the employee still works there (empty -> Kerala in
	# create_salary_structure_assignment, which also checks it against the list)
	state = (employment_state or "").strip() or (
		frappe.db.get_value(DOCTYPE, active.name, EMPLOYMENT_STATE)
		if frappe.get_meta(DOCTYPE).has_field(EMPLOYMENT_STATE)
		else None
	)
	if mode == AMEND:
		return amend_assignment(active.name, sub_band, submit, cost_centers, state)
	if mode != NEW_ASSIGNMENT:
		frappe.throw(_("Unknown edit mode {0}.").format(frappe.bold(mode)), SalaryStructurePopupError)

	if not from_date or getdate(from_date) <= getdate(active.from_date):
		frappe.throw(
			_("The new From Date must be after {0}, the From Date of the current assignment {1}.").format(
				frappe.bold(frappe.format_value(getdate(active.from_date), "Date")), active.name
			),
			SalaryStructurePopupError,
			title=_("Cannot Edit Salary Structure"),
		)
	grade = frappe.db.get_value("Employee", employee, "grade")
	return create_salary_structure_assignment(
		employee, grade, sub_band, from_date, submit=submit, cost_centers=cost_centers, employment_state=state
	)


def amend_assignment(name, sub_band, submit, cost_centers, state):
	"""Cancel assignment `name` and make its amended copy with the new sub band (same From Date).
	One request: if anything fails, the cancel is rolled back too."""
	from frappe.utils import cint

	from alantech_erp.setup.salary_structure_popup import (
		EMPLOYMENT_STATE,
		clean_cost_centers,
		clean_employment_state,
		fail,
	)

	current = frappe.get_doc("Salary Structure Assignment", name)
	frappe.has_permission("Salary Structure Assignment", "cancel", doc=current, throw=True)
	slips = frappe.get_all(
		"Salary Slip",
		filters={"employee": current.employee, "docstatus": 1, "end_date": (">=", current.from_date)},
		pluck="name",
		order_by="start_date",
		limit=3,
	)
	if slips:
		fail(
			_(
				"Assignment {0} cannot be corrected: submitted salary slips already use it ({1}). Choose "
				"\"New assignment from a new From Date\" instead, so the paid months stay as they are."
			).format(frappe.bold(current.name), ", ".join(slips))
		)

	grade = frappe.db.get_value("Employee", current.employee, "grade") or current.get("grade")
	details = get_grade_details(grade) if grade else {"sub_bands": []}
	gross = next((flt(r.gross_amount) for r in details["sub_bands"] if r.sub_band == sub_band), None)
	if not sub_band:
		fail(_("Select a Sub Band."))
	if gross is None or gross <= 0:
		fail(_("Sub Band {0} is not on Grade {1}.").format(frappe.bold(sub_band), frappe.bold(grade or "-")))
	cost_centers = clean_cost_centers(cost_centers, current.company)
	state = clean_employment_state(state)

	current.cancel()
	amended = frappe.copy_doc(current)
	amended.docstatus = 0  # copy_doc keeps the cancelled status
	amended.amended_from = current.name
	amended.base = gross
	amended.set(SUB_BAND, sub_band)
	if state:
		amended.set(EMPLOYMENT_STATE, state)
	if cost_centers:
		amended.set("payroll_cost_centers", cost_centers)
	amended.insert()
	if cint(submit):
		amended.submit()
	return {"name": amended.name, "docstatus": amended.docstatus, "base": gross, "amended_from": current.name}
