# Custom field on HRMS Attendance linking back to the Session Log that created it.
# Runs from after_migrate (hooks.py). Attendance belongs to HRMS, so never edit its JSON.

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"Attendance": [
		{
			"fieldname": "attendance_log",
			"label": "Session Log",
			"fieldtype": "Link",
			"options": "Session Log",
			"insert_after": "leave_application",
			"read_only": 1,
			"no_copy": 1,
			"search_index": 1,
		},
	],
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)
