# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Loan Eligibility fields on Loan Application (LR-03, ClickUp 14yr2e57ghf;
setup/loan_application_fields.py): field types and read-only / mandatory rules, placement after the
applicant fields, Employee-only visibility, no_copy + allow_on_submit, setup re-run, and the values
saving on a real Employee application, also after submit.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_application_fields

The record test creates a Loan Demand Offset Order, a Loan Product and a Loan Application for an
active employee inside a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from alantech_erp.setup.loan_application_fields import (
	CUSTOM_FIELDS,
	DOCTYPE,
	ELIGIBILITY_STATUSES,
	ELIGIBLE,
	IS_EMPLOYEE,
	OVERRIDDEN,
	REPAYMENT_MANDATORY,
	execute,
)
from alantech_erp.loan_rules.loan_application import CHECK_RESULT_FIELDS, OverrideReasonMissingError

READ_ONLY = ("loan_rule", "eligibility_status", "eligibility_result", "overridden_by", "overridden_on")
PREFIX = "ZZ LR03"


def meta_field(fieldname):
	return frappe.get_meta(DOCTYPE).get_field(fieldname)


def make_application(employee, company):
	order = frappe.get_doc(
		{
			"doctype": "Loan Demand Offset Order",
			"title": f"{PREFIX} Offset Order",
			"components": [{"demand_type": t} for t in ("Penalty", "Interest", "Principal")],
		}
	).insert()
	product = frappe.get_doc(
		{
			"doctype": "Loan Product",
			"product_code": f"{PREFIX}-PL",
			"product_name": f"{PREFIX} Personal Loan",
			"company": company,
			"rate_of_interest": 4,
			"maximum_loan_amount": 100000,
			"collection_offset_sequence_for_standard_asset": order.name,
			"collection_offset_sequence_for_sub_standard_asset": order.name,
		}
	).insert()
	return frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"applicant_type": "Employee",
			"applicant": employee,
			"company": company,
			"posting_date": today(),
			"loan_product": product.name,
			"loan_amount": 50000,
		}
	)


def make_open_rule(employee):
	"""An enabled Loan Rule with no limits for the employee's company: the employee is Eligible."""
	frappe.db.set_value("Employee", employee.name, "status", "Active", update_modified=False)
	rule = frappe.new_doc("Loan Rule")
	rule.update(
		{
			"rule_name": f"{PREFIX} Open Rule",
			"company": employee.company,
			"max_active_loans": 0,
			"max_open_applications": 0,
			"allow_override": 1,
			"override_role": "HR Manager",
		}
	)
	return rule.insert()


class TestLoanApplicationFields(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("loan_app_fields")
		self.addCleanup(frappe.db.rollback, save_point="loan_app_fields")
		# the site's own Loan Rules / Require Loan Rule must not decide these record tests
		frappe.db.set_value("Loan Rule", {"enabled": 1}, "enabled", 0)
		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 0)

	def test_field_types(self):
		expected = {
			"loan_eligibility_section": ("Section Break", None),
			# HTML keeps the section visible while the read-only fields are empty
			"eligibility_note": ("HTML", None),
			"loan_rule": ("Link", "Loan Rule"),
			"eligibility_status": ("Select", "\nEligible\nNot Eligible\nOverridden"),
			"eligibility_result": ("Long Text", None),
			"rule_override": ("Check", None),
			"override_reason": ("Small Text", None),
			"overridden_by": ("Link", "User"),
			"overridden_on": ("Datetime", None),
		}
		for fieldname, (fieldtype, options) in expected.items():
			with self.subTest(fieldname=fieldname):
				field = meta_field(fieldname)
				self.assertIsNotNone(field)
				self.assertEqual(field.fieldtype, fieldtype)
				if options:
					self.assertEqual(field.options, options)
		self.assertEqual(ELIGIBILITY_STATUSES, ("Eligible", "Not Eligible", "Overridden"))

	def test_read_only_and_editable(self):
		for fieldname in READ_ONLY:
			with self.subTest(fieldname=fieldname):
				self.assertTrue(meta_field(fieldname).read_only)
		self.assertFalse(meta_field("rule_override").read_only)
		self.assertFalse(meta_field("override_reason").read_only)

	def test_repayment_fields_mandatory_only_for_term_loans(self):
		"""Same conditions as Lending's validate_repayment_method, which runs only when is_term_loan
		(set by the Loan Product); before a product is picked the fields are hidden and not required.
		mandatory_depends_on is evaluated by the form only (JS expression)."""
		periods = meta_field("repayment_periods").mandatory_depends_on
		amount = meta_field("repayment_amount").mandatory_depends_on
		self.assertEqual(periods, "eval:doc.is_term_loan && doc.repayment_method == 'Repay Over Number of Periods'")
		self.assertEqual(amount, "eval:doc.is_term_loan && doc.repayment_method == 'Repay Fixed Amount per Period'")
		self.assertEqual(REPAYMENT_MANDATORY, {"repayment_periods": periods, "repayment_amount": amount})
		# why is_term_loan is in the condition: a new application already has this default
		app = frappe.new_doc(DOCTYPE)
		self.assertEqual(app.repayment_method, "Repay Over Number of Periods")
		self.assertFalse(app.is_term_loan)

	def test_employee_only_applicants(self):
		app_meta = frappe.get_meta(DOCTYPE)
		applicant_type = app_meta.get_field("applicant_type")
		self.assertEqual(applicant_type.options, "Employee")
		self.assertEqual(applicant_type.default, "Employee")
		self.assertTrue(applicant_type.read_only)
		self.assertTrue(app_meta.get_field("applicant").reqd)
		self.assertEqual(frappe.new_doc(DOCTYPE).applicant_type, "Employee")

		loan_type = frappe.get_meta("Loan").get_field("applicant_type")
		self.assertEqual(loan_type.options, "Employee")
		self.assertEqual(loan_type.default, "Employee")

	def test_override_reason_mandatory_when_overridden(self):
		field = meta_field("override_reason")
		self.assertEqual(field.mandatory_depends_on, "eval:doc.rule_override")
		self.assertEqual(field.depends_on, "eval:doc.rule_override")

	def test_section_collapsible_employee_only(self):
		section = meta_field("loan_eligibility_section")
		self.assertTrue(section.collapsible)
		self.assertEqual(section.depends_on, IS_EMPLOYEE)
		self.assertEqual(section.label, "Loan Eligibility")

	def test_placed_after_applicant_fields(self):
		order = [f.fieldname for f in frappe.get_meta(DOCTYPE).fields]
		section = order.index("loan_eligibility_section")
		self.assertLess(order.index("applicant"), section)
		self.assertLess(order.index("company"), section)
		self.assertLess(section, order.index("loan_product"))
		ours = [f["fieldname"] for f in CUSTOM_FIELDS[DOCTYPE]]
		self.assertEqual(order[section : section + len(ours)], ours)

	def test_no_copy_and_allow_on_submit(self):
		for row in CUSTOM_FIELDS[DOCTYPE]:
			with self.subTest(fieldname=row["fieldname"]):
				field = meta_field(row["fieldname"])
				self.assertTrue(field.no_copy)
				self.assertTrue(field.allow_on_submit)

	def test_setup_rerun_is_idempotent(self):
		execute()
		execute()
		for row in CUSTOM_FIELDS[DOCTYPE]:
			self.assertEqual(
				frappe.db.count("Custom Field", {"dt": DOCTYPE, "fieldname": row["fieldname"]}), 1
			)

	def test_values_saved_on_employee_application(self):
		employee = frappe.db.get_value("Employee", {"status": "Active"}, ["name", "company"], as_dict=True)
		if not employee:
			self.skipTest("No active employee on this site")
		# the engine (LR-04/05) fills the fields; a rule with no limits makes the employee Eligible
		rule = make_open_rule(employee)
		app = make_application(employee.name, employee.company)
		app.insert()
		saved = frappe.get_doc(DOCTYPE, app.name)
		self.assertEqual(saved.loan_rule, rule.name)
		self.assertEqual(saved.eligibility_status, ELIGIBLE)
		self.assertIn("loan-eligibility-result", saved.eligibility_result)

		# copy (duplicate / amend) starts with blank eligibility fields
		copy = frappe.copy_doc(saved, ignore_no_copy=False)
		self.assertFalse(copy.eligibility_status)
		self.assertFalse(copy.eligibility_result)

		# after submit the fields can still change: a failing check overridden on approval
		saved.submit()
		frappe.db.set_value("Loan Rule", rule.name, "min_service_months", 9999)
		saved.reload()
		saved.update(
			{
				"status": "Approved",
				"rule_override": 1,
				"override_reason": "Approved by HR for medical emergency",
			}
		)
		saved.save()
		saved.reload()
		self.assertEqual(saved.eligibility_status, OVERRIDDEN)
		self.assertEqual(saved.overridden_by, "Administrator")
		self.assertTrue(saved.overridden_on)

	def test_check_results_kept_after_submit_without_recheck(self):
		"""eligibility_result is rendered as HTML on the form: after submit, an update that does not
		re-run the check (no approval, no override change) cannot replace the stored results."""
		employee = frappe.db.get_value("Employee", {"status": "Active"}, ["name", "company"], as_dict=True)
		if not employee:
			self.skipTest("No active employee on this site")
		rule = make_open_rule(employee)
		app = make_application(employee.name, employee.company)
		app.insert()
		app.submit()
		checked = {f: app.get(f) for f in CHECK_RESULT_FIELDS}
		self.assertEqual(checked["loan_rule"], rule.name)
		self.assertEqual(checked["eligibility_status"], ELIGIBLE)

		app.reload()
		app.update(
			{
				"loan_rule": None,
				"eligibility_status": OVERRIDDEN,
				"eligibility_result": "<img src=x onerror=alert(1)>",
			}
		)
		app.save()
		app.reload()
		for field, value in checked.items():
			with self.subTest(field=field):
				self.assertEqual(app.get(field), value)

		# a re-check on approval still updates them
		frappe.db.set_value("Loan Rule", rule.name, "min_service_months", 9999)
		app.reload()
		app.update({"status": "Approved", "rule_override": 1, "override_reason": "Approved by HR"})
		app.save()
		app.reload()
		self.assertEqual(app.eligibility_status, OVERRIDDEN)
		self.assertIn("loan-eligibility-result", app.eligibility_result)
		self.assertNotEqual(app.eligibility_result, checked["eligibility_result"])

	def test_override_reason_required_when_ticked(self):
		employee = frappe.db.get_value("Employee", {"status": "Active"}, ["name", "company"], as_dict=True)
		if not employee:
			self.skipTest("No active employee on this site")
		app = make_application(employee.name, employee.company)
		app.rule_override = 1
		app.override_reason = "   "
		self.assertRaisesRegex(OverrideReasonMissingError, "Enter an Override Reason", app.insert)
		app.override_reason = "Approved by HR"
		app.insert()
