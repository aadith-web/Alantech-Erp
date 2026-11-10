# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Employee Loan Rules end to end on Loan Application (LR-04 ClickUp 14yr2e57ghg, LR-05 14yr2e57ghh;
loan_rules/engine.py + loan_rules/loan_application.py): the 16 test scenarios of the feature spec
plus leave, age, open applications, same-product counting, missing data and validity window.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_rule_eligibility

Data: one active employee of the site with no loan applications is used; its dates are adjusted
with frappe.db.set_value. The site's Loan Rules are disabled, Require Loan Rule is switched off, and
test Loan Rules, a Loan Product, Loans, Leave Applications and Employee Separations (written with
db_insert, prefix ZZ-LR05) are created. Everything runs in a savepoint per test and is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, getdate, today

from alantech_erp.loan_rules import engine
from alantech_erp.loan_rules.loan_application import (
	EmployeeApplicantOnlyError,
	LoanNotEligibleError,
	NoLoanRuleError,
	OverrideNotAllowedError,
)
from alantech_erp.setup.loan_application_fields import ELIGIBLE, NOT_ELIGIBLE, OVERRIDDEN

PREFIX = "ZZ-LR05"


def pick_employee():
	used = frappe.get_all("Loan Application", filters={"applicant_type": "Employee"}, pluck="applicant")
	filters = {"status": "Active"}
	if used:
		filters["name"] = ("not in", used)
	return frappe.db.get_value("Employee", filters, ["name", "company"], as_dict=True)


class TestLoanRuleEligibility(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.emp = pick_employee()

	def setUp(self):
		if not self.emp:
			self.skipTest("No active employee without loan applications on this site")
		frappe.set_user("Administrator")
		frappe.db.savepoint("lr05")
		self.addCleanup(frappe.db.rollback, save_point="lr05")
		self.addCleanup(frappe.set_user, "Administrator")

		self.today = getdate(today())
		self.company = self.emp.company
		frappe.db.set_value("Loan Rule", {"enabled": 1}, "enabled", 0)
		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 0)
		# a clean employee: 2 years of service, confirmed, 30 years old, no separation
		self.set_employee(
			status="Active",
			date_of_joining=add_months(self.today, -24),
			final_confirmation_date=add_months(self.today, -18),
			date_of_birth=add_months(self.today, -30 * 12),
			relieving_date=None,
			resignation_letter_date=None,
		)
		self.product = self.make_product("PL")
		self.counter = 0

	# ---------------------------------------------------------------- helpers

	def set_employee(self, **values):
		frappe.db.set_value("Employee", self.emp.name, values, update_modified=False)

	def make_product(self, code):
		order = frappe.db.get_value("Loan Demand Offset Order", {}, "name") or frappe.get_doc(
			{
				"doctype": "Loan Demand Offset Order",
				"title": f"{PREFIX} Offset",
				"components": [{"demand_type": "Principal"}],
			}
		).insert().name
		return frappe.get_doc(
			{
				"doctype": "Loan Product",
				"product_code": f"{PREFIX}-{code}",
				"product_name": f"{PREFIX} {code}",
				"company": self.company,
				"rate_of_interest": 4,
				"collection_offset_sequence_for_standard_asset": order,
				"collection_offset_sequence_for_sub_standard_asset": order,
			}
		).insert().name

	def make_rule(self, name="Rule", **kw):
		doc = frappe.new_doc("Loan Rule")
		doc.update(
			{
				"rule_name": f"{PREFIX} {name}",
				"company": self.company,
				"max_active_loans": 0,
				"max_open_applications": 0,
			}
		)
		doc.update(kw)
		return doc.insert()

	def application(self, **kw):
		doc = frappe.get_doc(
			{
				"doctype": "Loan Application",
				"applicant_type": "Employee",
				"applicant": self.emp.name,
				"company": self.company,
				"posting_date": self.today,
				"loan_product": self.product,
				"loan_amount": 50000,
			}
		)
		doc.update(kw)
		return doc

	def raw(self, doctype, **values):
		self.counter += 1
		doc = frappe.get_doc(dict({"doctype": doctype}, **values))
		doc.name = f"{PREFIX}-{doctype[:4]}-{self.counter}"
		doc.db_insert()
		return doc.name

	def loan(self, status="Disbursed", posting_date=None, closure_date=None, product=None, docstatus=1):
		return self.raw(
			"Loan",
			applicant_type="Employee",
			applicant=self.emp.name,
			company=self.company,
			loan_product=product or self.product,
			posting_date=posting_date or add_months(self.today, -3),
			status=status,
			closure_date=closure_date,
			loan_amount=10000,
			docstatus=docstatus,
		)

	def open_application(self, product=None, docstatus=0, status="Open"):
		return self.raw(
			"Loan Application",
			applicant_type="Employee",
			applicant=self.emp.name,
			company=self.company,
			loan_product=product or self.product,
			posting_date=self.today,
			status=status,
			docstatus=docstatus,
			loan_amount=1000,
		)

	def assert_blocked(self, doc, *messages, exc=LoanNotEligibleError):
		with self.assertRaises(exc) as ctx:
			doc.insert()
		for message in messages:
			self.assertIn(message, str(ctx.exception))
		return ctx.exception

	# ---------------------------------------------------------- spec scenarios

	def test_01_min_service(self):
		self.make_rule(min_service_months=12)
		self.set_employee(date_of_joining=add_months(self.today, -8))
		self.assert_blocked(self.application(), "You need 12 months of service; you have 8.")

	def test_02_probation_not_confirmed(self):
		self.make_rule(require_confirmation=1)
		self.set_employee(final_confirmation_date=add_months(self.today, 1))
		self.assert_blocked(self.application(), "Loan applications open after your probation is confirmed.")

	def test_03_active_loan_blocks(self):
		self.make_rule(max_active_loans=1)
		self.loan(status="Disbursed")
		self.assert_blocked(self.application(), "You already have 1 active loan(s); the limit is 1.")

	def test_04_closed_loan_allowed(self):
		self.make_rule(max_active_loans=1)
		self.loan(status="Closed", closure_date=add_months(self.today, -1))
		self.loan(status="Disbursed", docstatus=2)  # cancelled loans never count
		app = self.application().insert()
		self.assertEqual(app.eligibility_status, ELIGIBLE)

	def test_05_cooling_off(self):
		self.make_rule(cooling_off_months=6)
		closed = add_months(self.today, -2)
		self.loan(status="Closed", closure_date=closed)
		eligible_from = frappe.utils.formatdate(add_months(closed, 6))
		self.assert_blocked(
			self.application(), f"You can apply again from {eligible_from}, 6 months after your last loan closed."
		)

	def test_05b_cooling_off_uses_last_repayment_when_closure_date_blank(self):
		self.make_rule(cooling_off_months=6)
		loan = self.loan(status="Closed", closure_date=None)
		self.raw("Loan Repayment", against_loan=loan, posting_date=add_months(self.today, -1), docstatus=1)
		self.assert_blocked(self.application(), "after your last loan closed")

	def test_06_loans_per_year(self):
		self.make_rule(max_loans_per_year=2)
		start, _end = engine.fiscal_year_bounds(self.today, self.company)
		self.loan(status="Closed", posting_date=start, closure_date=start)
		self.loan(status="Closed", posting_date=self.today, closure_date=self.today)
		self.loan(status="Closed", posting_date=add_days(start, -1))  # previous fiscal year
		self.assert_blocked(self.application(), "Limit of 2 loans per fiscal year reached.")

	def test_07_resignation(self):
		self.make_rule(block_if_resignation=1)
		self.set_employee(resignation_letter_date=add_days(self.today, -3))
		self.assert_blocked(self.application(), "Not allowed while a resignation or separation is in progress.")

	def test_07b_open_employee_separation(self):
		self.make_rule(block_if_resignation=1)
		self.raw("Employee Separation", employee=self.emp.name, company=self.company, boarding_status="Pending", docstatus=0)
		self.assert_blocked(self.application(), "separation is in progress")

	def test_08_priority(self):
		self.make_rule("Five", priority=5)
		self.make_rule("Ten", priority=10)
		app = self.application().insert()
		self.assertEqual(app.loan_rule, f"{PREFIX} Ten")

	def test_08b_specificity_then_applicability(self):
		self.make_rule("General", priority=5)
		self.make_rule("Specific", priority=5, loan_products=[{"loan_product": self.product}])
		other = self.make_product("VL")
		self.make_rule("Other Product", priority=99, loan_products=[{"loan_product": other}])
		app = self.application().insert()
		self.assertEqual(app.loan_rule, f"{PREFIX} Specific")

	def test_09_no_rule_setting_off(self):
		app = self.application().insert()
		self.assertFalse(app.loan_rule)
		self.assertFalse(app.eligibility_status)
		self.assertFalse(app.eligibility_result)

	def test_10_no_rule_setting_on(self):
		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 1)
		self.assert_blocked(
			self.application(), "No loan policy covers you for this loan product. Contact HR.", exc=NoLoanRuleError
		)

	def test_11_warn_mode(self):
		self.make_rule(enforcement="Warn", min_service_months=36)
		frappe.clear_messages()
		app = self.application().insert()
		self.assertEqual(app.eligibility_status, NOT_ELIGIBLE)
		self.assertIn("Failed", app.eligibility_result)
		self.assertTrue(any("You need 36 months of service" in str(m) for m in frappe.get_message_log()))

	def test_12_override_by_role(self):
		self.make_rule(min_service_months=36, allow_override=1, override_role="HR Manager")
		app = self.application(rule_override=1, override_reason="Medical emergency").insert()
		self.assertEqual(app.eligibility_status, OVERRIDDEN)
		self.assertEqual(app.overridden_by, "Administrator")
		self.assertTrue(app.overridden_on)
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Loan Application", "reference_name": app.name, "comment_type": "Comment"},
			pluck="content",
		)
		self.assertEqual(len(comments), 1)
		self.assertIn("Medical emergency", comments[0])
		self.assertIn("You need 36 months of service", comments[0])

		# saving again keeps the stamp and adds no second comment
		stamped = app.overridden_on
		app.loan_amount = 40000
		app.save()
		self.assertEqual(app.overridden_on, stamped)
		self.assertEqual(
			frappe.db.count("Comment", {"reference_name": app.name, "comment_type": "Comment"}), 1
		)

	def test_12b_override_not_allowed_by_rule(self):
		self.make_rule(min_service_months=36, allow_override=0)
		self.assert_blocked(
			self.application(rule_override=1, override_reason="Please"),
			"does not allow overrides",
			exc=OverrideNotAllowedError,
		)

	def test_13_override_without_role(self):
		self.make_rule(min_service_months=36, allow_override=1, override_role="HR Manager")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "zz.lr05.hruser@example.com",
				"first_name": "ZZ LR05",
				"send_welcome_email": 0,
				# prepares applications for any employee (LR-09) but is not the rule's Override Role
				"roles": [{"role": "HR User"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(user.name)
		app = self.application(rule_override=1, override_reason="I need it")
		with self.assertRaises(OverrideNotAllowedError) as ctx:
			app.insert(ignore_permissions=True)
		self.assertIn("Only users with the", str(ctx.exception))

	def test_14_recheck_on_approval_after_submit(self):
		self.make_rule(block_if_resignation=1)
		app = self.application().insert()
		app.submit()
		self.assertEqual(app.eligibility_status, ELIGIBLE)
		self.set_employee(relieving_date=add_days(self.today, 30))
		app.reload()
		app.status = "Approved"
		with self.assertRaises(LoanNotEligibleError):
			app.save()

	def test_14b_approval_in_draft_rechecks(self):
		self.make_rule(block_if_resignation=1)
		app = self.application().insert()
		self.set_employee(resignation_letter_date=self.today)
		app.status = "Approved"
		with self.assertRaises(LoanNotEligibleError):
			app.save()

	def test_15_customer_applicant_not_checked(self):
		from alantech_erp.loan_rules.loan_application import evaluate

		self.make_rule(min_service_months=999)
		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 1)
		doc = frappe.new_doc("Loan Application")
		doc.update({"applicant_type": "Customer", "applicant": "Any Customer", "loan_rule": "x", "eligibility_status": ELIGIBLE})
		evaluate(doc)  # no exception, nothing matched
		self.assertFalse(doc.loan_rule)
		self.assertFalse(doc.eligibility_status)

	def test_15b_customer_applicant_refused(self):
		"""Employee loans only: Customer is no longer an Applicant Type option."""
		doc = self.application(applicant_type="Customer", applicant=None)
		self.assertRaisesRegex(EmployeeApplicantOnlyError, "Loans are given to employees only", doc.insert)

	def test_17_no_rule_draft_saves_but_cannot_submit(self):
		app = self.application().insert()  # Require Loan Rule off: draft allowed
		self.assertFalse(app.loan_rule)
		with self.assertRaises(NoLoanRuleError) as ctx:
			app.submit()
		self.assertIn("No loan policy covers you", str(ctx.exception))
		self.assertEqual(frappe.db.get_value("Loan Application", app.name, "docstatus"), 0)

		# a rule enabled later: the same draft submits
		rule = self.make_rule()
		app.reload()
		app.submit()
		self.assertEqual(app.loan_rule, rule.name)
		self.assertEqual(app.docstatus, 1)

	def test_16_all_failures_in_one_message(self):
		self.make_rule(min_service_months=36, require_confirmation=1, max_active_loans=1)
		self.set_employee(final_confirmation_date=None)
		self.loan(status="Disbursed")
		self.assert_blocked(
			self.application(),
			"You need 36 months of service; you have 24.",
			"Employee record incomplete: Final Confirmation Date",
			"You already have 1 active loan(s); the limit is 1.",
		)

	# ------------------------------------------------------------ other rules

	def test_on_approved_leave(self):
		self.make_rule(block_if_on_leave=1)
		self.raw(
			"Leave Application",
			employee=self.emp.name,
			company=self.company,
			from_date=add_days(self.today, -1),
			to_date=add_days(self.today, 1),
			status="Approved",
			docstatus=1,
		)
		self.assert_blocked(self.application(), "Not allowed while on approved leave (")

	def test_age_range(self):
		self.make_rule(min_age=35, max_age=58)
		self.assert_blocked(self.application(), "Applicant age must be between 35 and 58.")

	def test_inactive_employee_always_blocked(self):
		self.make_rule()
		self.set_employee(status="Suspended")
		self.assert_blocked(self.application(), "Only Active employees can apply")

	def test_open_applications_exclude_self_cancelled_and_others(self):
		self.make_rule(max_open_applications=1)
		self.open_application(docstatus=2)  # cancelled
		self.open_application(status="Rejected")
		app = self.application().insert()
		self.assertEqual(app.eligibility_status, ELIGIBLE)
		app.save()  # itself is never counted
		# a second application: the first one is now the open application
		self.assert_blocked(self.application(), f"You already have an open application: {app.name}.")

	def test_same_product_only(self):
		other = self.make_product("VL")
		self.make_rule(max_active_loans=1, same_product_only=1)
		self.loan(status="Disbursed", product=other)
		app = self.application().insert()  # the loan is for another product
		self.assertEqual(app.eligibility_status, ELIGIBLE)
		self.loan(status="Disbursed")
		self.assert_blocked(self.application(), "active loan(s)")

	def test_rule_outside_validity_window_ignored(self):
		self.make_rule(valid_upto=add_days(self.today, -1), min_service_months=999)
		app = self.application().insert()
		self.assertFalse(app.loan_rule)

	def test_eligible_result_and_override_cleared(self):
		self.make_rule(allow_override=1, override_role="HR Manager", description="Staff loan policy")
		app = self.application(rule_override=1, override_reason="Not needed").insert()
		self.assertEqual(app.eligibility_status, ELIGIBLE)
		self.assertFalse(app.rule_override)
		self.assertFalse(app.override_reason)
		self.assertIn("Passed", app.eligibility_result)
