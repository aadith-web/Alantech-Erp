"""Quotation approval workflow and Quotation fields for the sales flow.

Lead -> Deal (Opportunity) -> Estimation (Sales Manager) -> Quotation
  Level 1: Sales Manager approves the quotation before it is sent
  Level 2: client accepts / asks for revision / rejects (recorded by the salesperson)
-> Sales Order (only from a Client Approved quotation)

Runs on every `bench migrate` (see after_migrate in hooks.py). Safe to re-run: the workflow is
created once and then left alone, so changes made in the Workflow form are kept.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alantech_erp.sales import (
	APPROVED,
	CLIENT_APPROVED,
	DRAFT,
	LOST,
	PENDING_MANAGER,
	REJECTED,
	REVISION_REQUESTED,
	SENT_TO_CLIENT,
	WORKFLOW_NAME,
)

SALES_USER = "Sales User"
SALES_MANAGER = "Sales Manager"

QUOTATION_FIELDS = {
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
	]
}

# state -> Workflow State style
STATE_STYLES = {
	DRAFT: "",
	PENDING_MANAGER: "Warning",
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
	(REJECTED, "0", SALES_USER),
	(APPROVED, "1", SALES_USER),
	(SENT_TO_CLIENT, "1", SALES_USER),
	(CLIENT_APPROVED, "1", SALES_USER),
	(REVISION_REQUESTED, "2", SALES_USER),
	(LOST, "1", SALES_USER),
]

# (from state, action, to state, allowed role, allow self approval)
TRANSITIONS = [
	(DRAFT, "Submit for Approval", PENDING_MANAGER, SALES_USER, 1),
	# Level 1: manager approval (the person who created the quotation cannot approve it)
	(PENDING_MANAGER, "Approve", APPROVED, SALES_MANAGER, 0),
	(PENDING_MANAGER, "Reject", REJECTED, SALES_MANAGER, 1),
	(REJECTED, "Resubmit", PENDING_MANAGER, SALES_USER, 1),
	(APPROVED, "Send to Client", SENT_TO_CLIENT, SALES_USER, 1),
	# Level 2: client decision, recorded by the salesperson
	(SENT_TO_CLIENT, "Client Accepted", CLIENT_APPROVED, SALES_USER, 1),
	(SENT_TO_CLIENT, "Client Requested Revision", REVISION_REQUESTED, SALES_USER, 1),
	(SENT_TO_CLIENT, "Client Rejected", LOST, SALES_USER, 1),
]


def execute():
	if not frappe.db.exists("DocType", "Quotation"):
		return  # ERPNext not installed on this site

	create_custom_fields(QUOTATION_FIELDS, update=True)
	_create_workflow_states()
	_create_workflow_actions()
	_create_workflow()
	frappe.db.commit()


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
			"send_email_alert": 1,
		}
	)
	for state, doc_status, role in STATES:
		workflow.append("states", {"state": state, "doc_status": doc_status, "allow_edit": role})
	for state, action, next_state, role, self_approval in TRANSITIONS:
		workflow.append(
			"transitions",
			{
				"state": state,
				"action": action,
				"next_state": next_state,
				"allowed": role,
				"allow_self_approval": self_approval,
			},
		)
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
