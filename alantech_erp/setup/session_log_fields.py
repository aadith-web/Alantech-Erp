# Custom field on HRMS Attendance linking back to the Session Log that created it, and on Employee
# Checkin the sequence problem of a device / imported log that was saved anyway (setup/checkin_validation.py),
# and the flag on a check-out created by the midnight scheduler (setup/auto_checkout.py).
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
	"Employee Checkin": [
		{
			"fieldname": "sequence_warning",
			"label": "Sequence Warning",
			"fieldtype": "Small Text",
			"insert_after": "skip_auto_attendance",
			"read_only": 1,
			"no_copy": 1,
			"depends_on": "sequence_warning",
		},
		{
			"fieldname": "alt_auto_created",
			"label": "Auto Created",
			"fieldtype": "Check",
			"insert_after": "sequence_warning",
			"read_only": 1,
			"no_copy": 1,
			"search_index": 1,
			"description": "Check-out added by the daily scheduler (Auto Create Missing Checkout).",
		},
	],
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)