"""Employee Asset Handover: fill Total Assets (number of asset rows) on existing handovers
(ClickUp 14yr2e58jwz)."""

import frappe


def execute():
	if not frappe.db.has_column("Employee Asset Handover", "total_assets"):
		return
	frappe.db.sql(
		"""update `tabEmployee Asset Handover` h
		set h.total_assets = (select count(*) from `tabEmployee Asset Handover Item` i
			where i.parent = h.name and i.parenttype = 'Employee Asset Handover' and ifnull(i.asset, '') != '')"""
	)
