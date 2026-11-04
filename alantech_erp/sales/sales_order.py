"""Sales Order doc_events.

* An order can only be made from a quotation the client has approved.
* Before submit the client's LPO is required: LPO number and date (Customer's Purchase Order) and
  the LPO attachment, and the order is marked as a Project or an Individual Item Order.
* A Local customer must have its GSTIN and GST address before the order is confirmed.
* Customer Stage: "Account" until the customer's first submitted Sales Order, then "Customer".
"""

import frappe
from frappe import _
from frappe.utils import get_link_to_form

from alantech_erp.sales import CLIENT_APPROVED, workflow_is_active

STAGE_FIELD = "alt_customer_stage"
ACCOUNT = "Account"
CUSTOMER = "Customer"


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


def before_submit(doc, method=None):
	"""The client's LPO must be on the order before it is confirmed."""
	meta = doc.meta
	missing = [
		_(meta.get_label(field))
		for field in ("po_no", "po_date", "alt_lpo_attachment", "alt_order_category")
		if meta.has_field(field) and not doc.get(field)
	]
	if missing:
		frappe.throw(
			_("Enter the client's LPO before confirming the order: {0}.").format(", ".join(frappe.bold(m) for m in missing)),
			title=_("LPO Required"),
		)
	# Local customers: GSTIN and the GST address (sales/customer.py)
	from alantech_erp.sales.customer import check_tax_details

	check_tax_details(doc.customer, doc.get("customer_address"), _("confirming the order"))


def on_submit(doc, method=None):
	set_customer_stage(doc.customer)


def on_cancel(doc, method=None):
	set_customer_stage(doc.customer)


def set_customer_stage(customer):
	if not customer or not frappe.get_meta("Customer").has_field(STAGE_FIELD):
		return
	ordered = frappe.db.exists("Sales Order", {"customer": customer, "docstatus": 1})
	stage = CUSTOMER if ordered else ACCOUNT
	if frappe.db.get_value("Customer", customer, STAGE_FIELD) != stage:
		frappe.db.set_value("Customer", customer, STAGE_FIELD, stage, update_modified=False)
