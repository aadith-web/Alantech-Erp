"""Document types to collect at joining ("Employee Mandatory Fields", ClickUp 14yr2e57mhp).

Creates the document types of the joining list that are missing and flags the ones every new
employee must upload (Document Type Master > Mandatory at Joining). Aadhaar and PAN Card only for
Indian nationals, like the Aadhaar / PAN Number fields (setup/employee_nationality.py).
Existing types keep their number / date / alert settings; only the new joining fields are set.
"""

import frappe

INDIA = "India"

# name: (mandatory at joining, only for nationality, settings for a new type)
JOINING_DOCUMENTS = {
	"Aadhaar": (1, INDIA, {"number_format": "Aadhaar", "number_mandatory": 1}),
	"Pan Card": (1, INDIA, {"number_format": "PAN", "number_mandatory": 1}),
	"Bank Proof": (1, None, {"description": "Cancelled cheque or bank passbook."}),
	"Photograph": (1, None, {}),
	"Signed Offer Acceptance": (1, None, {}),
	"Signed Job Description Acceptance": (1, None, {}),
	"Educational Certificates": (1, None, {"description": "Educational and qualification certificates."}),
	"Experience Letter": (0, None, {"description": "Previous employment / experience letters (if experienced)."}),
	"Passport": (0, None, {"expiry_required": 1, "expiry_date_mandatory": 1, "alert_days_before": 180}),
	"Driving License": (0, None, {"expiry_required": 1, "expiry_date_mandatory": 1, "alert_days_before": 60}),
	"Visa": (0, None, {"expiry_required": 1, "expiry_date_mandatory": 1, "alert_days_before": 60}),
	"Labour Card": (0, None, {"expiry_required": 1, "expiry_date_mandatory": 1, "alert_days_before": 60}),
	"Emirates ID": (0, None, {"number_format": "Emirates ID", "expiry_required": 1, "expiry_date_mandatory": 1, "alert_days_before": 60}),
	"Company ID Card": (0, None, {"description": "Issued after joining."}),
}


def execute():
	frappe.reload_doc("alantech", "doctype", "document_type_master")
	for name, (mandatory, nationality, settings) in JOINING_DOCUMENTS.items():
		if not frappe.db.exists("Document Type Master", name):
			doc = frappe.new_doc("Document Type Master")
			doc.document_type_name = name
			doc.update(settings)
			doc.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Document Type Master",
			name,
			{"mandatory_at_joining": mandatory, "mandatory_for_nationality": nationality},
			update_modified=False,
		)
