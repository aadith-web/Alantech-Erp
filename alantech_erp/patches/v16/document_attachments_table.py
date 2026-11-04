import frappe


def execute():
	"""Document File became the Document Files table (several files per document):
	move each document's single file into the table as its first row."""
	if not frappe.db.has_column("Document", "attachment"):
		return
	for name, file_url in frappe.db.sql(
		"select name, attachment from `tabDocument` where ifnull(attachment, '') != ''"
	):
		if frappe.db.exists("Document Attachment", {"parent": name, "parenttype": "Document"}):
			continue
		frappe.get_doc({
			"doctype": "Document Attachment",
			"parent": name,
			"parenttype": "Document",
			"parentfield": "attachments",
			"idx": 1,
			"file": file_url,
		}).db_insert()
