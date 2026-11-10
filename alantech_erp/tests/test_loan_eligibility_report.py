# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Loan Eligibility script report (LR-08, ClickUp 14yr2e57ghm;
alantech/report/loan_eligibility): one row per active employee with the matched Loan Rule,
Eligible Yes / No, first failed reason and next eligible date (cooling-off); filters Company,
Loan Product, Department (with sub-departments), As On Date; summary counts; report access.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_eligibility_report

Data: same as test_loan_rule_eligibility (one active employee without loan applications, test Loan
Rules / Loan Product / Loans with prefix ZZ-LR05), in a savepoint per test that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, getdate, today

from alantech_erp.alantech.report.loan_eligibility.loan_eligibility import execute

# module import: importing the TestCase class itself would make the runner collect that suite here
from alantech_erp.tests import test_loan_rule_eligibility as lr05

REPORT = "Loan Eligibility"


class TestLoanEligibilityReport(IntegrationTestCase):
	# record helpers shared with the LR-04/05 suite
	set_employee = lr05.TestLoanRuleEligibility.set_employee
	make_product = lr05.TestLoanRuleEligibility.make_product
	make_rule = lr05.TestLoanRuleEligibility.make_rule
	raw = lr05.TestLoanRuleEligibility.raw
	loan = lr05.TestLoanRuleEligibility.loan

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.emp = lr05.pick_employee()

	def setUp(self):
		if not self.emp:
			self.skipTest("No active employee without loan applications on this site")
		frappe.set_user("Administrator")
		frappe.db.savepoint("lr08")
		self.addCleanup(frappe.db.rollback, save_point="lr08")
		self.addCleanup(frappe.set_user, "Administrator")

		self.today = getdate(today())
		self.company = self.emp.company
		self.counter = 0
		frappe.db.set_value("Loan Rule", {"enabled": 1}, "enabled", 0)
		self.set_employee(
			status="Active",
			date_of_joining=add_months(self.today, -24),
			final_confirmation_date=add_months(self.today, -18),
			date_of_birth=add_months(self.today, -30 * 12),
			relieving_date=None,
			resignation_letter_date=None,
		)
		self.product = self.make_product("PL")

	def run_report(self, **filters):
		filters = dict({"company": self.company, "loan_product": self.product}, **filters)
		columns, data, _message, _chart, summary = execute(filters)
		return columns, data, summary

	def row(self, **filters):
		rows = [r for r in self.run_report(**filters)[1] if r["employee"] == self.emp.name]
		return rows[0] if rows else None

	# ---------------------------------------------------------------- columns and filters

	def test_columns(self):
		columns = self.run_report()[0]
		self.assertEqual(
			[c["fieldname"] for c in columns],
			[
				"employee",
				"employee_name",
				"department",
				"grade",
				"loan_rule",
				"eligible",
				"failed_reason",
				"next_eligible_date",
			],
		)

	def test_company_and_loan_product_required(self):
		self.assertRaisesRegex(frappe.ValidationError, "Please select a Company", execute, {})
		self.assertRaisesRegex(
			frappe.ValidationError, "Please select a Loan Product", execute, {"company": self.company}
		)

	def test_one_row_per_active_employee(self):
		_columns, data, _summary = self.run_report()
		names = [r["employee"] for r in data]
		self.assertEqual(len(names), len(set(names)))
		self.assertEqual(
			set(names), set(frappe.get_all("Employee", {"status": "Active", "company": self.company}, pluck="name"))
		)
		self.set_employee(status="Left")
		self.assertIsNone(self.row())

	def test_department_filter_includes_sub_departments(self):
		departments = frappe.get_all(
			"Department", filters={"company": self.company, "is_group": 0}, pluck="name", limit=2
		)
		if len(departments) < 2:
			self.skipTest("Needs two departments for the company")
		own, other = departments
		self.set_employee(department=own)
		self.assertIsNotNone(self.row(department=own))
		self.assertIsNone(self.row(department=other))
		parent = frappe.db.get_value("Department", own, "parent_department")
		if parent:
			self.assertIsNotNone(self.row(department=parent))

	# ---------------------------------------------------------------- eligibility values

	def test_eligible_employee(self):
		rule = self.make_rule(min_service_months=12)
		row = self.row()
		self.assertEqual(row["loan_rule"], rule.name)
		self.assertEqual(row["eligible"], "Yes")
		self.assertFalse(row["failed_reason"])
		self.assertFalse(row["next_eligible_date"])

	def test_first_failed_reason(self):
		self.make_rule(min_service_months=36, require_confirmation=1)
		self.set_employee(final_confirmation_date=None)
		row = self.row()
		self.assertEqual(row["eligible"], "No")
		# checks run in a fixed order: status, service, confirmation, ...
		self.assertEqual(row["failed_reason"], "You need 36 months of service; you have 24.")

	def test_warn_rule_failure_is_not_eligible(self):
		self.make_rule(min_service_months=36, enforcement="Warn")
		self.assertEqual(self.row()["eligible"], "No")

	def test_no_rule(self):
		row = self.row()
		self.assertFalse(row.get("loan_rule"))
		self.assertEqual(row["eligible"], "No")
		self.assertEqual(row["failed_reason"], "No Loan Rule applies")

	def test_next_eligible_date_from_cooling_off(self):
		self.make_rule(cooling_off_months=6)
		closed_on = add_months(self.today, -2)
		self.loan(status="Closed", closure_date=closed_on)
		row = self.row()
		self.assertEqual(row["eligible"], "No")
		self.assertIn("You can apply again from", row["failed_reason"])
		self.assertEqual(getdate(row["next_eligible_date"]), getdate(add_months(closed_on, 6)))

	def test_loan_product_filter_decides_the_rule(self):
		other = self.make_product("HL")
		rule = self.make_rule(loan_products=[{"loan_product": other}])
		self.assertFalse(self.row().get("loan_rule"))  # PL
		self.assertEqual(self.row(loan_product=other)["loan_rule"], rule.name)

	def test_as_on_date(self):
		tomorrow = add_days(self.today, 1)
		rule = self.make_rule(valid_from=tomorrow)
		self.assertFalse(self.row().get("loan_rule"))
		self.assertEqual(self.row(as_on_date=str(tomorrow))["loan_rule"], rule.name)

	def test_summary_counts(self):
		self.make_rule()
		_columns, data, summary = self.run_report()
		counts = {s["label"]: s["value"] for s in summary}
		self.assertEqual(counts["Eligible"], sum(1 for r in data if r["eligible"] == "Yes"))
		self.assertEqual(counts["No Loan Rule"], sum(1 for r in data if not r.get("loan_rule")))
		self.assertEqual(sum(counts.values()), len(data))

	# ---------------------------------------------------------------- access

	def report_user(self, key, *roles):
		return (
			frappe.get_doc(
				{
					"doctype": "User",
					"email": f"zz.lr08.{key}@example.com",
					"first_name": f"ZZ LR08 {key}",
					"send_welcome_email": 0,
					"roles": [{"role": r} for r in roles],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_access(self):
		from frappe.desk.query_report import run

		filters = {"company": self.company, "loan_product": self.product}
		for role in ("HR Manager", "Loan Manager"):
			with self.subTest(role=role):
				frappe.set_user("Administrator")
				frappe.set_user(self.report_user(role.lower().replace(" ", ""), role))
				self.assertTrue(run(REPORT, filters)["result"])
		frappe.set_user("Administrator")
		frappe.set_user(self.report_user("emp", "Employee"))
		self.assertRaises(frappe.PermissionError, run, REPORT, filters)
