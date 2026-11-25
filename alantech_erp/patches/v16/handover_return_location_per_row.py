"""Employee Asset Handover: Return To Location moved from the form to each asset row (ClickUp
14yr2e58hwg). Existing receipts keep their location: the old form value is copied to rows that have
none. The old column stays in the table (Frappe does not drop columns), so it can still be read."""

import frappe


def execute():
	parent, child = "tabEmployee Asset Handover", "tabEmployee Asset Handover Item"
	if not frappe.db.has_column("Employee Asset Handover", "location") or not frappe.db.has_column(
		"Employee Asset Handover Item", "return_location"
	):
		return
	frappe.db.sql(
		f"""update `{child}` i join `{parent}` h on h.name = i.parent
		set i.return_location = h.location
		where h.transaction_type = 'Receipt' and ifnull(h.location, '') != ''
			and ifnull(i.return_location, '') = '' and i.parenttype = 'Employee Asset Handover'"""
	)
