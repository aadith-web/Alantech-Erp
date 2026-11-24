"""Warning when an employee is reactivated while some of their documents have expired.

hooks.py:
    doc_events = {"Employee": {"on_update": ["...document.expired_on_reactivation.employee_on_update"]}}

Reactivation = the status changes from anything else (Inactive, Left, Suspended, ...) to Active.
Only a warning: the save is not blocked. A document type counts as expired when its latest Expiry
Date is in the past, so an expired document that has since been renewed does not trigger it.
"""

import frappe
from frappe import _
from frappe.utils import escape_html, formatdate, get_link_to_form, getdate, today

SHOW_AT_MOST = 10


def employee_on_update(doc, method=None):
	if frappe.flags.in_import or frappe.flags.in_install or frappe.flags.in_patch:
		return
	before = doc.get_doc_before_save()
	if not before or doc.status != "Active" or before.status == "Active":
		return

	expired = get_expired_documents(doc.name)
	if not expired:
		return

	rows = "".join(
		"<li>{0}{1}: {2}</li>".format(
			frappe.bold(escape_html(row.document_type or row.name)),
			f" ({escape_html(row.card_number)})" if row.card_number else "",
			_("expired on {0}").format(formatdate(row.expiry_date)) + " - " + get_link_to_form("Document", row.name),
		)
		for row in expired[:SHOW_AT_MOST]
	)
	more = len(expired) - SHOW_AT_MOST
	if more > 0:
		rows += "<li>{0}</li>".format(_("and {0} more").format(more))

	frappe.msgprint(
		_("{0} has expired documents. Please review them:").format(frappe.bold(doc.employee_name or doc.name))
		+ f"<ul>{rows}</ul>",
		title=_("Expired Documents"),
		indicator="orange",
	)


def get_expired_documents(employee):
	"""One row per document type (or per document without a type): the one with the latest Expiry
	Date, when that date is in the past. Documents without an Expiry Date never expire."""
	latest = {}
	for row in frappe.get_all(
		"Document",
		filters={"reference_doctype": "Employee", "reference_name": employee, "expiry_date": ["is", "set"]},
		fields=["name", "document_type", "card_number", "expiry_date"],
		order_by="expiry_date asc",
	):
		latest[row.document_type or row.name] = row  # ascending: the last one wins

	run_date = getdate(today())
	return sorted(
		(row for row in latest.values() if getdate(row.expiry_date) < run_date),
		key=lambda row: getdate(row.expiry_date),
	)