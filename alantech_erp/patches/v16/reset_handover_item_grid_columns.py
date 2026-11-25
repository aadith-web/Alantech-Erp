"""Employee Asset Handover: forget the column widths users saved for the Assets table (ClickUp
14yr2e58jx0). Widths saved before the Condition column was added (e.g. Quantity 259px) pushed
Condition off the right edge; everyone now gets the new default layout (they can resize again)."""

import json

import frappe

CHILD = "Employee Asset Handover Item"


def execute():
	for row in frappe.db.sql(
		"select user, doctype, data from __UserSettings where doctype = 'Employee Asset Handover'", as_dict=True
	):
		data = json.loads(row.data or "{}")
		grid = data.get("GridView") or {}
		if CHILD not in grid:
			continue
		grid.pop(CHILD)
		frappe.db.sql(
			"update __UserSettings set data = %s where user = %s and doctype = %s",
			(json.dumps(data), row.user, row.doctype),
		)
		frappe.cache.hdel("_user_settings", f"{row.doctype}::{row.user}")
