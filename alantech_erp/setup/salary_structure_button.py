"""Employee form: Create Salary Structure / View Salary Structure button.

ClickUp: https://app.clickup.com/t/14yr2e586v5 (parent 14yr2e586v0, "Employee Grade, Sub Band &
Salary Structure creation from Employee form")

- No active Salary Structure Assignment: "Create Salary Structure" (users who may create an
  assignment, i.e. HR).
- Active assignment: "View Salary Structure" instead (users who may read it; employees see only
  their own, setup/salary_access.py).
Active = submitted, From Date on or before today, the latest of the employee (From Date, then the
last created). A future-dated assignment alone is not active.

The popups behind the buttons are ClickUp 14yr2e586v6 (create) and 14yr2e586v8 (view). Until then
Create opens a new Salary Structure Assignment filled from the employee and the grade, and View
opens the active assignment.

The button follows changes: submitting or cancelling an assignment sends `EVENT` (after commit) to
the users who have that Employee open, and their form checks again (public/js/employee.js).
Hooked in hooks.py: doc_events Salary Structure Assignment on_submit / on_cancel.
"""

import frappe
from frappe.utils import getdate, today

DOCTYPE = "Salary Structure Assignment"
EVENT = "alt_salary_structure_assignment_changed"


def get_active_assignment(employee, on_date=None):
	"""The employee's active assignment as a dict (name, salary_structure, from_date, base), or None.
	Read with the user's permissions, so a user who may not see it gets None."""
	rows = frappe.get_list(
		DOCTYPE,
		filters={"employee": employee, "docstatus": 1, "from_date": ("<=", getdate(on_date or today()))},
		fields=["name", "salary_structure", "from_date", "base"],
		order_by="from_date desc, creation desc",
		limit=1,
	)
	return rows[0] if rows else None


@frappe.whitelist()
def get_salary_structure_button(employee):
	"""What the Employee form shows: {"action": "view" | "create" | None, "assignment": dict | None,
	"new_assignment": defaults for Create}."""
	frappe.has_permission("Employee", "read", doc=employee, throw=True)
	assignment = get_active_assignment(employee)
	if assignment:
		return {"action": "view", "assignment": assignment}
	if not frappe.has_permission(DOCTYPE, "create"):
		return {"action": None}
	return {"action": "create", "new_assignment": new_assignment_defaults(employee)}


def new_assignment_defaults(employee):
	"""Employee, company, the grade's Default Salary Structure and Default Base Pay, From Date today."""
	emp = frappe.db.get_value("Employee", employee, ["company", "grade"], as_dict=True) or frappe._dict()
	grade = (
		frappe.db.get_value(
			"Employee Grade", emp.grade, ["default_salary_structure", "default_base_pay"], as_dict=True
		)
		if emp.grade
		else None
	) or frappe._dict()
	values = {"employee": employee, "company": emp.company, "from_date": today()}
	if grade.default_salary_structure:
		values["salary_structure"] = grade.default_salary_structure
	if grade.default_base_pay:
		values["base"] = grade.default_base_pay
	return values


def notify_change(doc, method=None):
	"""Salary Structure Assignment on_submit / on_cancel: open Employee forms check the button again."""
	frappe.publish_realtime(
		EVENT, {"employee": doc.employee}, doctype="Employee", docname=doc.employee, after_commit=True
	)
