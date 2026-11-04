"""Deal (ERPNext Opportunity) from a Quotation: the Quotation's Create Deal button.

The Deal is optional. It is filled from the quotation (customer, contact, quotation link) with
amount = quote value, the probability %, expected closing date and owner entered in the dialog.
A revised quotation updates the amount (sales/quotation.py sync_deal). Closing it as Won comes
with the Sales Order; Lost is the standard "Declare Lost" (reasons and competitors).

Sales Stage: set from the quotation (sales_stage_for) and moved along with it as the quotation goes
through approval, the client and revisions; it is read only on a Deal made from a quotation.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_link_to_form, getdate, nowdate

from alantech_erp.sales import (
	DRAFT,
	SALES_STAGES,
	STAGE_BY_STATE,
	STAGE_DRAFT,
	STAGE_REVISION,
	STAGE_SENT,
	workflow_is_active,
)


def sales_stage_for(quotation):
	"""Deal Sales Stage for the quotation's current state (None: leave the Deal as it is)."""
	state = quotation.get("workflow_state") if workflow_is_active() else None
	if state:
		if state == DRAFT and quotation.get("amended_from"):
			return STAGE_REVISION  # the client asked for a revision and this is the new version
		return STAGE_BY_STATE.get(state)
	# no approval workflow on the site: by docstatus
	if cint(quotation.docstatus) == 0:
		return STAGE_REVISION if quotation.get("amended_from") else STAGE_DRAFT
	if cint(quotation.docstatus) == 1:
		return STAGE_SENT
	return None


def stage_exists(stage):
	return bool(stage) and stage in SALES_STAGES and frappe.db.exists("Sales Stage", stage)


def validate_opportunity(doc, method=None):
	"""Opportunity validate: no Prospect flow (Deals are for Customers, made from the Quotation)."""
	if doc.get("opportunity_from") == "Prospect":
		frappe.throw(
			_("Prospects are not used. Convert the Lead to a Customer and create the Deal from its Quotation."),
			title=_("Prospect Not Used"),
		)
	if doc.get("alt_quotation") and doc.has_value_changed("sales_stage") and not doc.is_new():
		# the stage follows the quotation; only the quotation moves it
		expected = sales_stage_for(frappe.get_doc("Quotation", doc.alt_quotation))
		if expected and stage_exists(expected) and doc.sales_stage != expected:
			doc.sales_stage = expected


@frappe.whitelist(methods=["POST"])
def make_deal(quotation, probability=None, expected_closing=None, opportunity_owner=None):
	doc = frappe.get_doc("Quotation", quotation)
	doc.check_permission("write")
	frappe.has_permission("Opportunity", "create", throw=True)

	if doc.docstatus == 2:
		frappe.throw(_("Quotation {0} is cancelled.").format(frappe.bold(doc.name)))
	if doc.opportunity:
		frappe.throw(
			_("Quotation {0} already has Deal {1}.").format(
				frappe.bold(doc.name), get_link_to_form("Opportunity", doc.opportunity)
			),
			title=_("Deal Exists"),
		)
	if doc.quotation_to != "Customer":
		frappe.throw(
			_("Convert Lead {0} to a Customer before creating the Deal.").format(frappe.bold(doc.party_name)),
			title=_("Customer Required"),
		)
	probability = flt(probability)
	if probability < 0 or probability > 100:
		frappe.throw(_("Probability must be between 0 and 100%."))
	if expected_closing and getdate(expected_closing) < getdate(nowdate()):
		frappe.throw(_("The expected closing date cannot be in the past."))

	deal = frappe.new_doc("Opportunity")
	deal.update(
		{
			"opportunity_from": "Customer",
			"party_name": doc.party_name,
			"customer_name": doc.customer_name,
			"contact_person": doc.contact_person,
			"contact_email": doc.get("contact_email"),
			"contact_mobile": doc.get("contact_mobile"),
			"company": doc.company,
			"currency": doc.currency,
			"conversion_rate": doc.conversion_rate or 1,
			"transaction_date": nowdate(),
			"opportunity_amount": doc.grand_total,
			"base_opportunity_amount": doc.base_grand_total,
			"probability": probability,
			"expected_closing": expected_closing or doc.valid_till,
			"opportunity_owner": opportunity_owner or doc.owner,
			"territory": doc.get("territory"),
			"customer_group": doc.get("customer_group"),
			"alt_quotation": doc.name,
		}
	)
	stage = sales_stage_for(doc)
	if stage_exists(stage):
		deal.sales_stage = stage
	for field in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
		if deal.meta.has_field(field) and doc.get(field):
			deal.set(field, doc.get(field))
	if cint(doc.docstatus) == 1 and deal.meta.get_field("status") and "Quotation" in (
		deal.meta.get_field("status").options or ""
	).split("\n"):
		deal.status = "Quotation"
	deal.insert()

	doc.db_set("opportunity", deal.name)
	doc.add_comment("Info", _("Deal {0} created").format(get_link_to_form("Opportunity", deal.name)))
	return deal.name
