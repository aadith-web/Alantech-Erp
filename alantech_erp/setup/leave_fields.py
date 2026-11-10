"""Applicable gender on Leave Type (e.g. Maternity Leave: Female only). Runs from after_migrate."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"Leave Type": [
		{
			"fieldname": "alt_gender_section",
			"label": "Applicable Gender",
			"fieldtype": "Section Break",
			"insert_after": "is_optional_leave",
		},
		{
			"fieldname": "alt_for_male",
			"label": "Male",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "alt_gender_section",
		},
		{
			"fieldname": "alt_gender_column",
			"fieldtype": "Column Break",
			"insert_after": "alt_for_male",
		},
		{
			"fieldname": "alt_for_female",
			"label": "Female",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "alt_gender_column",
			"description": "Untick to stop employees of that gender from applying for this leave.",
		},
	],
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)
	allow_employees_to_read_leave_policy()


def allow_employees_to_read_leave_policy():
	"""The HRMS Employee form lists the masters an employee can be assigned (Leave Policy, ...) with a
	read check, so an Employee-role user opening the form got "Insufficient Permission for Leave Policy".
	Read only; create-only so a rule changed later in Role Permissions Manager is left alone."""
	import frappe
	from frappe.permissions import add_permission

	if frappe.db.exists("Custom DocPerm", {"parent": "Leave Policy", "role": "Employee", "permlevel": 0}):
		return
	add_permission("Leave Policy", "Employee", 0, "read")