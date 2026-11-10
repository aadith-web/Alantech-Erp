# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Loan Rules — the require_loan_rule setting (LR-02).

ClickUp: https://app.clickup.com/t/14yr2e57ghd (parent 14yr2e57ghb)

A Check field on Frappe Lending's Lending Settings (this Lending version has no "Loan Settings";
never edit its JSON). It decides what happens to a Loan Application with Applicant Type =
Employee when no enabled, valid Loan Rule matches it:

    Off (default)  the draft is saved without any checks, but it cannot be submitted
                   (loan_rules/loan_application.before_submit).
    On             the draft save is blocked too, with NO_RULE_MESSAGE.

    execute()                after_migrate (hooks.py): creates / updates the field. Skipped when
                             Lending is not installed. Never touches the saved value.
    is_loan_rule_required()  read by the rule engine / Loan Application hooks (LR-04, LR-05).
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint

SETTINGS_DOCTYPE = "Lending Settings"
FIELDNAME = "require_loan_rule"

# message from the feature spec, shown when no rule covers the employee and the setting is on
NO_RULE_MESSAGE = "No loan policy covers you for this loan product. Contact HR."

CUSTOM_FIELDS = {
	SETTINGS_DOCTYPE: [
		{
			"fieldname": "employee_loan_rules_section",
			"label": "Employee Loan Rules",
			"fieldtype": "Section Break",
			"insert_after": "column_break_hwkk",
		},
		{
			"fieldname": FIELDNAME,
			"label": "Require Loan Rule",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "employee_loan_rules_section",
			"description": "Applies when no enabled Loan Rule covers the employee and loan product. "
			"When ticked, the Loan Application cannot even be saved. When not ticked, it can be "
			"saved as a draft without checks, but it can never be submitted.",
		},
	]
}


def execute():
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return  # Lending not installed on this site
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)


def is_loan_rule_required() -> bool:
	"""True when employee loan applications without a matching Loan Rule must be blocked."""
	if not frappe.get_meta(SETTINGS_DOCTYPE).has_field(FIELDNAME):
		return False
	return bool(cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, FIELDNAME)))


def no_rule_message() -> str:
	return _(NO_RULE_MESSAGE)
