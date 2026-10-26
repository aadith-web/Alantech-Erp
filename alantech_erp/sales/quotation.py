"""Quotation doc_events for the two-level approval flow (see alantech_erp/sales/__init__.py)."""

import frappe
from frappe import _
from frappe.utils import flt, get_link_to_form

from alantech_erp.sales import LOCKED_STATES, LOST, REVISION_REQUESTED, workflow_is_active


def validate(doc, method=None):
	validate_estimation(doc)
	link_technical_offer(doc)


def validate_estimation(doc):
	"""A quotation for a deal must be priced from that deal's submitted Estimation."""
	if doc.docstatus != 0 or not doc.opportunity or not workflow_is_active():
		return

	if doc.get("alt_estimation"):
		est = frappe.db.get_value("Estimation", doc.alt_estimation, ["docstatus", "opportunity"], as_dict=True)
		if not est or est.docstatus != 1:
			frappe.throw(
				_("Estimation {0} must be submitted before it can be quoted.").format(
					get_link_to_form("Estimation", doc.alt_estimation)
				),
				title=_("Estimation Not Submitted"),
			)
		if est.opportunity != doc.opportunity:
			frappe.throw(
				_("Estimation {0} belongs to Deal {1}, not {2}.").format(
					frappe.bold(doc.alt_estimation), frappe.bold(est.opportunity), frappe.bold(doc.opportunity)
				),
				title=_("Wrong Estimation"),
			)
		return

	estimations = frappe.get_all(
		"Estimation",
		filters={"opportunity": doc.opportunity, "docstatus": 1},
		order_by="creation desc",
		pluck="name",
	)
	if len(estimations) == 1:
		doc.alt_estimation = estimations[0]
	elif not estimations:
		frappe.throw(
			_("Deal {0} has no submitted Estimation. The Sales Manager prepares the Estimation before the quotation is made.").format(
				get_link_to_form("Opportunity", doc.opportunity)
			),
			title=_("Estimation Required"),
		)
	else:
		frappe.throw(
			_("Deal {0} has more than one Estimation. Select one in the Estimation field.").format(
				frappe.bold(doc.opportunity)
			),
			title=_("Select Estimation"),
		)


def before_update_after_submit(doc, method=None):
	"""Prices approved by the manager cannot change ("Update Items"); revise the quotation instead."""
	if not workflow_is_active() or doc.get("workflow_state") not in LOCKED_STATES:
		return
	before = doc.get_doc_before_save()
	if before and flt(before.grand_total) != flt(doc.grand_total):
		frappe.throw(
			_("This quotation is {0}, so its items and prices cannot change. Use {1} to create a new version for manager approval.").format(
				frappe.bold(_(doc.workflow_state)), frappe.bold(_(REVISION_REQUESTED))
			),
			title=_("Quotation Locked"),
		)


def on_update_after_submit(doc, method=None):
	"""Keep the workflow state and ERPNext's Lost status in step, whichever one was used."""
	if not workflow_is_active():
		return

	if doc.get("workflow_state") == LOST and doc.status != "Lost":
		doc.db_set("status", "Lost")
		doc.update_opportunity("Lost")
		doc.update_lead()
	elif doc.status == "Lost" and doc.get("workflow_state") != LOST:
		# "Set as Lost" button used directly
		doc.db_set("workflow_state", LOST)


def link_technical_offer(doc):
	"""Keep the quotation pointing at the current Technical Offer of its Estimation.

	An amended quotation still carries the cancelled offer of the previous version; move it to the
	newest amendment of that offer.
	"""
	if doc.docstatus != 0:
		return
	name = doc.get("alt_technical_offer")
	if not name:
		if doc.get("alt_estimation"):
			from alantech_erp.alantech.doctype.estimation.estimation import latest_technical_offer

			doc.alt_technical_offer = latest_technical_offer(doc.alt_estimation)
		return

	seen = set()
	while frappe.db.get_value("Technical Offer", name, "docstatus") == 2 and name not in seen:
		seen.add(name)
		newer = frappe.db.get_value("Technical Offer", {"amended_from": name}, "name")
		if not newer:
			break
		name = newer
	doc.alt_technical_offer = name

	offer_estimation = frappe.db.get_value("Technical Offer", name, "estimation")
	if doc.get("alt_estimation") and offer_estimation and offer_estimation != doc.alt_estimation:
		frappe.throw(
			_("Technical Offer {0} is for Estimation {1}, not {2}.").format(
				frappe.bold(name), frappe.bold(offer_estimation), frappe.bold(doc.alt_estimation)
			),
			title=_("Wrong Technical Offer"),
		)


def before_submit(doc, method=None):
	"""The client gets the final offer: its Technical Offer must be submitted first."""
	if not doc.get("alt_technical_offer"):
		return
	status = frappe.db.get_value("Technical Offer", doc.alt_technical_offer, "docstatus")
	if status != 1:
		frappe.throw(
			_("Submit Technical Offer {0} before this quotation is approved.").format(
				get_link_to_form("Technical Offer", doc.alt_technical_offer)
			),
			title=_("Technical Offer Not Final"),
		)
