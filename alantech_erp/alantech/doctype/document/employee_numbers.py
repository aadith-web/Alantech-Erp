"""Aadhaar / PAN number kept the same on the Employee and on the employee's documents.

ClickUp: https://app.clickup.com/t/14yr2e57r7k (Aadhaar / PAN Number on Employee) with the
Employee Documents (HR-F07). A document type is matched by its Number Format, not its name:
Aadhaar -> Employee.alt_aadhaar_number, PAN -> Employee.pan_number.

- New document: a blank number is filled from the Employee (the form fills it as soon as the
  Document Type is chosen, get_employee_number; the server again on save, fill_from_employee).
- Document saved and Approved (HR uploads are approved at once, an employee's upload once HR
  approves it): its number is copied to the Employee (update_employee, Document.on_update): only
  that field, after the Employee's own checks (format, Aadhaar unique), with a timeline note. A
  full Employee save would re-run role profiles, approvers etc. and the Aadhaar + PAN pair rule.
- Employee saved with a changed Aadhaar / PAN: the employee's documents of that format, except
  rejected ones, get the new number (update_documents, Employee.on_update).
The Employee is not saved, so its on_update does not run back to the documents.
Both sides check numbers with document_number.clean_number, so they accept the same numbers.
"""

import frappe
from frappe import _

from alantech_erp.alantech.doctype.document.document_number import get_rules, number_key

EMPLOYEE_FIELDS = {"Aadhaar": "alt_aadhaar_number", "PAN": "pan_number"}
REJECTED = "Rejected"
APPROVED = "Approved"


def employee_field(document_type):
	"""Employee field holding this document type's number, or None."""
	if not document_type:
		return None
	return EMPLOYEE_FIELDS.get(get_rules(document_type).get("number_format"))


def employee_value(number):
	"""The number as compared on both sides: compact, upper case (Aadhaar 234567890124)."""
	return number_key(number) or None


def employee_display(field, value):
	"""How the Employee stores it: Aadhaar in groups of four ("2345 6789 0124"), PAN as is."""
	from alantech_erp.setup.employee_nationality import AADHAAR_FIELD, format_aadhaar

	return format_aadhaar(value) if field == AADHAAR_FIELD else value


@frappe.whitelist()
def get_employee_number(employee: str, document_type: str):
	"""Document form: the number saved on the Employee for this document type."""
	field = employee_field(document_type)
	if not field or not employee:
		return None
	frappe.has_permission("Employee", "read", employee, throw=True)
	return frappe.db.get_value("Employee", employee, field)


def fill_from_employee(doc):
	"""Document.validate (new documents): blank number = the Employee's."""
	if not doc.is_new() or (doc.card_number or "").strip() or doc.reference_doctype != "Employee":
		return
	field = employee_field(doc.document_type)
	if field and doc.reference_name:
		doc.card_number = frappe.db.get_value("Employee", doc.reference_name, field)


def update_employee(doc):
	"""Document.on_update: an approved Aadhaar / PAN document sets the Employee's number."""
	if doc.flags.alt_from_employee or doc.reference_doctype != "Employee" or doc.approval_status != APPROVED:
		return
	field = employee_field(doc.document_type)
	value = employee_value(doc.card_number)
	if not field or not value or not doc.reference_name:
		return
	current = frappe.db.get_value("Employee", doc.reference_name, field)
	if employee_value(current) == value:
		return
	from alantech_erp.setup.employee_nationality import check_identity_number

	# only this field: a full Employee save would also re-run role profiles, approvers etc.
	check_identity_number(field, value, doc.reference_name)
	stored = employee_display(field, value)
	frappe.db.set_value("Employee", doc.reference_name, field, stored)
	label = frappe.get_meta("Employee").get_label(field)
	frappe.get_doc("Employee", doc.reference_name).add_comment(
		"Info",
		_("{0} set to {1} from Document {2}.").format(_(label), stored, doc.name),
	)


def update_documents(employee, method=None):
	"""Employee.on_update: a changed Aadhaar / PAN goes to the employee's documents of that format."""
	for fmt, field in EMPLOYEE_FIELDS.items():
		value = employee_value(employee.get(field))
		if not value or not employee.has_value_changed(field):
			continue
		types = frappe.get_all("Document Type Master", filters={"number_format": fmt}, pluck="name")
		for name in frappe.get_all(
			"Document",
			filters={
				"reference_doctype": "Employee",
				"reference_name": employee.name,
				"document_type": ["in", types or [""]],
				"approval_status": ["!=", REJECTED],
			},
			pluck="name",
		):
			doc = frappe.get_doc("Document", name)
			if number_key(doc.card_number) == value:
				continue
			doc.card_number = value  # stored the document's way (e.g. "2345 6789 0124") by its validate
			doc.flags.alt_from_employee = True
			doc.save(ignore_permissions=True)
