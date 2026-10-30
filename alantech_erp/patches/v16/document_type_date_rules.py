import frappe


def execute():
	"""Document Type Master got Issue Date Required / Mandatory and Expiry Date Mandatory.
	Keep what each type did before: Issue Date shown and optional, Expiry Date mandatory
	wherever it was required. Then copy the rules to the documents (fetched fields)."""
	frappe.db.sql("update `tabDocument Type Master` set issue_date_required = 1")
	frappe.db.sql("update `tabDocument Type Master` set expiry_date_mandatory = expiry_required")
	frappe.db.sql(
		"""update `tabDocument` d join `tabDocument Type Master` t on t.name = d.document_type
		set d.expiry_required = t.expiry_required,
			d.expiry_date_mandatory = t.expiry_date_mandatory,
			d.issue_date_required = t.issue_date_required,
			d.issue_date_mandatory = t.issue_date_mandatory"""
	)
