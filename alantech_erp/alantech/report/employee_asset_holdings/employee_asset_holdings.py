"""Which employee holds which asset right now (Asset.custodian), with exit dates, so HR can
chase returns before the Full and Final Statement."""

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
		{"fieldname": "asset_category", "label": _("Category"), "fieldtype": "Link", "options": "Asset Category", "width": 120},
		{"fieldname": "asset_status", "label": _("Asset Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "location", "label": _("Location"), "fieldtype": "Link", "options": "Location", "width": 120},
		{"fieldname": "issued_on", "label": _("Issued On"), "fieldtype": "Datetime", "width": 150},
	]


def get_data(filters):
	asset_filters = {"docstatus": 1, "custodian": ["is", "set"], "status": ["not in", ("Sold", "Scrapped")]}
	if filters.company:
		asset_filters["company"] = filters.company
	if filters.employee:
		asset_filters["custodian"] = filters.employee
	assets = frappe.get_all("Asset", filters=asset_filters,
	                        fields=["name", "asset_name", "asset_category", "status", "location", "custodian"])
	if not assets:
		return []

	employees = {e.name: e for e in frappe.get_all(
		"Employee", filters={"name": ["in", list({a.custodian for a in assets})]},
		fields=["name", "employee_name", "department", "status", "relieving_date", "resignation_letter_date"])}
	issued_on = get_issue_dates([a.name for a in assets])

	rows = []
	for a in assets:
		emp = employees.get(a.custodian) or frappe._dict()
		if filters.department and emp.department != filters.department:
			continue
		if filters.leaving_only and not (emp.status == "Left" or emp.relieving_date or emp.resignation_letter_date):
			continue
		rows.append({
			"employee": a.custodian, "employee_name": emp.employee_name, "department": emp.department,
			"employee_status": emp.status, "relieving_date": emp.relieving_date,
			"asset": a.name, "asset_name": a.asset_name, "asset_category": a.asset_category,
			"asset_status": a.status, "location": a.location,
			"issued_on": issued_on.get((a.name, a.custodian)),
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
	return {(m.asset, m.to_employee): m.issued_on for m in movements}
