"""Sales flow (Alantech CRM workflow deck, requirements of 29-Oct-2026):

Lead -> Customer (Company = Zoho Account, Individual = Zoho Contact) -> Estimation (optional,
prepared by the Sales Manager) -> Technical Offer -> Quotation -> approval -> client -> Sales Order
(with the client's LPO). The Deal is optional: the Quotation's Create Deal button makes it.

Internal approval, value based and routed up the sales hierarchy (sales/hierarchy.py):
  Level 1: the creator's own Sales Manager (Sales Person tree) approves every quotation before it
           goes to the client. Nobody in the tree above the creator: any Sales Manager.
  Level 2: quotations above the limit in Selling Settings ("Quotation Level 2 Approval Above",
           company currency, grand total) also need the Sales Director above the creator
           (role "Quotation Level 2 Approver"). With no limit set, Level 1 is final.
  Either level can reject with remarks; the salesperson corrects and resubmits (back to Level 1).
  Approve opens a remarks popup (optional): the changes the salesperson must make before sending.

Approved (still a draft): only the quotation's owner can edit it, to apply the approver's remarks;
items, prices, discounts and taxes stay as approved (a price change needs Reject / Resubmit).
Send to Client submits it: from then on nothing can be edited.

Client decision: the salesperson records Client Accepted / Requested Revision / Rejected.
A revision cancels the Quotation; the amended version goes back through the same chain and keeps
the same Estimation (and Deal, whose amount follows the revised quotation).
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

# States in which the quoted prices are fixed (Approved: editable by the owner except the prices)
LOCKED_STATES = (APPROVED, SENT_TO_CLIENT, CLIENT_APPROVED)

# Workflow action that needs remarks
REJECT_ACTION = "Reject"
# Workflow action with optional approval remarks (Level 1 and Level 2)
APPROVE_ACTION = "Approve"
# Quotation fields holding the approval remarks of each level
APPROVAL_REMARKS_FIELDS = {LEVEL_1: "alt_level_1_remarks", LEVEL_2: "alt_level_2_remarks"}

# --------------------------------------------------------------------------- Deal sales stages
# The Deal (Opportunity) is only made from a Quotation, so its Sales Stage follows the quotation
# (sales/deal.py sales_stage_for, kept current by sales/quotation.py sync_deal). The ERPNext
# pre-quote stages (Prospecting, Qualification, Needs Analysis...) are not offered on the Deal.
STAGE_DRAFT = "Quotation Draft"
STAGE_REVISION = "Quotation Revision"
STAGE_APPROVAL = "Quotation Approval"
STAGE_APPROVED = "Quotation Approved"
STAGE_SENT = "Quotation Sent"
STAGE_ACCEPTED = "Client Accepted"
STAGE_LOST = "Lost"

# in pipeline order (Opportunity form offers only these)
SALES_STAGES = (
	STAGE_DRAFT,
	STAGE_REVISION,
	STAGE_APPROVAL,
	STAGE_APPROVED,
	STAGE_SENT,
	STAGE_ACCEPTED,
	STAGE_LOST,
)

# quotation workflow state -> Deal sales stage (a draft amended from a revision: STAGE_REVISION)
STAGE_BY_STATE = {
	DRAFT: STAGE_DRAFT,
	REJECTED: STAGE_DRAFT,
	PENDING_MANAGER: STAGE_APPROVAL,
	PENDING_LEVEL_2: STAGE_APPROVAL,
	APPROVED: STAGE_APPROVED,
	SENT_TO_CLIENT: STAGE_SENT,
	REVISION_REQUESTED: STAGE_REVISION,
	CLIENT_APPROVED: STAGE_ACCEPTED,
	LOST: STAGE_LOST,
}

# --------------------------------------------------------------------------- Customer tax type
# Local: GSTIN mandatory, and an Address carrying that GSTIN (sales/customer.py).
# Overseas: GST Category "Overseas", no GSTIN.
TAX_TYPE_FIELD = "alt_tax_type"
TAX_LOCAL = "Local"
TAX_OVERSEAS = "Overseas"


def workflow_is_active():
	from frappe.model.workflow import get_workflow_name

	return get_workflow_name("Quotation") == WORKFLOW_NAME

# --------------------------------------------------------------------------- Customer rules (CRM-F04)
# Customer Type: Company / Partnership (Zoho Account) or Individual (Zoho Contact).
INDIVIDUAL = "Individual"
# Mobile No and Email ID mandatory and unique across customers; GSTIN unique (sales/customer_unique.py).
# Cleaned-up copies of the customer's mobile and email, unique in the database.
MOBILE_KEY_FIELD = "alt_mobile_key"
EMAIL_KEY_FIELD = "alt_email_key"
# Customer Type, Tax Type and GSTIN are fixed after the first submitted transaction, except for:
LOCKED_FIELD_EDITORS = (SALES_MANAGER, "System Manager")
