# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee form: no "Insufficient Permission for Salary Structure" for employees.

On every refresh of a saved, active Employee, HRMS's form script (hrms/public/js/erpnext/employee.js,
add_assignment_actions) asks hrms.overrides.employee_master.get_assignable_masters whether a Leave
Policy, Salary Structure and Shift Schedule exist, to decide which "Create Assignments" buttons
to show. It runs frappe.get_list on each as the logged-in user, so an employee opening their own
record (no read on Salary Structure) got a Permission Error popup.

hooks.py override_whitelisted_methods points it here. A user who can read all three masters (HR)
gets HRMS's own answer. Anyone else gets the same check for the masters they can read, and
"not available" for the rest; they cannot create those assignments anyway (the buttons are also
gated by can_create). HRMS itself is not changed.
"""

import frappe
from hrms.overrides.employee_master import get_assignable_masters as hrms_get_assignable_masters


def master_filters(company):
	# same filters as hrms.overrides.employee_master.get_assignable_masters
	return {
		"Leave Policy": {"docstatus": 1},
		"Salary Structure": {"docstatus": 1, "is_active": "Yes", "company": company},
		"Shift Schedule": {"docstatus": 1},
	}


@frappe.whitelist()
def get_assignable_masters(company: str) -> dict[str, bool]:
	masters = master_filters(company)
	readable = {d for d in masters if frappe.has_permission(d, "read")}
	if len(readable) == len(masters):
		return hrms_get_assignable_masters(company)
	return {
		doctype: doctype in readable and bool(frappe.get_list(doctype, filters=filters, limit=1, pluck="name"))
		for doctype, filters in masters.items()
	}
