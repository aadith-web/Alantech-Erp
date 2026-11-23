"""Create Salary Structure popup on the Employee form: Grade, Sub Band, Gross Amount, From Date.

ClickUp: https://app.clickup.com/t/14yr2e586v6 (parent 14yr2e586v0). The button that opens it is
setup/salary_structure_button.py (ClickUp 14yr2e586v5); the popup is in public/js/employee.js.

- Grade: the employee's grade, read-only. An employee without a grade gets the one HR selects, saved
  to the Employee.
- Sub Band: only the sub bands on the grade's Sub Bands table (enabled ones).
- Gross Amount: read-only, from the grade + sub band row (employee_grade.get_gross_amount).
- Creates a Salary Structure Assignment: Base = Gross Amount, Salary Structure = the grade's
  Default Salary Structure (ClickUp 14yr2e586v4), Sub Band kept on the assignment
  (`alt_sub_band`, for the View popup). Submitted by default ("Submit" ticked), so it is the
  employee's active assignment at once; unticked it stays a draft for HR to check.

Cost Centers table (ClickUp 14yr2e589er): splits the employee's salary cost across cost centers
(Cost Center + Allocation %, whole numbers). Starts with the employee's Payroll Cost Center at 100%.
Rows go to the assignment's Cost Centers (payroll_cost_centers, HRMS), which the Payroll Entry
uses to split the salary cost. Refused unless the total is 100%, each cost center is a non-group,
enabled cost center of the employee's company, listed once, with more than 0%. An empty table
leaves HRMS's default (Payroll Cost Center of the employee / department at 100%).

Refused, with the reason: no grade, a sub band that is not on the grade, a grade without Default
Salary Structure or Gross Amount, an assignment (draft or submitted) with the same From Date.
Everything runs in one request: if the submit fails (e.g. payroll fields missing on the employee,
setup/employee_payroll_fields.py), nothing is saved, the grade on the Employee neither.

hooks.py: after_migrate `execute` (the Sub Band field on Salary Structure Assignment).
"""

import json

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt, getdate

DOCTYPE = "Salary Structure Assignment"
SUB_BAND = "alt_sub_band"

CUSTOM_FIELDS = {
	DOCTYPE: [
		{
			"fieldname": SUB_BAND,
			"fieldtype": "Link",
			"options": "Sub Band",
			"label": "Sub Band",
			"insert_after": "grade",
			"read_only": 1,
			"description": "Sub band of the grade whose Gross Amount is the Base (Create Salary Structure on the Employee).",
		}
	]
}


class SalaryStructurePopupError(frappe.ValidationError):
	pass


def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)


def fail(message):
	frappe.throw(message, SalaryStructurePopupError, title=_("Cannot Create Salary Structure"))


@frappe.whitelist()
def get_grade_details(grade):
	"""For the popup: the grade's Default Salary Structure and its enabled sub bands with gross."""
	frappe.has_permission("Employee Grade", "read", doc=grade, throw=True)
	from alantech_erp.setup.employee_grade import SUB_BANDS

	rows = frappe.get_all(
		"Employee Grade Sub Band",
		filters={"parenttype": "Employee Grade", "parent": grade, "parentfield": SUB_BANDS},
		fields=["sub_band", "gross_amount"],
		order_by="idx",
	)
	disabled = set(frappe.get_all("Sub Band", filters={"enabled": 0}, pluck="name"))
	return {
		"salary_structure": frappe.db.get_value("Employee Grade", grade, "default_salary_structure"),
		"sub_bands": [row for row in rows if row.sub_band not in disabled],
	}


def clean_cost_centers(rows, company):
	"""Popup Cost Centers rows -> [{cost_center, percentage}]; refused unless they add up to 100%."""
	if isinstance(rows, str):
		rows = json.loads(rows or "[]")
	rows = [r for r in rows or [] if r.get("cost_center") or r.get("percentage")]
	cleaned, seen = [], set()
	for idx, row in enumerate(rows, 1):
		cost_center = (row.get("cost_center") or "").strip()
		if not cost_center:
			fail(_("Cost Centers row {0}: select a Cost Center.").format(idx))
		if flt(row.get("percentage")) != cint(row.get("percentage")) or cint(row.get("percentage")) <= 0:
			fail(_("Cost Centers row {0}: Allocation % must be a whole number above 0.").format(idx))
		details = frappe.db.get_value(
			"Cost Center", cost_center, ["company", "is_group", "disabled"], as_dict=True
		)
		if not details:
			fail(_("Cost Centers row {0}: Cost Center {1} does not exist.").format(idx, frappe.bold(cost_center)))
		if details.company != company:
			fail(
				_("Cost Centers row {0}: Cost Center {1} does not belong to Company {2}.").format(
					idx, frappe.bold(cost_center), frappe.bold(company)
				)
			)
		if details.is_group or details.disabled:
			fail(
				_("Cost Centers row {0}: Cost Center {1} is a group or disabled.").format(
					idx, frappe.bold(cost_center)
				)
			)
		if cost_center in seen:
			fail(_("Cost Centers row {0}: Cost Center {1} is listed twice.").format(idx, frappe.bold(cost_center)))
		seen.add(cost_center)
		cleaned.append({"cost_center": cost_center, "percentage": cint(row.get("percentage"))})

	total = sum(r["percentage"] for r in cleaned)
	if cleaned and total != 100:
		fail(_("Total allocation across cost centers must be 100%. It is {0}%.").format(total))
	return cleaned


@frappe.whitelist()
def create_salary_structure_assignment(employee, grade, sub_band, from_date, submit=1, cost_centers=None):
	"""Create (and by default submit) the assignment; returns its name and docstatus."""
	frappe.has_permission(DOCTYPE, "create", throw=True)
	if cint(submit):
		frappe.has_permission(DOCTYPE, "submit", throw=True)
	emp = frappe.get_doc("Employee", employee)
	emp.check_permission("read")

	if not grade:
		fail(_("Select a Grade."))
	if emp.grade and emp.grade != grade:
		fail(
			_("{0} has Grade {1}. Change the grade on the Employee first.").format(
				frappe.bold(emp.employee_name), frappe.bold(emp.grade)
			)
		)
	if not sub_band:
		fail(_("Select a Sub Band."))
	if not from_date:
		fail(_("Enter the From Date."))
	cost_centers = clean_cost_centers(cost_centers, emp.company)

	details = get_grade_details(grade)
	gross = next((flt(r.gross_amount) for r in details["sub_bands"] if r.sub_band == sub_band), None)
	if gross is None:
		fail(_("Sub Band {0} is not on Grade {1}.").format(frappe.bold(sub_band), frappe.bold(grade)))
	if gross <= 0:
		fail(_("Sub Band {0} of Grade {1} has no Gross Amount.").format(frappe.bold(sub_band), frappe.bold(grade)))
	if not details["salary_structure"]:
		fail(_("Grade {0} has no Default Salary Structure. Set it on the grade first.").format(frappe.bold(grade)))

	duplicate = frappe.db.get_value(
		DOCTYPE,
		{"employee": employee, "from_date": getdate(from_date), "docstatus": ("<", 2)},
		"name",
	)
	if duplicate:
		fail(
			_("{0} already has Salary Structure Assignment {1} from {2}.").format(
				frappe.bold(emp.employee_name), duplicate, frappe.format_value(getdate(from_date), "Date")
			)
		)

	if not emp.grade:
		emp.check_permission("write")
		emp.grade = grade
		emp.save()

	assignment = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"employee": employee,
			"company": emp.company,
			"salary_structure": details["salary_structure"],
			"currency": frappe.db.get_value("Salary Structure", details["salary_structure"], "currency"),
			"from_date": from_date,
			"base": gross,
			SUB_BAND: sub_band,
			# empty: HRMS fills the employee's / department's Payroll Cost Center at 100%
			"payroll_cost_centers": cost_centers,
		}
	)
	assignment.insert()
	if cint(submit):
		assignment.submit()
	return {"name": assignment.name, "docstatus": assignment.docstatus, "base": gross}
