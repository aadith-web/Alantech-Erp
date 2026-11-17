# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee > Reports To: managers only.

ClickUp: https://app.clickup.com/t/14yr2e57t0m (parent HR-F07 14yr2e56cak)

A manager is an Active employee whose linked, enabled user has a Manager role: any role named
"... Manager" (HR Manager, Projects Manager, Sales Manager, Accounts Manager, ...), System Manager
not counted on its own, or Leave Approver. Leave Approver is included because the Reports To
becomes the employee's leave approver (setup/approvers.py), and the organisation structure gives
it to supervisors and heads (e.g. Production Supervisor) through their role profile. Ordinary
employees (Employee role only, or no user) are not managers.

- Form: the Reports To dropdown lists managers only (public/js/employee.js -> reports_to_query,
  ERPNext's employee_query with the manager filter).
- Server (Employee.validate, after org_structure.apply_designation_defaults): a Reports To set or
  changed to a non-manager is refused with ReportsToNotManagerError, so Data Import and the API
  follow the rule too. Values saved before are kept until the Reports To is changed.
- org_structure fills Reports To from the designation: it only picks a holder who is a manager,
  else the Managing Director (manager_holders below).
"""

import frappe
from frappe import _

APPROVER_ROLE = "Leave Approver"
NOT_COUNTED = {"System Manager"}


class ReportsToNotManagerError(frappe.ValidationError):
	pass


def manager_roles():
	roles = frappe.get_all("Role", filters={"name": ["like", "% Manager"], "disabled": 0}, pluck="name")
	return sorted({r for r in roles if r not in NOT_COUNTED} | {APPROVER_ROLE})


def manager_employees(employees=None):
	"""Names of Active employees whose user is enabled and holds a manager role (optionally only
	among `employees`)."""
	values = {"roles": tuple(manager_roles())}
	extra = ""
	if employees is not None:
		employees = [e for e in employees if e]
		if not employees:
			return []
		values["employees"] = tuple(employees)
		extra = "and emp.name in %(employees)s"
	return frappe.db.sql_list(
		f"""
		select distinct emp.name
		from `tabEmployee` emp
		join `tabUser` usr on usr.name = emp.user_id and usr.enabled = 1
		join `tabHas Role` hr on hr.parent = usr.name and hr.parenttype = 'User'
		where emp.status = 'Active' and hr.role in %(roles)s {extra}
		order by emp.name
		""",
		values,
	)


def is_manager(employee):
	return bool(employee) and bool(manager_employees([employee]))


def rule_active():
	"""Off in other modules' tests (their test employees have no roles), like the app's other
	Employee rules; tests/test_reports_to.py turns it on with frappe.flags.alt_check_reports_to."""
	return not frappe.flags.in_test or bool(frappe.flags.alt_check_reports_to)


def manager_holders(holders):
	"""org_structure: the holders of a designation who may be a Reports To, order kept."""
	if not rule_active():
		return holders
	allowed = set(manager_employees(holders))
	return [h for h in holders if h in allowed]


# ---------------------------------------------------------------------- form
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def reports_to_query(doctype, txt, searchfield, start, page_len, filters):
	"""Reports To dropdown: ERPNext's employee_query, managers only."""
	from erpnext.controllers.queries import employee_query

	if isinstance(filters, dict):
		filters = [[key, "=", value] for key, value in filters.items()]
	filters = list(filters or [])
	filters.append(["name", "in", manager_employees() or [""]])
	return employee_query(doctype, txt, searchfield, start, page_len, filters)


# ---------------------------------------------------------------------- server
def validate_reports_to(doc, method=None):
	"""Employee.validate: a Reports To set or changed must be a manager."""
	if not rule_active() or not doc.reports_to or not (doc.is_new() or doc.has_value_changed("reports_to")):
		return
	if is_manager(doc.reports_to):
		return
	name = frappe.db.get_value("Employee", doc.reports_to, "employee_name") or doc.reports_to
	frappe.throw(
		_(
			"{0} ({1}) cannot be Reports To: only a manager can be chosen, an active employee whose "
			"user has a Manager role (such as HR Manager or Projects Manager) or Leave Approver."
		).format(frappe.bold(name), doc.reports_to),
		ReportsToNotManagerError,
		title=_("Reports To Must Be a Manager"),
	)
