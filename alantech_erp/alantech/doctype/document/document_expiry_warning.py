# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Expiring soon / expired warnings on the Document form, the Document list and the Employee form's
Documents table, for the employee and for HR.

ClickUp: https://app.clickup.com/t/14yr2e58g46

- Expiring soon: the Expiry Date is within the type's alert window (Document Type Master > Alert
  Days Before Expiry, default 30, the same window as the Bell / Email alerts in document.py).
  Employee: "Your Passport is expiring in 20 days - Please update"; HR: "Passport of Vinitha K V is
  expiring in 20 days - Please update". Also "expires today" / "expires tomorrow".
- Expired: the Expiry Date has passed. Employee: "Your Passport has expired - Please update
  immediately"; HR: "Passport of Vinitha K V has expired - Please update immediately".
- Not warned: Rejected documents, and a document renewed by a newer one (another document of the
  same type for the same record, not Rejected, with a later Expiry Date): only the newest counts.
- "Your" wording is for the employee the document belongs to (also when they are HR).

Used by Document.onload (form), get_expiry_warnings (list banner, Employee form table).
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

DOCTYPE = "Document"
DEFAULT_ALERT_DAYS = 30
REJECTED = "Rejected"
EXPIRED, EXPIRING = "expired", "expiring"


def alert_days(document_type):
	return cint(frappe.db.get_value("Document Type Master", document_type, "alert_days_before")) or DEFAULT_ALERT_DAYS


def renewed_by(doc):
	"""A newer document of the same type for the same record, or None."""
	return frappe.db.get_value(
		DOCTYPE,
		{
			"name": ["!=", doc.name],
			"reference_doctype": doc.reference_doctype,
			"reference_name": doc.reference_name,
			"document_type": doc.document_type,
			"approval_status": ["!=", REJECTED],
			"expiry_date": [">", doc.expiry_date],
		},
		"name",
	)


def message(document_type, title, days_left, own):
	if days_left < 0:
		return (
			_("Your {0} has expired - Please update immediately").format(document_type)
			if own
			else _("{0} of {1} has expired - Please update immediately").format(document_type, title)
		)
	if days_left == 0:
		when = _("expires today")
	elif days_left == 1:
		when = _("expires tomorrow")
	else:
		when = _("is expiring in {0} days").format(days_left)
	return (
		_("Your {0} {1} - Please update").format(document_type, when)
		if own
		else _("{0} of {1} {2} - Please update").format(document_type, title, when)
	)


def warning_for(doc, window=None, user=None):
	"""{"status": "expired" | "expiring", "days_left", "message"} or None."""
	if not doc.get("expiry_date") or doc.get("approval_status") == REJECTED:
		return None
	days_left = (getdate(doc.expiry_date) - getdate(today())).days
	if days_left > (window if window is not None else alert_days(doc.document_type)):
		return None
	if renewed_by(doc):
		return None
	user = user or frappe.session.user
	own = bool(doc.get("employee")) and frappe.db.get_value("Employee", doc.employee, "user_id") == user
	return {
		"status": EXPIRED if days_left < 0 else EXPIRING,
		"days_left": days_left,
		"message": message(doc.document_type, doc.get("reference_title") or doc.reference_name, days_left, own),
	}


@frappe.whitelist()
def get_expiry_warnings(reference_doctype=None, reference_name=None):
	"""Warnings for the documents the user can see (list permission rules), expired first, then the
	soonest. Optionally only one record's documents (the Employee form)."""
	windows = {
		t.name: cint(t.alert_days_before) or DEFAULT_ALERT_DAYS
		for t in frappe.get_all("Document Type Master", fields=["name", "alert_days_before"])
	}
	horizon = frappe.utils.add_days(today(), max(windows.values(), default=DEFAULT_ALERT_DAYS))
	filters = {"expiry_date": ["<=", horizon], "approval_status": ["!=", REJECTED]}
	if reference_doctype and reference_name:
		filters.update({"reference_doctype": reference_doctype, "reference_name": reference_name})
	rows = frappe.get_list(
		DOCTYPE,
		filters=filters,
		fields=["name", "document_type", "expiry_date", "approval_status", "employee", "reference_doctype",
			"reference_name", "reference_title"],
		order_by="expiry_date asc",
		limit=500,
	)
	out = []
	for row in rows:
		warning = warning_for(row, windows.get(row.document_type, DEFAULT_ALERT_DAYS))
		if warning:
			out.append({"name": row.name, "document_type": row.document_type, "expiry_date": row.expiry_date,
				**warning})
	return out
