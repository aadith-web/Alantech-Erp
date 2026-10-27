"""Leave Approval workflow: Reports To approves first, then HR Manager.

    Pending --Approve (the Leave Approver)--> Pending HR Approval --Approve (HR Manager)--> Approved
       |                                            |
       +--Reject (the Leave Approver)--> Rejected <-+--Reject (HR Manager)

The Leave Approver is the employee's Reports To user (setup/approvers.py). When it is the HR
Manager (no Reports To, or a manager without a user) or empty (the Managing Director), HR
Manager approves or rejects in one step: Pending --> Approved / Rejected.
Approved / Rejected submit the application with that status.

execute() runs on every migrate (hooks.py after_migrate) and only CREATES what is missing, so a
workflow changed later in the UI is never overwritten.
"""

import frappe

WORKFLOW = "Leave Approval"
DOCTYPE = "Leave Application"
HR_ROLE = "HR Manager"
APPROVER_ROLE = "Leave Approver"

# the HR Manager's user, same rule as setup/approvers.hr_manager_user
HR_USER = (
	'frappe.db.get_value("Employee", {"designation": "HR Manager", "status": "Active", '
	'"user_id": ["is", "set"]}, "user_id", order_by="creation asc")'
)
IS_APPROVER = f"doc.leave_approver == frappe.session.user and doc.leave_approver != {HR_USER}"
HR_ONLY = f"not doc.leave_approver or doc.leave_approver == {HR_USER}"

STATES = [
	# state, docstatus, who may edit, status set on the application
	("Pending", 0, "Employee", None),
	("Pending HR Approval", 0, HR_ROLE, None),
	("Approved", 1, HR_ROLE, "Approved"),
	("Rejected", 1, HR_ROLE, "Rejected"),
	("Cancelled", 2, HR_ROLE, "Cancelled"),
]

TRANSITIONS = [
	# state, action, next state, role, condition
	("Pending", "Approve", "Pending HR Approval", APPROVER_ROLE, IS_APPROVER),
	("Pending", "Reject", "Rejected", APPROVER_ROLE, IS_APPROVER),
	("Pending", "Approve", "Approved", HR_ROLE, HR_ONLY),
	("Pending", "Reject", "Rejected", HR_ROLE, HR_ONLY),
	("Pending HR Approval", "Approve", "Approved", HR_ROLE, None),
	("Pending HR Approval", "Reject", "Rejected", HR_ROLE, None),
	("Approved", "Cancel", "Cancelled", HR_ROLE, None),
]

STATE_STYLE = {"Pending": "Warning", "Pending HR Approval": "Warning", "Approved": "Success",
	"Rejected": "Danger", "Cancelled": "Inverse"}


def leave_application_before_validate(doc, method=None):
	"""HRMS fills the Leave Approver only in the browser form. Fill it here too, so an application
	made any other way, or with the field cleared, still goes to Reports To before HR Manager."""
	if not doc.leave_approver and doc.employee:
		from hrms.hr.doctype.leave_application.leave_application import get_employee_leave_approver

		doc.leave_approver = get_employee_leave_approver(doc.employee)


def execute():
	if frappe.db.exists("Workflow", WORKFLOW):
		return
	for state, *_ in STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state,
				"style": STATE_STYLE.get(state)}).insert(ignore_permissions=True)
	for action in {t[1] for t in TRANSITIONS}:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)

	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW,
			"document_type": DOCTYPE,
			"is_active": 1,
			"workflow_state_field": "workflow_state",
			"send_email_alert": 1,
			"states": [
				{"state": s, "doc_status": str(ds), "allow_edit": role,
					"update_field": "status" if status else None, "update_value": status}
				for s, ds, role, status in STATES
			],
			"transitions": [
				{"state": s, "action": a, "next_state": n, "allowed": role, "condition": cond,
					"allow_self_approval": 1}
				for s, a, n, role, cond in TRANSITIONS
			],
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
