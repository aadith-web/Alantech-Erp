"""Which employee holds which asset right now (Asset.custodian), with exit dates, so HR can
chase returns before the Full and Final Statement.

Grouped assets (Asset Quantity above 1, ClickUp 14yr2e58hbm) are listed per employee with the
quantity held, from the submitted Employee Asset Handovers (employee_asset_handover.held_qty)."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "department", "label": _("Department"), "fieldtype": "Link", "options": "Department", "width": 140},
		{"fieldname": "employee_status", "label": _("Employee Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "relieving_date", "label": _("Relieving Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "asset", "label": _("Asset"), "fieldtype": "Link", "options": "Asset", "width": 140},
		{"fieldname": "asset_name", "label": _("Asset Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "qty", "label": _("Quantity"), "fieldtype": "Int", "width": 80},
		{"fieldname": "asset_category", "label": _("Category"), "fieldtype": "Link", "options": "Asset Category", "width": 120},
		{"fieldname": "asset_status", "label": _("Asset Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "location", "label": _("Location"), "fieldtype": "Link", "options": "Location", "width": 120},
		{"fieldname": "issued_on", "label": _("Issued On"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "warranty_expiry_date", "label": _("Warranty Expiry"), "fieldtype": "Date", "width": 120},
	]


def get_data(filters):
	from alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover import held_qty

	base = {"docstatus": 1, "status": ["not in", ("Sold", "Scrapped")]}
	if filters.company:
		base["company"] = filters.company
	fields = ["name", "asset_name", "asset_category", "status", "location", "custodian", "alt_warranty_expiry_date"]

	single_filters = {**base, "custodian": filters.employee or ["is", "set"], "asset_quantity": ["<=", 1]}
	holdings = [(a, a.custodian, 1) for a in frappe.get_all("Asset", filters=single_filters, fields=fields)]
	grouped = frappe.get_all("Asset", filters={**base, "asset_quantity": [">", 1]}, fields=fields)
	if grouped:
		by_name = {a.name: a for a in grouped}
		for (asset, employee), qty in held_qty(list(by_name), filters.employee).items():
			holdings.append((by_name[asset], employee, qty))
	if not holdings:
		return []

	employees = {e.name: e for e in frappe.get_all(
		"Employee", filters={"name": ["in", list({emp for _a, emp, _q in holdings})]},
		fields=["name", "employee_name", "department", "status", "relieving_date", "resignation_letter_date"])}
	issued_on = get_issue_dates([a.name for a, _e, _q in holdings])

	rows = []
	for a, employee, qty in holdings:
		emp = employees.get(employee) or frappe._dict()
		if filters.department and emp.department != filters.department:
			continue
		if filters.leaving_only and not (emp.status == "Left" or emp.relieving_date or emp.resignation_letter_date):
			continue
		rows.append({
			"employee": employee, "employee_name": emp.employee_name, "department": emp.department,
			"employee_status": emp.status, "relieving_date": emp.relieving_date,
			"asset": a.name, "asset_name": a.asset_name, "qty": qty, "asset_category": a.asset_category,
			"asset_status": a.status, "location": a.location,
			"issued_on": issued_on.get((a.name, employee)),
			"warranty_expiry_date": a.alt_warranty_expiry_date,
		})
	rows.sort(key=lambda r: (r["employee_name"] or "", r["asset_name"] or ""))
	return rows


def get_issue_dates(asset_names):
	"""Latest submitted movement that gave each asset to its current custodian."""
	movements = frappe.db.sql(
		"""
		select item.asset, item.to_employee, max(mv.transaction_date) as issued_on
		from `tabAsset Movement Item` item
		join `tabAsset Movement` mv on mv.name = item.parent
		where mv.docstatus = 1 and ifnull(item.to_employee, '') != '' and item.asset in %(assets)s
		group by item.asset, item.to_employee
		""",
		{"assets": asset_names},
		as_dict=True,
	)
	dates = {(m.asset, m.to_employee): m.issued_on for m in movements}
	# grouped assets: latest submitted Issue handover (they have no Asset Movement)
	for h in frappe.db.sql(
		"""
		select item.asset, h.employee, max(h.transaction_date) as issued_on
		from `tabEmployee Asset Handover Item` item
		join `tabEmployee Asset Handover` h on h.name = item.parent
		where h.docstatus = 1 and h.transaction_type = 'Issue' and item.asset in %(assets)s
		group by item.asset, h.employee
		""",
		{"assets": asset_names},
		as_dict=True,
	):
		if (h.asset, h.employee) not in dates or (h.issued_on and h.issued_on > dates[(h.asset, h.employee)]):
			dates[(h.asset, h.employee)] = h.issued_on
	return dates
