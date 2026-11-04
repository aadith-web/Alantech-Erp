"""Attendance Request approval: the employee's Leave Approver (their Reports To user) submits it,
which creates the Attendance. HR (HR User / HR Manager / System Manager) can submit any request.

The Leave Approver role gets submit permission on Attendance Request; before_submit then limits it
to the employee's own Leave Approver, so an approver cannot approve another team's request.

hooks.py:
    doc_events = {"Attendance Request": {"before_submit": "...attendance_request.check_approver"}}
    after_migrate = [..., "alantech_erp.setup.attendance_request.execute"]
"""

import frappe
from frappe import _

from alantech_erp.setup.access import FULL_ACCESS_ROLES

DOCTYPE = "Attendance Request"
APPROVER_ROLE = "Leave Approver"
APPROVER_RIGHTS = ("read", "write", "submit")


def check_approver(doc, method=None):
	user = frappe.session.user
	if user == "Administrator" or FULL_ACCESS_ROLES & set(frappe.get_roles(user)):
		return
	if frappe.db.get_value("Employee", doc.employee, "leave_approver") != user:
		frappe.throw(
			_("Only the Leave Approver of {0} can approve this Attendance Request.").format(
				frappe.bold(doc.employee_name or doc.employee)
			),
			frappe.PermissionError,
		)


def execute():
	"""Create-only: the Leave Approver permission row (rights changed later by hand are kept)."""
	if frappe.db.exists("Custom DocPerm", {"parent": DOCTYPE, "role": APPROVER_ROLE, "permlevel": 0}):
		return
	if not frappe.db.exists("Custom DocPerm", {"parent": DOCTYPE}):
		# first custom row: copy the standard ones, or they would stop applying
		from frappe.permissions import setup_custom_perms

		setup_custom_perms(DOCTYPE)
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": DOCTYPE,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": APPROVER_ROLE,
			"permlevel": 0,
			**{right: 1 for right in APPROVER_RIGHTS},
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=DOCTYPE)
