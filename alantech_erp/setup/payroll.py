"""Payroll setup for the HR-002-6 permission matrix (Step 7, tests/test_phase0_payroll.py).

- HR User may prepare a Payroll Entry (read, create, write); submitting and cancelling it stays with
  the HR Manager.
- Each company's default payroll payable account must be of type Payable, or HRMS refuses to submit
  a Payroll Entry ("Account type should be set Payable for payroll payable account").

hooks.py:
    after_migrate = [..., "alantech_erp.setup.payroll.execute"]
"""

import frappe

DOCTYPE = "Payroll Entry"
HR_USER_ROLE = "HR User"
HR_USER_RIGHTS = ("read", "write", "create")


def execute():
	allow_hr_user_to_prepare_payroll_entry()
	set_payroll_payable_account_type()


def allow_hr_user_to_prepare_payroll_entry():
	"""Create-only: the HR User permission row (rights changed later by hand are kept)."""
	if frappe.db.exists("Custom DocPerm", {"parent": DOCTYPE, "role": HR_USER_ROLE, "permlevel": 0}):
		return
	if not frappe.db.exists("Custom DocPerm", {"parent": DOCTYPE}):
		# first custom row: copy the standard ones, or they would stop applying
		from frappe.permissions import setup_custom_perms

		setup_custom_perms(DOCTYPE)
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": DOCTYPE,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": HR_USER_ROLE,
			"permlevel": 0,
			**{right: 1 for right in HR_USER_RIGHTS},
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=DOCTYPE)


def set_payroll_payable_account_type():
	"""Only a blank account type is filled in; a type someone chose is left alone."""
	for account in frappe.get_all("Company", pluck="default_payroll_payable_account"):
		if account and not frappe.db.get_value("Account", account, "account_type"):
			frappe.db.set_value("Account", account, "account_type", "Payable")
