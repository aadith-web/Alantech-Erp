"""Sales flow: Lead -> Deal (Opportunity) -> Estimation -> Quotation approval -> client -> Sales Order.

Internal approval (CRM-F07), value based:
  Level 1: a Sales Manager approves every quotation before it goes to the client.
  Level 2: quotations above the limit in Selling Settings ("Quotation Level 2 Approval Above",
           company currency, grand total) also need a "Quotation Level 2 Approver" (Sales Head / MD).
           With no limit set, the Sales Manager's approval is final.
  Either level can reject with remarks; the salesperson corrects and resubmits (back to Level 1).

Client decision: the salesperson records Client Accepted / Requested Revision / Rejected.
A revision cancels the Quotation; the amended version goes back to Level 1 and keeps the same Estimation.
"""

WORKFLOW_NAME = "ALT Quotation Approval"

# Roles
SALES_USER = "Sales User"
SALES_MANAGER = "Sales Manager"
LEVEL_2_ROLE = "Quotation Level 2 Approver"

# Approval levels (Quotation.alt_approval_level)
LEVEL_1 = "Level 1"
LEVEL_2 = "Level 2"

# Selling Settings field holding the Level 2 limit
LEVEL_2_LIMIT_FIELD = "alt_quotation_level_2_limit"

# Workflow states
DRAFT = "Draft"
PENDING_MANAGER = "Pending Manager Approval"
PENDING_LEVEL_2 = "Pending Level 2 Approval"
REJECTED = "Rejected"
APPROVED = "Approved"
SENT_TO_CLIENT = "Sent to Client"
CLIENT_APPROVED = "Client Approved"
REVISION_REQUESTED = "Revision Requested"
LOST = "Lost"

# Submitted states in which the quoted prices are fixed
LOCKED_STATES = (APPROVED, SENT_TO_CLIENT, CLIENT_APPROVED)

# Workflow action that needs remarks
REJECT_ACTION = "Reject"


def workflow_is_active():
	from frappe.model.workflow import get_workflow_name

	return get_workflow_name("Quotation") == WORKFLOW_NAME
