"""Employee Asset Handover rows: Warranty / Warranty Expiry copied from the Asset on existing rows
(ClickUp 14yr2e58k7e). Runs after the Asset warranty fields exist (setup/asset_handover.py)."""

import frappe

from alantech_erp.setup.asset_handover import execute as create_asset_fields


def execute():
	create_asset_fields()
	if not frappe.db.has_column("Employee Asset Handover Item", "warranty_expiry_date"):
		return
	frappe.db.sql(
		"""update `tabEmployee Asset Handover Item` i join `tabAsset` a on a.name = i.asset
		set i.warranty = a.alt_warranty, i.warranty_expiry_date = a.alt_warranty_expiry_date
		where i.warranty_expiry_date is null and (a.alt_warranty is not null or a.alt_warranty_expiry_date is not null)"""
	)
