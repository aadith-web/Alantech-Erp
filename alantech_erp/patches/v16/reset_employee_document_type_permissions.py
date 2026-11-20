"""Employee Document Type: back to HRMS's standard permissions.

HRMS v16 renamed Identification Document Type to Employee Document Type
(hrms/patches/v16_0/rename_identification_document_type.py) and the doctype's old Custom DocPerm
rows came with it: System Manager only, Employee Self Service without read. Custom rows replace the
standard ones, so HR Manager / HR User (no System Manager) got "Insufficient Permission for Employee
Document Type" on the Employee form's Documents table. Removing them is Role Permission Manager's
"Reset to Default": HR Manager and HR User read / write / create, Employee read.

Only when the custom rows leave HR Manager without read, so a rule set up on purpose is kept.
"""

import frappe

DOCTYPE = "Employee Document Type"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	rows = frappe.get_all("Custom DocPerm", filters={"parent": DOCTYPE}, fields=["role", "read", "permlevel"])
	if not rows or any(r.role == "HR Manager" and r.read and not r.permlevel for r in rows):
		return
	frappe.db.delete("Custom DocPerm", {"parent": DOCTYPE})
	frappe.clear_cache(doctype=DOCTYPE)
