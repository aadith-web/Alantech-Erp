"""Assets: Warranty normalised ("2 years" -> "2 Years") and Warranty Expiry Date recalculated as
Purchase Date + Warranty (setup/asset_warranty.py). A Warranty that is not a period is left as it
is; HR is asked to correct it the next time the Asset is saved."""

import frappe

from alantech_erp.setup.asset_warranty import expiry, label, parse


def execute():
	if not frappe.db.has_column("Asset", "alt_warranty"):
		return
	for a in frappe.get_all("Asset", filters={"alt_warranty": ["is", "set"]},
			fields=["name", "purchase_date", "alt_warranty"]):
		period = parse(a.alt_warranty)
		if not period:
			continue
		values = {"alt_warranty": label(*period)}
		if a.purchase_date:
			values["alt_warranty_expiry_date"] = expiry(a.purchase_date, *period)
		frappe.db.set_value("Asset", a.name, values, update_modified=False)
