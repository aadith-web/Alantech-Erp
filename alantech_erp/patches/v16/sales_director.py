"""Sales Head becomes Sales Director (CRM workflow deck: Sales Director -> Sales Managers -> Sales Engineers).

Renames the Designation and its Role Profile, so employees, users and reports-to designations
follow. If both already exist, the employees are moved to Sales Director instead.
"""

import frappe

OLD, NEW = "Sales Head", "Sales Director"
OLD_PROFILE, NEW_PROFILE = "ALT Sales Head", "ALT Sales Director"


def execute():
	_rename("Designation", OLD, NEW, "designation_name")
	_rename("Role Profile", OLD_PROFILE, NEW_PROFILE, "role_profile")

	if frappe.db.exists("Designation", NEW):
		frappe.db.set_value("Employee", {"designation": OLD}, "designation", NEW, update_modified=False)
		if frappe.get_meta("Designation").has_field("alt_reports_to"):
			frappe.db.set_value("Designation", {"alt_reports_to": OLD}, "alt_reports_to", NEW, update_modified=False)
			if frappe.db.exists("Role Profile", NEW_PROFILE):
				frappe.db.set_value("Designation", NEW, "alt_role_profile", NEW_PROFILE, update_modified=False)


def _rename(doctype, old, new, name_field):
	if not frappe.db.exists(doctype, old) or frappe.db.exists(doctype, new):
		return
	frappe.rename_doc(doctype, old, new, force=True, show_alert=False)
	frappe.db.set_value(doctype, new, name_field, new, update_modified=False)
