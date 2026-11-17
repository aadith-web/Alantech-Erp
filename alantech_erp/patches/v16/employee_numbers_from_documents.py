"""Aadhaar / PAN Number on the Employee from approved documents uploaded before the two were kept
equal (alantech/doctype/document/employee_numbers.py, ClickUp 14yr2e57r7k).

Only Employees whose field is still blank; the latest approved document of the format wins. A
number the Employee rules refuse (e.g. an Aadhaar already on another employee) is skipped and
logged, not copied.
"""

import frappe

from alantech_erp.alantech.doctype.document.employee_numbers import (
	EMPLOYEE_FIELDS,
	employee_display,
	employee_value,
)


def execute():
	from alantech_erp.setup.employee_nationality import check_identity_number

	for fmt, field in EMPLOYEE_FIELDS.items():
		types = frappe.get_all("Document Type Master", filters={"number_format": fmt}, pluck="name")
		if not types:
			continue
		done = set()
		for doc in frappe.get_all(
			"Document",
			filters={
				"reference_doctype": "Employee",
				"document_type": ["in", types],
				"approval_status": "Approved",
				"card_number": ["is", "set"],
			},
			fields=["name", "reference_name", "card_number"],
			order_by="modified desc",
		):
			if doc.reference_name in done or frappe.db.get_value("Employee", doc.reference_name, field):
				continue
			done.add(doc.reference_name)
			value = employee_value(doc.card_number)
			try:
				check_identity_number(field, value, doc.reference_name)
			except (frappe.ValidationError, frappe.DuplicateEntryError):
				frappe.clear_messages()
				print(f"Skipped {doc.name}: {field} {value} not valid for {doc.reference_name}")
				continue
			frappe.db.set_value(
				"Employee", doc.reference_name, field, employee_display(field, value), update_modified=False
			)
