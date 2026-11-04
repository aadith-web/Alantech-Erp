"""Quotation doc_events for the two-level approval flow (see alantech_erp/sales/__init__.py).

The approvers come from the Sales Person tree of the quotation's creator (sales/hierarchy.py) and
are stored on the quotation (alt_level_1_user / alt_level_2_user) when it is saved as a draft and
when it is (re)submitted for approval; the workflow transitions only show for them.

Approve asks for optional remarks (set_approval_remarks, before the workflow action). Approved is
still a draft: only the owner can edit it, to apply those remarks, and the items, prices,
discounts and taxes stay as approved (check_approved_changes). Send to Client submits it.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_link_to_form, now_datetime

from alantech_erp.sales import (
	APPROVAL_REMARKS_FIELDS,
	APPROVE_ACTION,
	APPROVED,
	DRAFT,
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
	STAGE_LOST,
	workflow_is_active,
)


def validate(doc, method=None):
	if doc.get("quotation_to") == "Prospect":
		frappe.throw(
			_("Prospects are not used. Quote a Customer (or a Lead that will be converted to a Customer)."),
			title=_("Prospect Not Used"),
		)
	keep_deal_on_revision(doc)
	validate_estimation(doc)
	link_technical_offer(doc)
	track_approval(doc)


# --------------------------------------------------------------------------- approvers (hierarchy)
def assign_approvers(doc):
	"""Level 1 / Level 2 approver of the creator, from the Sales Person tree."""
	from alantech_erp.sales.hierarchy import approvers_for, sales_person_of_user

	owner = doc.owner or frappe.session.user
	person = sales_person_of_user(owner)
	doc.alt_sales_person = person.name if person else None
	doc.alt_level_1_user, doc.alt_level_2_user = approvers_for(owner)


def check_approver(doc, field, level):
	"""Only the approver named on the quotation may act at that level (System Manager excepted)."""
	expected = doc.get(field)
	user = frappe.session.user
	if not expected or user == expected or user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return
	frappe.throw(
		_("{0} approval of this quotation is for {1} (the creator's line in the Sales Person tree).").format(
			_(level), frappe.bold(frappe.utils.get_fullname(expected))
		),
		frappe.PermissionError,
		title=_("Not the Approver"),
	)


# --------------------------------------------------------------------------- approval levels
def level_2_limit():
	if not frappe.get_meta("Selling Settings").has_field(LEVEL_2_LIMIT_FIELD):
		return 0
	return flt(frappe.db.get_single_value("Selling Settings", LEVEL_2_LIMIT_FIELD))


def required_level(doc):
	"""Level 2 when the grand total (company currency) is above the Selling Settings limit.

	When the Level 1 approver is already the Sales Director (a Sales Manager's own quotation, or
	an engineer directly under the director), their approval covers Level 2 as well.
	"""
	limit = level_2_limit()
	if not (limit > 0 and flt(doc.base_grand_total) > limit):
		return LEVEL_1
	if doc.get("alt_level_2_user") and doc.get("alt_level_2_user") == doc.get("alt_level_1_user"):
		return LEVEL_1
	return LEVEL_2


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
		if new == APPROVED and before and doc.docstatus == 0:
			check_approved_changes(doc, before)
		if doc.docstatus == 0 and new in (None, "", DRAFT, REJECTED):
			assign_approvers(doc)
		if doc.docstatus == 0 and new != PENDING_LEVEL_2:
			doc.alt_approval_level = required_level(doc)
		return

	if old == PENDING_MANAGER:
		check_approver(doc, "alt_level_1_user", LEVEL_1)
	elif old == PENDING_LEVEL_2:
		check_approver(doc, "alt_level_2_user", LEVEL_2)

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
		for field in (
			"alt_level_1_approver",
			"alt_level_1_approved_on",
			"alt_level_2_approver",
			"alt_level_2_approved_on",
			*APPROVAL_REMARKS_FIELDS.values(),
		):
			if doc.meta.has_field(field):
				doc.set(field, None)

	if new == PENDING_MANAGER:
		# (re)submitted for approval: approvers from the creator's current place in the tree,
		# level from the current total; the last rejection stays in the timeline
		if doc.quotation_to != "Customer":
			frappe.throw(
				_("Convert Lead {0} to a Customer (Company or Individual) before the quotation goes for approval.").format(
					frappe.bold(doc.party_name)
				),
				title=_("Customer Required"),
			)
		# Local customers: GSTIN and an address with it (sales/customer.py)
		from alantech_erp.sales.customer import check_tax_details

		check_tax_details(doc.party_name, doc.get("customer_address"), _("the quotation goes for approval"))
		assign_approvers(doc)
		doc.alt_approval_level = required_level(doc)
		doc.alt_rejection_remarks = None
		doc.alt_rejected_by = None


# --------------------------------------------------------------------------- approved, not yet sent
def _price_signature(doc):
	"""What the approver approved: customer, currency, items, discounts, taxes and totals."""
	precision = 6

	def num(value):
		return round(flt(value), precision)

	return (
		doc.get("quotation_to"),
		doc.get("party_name"),
		doc.get("currency"),
		num(doc.get("conversion_rate")),
		doc.get("selling_price_list"),
		doc.get("taxes_and_charges"),
		doc.get("apply_discount_on"),
		num(doc.get("additional_discount_percentage")),
		num(doc.get("discount_amount")),
		num(doc.get("grand_total")),
		num(doc.get("base_grand_total")),
		tuple(
			(row.item_code, row.get("uom"), num(row.qty), num(row.rate), num(row.get("discount_percentage")))
			for row in doc.get("items") or []
		),
		tuple(
			(row.charge_type, row.account_head, num(row.rate), num(row.tax_amount))
			for row in doc.get("taxes") or []
		),
	)


def can_edit_approved(doc, user=None):
	user = user or frappe.session.user
	return user == doc.owner or user == "Administrator" or "System Manager" in frappe.get_roles(user)


def check_approved_changes(doc, before):
	"""Approved, not yet sent: only the owner edits it (to apply the approver's remarks), and the
	approved items, prices, discounts and taxes cannot change."""
	if not can_edit_approved(doc):
		frappe.throw(
			_("Only {0}, who made this quotation, can change it before it is sent to the client.").format(
				frappe.bold(frappe.utils.get_fullname(doc.owner))
			),
			frappe.PermissionError,
			title=_("Not Allowed"),
		)
	if _price_signature(before) != _price_signature(doc):
		frappe.throw(
			_("This quotation is {0}: its customer, items, prices, discounts and taxes are fixed. Other details (validity, terms, contact, notes) can still be changed. To change prices, ask the approver to {1} it so you can revise and resubmit.").format(
				frappe.bold(_(APPROVED)), frappe.bold(_(REJECT_ACTION))
			),
			title=_("Approved Prices Fixed"),
		)


@frappe.whitelist(methods=["POST"])
def set_approval_remarks(name, remarks=None):
	"""Called by the Approve button just before the workflow action: the approver's remarks (changes
	the salesperson must make before sending) for the level being approved."""
	from frappe.model.workflow import get_transitions

	doc = frappe.get_doc("Quotation", name)
	if not any(t.action == APPROVE_ACTION for t in get_transitions(doc)):
		frappe.throw(_("You cannot approve this quotation in its current state."), frappe.PermissionError)
	level = LEVEL_2 if doc.get("workflow_state") == PENDING_LEVEL_2 else LEVEL_1
	check_approver(doc, "alt_level_2_user" if level == LEVEL_2 else "alt_level_1_user", level)
	field = APPROVAL_REMARKS_FIELDS[level]
	if doc.meta.has_field(field):
		doc.db_set(field, cstr(remarks).strip() or None, update_modified=False)


def approval_remarks_text(doc, html=True):
	"""The approvers' remarks, Level 1 then Level 2 ("" when none)."""
	esc = frappe.utils.escape_html if html else (lambda v: v)
	parts = []
	for level, field in APPROVAL_REMARKS_FIELDS.items():
		remarks = cstr(doc.get(field)).strip()
		if remarks:
			parts.append(f"{_(level)}: {esc(remarks)}")
	return ("<br>" if html else "\n").join(parts)


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
	"""Tell the approver and the salesperson what happened; keep the Deal's amount current.

	Approvers also get the workflow's own Workflow Action entry and email.
	"""
	sync_deal(doc)
	if not workflow_is_active():
		return
	before = doc.get_doc_before_save()
	old = before.get("workflow_state") if before else None
	new = doc.get("workflow_state")
	if not old or old == new:
		return

	actor = frappe.utils.get_fullname(frappe.session.user)
	if new == PENDING_MANAGER:
		_notify(
			doc.get("alt_level_1_user"),
			doc,
			_("Quotation {0} from {1} is waiting for your approval").format(doc.name, actor),
			_("{0} for {1}: {2}").format(doc.name, doc.customer_name or doc.party_name, doc.get_formatted("grand_total")),
		)
	elif new == REJECTED:
		doc.add_comment("Comment", _("Rejected: {0}").format(frappe.utils.escape_html(doc.alt_rejection_remarks)))
		_notify(
			doc.owner,
			doc,
			_("Quotation {0} was rejected by {1}").format(doc.name, actor),
			_("Reason: {0}<br><br>Make the changes and use <b>Resubmit</b> to send it for approval again.").format(
				frappe.utils.escape_html(doc.alt_rejection_remarks)
			),
		)
	elif new == PENDING_LEVEL_2:
		remarks = _remarks_comment(doc, LEVEL_1, actor)
		_notify(
			doc.owner,
			doc,
			_("Quotation {0} approved by {1} (Level 1)").format(doc.name, actor),
			_("It is above the Level 2 limit and is now waiting for the Sales Director.") + remarks,
		)
		_notify(
			doc.get("alt_level_2_user"),
			doc,
			_("Quotation {0} is waiting for your Level 2 approval").format(doc.name),
			_("Approved at Level 1 by {0}. {1} for {2}: {3}").format(
				actor, doc.name, doc.customer_name or doc.party_name, doc.get_formatted("grand_total")
			)
			+ remarks,
		)
	elif new == APPROVED:
		level = LEVEL_2 if old == PENDING_LEVEL_2 else LEVEL_1
		_remarks_comment(doc, level, actor)
		remarks = approval_remarks_text(doc)
		_notify(
			doc.owner,
			doc,
			_("Quotation {0} approved by {1}").format(doc.name, actor),
			(
				_("Approver remarks:<br>{0}<br><br>Make these changes (items and prices are fixed), then use <b>Send to Client</b> once it has gone out.").format(remarks)
				if remarks
				else _("It is ready to send to the client. Use <b>Send to Client</b> once it has gone out.")
			),
		)


def _remarks_comment(doc, level, actor):
	"""Timeline comment with the approver's remarks of `level`; returns them for the notification."""
	remarks = cstr(doc.get(APPROVAL_REMARKS_FIELDS[level])).strip()
	if not remarks:
		return ""
	text = frappe.utils.escape_html(remarks)
	doc.add_comment("Comment", _("Approved ({0}) by {1} with remarks: {2}").format(_(level), actor, text))
	return "<br><br>" + _("Remarks: {0}").format(text)


def _notify(user, doc, subject, message):
	if not user or user in ("Administrator", "Guest") or user == frappe.session.user:
		return
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	enqueue_create_notification(
		user,
		{
			"type": "Alert",
			"document_type": doc.doctype,
			"document_name": doc.name,
			"subject": subject,
			"email_content": message,
			"from_user": frappe.session.user,
		},
	)
	email = frappe.db.get_value("User", {"name": user, "enabled": 1}, "email")
	if email:
		frappe.sendmail(
			recipients=[email],
			subject=frappe.utils.strip_html(subject),
			message=f"<p>{subject}</p><p>{message}</p><p>{get_link_to_form(doc.doctype, doc.name)}</p>",
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)


# --------------------------------------------------------------------------- Deal (Opportunity)
def keep_deal_on_revision(doc):
	"""An amended (revised) quotation stays on the Deal of the version it replaces."""
	if doc.docstatus == 0 and not doc.opportunity and doc.amended_from:
		doc.opportunity = frappe.db.get_value("Quotation", doc.amended_from, "opportunity")


def sync_deal(doc):
	"""Deal amount = value of its current quotation (a revised quotation updates it), and its
	Sales Stage follows the quotation's state (sales/deal.py sales_stage_for)."""
	if not doc.opportunity or not frappe.get_meta("Opportunity").has_field("alt_quotation"):
		return
	from alantech_erp.sales.deal import sales_stage_for, stage_exists

	deal = frappe.db.get_value(
		"Opportunity",
		doc.opportunity,
		["opportunity_amount", "alt_quotation", "status", "sales_stage"],
		as_dict=True,
	)
	if not deal or deal.status == "Closed":
		return

	values = {}
	stage = sales_stage_for(doc)
	if stage_exists(stage) and deal.sales_stage != stage:
		values["sales_stage"] = stage

	# a cancelled version (revision requested) or a lost deal only moves the stage
	if doc.docstatus != 2 and deal.status != "Lost":
		if flt(deal.opportunity_amount) != flt(doc.grand_total):
			values["opportunity_amount"] = doc.grand_total
			values["base_opportunity_amount"] = doc.base_grand_total
		if deal.alt_quotation != doc.name:
			values["alt_quotation"] = doc.name
	elif deal.status == "Lost" and stage != STAGE_LOST:
		values.pop("sales_stage", None)
	if values:
		frappe.db.set_value("Opportunity", doc.opportunity, values)


def validate_estimation(doc):
	"""The Estimation is optional; a linked one must be submitted and for the same Customer."""
	if doc.docstatus != 0 or not doc.get("alt_estimation"):
		return
	est = frappe.db.get_value("Estimation", doc.alt_estimation, ["docstatus", "customer"], as_dict=True)
	if not est or est.docstatus != 1:
		frappe.throw(
			_("Estimation {0} must be submitted before it can be quoted.").format(
				get_link_to_form("Estimation", doc.alt_estimation)
			),
			title=_("Estimation Not Submitted"),
		)
	if doc.quotation_to != "Customer" or doc.party_name != est.customer:
		frappe.throw(
			_("Estimation {0} is for Customer {1}, not {2}.").format(
				frappe.bold(doc.alt_estimation), frappe.bold(est.customer), frappe.bold(doc.party_name)
			),
			title=_("Wrong Estimation"),
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

	offer = frappe.db.get_value("Technical Offer", name, ["estimation", "customer"], as_dict=True) or frappe._dict()
	if offer.customer and doc.quotation_to == "Customer" and offer.customer != doc.party_name:
		frappe.throw(
			_("Technical Offer {0} is for Customer {1}, not {2}.").format(
				frappe.bold(name), frappe.bold(offer.customer), frappe.bold(doc.party_name)
			),
			title=_("Wrong Technical Offer"),
		)
	offer_estimation = offer.estimation
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
			_("Submit Technical Offer {0} before this quotation is sent to the client.").format(
				get_link_to_form("Technical Offer", doc.alt_technical_offer)
			),
			title=_("Technical Offer Not Final"),
		)
