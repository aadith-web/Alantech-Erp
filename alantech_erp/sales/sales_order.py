"""Sales Order doc_events: an order can only be made from a quotation the client has approved."""

import frappe
from frappe import _
from frappe.utils import get_link_to_form

from alantech_erp.sales import CLIENT_APPROVED, workflow_is_active


def validate(doc, method=None):
	if doc.docstatus != 0 or not workflow_is_active():
		return

	quotations = {row.prevdoc_docname for row in doc.items if row.get("prevdoc_docname")}
	for quotation in sorted(quotations):
		state = frappe.db.get_value("Quotation", quotation, "workflow_state")
		if state != CLIENT_APPROVED:
			frappe.throw(
				_("Quotation {0} is {1}. A Sales Order can be made only after the client approves it (state {2}).").format(
					get_link_to_form("Quotation", quotation),
					frappe.bold(_(state or "not in workflow")),
					frappe.bold(_(CLIENT_APPROVED)),
				),
				title=_("Client Approval Pending"),
			)
