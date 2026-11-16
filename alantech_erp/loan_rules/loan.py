# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Loan Management flow (HR-F05-x): a Loan is made only from an Approved Loan Application.

ClickUp: https://app.clickup.com/t/14yr2e57kyk (parent HR-F05 14yr2e56cah)

The Loan Rule checks run on the Loan Application (loan_rules/loan_application.py). A Loan typed in
by hand (Add Loan, import, API) would skip them, so:

    validate(doc)  Loan doc_event validate (new / draft and on submit; a submitted Loan is never
                   re-checked): Loan Application is required and must be
                     - submitted with Status Approved,
                     - for the same Applicant, Company and Loan Product,
                     - not used by another Loan that is not cancelled,
                   and the Loan Amount cannot exceed the approved Loan Amount.
    approved_applications_without_loan()  whitelisted: the Approved applications that have no Loan
                   yet. public/js/loan_list.js lists them on the Loan list ("Add Loan" opens that
                   list; each row creates the Loan with Lending's create_loan mapper, which fills
                   Loan Application). Lending already makes Loan Application read-only on the form.

    loans_awaiting_disbursement()  whitelisted: Sanctioned / Partially Disbursed Loans with an amount
                   left to disburse; public/js/loan_disbursement_list.js lists them on the Loan
                   Disbursement list ("Add Loan Disbursement" opens that list; each row makes the
                   disbursement with Lending's make_loan_disbursement, as Create > Loan Disbursement
                   on the Loan does).

Loans submitted before this rule (without an application) are left as they are.

    set_applicant_name(doc)  Loan validate and Loan Application before_validate: Applicant Name is
                   filled from the Employee on the server. Lending fills it only in the browser by
                   loading the Employee record, which Accounts / Loan users cannot read, so it stayed
                   empty and the form showed only the employee ID.
"""

import frappe
from frappe import _
from frappe.utils import flt


class LoanWithoutApplicationError(frappe.ValidationError):
	pass


class AutoDisbursementNotAllowedError(frappe.PermissionError):
	pass


TITLE = _("Loan Application Required")


def set_applicant_name(doc):
	if doc.get("applicant_type") == "Employee" and doc.get("applicant"):
		doc.applicant_name = frappe.db.get_value("Employee", doc.applicant, "employee_name")


def validate(doc, method=None):
	if doc.docstatus == 2:
		return
	set_applicant_name(doc)
	validate_auto_disbursement(doc)
	if not doc.loan_application:
		frappe.throw(
			_(
				"A Loan can be created only from an Approved Loan Application. Approve the employee's "
				"Loan Application, then use Create > Loan on it (or Add Loan on the Loan list)."
			),
			LoanWithoutApplicationError,
			title=TITLE,
		)

	app = frappe.db.get_value(
		"Loan Application",
		doc.loan_application,
		["docstatus", "status", "applicant_type", "applicant", "company", "loan_product", "loan_amount"],
		as_dict=True,
	)
	if not app or app.docstatus != 1 or app.status != "Approved":
		frappe.throw(
			_("Loan Application {0} is not Approved. Only an Approved Loan Application can be turned into a Loan.").format(
				frappe.bold(doc.loan_application)
			),
			LoanWithoutApplicationError,
			title=TITLE,
		)

	for field in ("applicant_type", "applicant", "company", "loan_product"):
		if doc.get(field) and doc.get(field) != app.get(field):
			frappe.throw(
				_("{0} must be the same as on Loan Application {1} ({2}).").format(
					_(doc.meta.get_label(field)), frappe.bold(doc.loan_application), app.get(field)
				),
				LoanWithoutApplicationError,
				title=TITLE,
			)

	if flt(doc.loan_amount) > flt(app.loan_amount):
		frappe.throw(
			_("Loan Amount cannot be more than the approved amount {0} on Loan Application {1}.").format(
				frappe.format_value(app.loan_amount, {"fieldtype": "Currency"}), frappe.bold(doc.loan_application)
			),
			LoanWithoutApplicationError,
			title=TITLE,
		)

	other = frappe.db.get_value(
		"Loan",
		{"loan_application": doc.loan_application, "docstatus": ("<", 2), "name": ("!=", doc.name or "")},
		"name",
	)
	if other:
		frappe.throw(
			_("Loan Application {0} already has Loan {1}.").format(frappe.bold(doc.loan_application), frappe.bold(other)),
			LoanWithoutApplicationError,
			title=TITLE,
		)


def validate_auto_disbursement(doc):
	"""Lending's Auto Create Disbursement on Loan Booking makes and submits the Loan Disbursement as
	the user submitting the Loan. Loans are made by the HR Head, disbursements by the Accounts Head
	(setup/loan_permissions.py EXACT), so it is refused for a user who cannot disburse."""
	from alantech_erp.setup.loan_permissions import can_create_loan_disbursement

	if doc.get("auto_create_disbursement_on_loan_booking") and not can_create_loan_disbursement():
		frappe.throw(
			_(
				"Untick Auto Create Disbursement on Loan Booking: loans are disbursed by the Accounts "
				"Department Head through a Loan Disbursement."
			),
			AutoDisbursementNotAllowedError,
			title=_("Not Permitted"),
		)


@frappe.whitelist()
def approved_applications_without_loan():
	"""Approved Loan Applications the user can read that have no Loan (other than a cancelled one)."""
	used = frappe.get_all(
		"Loan", filters={"docstatus": ("<", 2), "loan_application": ("is", "set")}, pluck="loan_application"
	)
	filters = {"docstatus": 1, "status": "Approved"}
	if used:
		filters["name"] = ("not in", used)
	return frappe.get_list(
		"Loan Application",
		filters=filters,
		fields=["name", "applicant", "applicant_name", "company", "loan_product", "loan_amount", "posting_date"],
		order_by="posting_date asc, name asc",
	)


DISBURSABLE_STATUSES = ("Sanctioned", "Partially Disbursed")


@frappe.whitelist()
def loans_awaiting_disbursement():
	"""Submitted Loans the user can read that are Sanctioned / Partially Disbursed and still have an
	amount left to disburse (public/js/loan_disbursement_list.js lists them on Loan Disbursement)."""
	loans = frappe.get_list(
		"Loan",
		filters={"docstatus": 1, "status": ("in", DISBURSABLE_STATUSES)},
		fields=[
			"name",
			"status",
			"applicant",
			"applicant_name",
			"company",
			"loan_product",
			"loan_amount",
			"disbursed_amount",
			"posting_date",
		],
		order_by="posting_date asc, name asc",
	)
	for loan in loans:
		loan.pending_amount = flt(loan.loan_amount) - flt(loan.disbursed_amount)
		if not loan.applicant_name and loan.applicant:
			loan.applicant_name = frappe.db.get_value("Employee", loan.applicant, "employee_name")
	return [loan for loan in loans if loan.pending_amount > 0]


# Lending doctypes whose Applicant is an Employee (Dynamic Link on applicant_type); the employee's
# name is shown under the Applicant box by public/js/loan_applicant_name.js
APPLICANT_NAME_DOCTYPES = (
	"Collection Case",
	"Loan",
	"Loan Application",
	"Loan Balance Adjustment",
	"Loan Demand",
	"Loan Disbursement",
	"Loan Interest Accrual",
	"Loan Refund",
	"Loan Repayment",
	"Loan Restructure",
	"Loan Security Assignment",
	"Loan Security Release",
	"Loan Security Shortfall",
	"Loan Write Off",
	"Sanctioned Loan Amount",
)


@frappe.whitelist()
def get_applicant_name(doctype: str, applicant: str) -> str | None:
	"""Employee name for the Applicant box on a Lending form. Users of these forms (Accounts, Loan
	roles) often cannot read Employee, so the name is read here for anyone who can read the form's
	doctype, never the rest of the Employee record."""
	if doctype not in APPLICANT_NAME_DOCTYPES or not frappe.has_permission(doctype, "read"):
		return None
	return frappe.db.get_value("Employee", applicant, "employee_name")
