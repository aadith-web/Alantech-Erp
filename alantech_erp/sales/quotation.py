"""Quotation doc_events for the two-level approval flow (see alantech_erp/sales/__init__.py)."""

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_link_to_form, now_datetime

from alantech_erp.sales import (
	APPROVED,
	LEVEL_1,
	LEVEL_2,
	LEVEL_2_LIMIT_FIELD,
	LOCKED_STATES,
	LOST,
	PENDING_LEVEL_2,
	PENDING_MANAGER,
	REJECT_ACTION,
	REJECTED,
	REVISION_REQUESTED,
	workflow_is_active,
)


def validate(doc, method=None):
	validate_estimation(doc)
	link_technical_offer(doc)
	track_approval(doc)


# --------------------------------------------------------------------------- approval levels
def level_2_limit():
	if not frappe.get_meta("Selling Settings").has_field(LEVEL_2_LIMIT_FIELD):
		return 0
	return flt(frappe.db.get_single_value("Selling Settings", LEVEL_2_LIMIT_FIELD))


def required_level(doc):
	"""Level 2 when the grand total (company currency) is above the Selling Settings limit."""
	limit = level_2_limit()
	return LEVEL_2 if limit > 0 and flt(doc.base_grand_total) > limit else LEVEL_1


def track_approval(doc):
	"""Keep the approval level current and record who approved / rejected at each level.

	Runs in validate, so it covers the workflow buttons as well as API / import saves.
	"""
	if not workflow_is_active():
		return

	before = doc.get_doc_before_save()
	old = before.get("workflow_state") if before else None
	new = doc.get("workflow_state")
	user = frappe.session.user

	if old == new or not before:  # plain save / new quotation
		if new == PENDING_LEVEL_2 and before and flt(before.base_grand_total) != flt(doc.base_grand_total):
			frappe.throw(
				_("The Sales Manager has already approved this quotation. To change prices, {0} it with remarks so the salesperson can revise it.").format(
					frappe.bold(_(REJECT_ACTION))
				),
				title=_("Quotation Locked"),
			)
		if doc.docstatus == 0 and new != PENDING_LEVEL_2:
			doc.alt_approval_level = required_level(doc)
		return

	if old == PENDING_MANAGER and new in (APPROVED, PENDING_LEVEL_2):
		# the route (Approved / Level 2) was picked from the level saved on the quotation
		if required_level(doc) != (doc.get("alt_approval_level") or LEVEL_1):
			frappe.throw(
				_("The Level 2 approval limit in Selling Settings has changed since this quotation was saved. Save the quotation once and approve again."),
				title=_("Approval Level Changed"),
			)
		doc.alt_level_1_approver = user
		doc.alt_level_1_approved_on = now_datetime()

	elif old == PENDING_LEVEL_2 and new == APPROVED:
		if user == doc.get("alt_level_1_approver"):
			frappe.throw(
				_("You approved this quotation at Level 1. Level 2 approval must come from another approver."),
				title=_("Second Approver Required"),
			)
		doc.alt_level_2_approver = user
		doc.alt_level_2_approved_on = now_datetime()

	elif new == REJECTED:
		if not cstr(doc.get("alt_rejection_remarks")).strip():
			frappe.throw(
				_("Enter the reason for rejection so the salesperson knows what to change."),
				title=_("Remarks Required"),
			)
		doc.alt_rejected_by = user
		for field in ("alt_level_1_approver", "alt_level_1_approved_on", "alt_level_2_approver", "alt_level_2_approved_on"):
			doc.set(field, None)

	if new == PENDING_MANAGER:
		# (re)submitted for approval: level from the current total, last rejection stays in the timeline
		doc.alt_approval_level = required_level(doc)
		doc.alt_rejection_remarks = None
		doc.alt_rejected_by = None


@frappe.whitelist(methods=["POST"])
def set_rejection_remarks(name, remarks):
	"""Called by the Reject button just before the workflow action (apply_workflow reloads the doc from the DB)."""
	from frappe.model.workflow import get_transitions

	remarks = cstr(remarks).strip()
	if not remarks:
		frappe.throw(_("Enter the reason for rejection."), title=_("Remarks Required"))

	doc = frappe.get_doc("Quotation", name)
	if not any(t.action == REJECT_ACTION for t in get_transitions(doc)):
		frappe.throw(_("You cannot reject this quotation in its current state."), frappe.PermissionError)

	doc.db_set("alt_rejection_remarks", remarks, update_modified=False)


def on_change(doc, method=None):
	"""Tell the salesperson what happened to their quotation.

	Approvers are notified by the workflow itself (Workflow Action email + list for the next role).
	"""
	if not workflow_is_active():
		return
	before = doc.get_doc_before_save()
	old = before.get("workflow_state") if before else None
	new = doc.get("workflow_state")
	if not old or old == new:
		return

	actor = frappe.utils.get_fullname(frappe.session.user)
	if new == REJECTED:
		doc.add_comment("Comment", _("Rejected: {0}").format(frappe.utils.escape_html(doc.alt_rejection_remarks)))
		_notify_owner(
			doc,
			_("Quotation {0} was rejected by {1}").format(doc.name, actor),
			_("Reason: {0}<br><br>Make the changes and use <b>Resubmit</b> to send it for approval again.").format(
				frappe.utils.escape_html(doc.alt_rejection_remarks)
			),
		)
	elif new == PENDING_LEVEL_2:
		_notify_owner(
			doc,
			_("Quotation {0} approved by {1} (Level 1)").format(doc.name, actor),
			_("It is above the Level 2 limit and is now waiting for Level 2 approval."),
		)
	elif new == APPROVED:
		_notify_owner(
			doc,
			_("Quotation {0} approved by {1}").format(doc.name, actor),
			_("It is ready to send to the client. Use <b>Send to Client</b> once it has gone out."),
		)


def _notify_owner(doc, subject, message):
	owner = doc.owner
	if not owner or owner in ("Administrator", "Guest") or owner == frappe.session.user:
		return
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	enqueue_create_notification(
		owner,
		{
			"type": "Alert",
			"document_type": doc.doctype,
			"document_name": doc.name,
			"subject": subject,
			"email_content": message,
			"from_user": frappe.session.user,
		},
	)
	email = frappe.db.get_value("User", {"name": owner, "enabled": 1}, "email")
	if email:
		frappe.sendmail(
			recipients=[email],
			subject=frappe.utils.strip_html(subject),
			message=f"<p>{subject}</p><p>{message}</p><p>{get_link_to_form(doc.doctype, doc.name)}</p>",
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)


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
