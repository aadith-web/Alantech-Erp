# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Fill Document.number_key for existing documents and list numbers already used twice.

ClickUp: https://app.clickup.com/t/14yr2e57c6k
The duplicate check compares number_key (document_number.number_key), so existing documents need
it. Duplicates saved before the fix are not changed: they are printed (and written to the Error Log)
for HR to correct; saving one of them again is refused until its number is fixed.
"""

import frappe

from alantech_erp.alantech.doctype.document.document_number import REJECTED, number_key


def execute():
	seen = {}
	duplicates = []
	for doc in frappe.get_all(
		"Document",
		fields=["name", "document_type", "card_number", "reference_title", "approval_status"],
		order_by="creation asc",
	):
		key = number_key(doc.card_number)
		frappe.db.set_value("Document", doc.name, "number_key", key, update_modified=False)
		if not key or doc.approval_status == REJECTED:
			continue
		first = seen.setdefault((doc.document_type, key), doc)
		if first is not doc:
			duplicates.append(
				f"{doc.document_type} {doc.card_number}: {doc.name} ({doc.reference_title}) "
				f"duplicates {first.name} ({first.reference_title})"
			)

	if duplicates:
		message = "Documents with a number already used:\n" + "\n".join(duplicates)
		print(message)
		frappe.log_error(title="Duplicate document numbers to correct", message=message)
