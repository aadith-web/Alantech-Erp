"""Assets: Warranty (Years) / (Months) dropdowns filled from the Warranty text already saved
(setup/asset_warranty.py), with the Warranty Expiry Date recalculated from the Purchase Date."""

import frappe

from alantech_erp.setup.asset_handover import execute as create_asset_fields
from alantech_erp.setup.asset_warranty import expiry, label, parse


def execute():
	create_asset_fields()
	if not frappe.db.has_column("Asset", "alt_warranty_years"):
		return
	for a in frappe.get_all("Asset", filters={"alt_warranty": ["is", "set"]},
			fields=["name", "purchase_date", "alt_warranty", "alt_warranty_years", "alt_warranty_months"]):
		if a.alt_warranty_years or a.alt_warranty_months:
			continue
		period = parse(a.alt_warranty)
		if not period:
			continue
		years, months = period
		years, months = years + months // 12, months % 12
		values = {"alt_warranty": label(years, months), "alt_warranty_years": str(years) if years else None,
			"alt_warranty_months": str(months) if months else None}
		if a.purchase_date:
			values["alt_warranty_expiry_date"] = expiry(a.purchase_date, years, months)
		frappe.db.set_value("Asset", a.name, values, update_modified=False)
