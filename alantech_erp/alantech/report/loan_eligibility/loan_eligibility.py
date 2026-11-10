# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Loan Eligibility (LR-08): one row per active employee with the Loan Rule that would apply to a
loan application today (or on As On Date) and whether the employee would pass it.

ClickUp: https://app.clickup.com/t/14yr2e57ghm (parent 14yr2e57ghb)

Columns: employee, name, department, grade, matched Loan Rule, Eligible (Yes / No), first failed
reason, next eligible date (cooling-off: last loan closed + the rule's cooling-off months).
Filters: Company and Loan Product (required; a rule limited to products only matches a chosen
product, so a blank product would show "No Loan Rule" for everyone; the form picks the product
when the company has just one), Department (with its sub-departments), As On Date.

Same engine as the Loan Application check (loan_rules/engine.py): the rules are loaded once, then
matched and checked per employee. No matching rule = Eligible No, reason "No Loan Rule applies"
(such an application cannot be submitted). A Warn rule that fails is also No (the application
would be saved as Not Eligible).

Access: ref_doctype Loan Rule, roles HR Manager / Loan Manager / System Manager (report
permission on Loan Rule); employees only read Loan Rules and cannot open it.
"""

import frappe
from frappe import _
from frappe.utils import getdate, today
from frappe.utils.nestedset import get_descendants_of

from alantech_erp.loan_rules import engine

YES, NO = "Yes", "No"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Please select a Company."))
	# rules are usually limited to products; without one, those rules would match nobody
	if not filters.loan_product:
		frappe.throw(_("Please select a Loan Product."))
	filters.as_on_date = getdate(filters.as_on_date or today())
	data = get_data(filters)
	return get_columns(), data, None, None, get_summary(data)


def get_columns():
	return [
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 130},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "department", "label": _("Department"), "fieldtype": "Link", "options": "Department", "width": 160},
		{"fieldname": "grade", "label": _("Grade"), "fieldtype": "Link", "options": "Employee Grade", "width": 100},
		{"fieldname": "loan_rule", "label": _("Loan Rule"), "fieldtype": "Link", "options": "Loan Rule", "width": 170},
		{"fieldname": "eligible", "label": _("Eligible"), "fieldtype": "Data", "width": 80},
		{"fieldname": "failed_reason", "label": _("First Failed Reason"), "fieldtype": "Data", "width": 320},
		{"fieldname": "next_eligible_date", "label": _("Next Eligible Date"), "fieldtype": "Date", "width": 130},
	]


def get_employees(filters):
	conditions = {"status": "Active", "company": filters.company}
	if filters.department:
		conditions["department"] = ("in", [filters.department, *get_descendants_of("Department", filters.department)])
	return frappe.get_all("Employee", filters=conditions, fields=list(engine.EMPLOYEE_FIELDS), order_by="name")


def get_data(filters):
	rules = engine.candidate_rules(filters.company, filters.as_on_date)
	rule_docs = {}
	data = []
	for emp in get_employees(filters):
		row = {
			"employee": emp.name,
			"employee_name": emp.employee_name,
			"department": emp.department,
			"grade": emp.grade,
		}
		name = engine.pick_rule(rules, engine.build_context(emp, filters.loan_product))
		if not name:
			row.update(eligible=NO, failed_reason=_("No Loan Rule applies"))
			data.append(row)
			continue
		rule = rule_docs.get(name) or rule_docs.setdefault(name, frappe.get_doc("Loan Rule", name))
		results = engine.run_checks(rule, emp, filters.as_on_date, filters.loan_product, filters.company)
		failures = engine.failure_messages(results)
		cooling_off = next((r for r in results if r["check"] == engine.COOLING_OFF), None)
		row.update(
			loan_rule=name,
			eligible=NO if failures else YES,
			failed_reason=failures[0] if failures else None,
			next_eligible_date=(
				cooling_off.get("eligible_from") if cooling_off and not cooling_off["passed"] else None
			),
		)
		data.append(row)
	return data


def get_summary(data):
	eligible = sum(1 for r in data if r["eligible"] == YES)
	no_rule = sum(1 for r in data if not r.get("loan_rule"))
	return [
		{"label": _("Eligible"), "value": eligible, "indicator": "Green", "datatype": "Int"},
		{"label": _("Not Eligible"), "value": len(data) - eligible - no_rule, "indicator": "Red", "datatype": "Int"},
		{"label": _("No Loan Rule"), "value": no_rule, "indicator": "Orange", "datatype": "Int"},
	]
