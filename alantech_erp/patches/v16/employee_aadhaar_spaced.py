"""Employee Aadhaar Number stored in groups of four ("2345 6789 0124"), like the Aadhaar
documents (setup/employee_nationality.format_aadhaar). Earlier values were digits only."""

import frappe


def execute():
	from alantech_erp.setup.employee_nationality import AADHAAR_FIELD, format_aadhaar

	if not frappe.db.has_column("Employee", AADHAAR_FIELD):
		return
	for name, value in frappe.get_all(
		"Employee", filters={AADHAAR_FIELD: ["is", "set"]}, fields=["name", AADHAAR_FIELD], as_list=True
	):
		formatted = format_aadhaar(value)
		if formatted != value:
			frappe.db.set_value("Employee", name, AADHAAR_FIELD, formatted, update_modified=False)
