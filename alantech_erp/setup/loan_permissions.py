# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Loan Rules — roles and permissions (LR-09).

ClickUp: https://app.clickup.com/t/14yr2e57ghn (parent 14yr2e57ghb)

Loan Rule (doctype JSON, LR-01)       HR Manager, Loan Manager, System Manager full; Employee read
                                      (the rules are the published loan policy)
Loan Eligibility report (LR-08)       HR Manager, Loan Manager, System Manager
Override Loan Rule (LR-05 / LR-06)    role check, not a permlevel: each rule names its own Override
                                      Role. Server: loan_rules/loan_application.ensure_override_allowed;
                                      form: public/js/loan_application.js shows the checkbox only to
                                      that role. Overridden By / On are stamped by the server only.

Frappe Lending's own permissions are extended here (never in its JSON):

    execute()  after_migrate (hooks.py). Create-only Custom DocPerm rows (a role that already has a
               rule on that doctype and permlevel keeps it as HR set it):
      Loan Application  HR Manager  full, like Loan Manager (submit / cancel / amend; level 1 =
                                    status and approval fields)
                        HR User     prepares applications: read / write / create, level 1 read;
                                    no submit, cancel or approval
      Loan Product      HR Manager, HR User, Employee  read (to pick the product on an application)
      Loan              HR Manager full, like Loan Manager (creates the Loan from an Approved
                        application, submits / cancels / amends it); HR User read
                        (patches/v16/loan_hr_manager_create_loan.py upgrades sites set up before)
      Loan Category, Loan Classification, Loan Partner   HR Manager, HR User read (the Loan
                        form links to them)
      Process Loan Demand  Loan Manager (every HR Manager, setup/loan_roles.py) create / submit:
                        payroll raises each month's loan demand while building salary slips (the
                        accrual doctypes are Loan Manager's already); an HR User cannot build the
                        slip of an employee with a Repay From Salary loan
      Loan Origination Settings  HR Manager, HR User, Employee, Loan Manager, Loan LOS User read
                        (Lending's Loan Application form script reads it on every load)

    Own records only (hooks.py permission_query_conditions / has_permission): Lending gives the
    Employee role create / submit on Loan Application and read on Loan, and Applicant is a Dynamic
    Link, which Employee user permissions do not filter. Users without a LOAN_STAFF_ROLES role see
    and open only applications and loans whose Applicant is their own Employee record, and
    validate_own_applicant (Loan Application before_validate) refuses an application for someone
    else.
"""

import frappe
from frappe import _

# see and handle every employee's applications and loans
LOAN_STAFF_ROLES = {
	"System Manager",
	"HR Manager",
	"HR User",
	"Loan Manager",
	"Loan LOS User",
	"Loan Reporter",
}

_FULL = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "print", "email", "share")

# Link targets of Loan that only Lending's loan roles can read
LOAN_MASTERS = ("Loan Category", "Loan Classification", "Loan Partner")

# (doctype, role, permlevel): rights
PERMISSIONS = {
	("Loan Application", "HR Manager", 0): _FULL,
	("Loan Application", "HR Manager", 1): ("read", "write", "delete", "report", "export", "print", "email", "share"),
	("Loan Application", "HR User", 0): ("read", "write", "create", "report", "export", "print", "email", "share"),
	("Loan Application", "HR User", 1): ("read", "report", "print"),
	("Loan Product", "HR Manager", 0): ("read", "report"),
	("Loan Product", "HR User", 0): ("read",),
	("Loan Product", "Employee", 0): ("read",),
	# HR Manager creates the Loan from an Approved application (Create > Loan) and sanctions it
	("Loan", "HR Manager", 0): _FULL,
	("Loan", "HR User", 0): ("read",),
	# masters the Loan form links to (and fetches from when the Loan is created from an
	# application); Lending grants them to Loan Manager only, so without read the HR form stopped
	# with "Insufficient Permission for Loan Category"
	**{
		(doctype, role, 0): ("read",)
		for doctype in LOAN_MASTERS
		for role in ("HR Manager", "HR User")
	},
	# a salary slip of an employee with a Repay From Salary loan raises the month's demand through
	# Lending's process_daily_loan_demands, which inserts and submits a Process Loan Demand as the
	# user building the slip; Lending grants that doctype to System Manager only (HR-F05-x)
	("Process Loan Demand", "Loan Manager", 0): ("read", "create", "submit", "report"),
	# Salary slips of employees with such a loan are therefore made by an HR Manager (Loan Manager),
	# not an HR User: the slip also inserts Loan Interest Accrual / Loan Demand records, which stay
	# with Lending's loan roles.
	# Lending's loan_application.js reads employee_loans from it on every form load; without read
	# the form shows "No permission for Loan Origination Settings" (two Check fields, nothing
	# sensitive). Lending grants it to System Manager only, not even to Loan Manager.
	**{
		("Loan Origination Settings", role, 0): ("read",)
		for role in ("HR Manager", "HR User", "Employee", "Loan Manager", "Loan LOS User")
	},
}

OWN_RECORD_DOCTYPES = ("Loan Application", "Loan")


class OwnLoanApplicationOnlyError(frappe.PermissionError):
	pass


# ---------------------------------------------------------------------- after_migrate


def execute():
	from frappe.permissions import add_permission

	for (doctype, role, permlevel), rights in PERMISSIONS.items():
		if not (frappe.db.exists("DocType", doctype) and frappe.db.exists("Role", role)):
			continue
		key = {"parent": doctype, "role": role, "permlevel": permlevel, "if_owner": 0}
		if frappe.db.exists("Custom DocPerm", key):
			continue
		# copies the doctype's standard rules to Custom DocPerm first when it has none yet
		add_permission(doctype, role, permlevel, "read")
		frappe.db.set_value("Custom DocPerm", key, {right: 1 for right in rights})
		frappe.clear_cache(doctype=doctype)


# ---------------------------------------------------------------------- own records only


def is_loan_staff(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(LOAN_STAFF_ROLES & set(frappe.get_roles(user)))


def own_employees(user=None):
	user = user or frappe.session.user
	if user == "Guest":
		return []
	return frappe.get_all("Employee", filters={"user_id": user}, pluck="name")


def _query_conditions(doctype, user):
	user = user or frappe.session.user
	if is_loan_staff(user):
		return ""
	employees = own_employees(user)
	if not employees:
		return "1=0"
	values = ", ".join(frappe.db.escape(name) for name in employees)
	return f"(`tab{doctype}`.`applicant_type` = 'Employee' and `tab{doctype}`.`applicant` in ({values}))"


def loan_application_query_conditions(user=None):
	return _query_conditions("Loan Application", user)


def loan_query_conditions(user=None):
	return _query_conditions("Loan", user)


def has_permission(doc, ptype=None, user=None, debug=False):
	"""A single record: staff any; others only their own (a new, still empty application is
	allowed; validate_own_applicant checks it on save)."""
	user = user or frappe.session.user
	if is_loan_staff(user) or not doc.get("applicant"):
		return True
	return doc.get("applicant_type") == "Employee" and doc.applicant in own_employees(user)


def validate_own_applicant(doc):
	"""Loan Application before_validate: an employee applies only for themselves."""
	if is_loan_staff() or not doc.get("applicant"):
		return
	if doc.applicant not in own_employees():
		frappe.throw(
			_("You can apply for a loan only for yourself."),
			OwnLoanApplicationOnlyError,
			title=_("Not Permitted"),
		)
