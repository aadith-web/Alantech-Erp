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
