# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Appraisal for an employee: "Insufficient Permission for Designation" on save / submit.

The Appraisal form checks every link value it holds (frappe.client.validate_link_and_fetch ->
search_widget), which needs at least the "select" right on the linked DocType. The Employee role
had no right on Designation (Appraisal.designation, fetched from the Employee), KRA (Appraisal KRA
rows) and Employee Feedback Criteria (self-rating rows), so an employee filling their own appraisal
was refused.

execute() (after_migrate) gives the Employee role SELECT only on those DocTypes: it can pick and
validate the value, but cannot open, list or read the records. Create-only: a permission row HR
changed later is kept.
"""

import frappe

ROLE = "Employee"
DOCTYPES = ("Designation", "KRA", "Employee Feedback Criteria")


def execute():
	from frappe.permissions import setup_custom_perms

	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": ROLE, "permlevel": 0}):
			continue
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			setup_custom_perms(doctype)  # first custom row: copy the standard ones so they keep applying
		frappe.get_doc({
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": ROLE,
			"permlevel": 0,
			"select": 1,
			"read": 0,  # Custom DocPerm defaults read to 1
		}).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)
