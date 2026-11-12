# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Loan Rules — rule matching and eligibility checks (LR-04).

ClickUp: https://app.clickup.com/t/14yr2e57ghg (parent 14yr2e57ghb)

    get_applicable_rule(application)   the one Loan Rule that applies, or None:
        1. enabled rules of the application's company, valid on its posting date
        2. every filled applicability list contains the employee's / application's value
           (loan product, employment type, grade, designation, department, branch); blank = all
        3. sort: priority (high first), specificity (filled lists, high first), name
    run_checks(rule, employee, posting_date, loan_product, company, exclude_application, loan_amount)
        list of {check, label, passed, expected, actual, message}; the cooling-off row also has
        eligible_from (ISO date) when a loan has closed; the salary-limit row has
        max_eligible_amount. Failures are never raised here.
    candidate_rules(company, posting_date) + pick_rule(rules, context)
        the same matching split in two, to load the rules once for many employees (LR-08)
    check_eligibility(...)             rule + results + eligible flag (used by the Loan
                                       Application hooks, LR-05, and the API, LR-07)

Definitions (verified against the installed Lending / HRMS):
- Active loan: submitted Loan whose status is not Closed, Written Off or Settled.
- Last closure: closure_date of the latest Closed / Settled loan; when Lending left it blank,
  the loan's last submitted Loan Repayment posting date.
- Loans per year: submitted Loans with posting_date inside the company's fiscal year of the
  application's posting date (calendar year when no fiscal year is set up).
- Open application: Loan Application with status Open, not cancelled, not the one being checked.
- Counts are per company and per employee; with same_product_only, per loan product too.
- Service months: whole months from date_of_joining to the posting date.
- Missing date_of_joining / date_of_birth / final_confirmation_date that a rule needs fails with
  "Employee record incomplete: <field>"; nothing passes silently.
- Every date-based check uses the application's posting date, not today.
- Annual gross salary (Annual Salary Loan Eligibility %): gross pay of a preview Salary Slip from
  the employee's latest submitted Salary Structure Assignment on or before the posting date (full
  period, no leave-without-pay, no overtime), times the pay periods in a year (Monthly 12,
  Bimonthly 24, Fortnightly 26, Weekly 52, Daily 365). Max eligible loan = annual gross x % / 100;
  the Loan Amount must not exceed it. No assignment fails with "No Salary Structure Assignment".
  Without a loan amount (Loan Eligibility report, API without one) only the limit is shown.
"""

import frappe
from dateutil.relativedelta import relativedelta
from frappe import _
from frappe.utils import add_months, cint, escape_html, flt, fmt_money, formatdate, getdate

INACTIVE_LOAN_STATUSES = ("Closed", "Written Off", "Settled")
CLOSED_LOAN_STATUSES = ("Closed", "Settled")

# Loan Rule table -> (child doctype, child link field, value source)
# value source: "loan_product" from the application, anything else from the Employee
APPLICABILITY = {
	"loan_products": ("Loan Rule Product", "loan_product", "loan_product"),
	"employment_types": ("Loan Rule Employment Type", "employment_type", "employment_type"),
	"grades": ("Loan Rule Grade", "grade", "grade"),
	"designations": ("Loan Rule Designation", "designation", "designation"),
	"departments": ("Loan Rule Department", "department", "department"),
	"branches": ("Loan Rule Branch", "branch", "branch"),
}

EMPLOYEE_FIELDS = (
	"name",
	"employee_name",
	"company",
	"status",
	"date_of_joining",
	"date_of_birth",
	"final_confirmation_date",
	"relieving_date",
	"resignation_letter_date",
	"employment_type",
	"grade",
	"designation",
	"department",
	"branch",
)

# check keys (stable ids for reports / API) and their labels
STATUS = "status"
SERVICE = "service"
CONFIRMATION = "confirmation"
AGE = "age"
SEPARATION = "separation"
ON_LEAVE = "on_leave"
ACTIVE_LOANS = "active_loans"
OPEN_APPLICATIONS = "open_applications"
COOLING_OFF = "cooling_off"
LOANS_PER_YEAR = "loans_per_year"
SALARY_LIMIT = "salary_limit"

# Salary Structure payroll_frequency -> pay periods per year (HRMS "Bimonthly" = twice a month)
PERIODS_PER_YEAR = {"Monthly": 12, "Bimonthly": 24, "Fortnightly": 26, "Weekly": 52, "Daily": 365}

CHECK_LABELS = {
	STATUS: "Employee status",
	SERVICE: "Service",
	CONFIRMATION: "Confirmation",
	AGE: "Age",
	SEPARATION: "Separation",
	ON_LEAVE: "On leave",
	ACTIVE_LOANS: "Active loans",
	OPEN_APPLICATIONS: "Open applications",
	COOLING_OFF: "Cooling-off",
	LOANS_PER_YEAR: "Loans per year",
	SALARY_LIMIT: "Loan amount (salary limit)",
}


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


def get_applicable_rule(application):
	"""The Loan Rule (Document) that applies to a Loan Application-like object, or None.

	`application` needs company, posting_date, loan_product and applicant (employee).
	"""
	employee = get_employee(application.get("applicant"))
	if not employee:
		return None
	name = find_rule_name(
		company=application.get("company"),
		posting_date=application.get("posting_date"),
		context=build_context(employee, application.get("loan_product")),
	)
	return frappe.get_doc("Loan Rule", name) if name else None


def find_rule_name(company, posting_date, context):
	return pick_rule(candidate_rules(company, posting_date), context)


def candidate_rules(company, posting_date):
	"""Enabled rules of the company valid on posting_date, each with .applicability loaded.
	Load once and call pick_rule per employee when matching many employees (Loan Eligibility
	report, LR-08)."""
	posting_date = getdate(posting_date)
	rules = [
		r
		for r in frappe.get_all(
			"Loan Rule",
			filters={"enabled": 1, "company": company},
			fields=["name", "priority", "valid_from", "valid_upto"],
		)
		if is_valid_on(r, posting_date)
	]
	if not rules:
		return []
	applicability = load_applicability([r.name for r in rules])
	for rule in rules:
		rule.applicability = applicability.get(rule.name, {})
	return rules


def is_valid_on(rule, posting_date):
	posting_date = getdate(posting_date)
	if rule.get("valid_from") and getdate(rule["valid_from"]) > posting_date:
		return False
	if rule.get("valid_upto") and getdate(rule["valid_upto"]) < posting_date:
		return False
	return True


def load_applicability(rule_names):
	"""{rule name: {table: set(values)}} for the given rules, one query per child doctype."""
	out = {name: {table: set() for table in APPLICABILITY} for name in rule_names}
	for table, (child, field, _source) in APPLICABILITY.items():
		for row in frappe.get_all(
			child,
			filters={"parenttype": "Loan Rule", "parentfield": table, "parent": ("in", rule_names)},
			fields=["parent", field],
		):
			if row.get(field):
				out[row.parent][table].add(row.get(field))
	return out


def build_context(employee, loan_product):
	"""{table: value} the applicability lists are matched against."""
	return {
		table: (loan_product if source == "loan_product" else employee.get(source))
		for table, (_child, _field, source) in APPLICABILITY.items()
	}


def rule_matches(applicability, context):
	"""Every filled list must contain the value; blank lists match everyone."""
	return all((not values) or (context.get(table) in values) for table, values in applicability.items())


def specificity(applicability):
	return sum(1 for values in applicability.values() if values)


def pick_rule(rules, context):
	"""Name of the matching rule with the highest priority, then specificity, then name."""
	matching = [r for r in rules if rule_matches(r.applicability, context)]
	if not matching:
		return None
	matching.sort(key=lambda r: (-cint(r.priority), -specificity(r.applicability), r.name))
	return matching[0].name


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_eligibility(
	employee, loan_product, posting_date, company=None, exclude_application=None, loan_amount=None
):
	"""{"rule": Loan Rule or None, "results": [...], "eligible": bool} for one employee + product.

	With no matching rule, results is empty and eligible is True; the caller decides what
	require_loan_rule means.
	"""
	emp = get_employee(employee)
	if not emp:
		frappe.throw(_("Employee {0} not found.").format(employee))
	company = company or emp.company
	application = frappe._dict(
		applicant=employee, company=company, posting_date=posting_date, loan_product=loan_product
	)
	rule = get_applicable_rule(application)
	if not rule:
		return {"rule": None, "results": [], "eligible": True}
	results = run_checks(
		rule, employee, posting_date, loan_product, company, exclude_application, loan_amount
	)
	return {"rule": rule, "results": results, "eligible": all(r["passed"] for r in results)}


def run_checks(
	rule, employee, posting_date, loan_product, company=None, exclude_application=None, loan_amount=None
):
	emp = get_employee(employee) if isinstance(employee, str) else employee
	posting_date = getdate(posting_date)
	company = company or emp.company
	scope = loan_scope(emp.name, company, loan_product if rule.same_product_only else None)

	results = [
		check_status(emp.status),
		check_service(rule.min_service_months, emp.date_of_joining, posting_date),
		check_confirmation(rule.require_confirmation, emp.final_confirmation_date, posting_date),
		check_age(rule.min_age, rule.max_age, emp.date_of_birth, posting_date),
	]
	if rule.block_if_resignation:
		results.append(check_separation(emp, has_open_separation(emp.name)))
	if rule.block_if_on_leave:
		results.append(check_on_leave(approved_leave_on(emp.name, posting_date)))
	if cint(rule.max_active_loans):
		results.append(check_active_loans(rule.max_active_loans, count_active_loans(scope)))
	if cint(rule.max_open_applications):
		results.append(
			check_open_applications(
				rule.max_open_applications, open_applications(scope, exclude_application)
			)
		)
	if cint(rule.cooling_off_months):
		results.append(check_cooling_off(rule.cooling_off_months, last_closure_date(scope), posting_date))
	if cint(rule.max_loans_per_year):
		start, end = fiscal_year_bounds(posting_date, company)
		results.append(check_loans_per_year(rule.max_loans_per_year, count_loans_between(scope, start, end)))
	if flt(rule.get("annual_salary_loan_percent")) > 0:
		results.append(
			check_salary_limit(
				rule.annual_salary_loan_percent,
				annual_gross_salary(emp.name, posting_date, company),
				loan_amount,
				company,
			)
		)
	return [r for r in results if r]


def result(check, passed, expected, actual, message="", **extra):
	return {
		"check": check,
		"label": _(CHECK_LABELS[check]),
		"passed": bool(passed),
		"expected": expected,
		"actual": actual,
		"message": "" if passed else message,
		**extra,
	}


def incomplete(check, expected, field_label):
	return result(
		check,
		False,
		expected,
		_("Not set"),
		_("Employee record incomplete: {0}").format(_(field_label)),
	)


def check_status(status):
	return result(
		STATUS,
		status == "Active",
		_("Active"),
		_(status or "Not set"),
		_("Only Active employees can apply; employee status is {0}.").format(_(status or "Not set")),
	)


def service_months(date_of_joining, on_date):
	if getdate(date_of_joining) > getdate(on_date):
		return 0
	delta = relativedelta(getdate(on_date), getdate(date_of_joining))
	return delta.years * 12 + delta.months


def check_service(min_months, date_of_joining, posting_date):
	min_months = cint(min_months)
	if not min_months:
		return None
	expected = _("{0} months").format(min_months)
	if not date_of_joining:
		return incomplete(SERVICE, expected, "Date of Joining")
	actual = service_months(date_of_joining, posting_date)
	return result(
		SERVICE,
		actual >= min_months,
		expected,
		_("{0} months").format(actual),
		_("You need {0} months of service; you have {1}.").format(min_months, actual),
	)


def check_confirmation(required, confirmation_date, posting_date):
	if not cint(required):
		return None
	expected = _("Confirmed on or before {0}").format(formatdate(posting_date))
	if not confirmation_date:
		res = incomplete(CONFIRMATION, expected, "Final Confirmation Date")
		res["message"] += " " + _("Loan applications open after your probation is confirmed.")
		return res
	return result(
		CONFIRMATION,
		getdate(confirmation_date) <= getdate(posting_date),
		expected,
		formatdate(confirmation_date),
		_("Loan applications open after your probation is confirmed."),
	)


def age_on(date_of_birth, on_date):
	return relativedelta(getdate(on_date), getdate(date_of_birth)).years


def check_age(min_age, max_age, date_of_birth, posting_date):
	min_age, max_age = cint(min_age), cint(max_age)
	if not (min_age or max_age):
		return None
	if min_age and max_age:
		expected = _("{0} to {1} years").format(min_age, max_age)
		message = _("Applicant age must be between {0} and {1}.").format(min_age, max_age)
	elif min_age:
		expected = _("At least {0} years").format(min_age)
		message = _("Applicant must be at least {0} years old.").format(min_age)
	else:
		expected = _("At most {0} years").format(max_age)
		message = _("Applicant must be at most {0} years old.").format(max_age)
	if not date_of_birth:
		return incomplete(AGE, expected, "Date of Birth")
	age = age_on(date_of_birth, posting_date)
	passed = (not min_age or age >= min_age) and (not max_age or age <= max_age)
	return result(AGE, passed, expected, _("{0} years").format(age), message)


def check_separation(employee, open_separation):
	reasons = []
	if employee.get("resignation_letter_date"):
		reasons.append(_("Resignation Letter Date {0}").format(formatdate(employee.resignation_letter_date)))
	if employee.get("relieving_date"):
		reasons.append(_("Relieving Date {0}").format(formatdate(employee.relieving_date)))
	if open_separation:
		reasons.append(_("Employee Separation {0}").format(open_separation))
	return result(
		SEPARATION,
		not reasons,
		_("No resignation or separation"),
		", ".join(reasons) or _("None"),
		_("Not allowed while a resignation or separation is in progress."),
	)


def check_on_leave(leave):
	"""leave: {"name", "from_date", "to_date"} of an approved leave covering the date, or None."""
	if not leave:
		return result(ON_LEAVE, True, _("Not on approved leave"), _("Not on leave"))
	period = (formatdate(leave["from_date"]), formatdate(leave["to_date"]))
	return result(
		ON_LEAVE,
		False,
		_("Not on approved leave"),
		_("{0} ({1} to {2})").format(leave["name"], *period),
		_("Not allowed while on approved leave ({0} to {1}).").format(*period),
	)


def check_active_loans(max_loans, active_count):
	max_loans = cint(max_loans)
	return result(
		ACTIVE_LOANS,
		active_count < max_loans,
		_("Fewer than {0}").format(max_loans),
		str(active_count),
		_("You already have {0} active loan(s); the limit is {1}.").format(active_count, max_loans),
	)


def check_open_applications(max_open, names):
	max_open = cint(max_open)
	return result(
		OPEN_APPLICATIONS,
		len(names) < max_open,
		_("Fewer than {0}").format(max_open),
		", ".join(names) or "0",
		_("You already have an open application: {0}.").format(", ".join(names)),
	)


def check_cooling_off(months, closed_on, posting_date):
	months = cint(months)
	expected = _("{0} months after the last loan closed").format(months)
	if not closed_on:
		return result(COOLING_OFF, True, expected, _("No closed loan"))
	eligible_from = getdate(add_months(closed_on, months))
	return result(
		COOLING_OFF,
		getdate(posting_date) >= eligible_from,
		expected,
		_("Last loan closed {0}").format(formatdate(closed_on)),
		_("You can apply again from {0}, {1} months after your last loan closed.").format(
			formatdate(eligible_from), months
		),
		eligible_from=str(eligible_from),  # next eligible date (Loan Eligibility report, API)
	)


def check_loans_per_year(max_loans, count):
	max_loans = cint(max_loans)
	return result(
		LOANS_PER_YEAR,
		count < max_loans,
		_("Fewer than {0}").format(max_loans),
		str(count),
		_("Limit of {0} loans per fiscal year reached.").format(max_loans),
	)


def check_salary_limit(percent, annual_gross, loan_amount=None, company=None):
	"""percent of annual gross salary = the most the employee may borrow. annual_gross None = no
	Salary Structure Assignment. loan_amount None = no amount to compare (only the limit is shown)."""
	percent = flt(percent)
	pct = f"{percent:g}"  # 50 not 50.0
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None

	def money(value):
		return fmt_money(value, currency=currency)

	if annual_gross is None:
		return result(
			SALARY_LIMIT,
			False,
			_("{0}% of annual gross salary").format(pct),
			_("No salary"),
			_("No Salary Structure Assignment for the employee on the posting date; the loan limit "
			  "({0}% of annual gross salary) cannot be worked out.").format(pct),
		)
	max_amount = flt(annual_gross * percent / 100, 2)
	expected = _("Up to {0} ({1}% of annual gross {2})").format(money(max_amount), pct, money(annual_gross))
	if loan_amount is None:
		return result(
			SALARY_LIMIT, True, expected, _("Max eligible {0}").format(money(max_amount)),
			max_eligible_amount=max_amount,
		)
	loan_amount = flt(loan_amount)
	return result(
		SALARY_LIMIT,
		loan_amount <= max_amount,
		expected,
		money(loan_amount),
		_("Loan Amount {0} is more than the maximum eligible {1} ({2}% of annual gross salary {3}).").format(
			money(loan_amount), money(max_amount), pct, money(annual_gross)
		),
		max_eligible_amount=max_amount,
	)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def get_employee(employee):
	if not employee:
		return None
	return frappe.db.get_value("Employee", employee, EMPLOYEE_FIELDS, as_dict=True)


def loan_scope(employee, company, loan_product=None):
	scope = {"applicant_type": "Employee", "applicant": employee, "company": company}
	if loan_product:
		scope["loan_product"] = loan_product
	return scope


def count_active_loans(scope):
	return frappe.db.count(
		"Loan", dict(scope, docstatus=1, status=("not in", INACTIVE_LOAN_STATUSES))
	)


def open_applications(scope, exclude=None):
	filters = dict(scope, status="Open", docstatus=("!=", 2))
	if exclude:
		filters["name"] = ("!=", exclude)
	return frappe.get_all("Loan Application", filters=filters, pluck="name", order_by="creation asc")


def last_closure_date(scope):
	loans = frappe.get_all(
		"Loan",
		filters=dict(scope, docstatus=1, status=("in", CLOSED_LOAN_STATUSES)),
		fields=["name", "closure_date"],
	)
	dates = [getdate(l.closure_date) for l in loans if l.closure_date]
	missing = [l.name for l in loans if not l.closure_date]
	if missing:
		last_repayment = frappe.get_all(
			"Loan Repayment",
			filters={"against_loan": ("in", missing), "docstatus": 1},
			pluck="posting_date",
			order_by="posting_date desc",
			limit=1,
		)
		if last_repayment and last_repayment[0]:
			dates.append(getdate(last_repayment[0]))
	return max(dates) if dates else None


def count_loans_between(scope, start, end):
	return frappe.db.count("Loan", dict(scope, docstatus=1, posting_date=("between", [start, end])))


def fiscal_year_bounds(posting_date, company):
	from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

	try:
		_name, start, end = get_fiscal_year(posting_date, company=company)[:3]
		return getdate(start), getdate(end)
	except FiscalYearError:
		posting_date = getdate(posting_date)
		return posting_date.replace(month=1, day=1), posting_date.replace(month=12, day=31)


def annual_gross_salary(employee, posting_date, company=None):
	"""Annual gross salary on posting_date, or None without a submitted Salary Structure Assignment.

	Built like HRMS's salary slip preview (Salary Structure > Preview Salary Slip) but without its
	Employee read-permission check: Loan users (Accounts, Loan Manager) cannot read Employee and
	only the total is used here, never shown slip by slip. Cached per request."""
	posting_date = getdate(posting_date)
	key = (employee, str(posting_date), company)
	cache = getattr(frappe.local, "alt_annual_gross_salary", None)
	if cache is None:
		cache = frappe.local.alt_annual_gross_salary = {}
	if key in cache:
		return cache[key]

	filters = {"employee": employee, "docstatus": 1, "from_date": ("<=", posting_date)}
	if company:
		filters["company"] = company
	structure = frappe.db.get_value(
		"Salary Structure Assignment", filters, "salary_structure", order_by="from_date desc"
	)
	annual = None
	if structure:
		from frappe.model.mapper import get_mapped_doc

		def postprocess(source, target):
			target.employee = employee
			target.posting_date = posting_date
			target.start_date = posting_date
			target.run_method("process_salary_structure", for_preview=1)

		slip = get_mapped_doc(
			"Salary Structure",
			structure,
			{
				"Salary Structure": {
					"doctype": "Salary Slip",
					"field_map": {"total_earning": "gross_pay", "name": "salary_structure", "currency": "currency"},
				}
			},
			None,
			postprocess,
			ignore_permissions=True,
			ignore_child_tables=True,
			cached=True,
		)
		periods = PERIODS_PER_YEAR.get(slip.payroll_frequency or "Monthly", 12)
		# full-period earnings (default_amount is the amount before leave-without-pay), counted as
		# HRMS counts gross pay: statistical / "do not include in total" components left out
		gross = sum(
			flt(row.default_amount) or flt(row.amount)
			for row in slip.earnings
			if not (row.get("statistical_component") or row.get("do_not_include_in_total"))
		)
		annual = flt(gross * periods, 2)
	cache[key] = annual
	return annual


def has_open_separation(employee):
	return frappe.db.get_value(
		"Employee Separation",
		{"employee": employee, "docstatus": ("!=", 2), "boarding_status": ("!=", "Completed")},
		"name",
	)


def approved_leave_on(employee, on_date):
	return frappe.db.get_value(
		"Leave Application",
		{
			"employee": employee,
			"status": "Approved",
			"docstatus": 1,
			"from_date": ("<=", on_date),
			"to_date": (">=", on_date),
		},
		["name", "from_date", "to_date"],
		as_dict=True,
	)


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def failure_messages(results):
	return [r["message"] for r in results if not r["passed"]]


def render_results_html(rule, results, status=None):
	"""Check list stored in Loan Application.eligibility_result (read-only Long Text)."""
	rows = "".join(
		"<tr><td>{label}</td><td>{expected}</td><td>{actual}</td><td>{icon}</td></tr>".format(
			label=escape_html(r["label"]),
			expected=escape_html(r["expected"]),
			actual=escape_html(r["actual"]),
			icon=(
				'<span class="indicator-pill green">' + escape_html(_("Passed")) + "</span>"
				if r["passed"]
				else '<span class="indicator-pill red">' + escape_html(_("Failed")) + "</span>"
			),
		)
		for r in results
	)
	header = _("Loan Rule {0} ({1})").format(escape_html(rule.name), escape_html(_(rule.enforcement)))
	if status:
		header += " &middot; " + escape_html(_(status))
	return (
		f'<div class="loan-eligibility-result"><p><b>{header}</b></p>'
		'<table class="table table-bordered table-sm"><thead><tr>'
		f"<th>{escape_html(_('Check'))}</th><th>{escape_html(_('Required'))}</th>"
		f"<th>{escape_html(_('Actual'))}</th><th>{escape_html(_('Result'))}</th>"
		f"</tr></thead><tbody>{rows}</tbody></table></div>"
	)
