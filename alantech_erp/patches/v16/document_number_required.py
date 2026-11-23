"""Show Number on Document Type Master (ClickUp 14yr2e58dq2): every existing type keeps its Number
field (Show Number ticked; HR unticks it for types without a number), and existing Documents get the
new hidden Number Required copied from their type, so their Number field stays visible."""

import frappe


def execute():
	frappe.db.sql("update `tabDocument Type Master` set number_required = 1")
	frappe.db.sql(
		"""update `tabDocument` d join `tabDocument Type Master` t on t.name = d.document_type
		set d.number_required = t.number_required"""
	)
