# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Loan Rules — Loan Eligibility fields on Loan Application (LR-03).

ClickUp: https://app.clickup.com/t/14yr2e57ghf (parent 14yr2e57ghb)

Custom fields on Frappe Lending's Loan Application (never edit its JSON), in a collapsible
"Loan Eligibility" section right after the applicant fields (after Company), shown only when
Applicant Type = Employee:

    eligibility_note     HTML                             short explanation; keeps the section visible
                                                          while the read-only fields are still empty
    loan_rule            Link Loan Rule, read-only        matched rule, set on validate (LR-04/05)
    eligibility_status   Select, read-only                Eligible / Not Eligible / Overridden
    eligibility_result   Long Text, read-only             HTML check list (pass/fail + actual values)
    rule_override        Check                            ticked by a user holding the rule's
                                                          override_role (role check: LR-05)
    override_reason      Small Text                       mandatory when rule_override is ticked
    overridden_by / _on  Link User / Datetime, read-only  stamped on save when overridden (LR-05)

All fields are no_copy (a duplicated or amended application is checked fresh) and allow_on_submit
(the check re-runs when a submitted application moves to Approved).

    execute()   after_migrate (hooks.py): creates / updates the fields. Skipped when Lending is
                not installed. Field values on existing applications are never touched.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

DOCTYPE = "Loan Application"

ELIGIBLE = "Eligible"
NOT_ELIGIBLE = "Not Eligible"
OVERRIDDEN = "Overridden"
ELIGIBILITY_STATUSES = (ELIGIBLE, NOT_ELIGIBLE, OVERRIDDEN)

IS_EMPLOYEE = "eval:doc.applicant_type == 'Employee'"

ELIGIBILITY_NOTE = (
	'<p class="text-muted small">'
	"Employee loan applications are checked against the matching Loan Rule (service, "
	"confirmation, age, separation, leave and loan limits) when saved and again on approval."
	"</p>"
)
IS_OVERRIDDEN = "eval:doc.rule_override"

# common to every field: fresh on duplicate / amend, editable by the server after submit
_COMMON = {"no_copy": 1, "allow_on_submit": 1}

CUSTOM_FIELDS = {
	DOCTYPE: [
		dict(
			_COMMON,
			fieldname="loan_eligibility_section",
			label="Loan Eligibility",
			fieldtype="Section Break",
			collapsible=1,
			depends_on=IS_EMPLOYEE,
			insert_after="company",
		),
		# HTML is never hidden by "Hide Empty Read-Only Fields", so the section shows on a new
		# employee application before any check has filled the read-only fields below
		dict(
			_COMMON,
			fieldname="eligibility_note",
			fieldtype="HTML",
			options=ELIGIBILITY_NOTE,
			insert_after="loan_eligibility_section",
		),
		dict(
			_COMMON,
			fieldname="loan_rule",
			label="Loan Rule",
			fieldtype="Link",
			options="Loan Rule",
			read_only=1,
			insert_after="eligibility_note",
			description="Loan Rule matched for this employee and loan product.",
		),
		dict(
			_COMMON,
			fieldname="eligibility_status",
			label="Eligibility Status",
			fieldtype="Select",
			options="\n" + "\n".join(ELIGIBILITY_STATUSES),
			read_only=1,
			in_standard_filter=1,
			insert_after="loan_rule",
			description="Result of the last eligibility check.",
		),
		dict(
			_COMMON,
			fieldname="loan_eligibility_column",
			fieldtype="Column Break",
			insert_after="eligibility_status",
		),
		dict(
			_COMMON,
			fieldname="rule_override",
			label="Override Loan Rule",
			fieldtype="Check",
			default="0",
			# shown by public/js/loan_application.js only to holders of the matched rule's
			# Override Role (or when already ticked); visible before the first save so a new
			# application failing a Block rule can be overridden (LR-06)
			depends_on=IS_EMPLOYEE,
			insert_after="loan_eligibility_column",
			description="Only for users holding the rule's Override Role, when the rule allows override.",
		),
		dict(
			_COMMON,
			fieldname="override_reason",
			label="Override Reason",
			fieldtype="Small Text",
			depends_on=IS_OVERRIDDEN,
			mandatory_depends_on=IS_OVERRIDDEN,
			insert_after="rule_override",
		),
		dict(
			_COMMON,
			fieldname="overridden_by",
			label="Overridden By",
			fieldtype="Link",
			options="User",
			read_only=1,
			depends_on="eval:doc.overridden_by",
			insert_after="override_reason",
		),
		dict(
			_COMMON,
			fieldname="overridden_on",
			label="Overridden On",
			fieldtype="Datetime",
			read_only=1,
			depends_on="eval:doc.overridden_on",
			insert_after="overridden_by",
		),
		dict(
			_COMMON,
			fieldname="eligibility_result_section",
			fieldtype="Section Break",
			# __eligibility_preview: set by public/js/loan_application.js while a live preview shows
			depends_on="eval:doc.applicant_type == 'Employee' && (doc.eligibility_result || doc.__eligibility_preview)",
			insert_after="overridden_on",
		),
		dict(
			_COMMON,
			fieldname="eligibility_result",
			label="Eligibility Result",
			fieldtype="Long Text",
			read_only=1,
			hidden=1,  # stored HTML; shown rendered by eligibility_result_html
			insert_after="eligibility_result_section",
		),
		# a read-only Long Text shows its HTML as plain text; public/js/loan_application.js renders
		# eligibility_result (built with escaped values in engine.render_results_html) here
		dict(
			_COMMON,
			fieldname="eligibility_result_html",
			label="Eligibility Result",
			fieldtype="HTML",
			insert_after="eligibility_result",
		),
	]
}


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return  # Lending not installed on this site
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	set_repayment_mandatory()
	set_employee_only_applicants()


# Alantech gives loans to employees only: Lending's Customer applicant is removed from the
# Applicant Type options (Frappe then refuses "Customer" on save, also via API / import), Employee
# is the default and the only choice, and the Applicant (the employee) is mandatory.
EMPLOYEE_ONLY = {
	DOCTYPE: [
		("applicant_type", "options", "Employee", "Text"),
		("applicant_type", "default", "Employee", "Text"),
		("applicant_type", "read_only", 1, "Check"),
		("applicant", "reqd", 1, "Check"),
	],
	"Loan": [
		("applicant_type", "options", "Employee", "Text"),
		("applicant_type", "default", "Employee", "Text"),
	],
}


def set_employee_only_applicants():
	for doctype, properties in EMPLOYEE_ONLY.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for fieldname, prop, value, prop_type in properties:
			make_property_setter(doctype, fieldname, prop, value, prop_type, validate_fields_for_doctype=False)


# Lending's LoanApplication.validate_repayment_method requires these but the fields carry no reqd,
# so the form shows no asterisk and only a "Please enter ..." message on save. Same conditions as
# the server check, which runs only for term loans (is_term_loan comes from the Loan Product;
# repayment_method has a default, so without is_term_loan the field would be required while hidden).
REPAYMENT_MANDATORY = {
	"repayment_periods": "eval:doc.is_term_loan && doc.repayment_method == 'Repay Over Number of Periods'",
	"repayment_amount": "eval:doc.is_term_loan && doc.repayment_method == 'Repay Fixed Amount per Period'",
}


def set_repayment_mandatory():
	for fieldname, condition in REPAYMENT_MANDATORY.items():
		make_property_setter(
			DOCTYPE, fieldname, "mandatory_depends_on", condition, "Code", validate_fields_for_doctype=False
		)
