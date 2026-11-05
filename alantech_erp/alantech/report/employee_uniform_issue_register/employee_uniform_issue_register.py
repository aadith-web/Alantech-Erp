"""Employee Uniform Issue Register: one row per item issued on a submitted Employee Uniform Issue,
with a total row for Qty and Amount (add_total_row in the report JSON)."""

import frappe
from frappe import _
from frappe.utils import getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	return get_columns(), get_data(filters)


def validate_filters(filters):
	if filters.from_date and filters.to_date and getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date."))


def get_columns():
	return [
		{"fieldname": "name", "label": _("EUI No"), "fieldtype": "Link", "options": "Employee Uniform Issue", "width": 150},
		{"fieldname": "issue_date", "label": _("Issue Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "department", "label": _("Department"), "fieldtype": "Link", "options": "Department", "width": 140},
		{"fieldname": "item_code", "label": _("Item Code"), "fieldtype": "Link", "options": "Item", "width": 130},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "size", "label": _("Size"), "fieldtype": "Data", "width": 70},
		{"fieldname": "qty", "label": _("Qty"), "fieldtype": "Float", "width": 80},
		# a sum of rates means nothing: no total for this column
		{"fieldname": "rate", "label": _("Rate"), "fieldtype": "Currency", "width": 110, "disable_total": 1},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "stock_entry", "label": _("Stock Entry"), "fieldtype": "Link", "options": "Stock Entry", "width": 150},
	]


def get_data(filters):
	issue = frappe.qb.DocType("Employee Uniform Issue")
	item = frappe.qb.DocType("Employee Uniform Issue Item")
	query = (
		frappe.qb.from_(issue)
		.join(item)
		.on((item.parent == issue.name) & (item.parenttype == "Employee Uniform Issue"))
		.select(
			issue.name,
			issue.issue_date,
			issue.employee,
			issue.employee_name,
			issue.department,
			item.item_code,
			item.item_name,
			item.size,
			item.qty,
			item.rate,
			item.amount,
			issue.stock_entry,
		)
		.where(issue.docstatus == 1)
		.orderby(issue.issue_date, order=frappe.qb.desc)
		.orderby(issue.name, order=frappe.qb.desc)
		.orderby(item.idx)
	)

	if filters.company:
		query = query.where(issue.company == filters.company)
	if filters.from_date:
		query = query.where(issue.issue_date >= getdate(filters.from_date))
	if filters.to_date:
		query = query.where(issue.issue_date <= getdate(filters.to_date))
	if filters.employee:
		query = query.where(issue.employee == filters.employee)
	if filters.item_code:
		query = query.where(item.item_code == filters.item_code)
	if filters.department:
		query = query.where(issue.department.isin(get_departments(filters.department)))

	return query.run(as_dict=True)


def get_departments(department):
	"""The department and its sub-departments (Department is a tree)."""
	lft, rgt = frappe.db.get_value("Department", department, ["lft", "rgt"]) or (None, None)
	if lft is None:
		return [department]
	return frappe.get_all("Department", filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name")
