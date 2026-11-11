# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Loan Rules — eligibility on Frappe Lending's Loan Application (LR-05, with the LR-03
Override Reason check).

ClickUp: https://app.clickup.com/t/14yr2e57ghh (parent 14yr2e57ghb)

Hooked in hooks.py doc_events "Loan Application":
    before_validate             Applicant Type must be Employee (employee loans only; the option list
                                is narrowed in setup/loan_application_fields.py); an employee
                                applies only for themselves (setup/loan_permissions.py, LR-09)
    validate                    every save and submit
    before_submit               no matching Loan Rule -> submit refused ("no loan policy" message),
                                whatever Require Loan Rule says (it only decides the draft save)
    before_update_after_submit  status of a submitted application changed to Approved, or
                                rule_override changed after submit
    on_update / on_update_after_submit   timeline comment for a new override

evaluate(doc), only for Applicant Type = Employee (other applicants: eligibility fields cleared):
1. Match the Loan Rule (engine.get_applicable_rule) and store it in loan_rule.
   No rule: Lending Settings > Require Loan Rule on -> blocked with the "no loan policy" message;
   off -> the draft is saved without checks, eligibility fields cleared; it cannot be submitted
   (before_submit).
2. Run every check (engine.run_checks), store the HTML check list in eligibility_result.
3. All passed -> Eligible (any override is cleared, it is not needed).
   Failures:
   - rule_override ticked (allowed, see below) -> Overridden; overridden_by / overridden_on stamped;
     a timeline comment lists the failed checks and the reason.
   - Enforcement Warn -> saved as Not Eligible with an orange message listing every failure.
   - Enforcement Block -> nothing saved; one message lists every failure.

Override: ticking rule_override needs the rule's Allow Override and the user holding its Override
Role (checked on the server, whatever the form shows) plus an Override Reason. An override already
stamped by an authorised user is kept when someone else later saves the application unchanged.
"""

import frappe
from frappe import _
from frappe.utils import escape_html, now_datetime

from alantech_erp.loan_rules import engine
from alantech_erp.loan_rules.loan import set_applicant_name
from alantech_erp.setup.loan_application_fields import ELIGIBLE, NOT_ELIGIBLE, OVERRIDDEN
from alantech_erp.setup.loan_permissions import validate_own_applicant
from alantech_erp.setup.loan_rule_settings import is_loan_rule_required, no_rule_message

EMPLOYEE = "Employee"
APPROVED = "Approved"

ELIGIBILITY_FIELDS = (
	"loan_rule",
	"eligibility_status",
	"eligibility_result",
	"rule_override",
	"override_reason",
	"overridden_by",
	"overridden_on",
)


class LoanNotEligibleError(frappe.ValidationError):
	pass


class NoLoanRuleError(LoanNotEligibleError):
	pass


class OverrideReasonMissingError(frappe.ValidationError):
	pass


class OverrideNotAllowedError(frappe.PermissionError):
	pass


class EmployeeApplicantOnlyError(frappe.ValidationError):
	pass


# ---------------------------------------------------------------------------
# doc_events
# ---------------------------------------------------------------------------


def before_validate(doc, method=None):
	"""Employee loans only. Runs before Lending's own code, which would otherwise try to create a
	Customer for a Customer applicant (LoanApplication.before_save)."""
	if doc.applicant_type != EMPLOYEE:
		frappe.throw(
			_("Loans are given to employees only. Set Applicant Type to Employee."),
			EmployeeApplicantOnlyError,
			title=_("Employee Loans Only"),
		)
	validate_own_applicant(doc)
	set_applicant_name(doc)


def validate(doc, method=None):
	validate_override_reason(doc)
	evaluate(doc)


def before_submit(doc, method=None):
	"""An Employee application is submitted only under a Loan Rule. validate() has just matched the
	rule; with none, saving the draft depends on Require Loan Rule but submitting never works."""
	if doc.applicant_type == EMPLOYEE and not doc.loan_rule:
		frappe.throw(no_rule_message(), NoLoanRuleError, title=_("No Loan Policy"))


def before_update_after_submit(doc, method=None):
	"""Re-check when a submitted application is approved: service, separation or other loans
	may have changed since the employee applied. An override ticked after submit is checked too."""
	approved_now = doc.status == APPROVED and doc.has_value_changed("status")
	if approved_now or doc.has_value_changed("rule_override"):
		validate_override_reason(doc)
		evaluate(doc)
	else:
		keep_check_results(doc)


# set only by evaluate(); eligibility_result is rendered as HTML on the form; the override stamp
# cannot be written over without a re-check either (LR-09)
CHECK_RESULT_FIELDS = (
	"loan_rule",
	"eligibility_status",
	"eligibility_result",
	"override_reason",
	"overridden_by",
	"overridden_on",
)


def keep_check_results(doc):
	"""After submit without a re-check, the stored results stay as the last check left them
	(they are allow_on_submit only so the server can update them)."""
	before = doc.get_doc_before_save()
	if not before:
		return
	for field in CHECK_RESULT_FIELDS:
		doc.set(field, before.get(field))


def on_update(doc, method=None):
	add_override_comment(doc)


def on_update_after_submit(doc, method=None):
	add_override_comment(doc)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------


def validate_override_reason(doc):
	if doc.get("rule_override") and not (doc.get("override_reason") or "").strip():
		frappe.throw(
			_("Enter an Override Reason to override the Loan Rule."),
			OverrideReasonMissingError,
			title=_("Override Reason Required"),
		)


def evaluate(doc):
	if doc.applicant_type != EMPLOYEE or not doc.applicant:
		clear_eligibility(doc)
		return

	rule = engine.get_applicable_rule(doc)
	if not rule:
		clear_eligibility(doc)
		if is_loan_rule_required():
			frappe.throw(no_rule_message(), NoLoanRuleError, title=_("No Loan Policy"))
		return

	doc.loan_rule = rule.name
	if newly_overridden(doc):
		ensure_override_allowed(doc, rule)
	elif not doc.rule_override:
		# Overridden By / On are stamped by the server only: never kept without an override (LR-09)
		clear_override(doc)

	results = engine.run_checks(
		rule, doc.applicant, doc.posting_date, doc.loan_product, doc.company, doc.name, doc.loan_amount
	)
	failures = engine.failure_messages(results)

	if not failures:
		clear_override(doc)
		set_result(doc, rule, results, ELIGIBLE)
		return

	if doc.rule_override:
		stamp_override(doc)
		set_result(doc, rule, results, OVERRIDDEN)
		doc.flags.loan_rule_override_failures = failures
		return

	if rule.enforcement == "Warn":
		set_result(doc, rule, results, NOT_ELIGIBLE)
		frappe.msgprint(
			failure_message(rule, failures, warn=True),
			title=_("Loan Eligibility Warning"),
			indicator="orange",
		)
		return

	frappe.throw(failure_message(rule, failures), LoanNotEligibleError, title=_("Not Eligible for this Loan"))


def newly_overridden(doc):
	"""True when this save ticks rule_override (an existing, stamped override is left alone)."""
	if not doc.rule_override:
		return False
	before = doc.get_doc_before_save()
	return not (before and before.get("rule_override") and doc.overridden_by)


def can_override(rule, user=None):
	return bool(
		rule.allow_override and rule.override_role and rule.override_role in frappe.get_roles(user)
	)


def ensure_override_allowed(doc, rule):
	if not rule.allow_override:
		frappe.throw(
			_("Loan Rule {0} does not allow overrides.").format(frappe.bold(rule.name)),
			OverrideNotAllowedError,
			title=_("Override Not Allowed"),
		)
	if not can_override(rule):
		frappe.throw(
			_("Only users with the {0} role can override Loan Rule {1}.").format(
				frappe.bold(rule.override_role), frappe.bold(rule.name)
			),
			OverrideNotAllowedError,
			title=_("Override Not Allowed"),
		)


def stamp_override(doc):
	if newly_overridden(doc) or not doc.overridden_by:
		doc.overridden_by = frappe.session.user
		doc.overridden_on = now_datetime()


def clear_override(doc):
	for field in ("rule_override", "override_reason", "overridden_by", "overridden_on"):
		doc.set(field, 0 if field == "rule_override" else None)


def clear_eligibility(doc):
	for field in ELIGIBILITY_FIELDS:
		if doc.get(field):
			doc.set(field, 0 if field == "rule_override" else None)


def set_result(doc, rule, results, status):
	doc.eligibility_status = status
	doc.eligibility_result = engine.render_results_html(rule, results, status)


def failure_message(rule, failures, warn=False):
	intro = (
		_("This application does not meet Loan Rule {0}; it is saved as Not Eligible:")
		if warn
		else _("This application does not meet Loan Rule {0}:")
	).format(frappe.bold(rule.name))
	items = "".join(f"<li>{escape_html(m)}</li>" for m in failures)
	message = f"{intro}<ul>{items}</ul>"
	if rule.description:
		message += f"<p class='text-muted'>{escape_html(rule.description)}</p>"
	return message


def add_override_comment(doc):
	failures = doc.flags.pop("loan_rule_override_failures", None)
	if not failures or not newly_overridden_comment_needed(doc):
		return
	items = "".join(f"<li>{escape_html(m)}</li>" for m in failures)
	doc.add_comment(
		"Comment",
		_("Loan Rule {0} overridden. Reason: {1}").format(
			escape_html(doc.loan_rule), escape_html(doc.override_reason or "")
		)
		+ f"<br>{escape_html(_('Failed checks'))}:<ul>{items}</ul>",
	)


def newly_overridden_comment_needed(doc):
	"""Comment once per override: when it was stamped in this save."""
	before = doc.get_doc_before_save()
	return not before or before.get("overridden_on") != doc.overridden_on
