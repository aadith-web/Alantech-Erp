import frappe

from alantech_erp.alantech.doctype.document.document_number import FORMATS

# Passport / Driving License may be Indian or foreign: left for HR to choose
DEFAULT_FORMATS = {"Aadhaar": "Aadhaar", "Pan Card": "PAN", "Emirates ID": "Emirates ID"}


def execute():
	for doc_type, fmt in DEFAULT_FORMATS.items():
		if frappe.db.exists("Document Type Master", doc_type) and not frappe.db.get_value(
			"Document Type Master", doc_type, "number_format"
		):
			frappe.db.set_value(
				"Document Type Master",
				doc_type,
				{"number_format": fmt, "number_example": FORMATS[fmt]["example"]},
				update_modified=False,
			)
