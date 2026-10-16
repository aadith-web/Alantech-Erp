import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, today


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "name", "label": _("Document"), "fieldtype": "Link", "options": "Document", "width": 140},
		{"fieldname": "reference_doctype", "label": _("Belongs To Type"), "fieldtype": "Link", "options": "DocType", "width": 120},
		{"fieldname": "reference_name", "label": _("Belongs To"), "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 140},
		{"fieldname": "reference_title", "label": _("Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Link", "options": "Document Type Master", "width": 130},
		{"fieldname": "card_number", "label": _("Number"), "fieldtype": "Data", "width": 140},
		{"fieldname": "issue_date", "label": _("Issue Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "expiry_date", "label": _("Expiry Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "days_left", "label": _("Days Left"), "fieldtype": "Int", "width": 90},
	]


def get_data(filters):
	# Only Approved documents are valid; get_list also hides Inactive/Left employees
	conditions = {"approval_status": "Approved"}
	if filters.document_type:
		conditions["document_type"] = filters.document_type
	if filters.reference_doctype:
		conditions["reference_doctype"] = filters.reference_doctype
	within = cint(filters.expiring_within_days) if filters.expiring_within_days not in (None, "") else 90
	upper = add_days(today(), within)
	conditions["expiry_date"] = ["<=", upper] if filters.include_expired else ["between", [today(), upper]]

	rows = frappe.get_list("Document", filters=conditions, order_by="expiry_date asc",
		fields=["name", "reference_doctype", "reference_name", "reference_title",
		        "document_type", "card_number", "issue_date", "expiry_date"])
	for row in rows:
		row.days_left = date_diff(row.expiry_date, today())
	return rows
