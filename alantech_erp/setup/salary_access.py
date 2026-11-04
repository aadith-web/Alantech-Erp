"""Employees see only their own salary records.

The Employee User Permission also allows every employee below the user in the Reports To tree, so a
manager (e.g. a Leave Approver) would read their reportees' Salary Structure Assignments and Salary
Slips through the Employee role. Leave Approver is only for approving leave: these hooks keep salary
records to the employee's own, whatever the tree says. HR (FULL_ACCESS_ROLES) sees every record.

hooks.py: permission_query_conditions / has_permission for SALARY_DOCTYPES.
"""

import frappe

SALARY_DOCTYPES = ("Salary Structure Assignment", "Salary Slip")


def _unrestricted(user):
	from alantech_erp.setup.access import FULL_ACCESS_ROLES

	return user == "Administrator" or bool(FULL_ACCESS_ROLES & set(frappe.get_roles(user)))


def _own_employees(user):
	return frappe.get_all("Employee", filters={"user_id": user}, pluck="name")


def _query_conditions(doctype, user):
	user = user or frappe.session.user
	if _unrestricted(user):
		return ""
	employees = _own_employees(user)
	if not employees:
		return "1=0"
	values = ", ".join(frappe.db.escape(name) for name in employees)
	return f"`tab{doctype}`.`employee` in ({values})"


def salary_structure_assignment_query_conditions(user=None):
	"""Filters the list view, reports and search."""
	return _query_conditions("Salary Structure Assignment", user)


def salary_slip_query_conditions(user=None):
	return _query_conditions("Salary Slip", user)


def has_permission(doc, ptype=None, user=None):
	"""Checks a single record (opening by URL, API)."""
	user = user or frappe.session.user
	if _unrestricted(user) or not doc.get("employee"):
		return True
	return doc.employee in _own_employees(user)
