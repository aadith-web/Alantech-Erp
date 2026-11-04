"""Sales flow setup: Quotation approval workflow and the CRM fields (Alantech CRM requirements).

Lead -> Customer (Company / Individual) -> Estimation (optional, Sales Manager) -> Technical Offer
-> Quotation
  Level 1: the creator's Sales Manager (Sales Person tree) approves every quotation before it is sent
  Level 2: above the limit in Selling Settings, the Sales Director above the creator also approves
  Reject (either level) needs remarks; the salesperson resubmits and it starts again at Level 1
  Client: accepts / asks for revision / rejects (recorded by the salesperson)
-> Sales Order (only from a Client Approved quotation, with the client's LPO)
Deal: optional, created from the Quotation (Create Deal); its amount and Sales Stage follow the
quotation (the Alantech sales stages replace ERPNext's pre-quote ones such as Prospecting).
Prospect: not used (sales/prospect.py); left to System Managers only.
Customer: Tax Type Local (GSTIN + GST address mandatory) or Overseas (sales/customer.py); Mobile No
and Email ID mandatory and unique, Company / Individual rules (CRM-F04, sales/customer_unique.py).

Runs on every `bench migrate` (see after_migrate in hooks.py). Safe to re-run: the workflow is
created once and then left alone, so changes made in the Workflow form are kept. A workflow
created by an older version of this file (without Level 2, or approving by role only instead of
by the sales hierarchy) is upgraded once.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cstr

from alantech_erp.sales import (
	APPROVED,
	CLIENT_APPROVED,
	DRAFT,
	LEVEL_1,
	LEVEL_2,
	LEVEL_2_LIMIT_FIELD,
	LEVEL_2_ROLE,
	LOST,
	PENDING_LEVEL_2,
	PENDING_MANAGER,
	REJECT_ACTION,
	REJECTED,
	REVISION_REQUESTED,
	SALES_MANAGER,
	SALES_STAGES,
	SALES_USER,
	SENT_TO_CLIENT,
	STAGE_DRAFT,
	TAX_LOCAL,
	TAX_OVERSEAS,
	TAX_TYPE_FIELD,
	WORKFLOW_NAME,
)

_APPROVAL_FIELD = {"read_only": 1, "no_copy": 1, "allow_on_submit": 1}

CUSTOM_FIELDS = {
	"Quotation": [
		{
			"fieldname": "alt_estimation",
			"label": "Estimation",
			"fieldtype": "Link",
			"options": "Estimation",
			"insert_after": "opportunity",
			"read_only_depends_on": "eval:doc.docstatus > 0",
			"search_index": 1,
		},
		{
			"fieldname": "alt_technical_offer",
			"label": "Technical Offer",
			"fieldtype": "Link",
			"options": "Technical Offer",
			"insert_after": "alt_estimation",
			"read_only_depends_on": "eval:doc.docstatus > 0",
			"description": "Printed with the quotation (print format Alantech Proposal)",
		},
		# Approval trail (set by alantech_erp.sales.quotation, never typed in)
		{
			"fieldname": "alt_approval_section",
			"label": "Approval",
			"fieldtype": "Section Break",
			"insert_after": "utm_content",
			"collapsible": 1,
			"collapsible_depends_on": "eval:doc.alt_rejection_remarks",
		},
		{
			"fieldname": "alt_approval_level",
			"label": "Approval Required",
			"fieldtype": "Select",
			"options": f"\n{LEVEL_1}\n{LEVEL_2}",
			"insert_after": "alt_approval_section",
			"in_standard_filter": 1,
			"description": "Level 2 when the grand total (company currency) is above the limit in Selling Settings",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_rejection_remarks",
			"label": "Rejection Remarks",
			"fieldtype": "Small Text",
			"insert_after": "alt_approval_level",
			"depends_on": "eval:doc.alt_rejection_remarks",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_rejected_by",
			"label": "Rejected By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "alt_rejection_remarks",
			"depends_on": "eval:doc.alt_rejected_by",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_sales_person",
			"label": "Sales Person (Creator)",
			"fieldtype": "Link",
			"options": "Sales Person",
			"insert_after": "alt_rejected_by",
			"in_standard_filter": 1,
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_level_1_user",
			"label": "Level 1 Approver (Sales Manager)",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "alt_sales_person",
			"description": "From the Sales Person tree; empty: any Sales Manager",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_level_2_user",
			"label": "Level 2 Approver (Sales Director)",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "alt_level_1_user",
			"depends_on": f"eval:doc.alt_approval_level == '{LEVEL_2}'",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_approval_column",
			"fieldtype": "Column Break",
			"insert_after": "alt_level_2_user",
		},
		{
			"fieldname": "alt_level_1_approver",
			"label": "Level 1 Approved By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "alt_approval_column",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_level_1_approved_on",
			"label": "Level 1 Approved On",
			"fieldtype": "Datetime",
			"insert_after": "alt_level_1_approver",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_level_2_approver",
			"label": "Level 2 Approved By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "alt_level_1_approved_on",
			"depends_on": f"eval:doc.alt_approval_level == '{LEVEL_2}'",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_level_2_approved_on",
			"label": "Level 2 Approved On",
			"fieldtype": "Datetime",
			"insert_after": "alt_level_2_approver",
			"depends_on": f"eval:doc.alt_approval_level == '{LEVEL_2}'",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_level_1_remarks",
			"label": "Level 1 Approval Remarks",
			"fieldtype": "Small Text",
			"insert_after": "alt_level_2_approved_on",
			"depends_on": "eval:doc.alt_level_1_remarks",
			"description": "Changes the Sales Manager asked for when approving",
			**_APPROVAL_FIELD,
		},
		{
			"fieldname": "alt_level_2_remarks",
			"label": "Level 2 Approval Remarks",
			"fieldtype": "Small Text",
			"insert_after": "alt_level_1_remarks",
			"depends_on": "eval:doc.alt_level_2_remarks",
			"description": "Changes the Sales Director asked for when approving",
			**_APPROVAL_FIELD,
		},
	],
	"Opportunity": [
		{
			"fieldname": "alt_quotation",
			"label": "Quotation",
			"fieldtype": "Link",
			"options": "Quotation",
			"insert_after": "expected_closing",
			"read_only": 1,
			"no_copy": 1,
			"description": "The Deal was created from this quotation; its amount follows the quotation",
		},
	],
	"Customer": [
		{
			"fieldname": "alt_customer_stage",
			"label": "Customer Stage",
			"fieldtype": "Select",
			"options": "Account\nCustomer",
			"default": "Account",
			"insert_after": "customer_type",
			"read_only": 1,
			"no_copy": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"description": "Account until the first submitted Sales Order, then Customer",
		},
		{
			"fieldname": TAX_TYPE_FIELD,
			"label": "Tax Type",
			"fieldtype": "Select",
			"options": f"\n{TAX_LOCAL}\n{TAX_OVERSEAS}",
			"insert_after": "alt_customer_stage",
			"reqd": 1,
			"allow_in_quick_entry": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"description": (
				"Local: GSTIN is mandatory and the customer needs an address with that GSTIN. "
				"Overseas: GST Category Overseas, no GSTIN."
			),
		},
	],
	"Sales Order": [
		{
			"fieldname": "alt_lpo_attachment",
			"label": "LPO Attachment",
			"fieldtype": "Attach",
			"insert_after": "po_date",
			"allow_on_submit": 0,
			"description": "The client's LPO; LPO number, date and attachment are needed to confirm the order",
		},
		{
			"fieldname": "alt_order_category",
			"label": "Order For",
			"fieldtype": "Select",
			"options": "\nProject\nIndividual Item Order",
			"insert_after": "alt_lpo_attachment",
			"in_standard_filter": 1,
		},
	],
	"Selling Settings": [
		{
			"fieldname": "alt_quotation_approval_section",
			"label": "Quotation Approval",
			"fieldtype": "Section Break",
			"insert_after": "allow_zero_qty_in_sales_order",
		},
		{
			"fieldname": LEVEL_2_LIMIT_FIELD,
			"label": "Quotation Level 2 Approval Above",
			"fieldtype": "Currency",
			"insert_after": "alt_quotation_approval_section",
			"non_negative": 1,
			"description": (
				"Every quotation is approved by a Sales Manager. Quotations whose grand total "
				"(company currency) is above this amount also need a Quotation Level 2 Approver. "
				"Leave 0 for Sales Manager approval only."
			),
		},
	],
}

# state -> Workflow State style
STATE_STYLES = {
	DRAFT: "",
	PENDING_MANAGER: "Warning",
	PENDING_LEVEL_2: "Warning",
	REJECTED: "Danger",
	APPROVED: "Primary",
	SENT_TO_CLIENT: "Info",
	CLIENT_APPROVED: "Success",
	REVISION_REQUESTED: "Warning",
	LOST: "Danger",
}

# (state, doc_status, role that can edit in this state)
STATES = [
	(DRAFT, "0", SALES_USER),
	(PENDING_MANAGER, "0", SALES_MANAGER),
	(PENDING_LEVEL_2, "0", LEVEL_2_ROLE),
	(REJECTED, "0", SALES_USER),
	# Approved stays a draft so the owner can apply the approver's remarks (prices fixed,
	# sales/quotation.py); Send to Client submits it
	(APPROVED, "0", SALES_USER),
	(SENT_TO_CLIENT, "1", SALES_USER),
	(CLIENT_APPROVED, "1", SALES_USER),
	(REVISION_REQUESTED, "2", SALES_USER),
	(LOST, "1", SALES_USER),
]

# Approvers from the Sales Person tree (sales/hierarchy.py); empty = anyone with the role.
# Frappe also evaluates these as the user who just acted, to create the next Workflow Actions
# (the creator on submit, the Level 1 approver on Level 1 approval), so that user passes too;
# sales/quotation.py check_approver stops anyone else server-side.
LEVEL_1_USER = (
	"(not doc.alt_level_1_user or frappe.session.user in (doc.alt_level_1_user, doc.owner)"
	")"
)
LEVEL_2_USER = (
	"(not doc.alt_level_2_user or frappe.session.user in (doc.alt_level_2_user, doc.alt_level_1_user)"
	")"
)
NEEDS_LEVEL_2 = f"doc.alt_approval_level == '{LEVEL_2}' and {LEVEL_1_USER}"
LEVEL_1_ONLY = f"doc.alt_approval_level != '{LEVEL_2}' and {LEVEL_1_USER}"

# (from state, action, to state, allowed role, allow self approval, condition)
TRANSITIONS = [
	(DRAFT, "Submit for Approval", PENDING_MANAGER, SALES_USER, 1, None),
	# Level 1: the creator's Sales Manager (never the person who created the quotation)
	(PENDING_MANAGER, "Approve", APPROVED, SALES_MANAGER, 0, LEVEL_1_ONLY),
	(PENDING_MANAGER, "Approve", PENDING_LEVEL_2, SALES_MANAGER, 0, NEEDS_LEVEL_2),
	(PENDING_MANAGER, REJECT_ACTION, REJECTED, SALES_MANAGER, 0, LEVEL_1_USER),
	# Level 2: above the Selling Settings limit, the Sales Director
	(PENDING_LEVEL_2, "Approve", APPROVED, LEVEL_2_ROLE, 0, LEVEL_2_USER),
	(PENDING_LEVEL_2, REJECT_ACTION, REJECTED, LEVEL_2_ROLE, 0, LEVEL_2_USER),
	(REJECTED, "Resubmit", PENDING_MANAGER, SALES_USER, 1, None),
	(APPROVED, "Send to Client", SENT_TO_CLIENT, SALES_USER, 1, None),
	# Client decision, recorded by the salesperson
	(SENT_TO_CLIENT, "Client Accepted", CLIENT_APPROVED, SALES_USER, 1, None),
	(SENT_TO_CLIENT, "Client Requested Revision", REVISION_REQUESTED, SALES_USER, 1, None),
	(SENT_TO_CLIENT, "Client Rejected", LOST, SALES_USER, 1, None),
]


def execute():
	if not frappe.db.exists("DocType", "Quotation"):
		return  # ERPNext not installed on this site

	create_custom_fields(CUSTOM_FIELDS, update=True)
	_hide_unused_fields()
	_set_customer_stages()
	_set_customer_tax_types()
	_customer_form_rules()
	_create_sales_stages()
	_deal_stage_follows_quotation()
	_retire_prospect()
	_create_role()
	_create_workflow_states()
	_create_workflow_actions()
	_create_workflow()
	frappe.db.commit()


def _create_role():
	"""Level 2 role; org_structure gives it to the ALT Sales Head and ALT Managing Director profiles."""
	if not frappe.db.exists("Role", LEVEL_2_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": LEVEL_2_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)


def _create_workflow_states():
	for state, style in STATE_STYLES.items():
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": style}
			).insert(ignore_permissions=True)


def _create_workflow_actions():
	for action in dict.fromkeys(t[1] for t in TRANSITIONS):
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(
				{"doctype": "Workflow Action Master", "workflow_action_name": action}
			).insert(ignore_permissions=True)


def _approved_stays_draft(workflow):
	"""Workflows made before CRM-F07 approval remarks submitted the quotation on Approve; now Approved
	is a draft the owner can edit and Send to Client submits it. Changed once (True: changed)."""
	changed = False
	for row in workflow.states:
		if row.state == APPROVED and cstr(row.doc_status) != "0":
			row.doc_status = "0"
			row.allow_edit = SALES_USER
			changed = True
	return changed


def _create_workflow():
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)
		if any("doc.owner" in (row.condition or "") for row in workflow.transitions):
			# current version: leave any changes made in the Workflow form alone, except this one
			if _approved_stays_draft(workflow):
				workflow.save(ignore_permissions=True)
				print(f"{WORKFLOW_NAME}: Approved is now editable by the owner; Send to Client submits the quotation.")
			return
		# created before Level 2 / hierarchy approvers existed: rebuild the states and transitions once
		_set_states_and_transitions(workflow)
		workflow.save(ignore_permissions=True)
		print(f"{WORKFLOW_NAME}: approvals now follow the Sales Person tree (Level 1 Sales Manager, Level 2 Sales Director).")
		return

	if frappe.db.exists("Workflow", {"document_type": "Quotation", "is_active": 1}):
		print(f"Skipped {WORKFLOW_NAME}: another active Quotation workflow exists.")
		return

	workflow = frappe.new_doc("Workflow")
	workflow.update(
		{
			"workflow_name": WORKFLOW_NAME,
			"document_type": "Quotation",
			"workflow_state_field": "workflow_state",
			"is_active": 1,
			# Workflow Action emails to the approvers of each pending state
			"send_email_alert": 1,
		}
	)
	_set_states_and_transitions(workflow)
	workflow.insert(ignore_permissions=True)

	# Inserting the workflow puts every existing submitted quotation in "Approved".
	# Move the ones already ordered or lost to the matching state.
	for status, state in (("Ordered", CLIENT_APPROVED), ("Partially Ordered", CLIENT_APPROVED), ("Lost", LOST)):
		frappe.db.set_value(
			"Quotation",
			{"docstatus": 1, "status": status},
			"workflow_state",
			state,
			update_modified=False,
		)


def _set_states_and_transitions(workflow):
	workflow.set("states", [])
	workflow.set("transitions", [])
	for state, doc_status, role in STATES:
		workflow.append("states", {"state": state, "doc_status": doc_status, "allow_edit": role})
	for state, action, next_state, role, self_approval, condition in TRANSITIONS:
		workflow.append(
			"transitions",
			{
				"state": state,
				"action": action,
				"next_state": next_state,
				"allowed": role,
				"allow_self_approval": self_approval,
				"condition": condition,
			},
		)


# Quotation fields Alantech did not use in Zoho CRM (requirements: coupon, incoterm, shipping rule, UTM...)
HIDDEN_QUOTATION_FIELDS = ("coupon_code", "incoterm", "named_place", "shipping_rule", "utm_medium", "utm_content")


def _hide_unused_fields():
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	meta = frappe.get_meta("Quotation")
	for field in HIDDEN_QUOTATION_FIELDS:
		df = meta.get_field(field)
		if df and not df.hidden and not df.reqd:
			make_property_setter("Quotation", field, "hidden", 1, "Check", validate_fields_for_doctype=False)


def _set_customer_stages():
	"""Customers with a submitted Sales Order are at stage Customer; the rest are Accounts."""
	if not frappe.db.has_column("Customer", "alt_customer_stage"):
		return
	ordered = frappe.get_all("Sales Order", filters={"docstatus": 1}, pluck="customer", distinct=True)
	if ordered:
		frappe.db.set_value(
			"Customer",
			{"name": ["in", ordered], "alt_customer_stage": ["!=", "Customer"]},
			"alt_customer_stage",
			"Customer",
			update_modified=False,
		)
	frappe.db.set_value(
		"Customer",
		{"alt_customer_stage": ["is", "not set"]},
		"alt_customer_stage",
		"Account",
		update_modified=False,
	)


# --------------------------------------------------------------------------- Deal sales stages
def _create_sales_stages():
	for stage in SALES_STAGES:
		if not frappe.db.exists("Sales Stage", stage):
			frappe.get_doc({"doctype": "Sales Stage", "stage_name": stage}).insert(ignore_permissions=True)


def _deal_stage_follows_quotation():
	"""Opportunity.sales_stage: Alantech default (not Prospecting), read only on a Deal from a
	quotation, and every such Deal moved to the stage of its quotation."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	from alantech_erp.sales.deal import sales_stage_for

	meta = frappe.get_meta("Opportunity")
	if not meta.has_field("sales_stage"):
		return
	df = meta.get_field("sales_stage")
	for prop, value, prop_type in (
		("default", STAGE_DRAFT, "Data"),
		("read_only_depends_on", "eval:doc.alt_quotation", "Code"),
		("description", "Follows the quotation (approval, client, revision)", "Small Text"),
	):
		if (df.get(prop) or "") != value:
			make_property_setter("Opportunity", "sales_stage", prop, value, prop_type, validate_fields_for_doctype=False)

	if not meta.has_field("alt_quotation"):
		return
	deals = frappe.get_all(
		"Opportunity",
		filters={"alt_quotation": ["is", "set"], "status": ["!=", "Closed"]},
		fields=["name", "alt_quotation", "sales_stage"],
	)
	for deal in deals:
		if not frappe.db.exists("Quotation", deal.alt_quotation):
			continue
		stage = sales_stage_for(frappe.get_doc("Quotation", deal.alt_quotation))
		if stage and stage != deal.sales_stage:
			frappe.db.set_value("Opportunity", deal.name, "sales_stage", stage, update_modified=False)


# --------------------------------------------------------------------------- Prospect (not used)
def _retire_prospect():
	"""Hide the Prospect flow: Customer "From Prospect" hidden, Prospect left to System Managers.

	Prospect permissions become a single System Manager row (Custom DocPerm) the first time, so it
	drops out of the CRM menus and search for everyone else; Role Permissions Manager > Reset to
	Default brings the standard ones back.
	"""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	df = frappe.get_meta("Customer").get_field("prospect_name")
	if df and not df.hidden:
		make_property_setter("Customer", "prospect_name", "hidden", 1, "Check", validate_fields_for_doctype=False)

	if not frappe.db.exists("DocType", "Prospect") or frappe.db.exists("Custom DocPerm", {"parent": "Prospect"}):
		return
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": "Prospect",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": "System Manager",
			"permlevel": 0,
			"read": 1,
			"write": 1,
			"delete": 1,
			"report": 1,
			"export": 1,
			"print": 1,
			"email": 1,
			"share": 1,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Prospect")


# --------------------------------------------------------------------------- Customer rules (CRM-F04)
_NOT_INDIVIDUAL = "eval:doc.customer_type!='Individual'"
_NEW = "eval:doc.__islocal"
# (field, property, value, property type): rules also checked server side (sales/customer*.py)
CUSTOMER_PROPERTIES = [
	# Mobile No / Email ID: entered on a new customer (the Primary Contact is made from them),
	# then shown from the Primary Contact as before
	("mobile_no", "fieldtype", "Data", "Select"),
	# plain Data: Frappe's Phone / Email checks would block saving customers whose old contact
	# values are irregular; new and changed values are checked in sales/customer_unique.py
	("mobile_no", "options", "", "Text"),
	("mobile_no", "read_only_depends_on", "eval:!doc.__islocal", "Code"),
	("mobile_no", "mandatory_depends_on", _NEW, "Code"),
	("mobile_no", "description", "With country code, e.g. +91 98470 12345. Unique: one customer per mobile number.", "Small Text"),
	("email_id", "fieldtype", "Data", "Select"),
	("email_id", "options", "", "Text"),
	("email_id", "read_only_depends_on", "eval:!doc.__islocal", "Code"),
	("email_id", "mandatory_depends_on", _NEW, "Code"),
	("email_id", "description", "Unique: one customer per email.", "Small Text"),
	# Company / Partnership: Territory and Industry mandatory; Individual: no Industry
	("territory", "mandatory_depends_on", _NOT_INDIVIDUAL, "Code"),
	("territory", "allow_in_quick_entry", "1", "Check"),
	("industry", "mandatory_depends_on", _NOT_INDIVIDUAL, "Code"),
	("industry", "depends_on", _NOT_INDIVIDUAL, "Code"),
	("industry", "allow_in_quick_entry", "1", "Check"),
	# Overseas: Default Currency mandatory
	("default_currency", "mandatory_depends_on", "eval:doc.alt_tax_type=='Overseas'", "Code"),
	("default_currency", "depends_on", "eval:doc.alt_tax_type=='Overseas' || doc.default_currency", "Code"),
	("default_currency", "allow_in_quick_entry", "1", "Check"),
]


def _customer_form_rules():
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	from alantech_erp.sales.customer_unique import setup_keys

	meta = frappe.get_meta("Customer")
	for field, prop, value, prop_type in CUSTOMER_PROPERTIES:
		df = meta.get_field(field)
		if df and cstr(df.get(prop)) != value:
			make_property_setter("Customer", field, prop, value, prop_type, validate_fields_for_doctype=False)
	frappe.clear_cache(doctype="Customer")
	setup_keys()


# --------------------------------------------------------------------------- Customer tax type
def _set_customer_tax_types():
	"""Existing customers without a Tax Type: Overseas from GST Category, Local from a GSTIN."""
	from alantech_erp.sales.customer import tax_type_from_gst

	if not frappe.db.has_column("Customer", TAX_TYPE_FIELD) or not frappe.db.has_column("Customer", "gst_category"):
		return
	for row in frappe.get_all(
		"Customer",
		filters={TAX_TYPE_FIELD: ["is", "not set"]},
		fields=["name", "gst_category", "gstin"],
	):
		tax_type = tax_type_from_gst(row.gst_category, row.gstin)
		if tax_type:
			frappe.db.set_value("Customer", row.name, TAX_TYPE_FIELD, tax_type, update_modified=False)
