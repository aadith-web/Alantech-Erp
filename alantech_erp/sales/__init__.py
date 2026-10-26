"""Sales flow: Lead -> Deal (Opportunity) -> Estimation -> Quotation with two approval levels -> Sales Order.

Level 1: the Sales Manager approves the Quotation before it goes to the client.
Level 2: the client accepts it (recorded by the salesperson). A revision cancels the Quotation;
the amended version goes back to Level 1 and keeps the same Estimation.
"""

WORKFLOW_NAME = "ALT Quotation Approval"

# Workflow states
DRAFT = "Draft"
PENDING_MANAGER = "Pending Manager Approval"
REJECTED = "Rejected"
APPROVED = "Approved"
SENT_TO_CLIENT = "Sent to Client"
CLIENT_APPROVED = "Client Approved"
REVISION_REQUESTED = "Revision Requested"
LOST = "Lost"

# Submitted states in which the quoted prices are fixed
LOCKED_STATES = (APPROVED, SENT_TO_CLIENT, CLIENT_APPROVED)


def workflow_is_active():
	from frappe.model.workflow import get_workflow_name

	return get_workflow_name("Quotation") == WORKFLOW_NAME
