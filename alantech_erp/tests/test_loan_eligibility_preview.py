# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Eligibility API and live preview on Loan Application (LR-07 ClickUp 14yr2e57ghk, LR-06
14yr2e57ghj; loan_rules/api.py + public/js/loan_application.js): check_loan_eligibility returns what
the save would decide without saving (matched rule, overall status, per-check results), the Block /
Warn / no-rule outcomes, the open-application exclusion, access (employee: only self, also without
passing employee; HR Manager / HR User / Loan Manager: anyone), the Override Role check behind the
Override Loan Rule checkbox, and the field setup the form script relies on.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_eligibility_preview

Data: same as test_loan_rule_eligibility (one active employee without loan applications, test Loan
Rules / Loan Product with prefix ZZ-LR05), in a savepoint per test that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, getdate, today

from alantech_erp.loan_rules.api import (
	NO_LOAN_RULE,
	LoanEligibilityAccessError,
	can_override_loan_rule,
	check_loan_eligibility,
	preview_note,
)
from alantech_erp.setup.loan_application_fields import ELIGIBLE, IS_EMPLOYEE, NOT_ELIGIBLE
from alantech_erp.setup.loan_rule_settings import no_rule_message
# module import: importing the TestCase class itself would make the runner collect that suite here
from alantech_erp.tests import test_loan_rule_eligibility as lr05


class TestLoanEligibilityPreview(IntegrationTestCase):
	# record helpers shared with the LR-04/05 suite
	set_employee = lr05.TestLoanRuleEligibility.set_employee
	make_product = lr05.TestLoanRuleEligibility.make_product
	make_rule = lr05.TestLoanRuleEligibility.make_rule
	application = lr05.TestLoanRuleEligibility.application

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.emp = lr05.pick_employee()

	def setUp(self):
		if not self.emp:
			self.skipTest("No active employee without loan applications on this site")
		frappe.set_user("Administrator")
		frappe.db.savepoint("lr06")
		self.addCleanup(frappe.db.rollback, save_point="lr06")
		self.addCleanup(frappe.set_user, "Administrator")

		self.today = getdate(today())
		self.company = self.emp.company
		frappe.db.set_value("Loan Rule", {"enabled": 1}, "enabled", 0)
		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 0)
		self.set_employee(
			status="Active",
			date_of_joining=add_months(self.today, -24),
			final_confirmation_date=add_months(self.today, -18),
			date_of_birth=add_months(self.today, -30 * 12),
			relieving_date=None,
			resignation_letter_date=None,
		)
		self.product = self.make_product("PL")

	def preview(self, **kw):
		args = dict(
			employee=self.emp.name, loan_product=self.product, posting_date=str(self.today), company=self.company
		)
		args.update(kw)
		return check_loan_eligibility(**args)

	# ---------------------------------------------------------------- outcomes

	def test_eligible_matches_what_save_stores(self):
		rule = self.make_rule(min_service_months=12, allow_override=1, override_role="HR Manager")
		before = frappe.db.count("Loan Application")
		data = self.preview()
		self.assertEqual(frappe.db.count("Loan Application"), before)  # nothing saved
		self.assertEqual(data["rule"], rule.name)
		self.assertTrue(data["eligible"])
		self.assertFalse(data["blocked"])
		self.assertEqual(data["status"], ELIGIBLE)
		self.assertEqual(data["failures"], [])
		self.assertIn("loan-eligibility-result", data["html"])
		self.assertIn("Preview: the application meets this rule.", data["html"])

		app = self.application().insert()
		self.assertEqual(app.loan_rule, data["rule"])
		self.assertEqual(app.eligibility_status, data["status"])

	def test_block_rule_failing(self):
		self.make_rule(min_service_months=36, allow_override=1, override_role="HR Manager")
		data = self.preview()
		self.assertFalse(data["eligible"])
		self.assertTrue(data["blocked"])
		self.assertEqual(data["status"], NOT_ELIGIBLE)
		self.assertEqual(data["failures"], ["You need 36 months of service; you have 24."])
		self.assertEqual(
			data["message"], "Preview: saving will be blocked unless the Loan Rule is overridden."
		)
		self.assertTrue(data["allow_override"])
		self.assertTrue(data["can_override"])  # Administrator holds HR Manager
		self.assertIn("indicator-pill red", data["html"])

	def test_warn_rule_failing_is_not_blocked(self):
		self.make_rule(min_service_months=36, enforcement="Warn")
		data = self.preview()
		self.assertFalse(data["eligible"])
		self.assertFalse(data["blocked"])
		self.assertEqual(data["message"], "Preview: the application can be saved, as Not Eligible.")
		self.assertFalse(data["can_override"])

	def test_no_rule(self):
		data = self.preview()
		self.assertIsNone(data["rule"])
		self.assertEqual(data["status"], NO_LOAN_RULE)
		self.assertEqual(data["results"], [])
		self.assertFalse(data["eligible"])  # a draft without a rule can never be submitted
		self.assertFalse(data["blocked"])  # but it can be saved while Require Loan Rule is off
		self.assertEqual(
			data["message"], "No Loan Rule applies: the draft can be saved, but it cannot be submitted."
		)
		self.assertIn("text-danger", data["html"])

		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 1)
		data = self.preview()
		self.assertFalse(data["eligible"])
		self.assertTrue(data["blocked"])
		self.assertEqual(data["message"], no_rule_message())
		self.assertIn("text-danger", data["html"])

	def test_rule_matched_on_loan_product(self):
		other = self.make_product("HL")
		rule = self.make_rule(loan_products=[{"loan_product": other}])
		self.assertIsNone(self.preview()["rule"])
		self.assertEqual(self.preview(loan_product=other)["rule"], rule.name)

	def test_posting_date_defaults_to_today(self):
		rule = self.make_rule(valid_from=self.today)
		self.assertEqual(self.preview(posting_date=None)["rule"], rule.name)
		self.assertIsNone(self.preview(posting_date=str(add_months(self.today, -1)))["rule"])

	def test_application_being_edited_is_not_counted_as_open(self):
		self.make_rule(max_open_applications=1)
		app = self.application().insert()
		self.assertFalse(self.preview()["eligible"])  # a new, second application
		self.assertTrue(self.preview(loan_application=app.name)["eligible"])  # editing this one

	# ---------------------------------------------------------------- access

	def make_user(self, key, *roles):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"zz.lr07.{key}@example.com",
				"first_name": f"ZZ LR07 {key}",
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
		return user.name

	def other_employee(self):
		return frappe.db.get_value("Employee", {"name": ("!=", self.emp.name)}, "name")

	def test_guest_refused(self):
		frappe.set_user("Guest")
		self.assertRaises(LoanEligibilityAccessError, self.preview)

	def test_employee_checks_only_self(self):
		"""LR-07: an employee can query only their own eligibility; employee may be left out."""
		self.make_rule()
		user = self.make_user("emp", "Employee")
		frappe.db.set_value("Employee", self.emp.name, "user_id", user, update_modified=False)
		frappe.set_user(user)
		self.assertEqual(self.preview()["employee"], self.emp.name)
		self.assertEqual(self.preview(employee=None)["employee"], self.emp.name)  # own record
		other = self.other_employee()
		with self.assertRaises(LoanEligibilityAccessError) as ctx:
			self.preview(employee=other)
		self.assertIn("only for yourself", str(ctx.exception))
		# an unknown ID gets the same answer: other employees cannot be probed
		self.assertRaises(LoanEligibilityAccessError, self.preview, employee="ZZ-NO-SUCH-EMP")

	def test_hr_and_loan_roles_check_any_employee(self):
		self.make_rule()
		for role in ("HR Manager", "HR User", "Loan Manager"):
			with self.subTest(role=role):
				frappe.set_user("Administrator")
				user = self.make_user(role.lower().replace(" ", ""), role)
				frappe.set_user(user)
				self.assertEqual(self.preview()["employee"], self.emp.name)

	def test_user_without_employee_record(self):
		frappe.set_user(self.make_user("nolink", "Employee"))
		with self.assertRaises(frappe.DoesNotExistError) as ctx:
			self.preview(employee=None)
		self.assertIn("No Employee record is linked to your user", str(ctx.exception))
		self.assertRaises(LoanEligibilityAccessError, self.preview)  # someone else's record

	def test_unknown_loan_product(self):
		self.assertRaises(frappe.DoesNotExistError, self.preview, loan_product="ZZ-NO-SUCH-PRODUCT")

	def test_response_shape(self):
		"""LR-07: matched rule, overall status and per-check results, plus what was checked."""
		rule = self.make_rule(min_service_months=36)
		data = self.preview()
		self.assertEqual(data["employee"], self.emp.name)
		self.assertTrue(data["employee_name"])
		self.assertEqual(data["company"], self.company)
		self.assertEqual(data["loan_product"], self.product)
		self.assertEqual(data["posting_date"], str(self.today))
		self.assertEqual(data["rule"], rule.name)
		self.assertEqual(data["status"], NOT_ELIGIBLE)
		service = next(r for r in data["results"] if r["check"] == "service")
		self.assertEqual(
			service,
			{
				"check": "service",
				"label": "Service",
				"passed": False,
				"expected": "36 months",
				"actual": "24 months",
				"message": "You need 36 months of service; you have 24.",
			},
		)
		self.assertTrue(next(r for r in data["results"] if r["check"] == "status")["passed"])

	def test_unknown_employee(self):
		self.assertRaises(frappe.DoesNotExistError, self.preview, employee="ZZ-NO-SUCH-EMP")

	def test_can_override_loan_rule(self):
		allowed = self.make_rule("Allowed", allow_override=1, override_role="HR Manager")
		not_allowed = self.make_rule("Not Allowed", allow_override=0)
		self.assertTrue(can_override_loan_rule(allowed.name))
		self.assertFalse(can_override_loan_rule(not_allowed.name))
		self.assertFalse(can_override_loan_rule("ZZ-NO-SUCH-RULE"))
		self.assertFalse(can_override_loan_rule(""))
		frappe.set_user("Guest")
		self.assertFalse(can_override_loan_rule(allowed.name))

	# ---------------------------------------------------------------- setup the form relies on

	def test_form_field_setup(self):
		meta = frappe.get_meta("Loan Application")
		# visible before the first save; the script narrows it to the Override Role
		self.assertEqual(meta.get_field("rule_override").depends_on, IS_EMPLOYEE)
		self.assertIn("doc.__eligibility_preview", meta.get_field("eligibility_result_section").depends_on)
		self.assertEqual(meta.get_field("eligibility_result_html").fieldtype, "HTML")
		self.assertTrue(meta.get_field("eligibility_result").hidden)


class TestPreviewNote(IntegrationTestCase):
	def test_messages(self):
		block = frappe._dict(enforcement="Block", allow_override=0)
		self.assertEqual(preview_note(block, []), "Preview: the application meets this rule.")
		self.assertEqual(preview_note(block, ["x"]), "Preview: saving will be blocked.")
		block.allow_override = 1
		self.assertEqual(
			preview_note(block, ["x"]), "Preview: saving will be blocked unless the Loan Rule is overridden."
		)
		warn = frappe._dict(enforcement="Warn", allow_override=1)
		self.assertEqual(preview_note(warn, ["x"]), "Preview: the application can be saved, as Not Eligible.")
