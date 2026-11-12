# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Loan Rules — eligibility API (LR-07) used by the live preview (LR-06), self service and
mobile.

ClickUp: https://app.clickup.com/t/14yr2e57ghk (LR-07), https://app.clickup.com/t/14yr2e57ghj
(LR-06), parent 14yr2e57ghb

    check_loan_eligibility(employee, loan_product, posting_date, company, loan_application, loan_amount)
        The matched rule, overall status and per-check results the Loan Application would get on
        save, without saving anything. employee may be left out: the caller's own Employee record
        (Employee.user_id) is used, for self service and mobile. Called by
        public/js/loan_application.js when applicant / loan product / application date / company
        change on a draft application.
    can_override_loan_rule(loan_rule)
        Whether the current user may tick Override Loan Rule for that rule (rule allows override
        and the user holds its Override Role). The form shows the checkbox only then.

Access (check_eligibility_access):
    HR Manager, HR User, Loan Manager, System Manager (and Administrator)   any employee
    anyone else                                                             only their own
                                                                            Employee record
    HR User is included because HR Users create Loan Applications for employees and the form
    preview calls this API. The save-time check in loan_application.py stays the authority.

Overall status: Eligible / Not Eligible (a rule applies) or No Loan Rule (none applies; such an
application can never be submitted).
"""

import frappe
from frappe import _
from frappe.utils import escape_html, flt, getdate, today

from alantech_erp.loan_rules import engine
from alantech_erp.loan_rules.loan_application import can_override
from alantech_erp.setup.loan_application_fields import ELIGIBLE, NOT_ELIGIBLE
from alantech_erp.setup.loan_rule_settings import is_loan_rule_required, no_rule_message

NO_LOAN_RULE = "No Loan Rule"
# roles that may check any employee's eligibility (LR-07: HR / Loans Manager)
ANY_EMPLOYEE_ROLES = ("HR Manager", "HR User", "Loan Manager", "System Manager")


class LoanEligibilityAccessError(frappe.PermissionError):
	pass


@frappe.whitelist()
def check_loan_eligibility(
	employee: str | None = None,
	loan_product: str | None = None,
	posting_date: str | None = None,
	company: str | None = None,
	loan_application: str | None = None,
	loan_amount: float | None = None,
) -> dict:
	"""{employee, employee_name, company, loan_product, posting_date, rule, enforcement, status,
	eligible, blocked, results, failures, message, html, allow_override, can_override}
	for one employee + loan product on posting_date (default today).

	status    Eligible / Not Eligible / No Loan Rule
	eligible  a rule applies and every check passed (without a rule the application can never
	          be submitted)
	blocked   saving the application would be refused (Block rule failing, or no rule while
	          Lending Settings > Require Loan Rule is on) unless an allowed override is ticked
	results   one row per check: {check, label, passed, expected, actual, message}
	"""
	employee = check_eligibility_access(employee)
	if loan_product and not frappe.db.exists("Loan Product", loan_product):
		frappe.throw(_("Loan Product {0} not found.").format(loan_product), frappe.DoesNotExistError)

	posting_date = getdate(posting_date or today())
	emp = engine.get_employee(employee)
	company = company or emp.company
	data = engine.check_eligibility(
		employee,
		loan_product,
		posting_date,
		company=company,
		exclude_application=loan_application,
		# blank amount: the salary-limit row only shows the maximum eligible amount
		loan_amount=flt(loan_amount) if loan_amount not in (None, "") else None,
	)
	rule, results = data["rule"], data["results"]
	out = {
		"employee": employee,
		"employee_name": emp.employee_name,
		"company": company,
		"loan_product": loan_product,
		"posting_date": str(posting_date),
	}

	if not rule:
		required = is_loan_rule_required()
		message = (
			no_rule_message()
			if required
			else _("No Loan Rule applies: the draft can be saved, but it cannot be submitted.")
		)
		return dict(
			out,
			rule=None,
			enforcement=None,
			status=NO_LOAN_RULE,
			eligible=False,  # never submittable without a rule
			blocked=required,
			results=[],
			failures=[],
			message=message,
			html=render_message_html(message, error=True),
			allow_override=False,
			can_override=False,
		)

	failures = engine.failure_messages(results)
	eligible = not failures
	status = ELIGIBLE if eligible else NOT_ELIGIBLE
	blocked = bool(failures) and rule.enforcement != "Warn"
	message = preview_note(rule, failures)
	return dict(
		out,
		rule=rule.name,
		enforcement=rule.enforcement,
		status=status,
		eligible=eligible,
		blocked=blocked,
		results=results,
		failures=failures,
		message=message,
		html=engine.render_results_html(rule, results, status) + render_message_html(message, error=blocked),
		allow_override=bool(rule.allow_override),
		can_override=can_override(rule),
	)


def check_eligibility_access(employee=None, user=None):
	"""The Employee to check, after the access rule; employee defaults to the user's own."""
	user = user or frappe.session.user
	own = frappe.db.get_value("Employee", {"user_id": user}, "name") if user != "Guest" else None
	employee = employee or own
	if not employee:
		frappe.throw(
			_("No Employee record is linked to your user."),
			frappe.DoesNotExistError,
			title=_("Employee Not Found"),
		)
	# access before existence, so other employees' IDs cannot be probed
	if not (employee == own or user == "Administrator" or set(ANY_EMPLOYEE_ROLES) & set(frappe.get_roles(user))):
		frappe.throw(
			_("You can check loan eligibility only for yourself."),
			LoanEligibilityAccessError,
			title=_("Not Permitted"),
		)
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Employee {0} not found.").format(employee), frappe.DoesNotExistError)
	return employee


@frappe.whitelist()
def can_override_loan_rule(loan_rule: str) -> bool:
	if not loan_rule or not frappe.db.exists("Loan Rule", loan_rule):
		return False
	return can_override(frappe.get_cached_doc("Loan Rule", loan_rule))


def preview_note(rule, failures):
	if not failures:
		return _("Preview: the application meets this rule.")
	if rule.enforcement == "Warn":
		return _("Preview: the application can be saved, as Not Eligible.")
	if rule.allow_override:
		return _("Preview: saving will be blocked unless the Loan Rule is overridden.")
	return _("Preview: saving will be blocked.")


def render_message_html(message, error=False):
	css = "text-danger" if error else "text-muted"
	return f'<p class="{css} small loan-eligibility-note">{escape_html(message)}</p>'
