"""Quotation approval workflow and Quotation fields for the sales flow (CRM-F07).

Lead -> Deal (Opportunity) -> Estimation (Sales Manager) -> Quotation
  Level 1: Sales Manager approves every quotation before it is sent
  Level 2: above the limit in Selling Settings, a Quotation Level 2 Approver (Sales Head / MD) also approves
  Reject (either level) needs remarks; the salesperson resubmits and it starts again at Level 1
  Client: accepts / asks for revision / rejects (recorded by the salesperson)
-> Sales Order (only from a Client Approved quotation)

Runs on every `bench migrate` (see after_migrate in hooks.py). Safe to re-run: the workflow is
created once and then left alone, so changes made in the Workflow form are kept. A workflow
created by an older version of this file (without the Level 2 state) is upgraded once.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

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
	SALES_USER,
	SENT_TO_CLIENT,
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
			"fieldname": "alt_approval_column",
			"fieldtype": "Column Break",
			"insert_after": "alt_rejected_by",
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
	(APPROVED, "1", SALES_USER),
	(SENT_TO_CLIENT, "1", SALES_USER),
	(CLIENT_APPROVED, "1", SALES_USER),
	(REVISION_REQUESTED, "2", SALES_USER),
	(LOST, "1", SALES_USER),
]

NEEDS_LEVEL_2 = f"doc.alt_approval_level == '{LEVEL_2}'"
LEVEL_1_ONLY = f"doc.alt_approval_level != '{LEVEL_2}'"

# (from state, action, to state, allowed role, allow self approval, condition)
TRANSITIONS = [
	(DRAFT, "Submit for Approval", PENDING_MANAGER, SALES_USER, 1, None),
	# Level 1: Sales Manager (never the person who created the quotation)
	(PENDING_MANAGER, "Approve", APPROVED, SALES_MANAGER, 0, LEVEL_1_ONLY),
	(PENDING_MANAGER, "Approve", PENDING_LEVEL_2, SALES_MANAGER, 0, NEEDS_LEVEL_2),
	(PENDING_MANAGER, REJECT_ACTION, REJECTED, SALES_MANAGER, 1, None),
	# Level 2: above the Selling Settings limit
	(PENDING_LEVEL_2, "Approve", APPROVED, LEVEL_2_ROLE, 0, None),
	(PENDING_LEVEL_2, REJECT_ACTION, REJECTED, LEVEL_2_ROLE, 1, None),
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


def _create_workflow():
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", WORKFLOW_NAME)
		if any(row.state == PENDING_LEVEL_2 for row in workflow.states):
			return  # current version: leave any changes made in the Workflow form alone
		# created before Level 2 existed: rebuild the states and transitions once
		_set_states_and_transitions(workflow)
		workflow.save(ignore_permissions=True)
		print(f"{WORKFLOW_NAME}: added Level 2 approval and reject remarks.")
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
