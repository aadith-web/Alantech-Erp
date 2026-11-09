"""Document Expiry: documents whose Expiry Date falls within the chosen number of days (and,
optionally, those already expired), soonest first.

ClickUp 14yr2e57cqm ("list not displayed"):
- Only documents that HAVE an Expiry Date are listed (a "<=" date filter also matched empty dates,
  so Aadhaar / Driving License rows without a date appeared with 0 days left).
- Approval Status filter: Approved (default, as the daily alerts) or "Approved and Pending": a
  document an employee uploaded still expires while it waits for HR. Rejected never.
- When rows are left out because they wait for approval, the report says so above the table, so an
  empty report is never silent.
Documents of Inactive / Left employees stay hidden (Document permission query, via get_list).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, today

APPROVED, PENDING = "Approved", "Pending Approval"
APPROVED_AND_PENDING = "Approved and Pending"
DEFAULT_DAYS = 90


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data, get_message(filters)


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
		{"fieldname": "approval_status", "label": _("Approval Status"), "fieldtype": "Data", "width": 130},
	]


def statuses(filters):
	return [APPROVED, PENDING] if filters.approval_status == APPROVED_AND_PENDING else [APPROVED]


def get_filters(filters, approval_statuses):
	"""Document list filters: an Expiry Date is required, then the range and the other filters."""
	within = cint(filters.expiring_within_days) if filters.expiring_within_days not in (None, "") else DEFAULT_DAYS
	upper = add_days(today(), within)
	conditions = [
		["approval_status", "in", approval_statuses],
		["expiry_date", "is", "set"],
		["expiry_date", "<=", upper] if filters.include_expired else ["expiry_date", "between", [today(), upper]],
	]
	if filters.document_type:
		conditions.append(["document_type", "=", filters.document_type])
	if filters.reference_doctype:
		conditions.append(["reference_doctype", "=", filters.reference_doctype])
	return conditions


def get_documents(filters, approval_statuses, fields):
	# get_list: the Document permission query also hides Inactive / Left employees
	return frappe.get_list(
		"Document", filters=get_filters(filters, approval_statuses), fields=fields, order_by="expiry_date asc"
	)


def get_data(filters):
	rows = get_documents(
		filters,
		statuses(filters),
		["name", "reference_doctype", "reference_name", "reference_title", "document_type", "card_number",
		 "issue_date", "expiry_date", "approval_status"],
	)
	for row in rows:
		row.days_left = date_diff(row.expiry_date, today())
	return rows


def get_message(filters):
	"""Pending documents in the range that the Approved-only view leaves out."""
	if filters.approval_status == APPROVED_AND_PENDING:
		return None
	pending = len(get_documents(filters, [PENDING], ["name"]))
	if not pending:
		return None
	return _(
		"{0} document(s) in this range are waiting for HR Manager approval and are not listed. "
		"Set Approval Status to '{1}' to include them."
	).format(pending, _(APPROVED_AND_PENDING))
