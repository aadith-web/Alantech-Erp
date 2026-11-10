# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Loan Rule engine, pure logic (LR-04, ClickUp 14yr2e57ghg; loan_rules/engine.py): rule matching
and ordering, validity window, every check function with its messages, and the HTML check list.
No database writes.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_unit_loan_rule_engine
"""

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.loan_rules import engine


def rule(name, priority=0, **applicability):
	full = {table: set() for table in engine.APPLICABILITY}
	full.update({k: set(v) for k, v in applicability.items()})
	return frappe._dict(name=name, priority=priority, applicability=full)


CONTEXT = {
	"loan_products": "PL",
	"employment_types": "Permanent",
	"grades": "G1",
	"designations": "Accountant",
	"departments": "Accounts",
	"branches": "Kochi",
}


class TestRuleMatching(UnitTestCase):
	def test_blank_lists_match_everyone(self):
		self.assertTrue(engine.rule_matches(rule("A").applicability, CONTEXT))

	def test_every_filled_list_must_contain_value(self):
		self.assertTrue(engine.rule_matches(rule("A", loan_products=["PL", "VL"]).applicability, CONTEXT))
		self.assertFalse(engine.rule_matches(rule("A", loan_products=["VL"]).applicability, CONTEXT))
		both = rule("A", loan_products=["PL"], grades=["G2"]).applicability
		self.assertFalse(engine.rule_matches(both, CONTEXT))

	def test_missing_employee_value_fails_a_filled_list(self):
		context = dict(CONTEXT, grades=None)
		self.assertFalse(engine.rule_matches(rule("A", grades=["G1"]).applicability, context))
		self.assertTrue(engine.rule_matches(rule("A").applicability, context))

	def test_priority_wins(self):
		rules = [rule("Low", priority=5), rule("High", priority=10)]
		self.assertEqual(engine.pick_rule(rules, CONTEXT), "High")

	def test_specificity_breaks_priority_tie(self):
		rules = [rule("General", priority=5), rule("Specific", priority=5, loan_products=["PL"], branches=["Kochi"])]
		self.assertEqual(engine.pick_rule(rules, CONTEXT), "Specific")

	def test_name_breaks_full_tie(self):
		self.assertEqual(engine.pick_rule([rule("B"), rule("A")], CONTEXT), "A")

	def test_no_match(self):
		self.assertIsNone(engine.pick_rule([rule("A", loan_products=["VL"])], CONTEXT))

	def test_build_context(self):
		emp = frappe._dict(employment_type="Permanent", grade="G1", designation="Accountant", department="Accounts", branch="Kochi")
		self.assertEqual(engine.build_context(emp, "PL"), CONTEXT)

	def test_validity_window(self):
		r = {"valid_from": "2026-01-01", "valid_upto": "2026-12-31"}
		self.assertTrue(engine.is_valid_on(r, "2026-01-01"))
		self.assertTrue(engine.is_valid_on(r, "2026-12-31"))
		self.assertFalse(engine.is_valid_on(r, "2025-12-31"))
		self.assertFalse(engine.is_valid_on(r, "2027-01-01"))
		self.assertTrue(engine.is_valid_on({}, "2030-01-01"))


class TestChecks(UnitTestCase):
	def test_status(self):
		self.assertTrue(engine.check_status("Active")["passed"])
		res = engine.check_status("Suspended")
		self.assertFalse(res["passed"])
		self.assertIn("Suspended", res["message"])

	def test_service_months(self):
		self.assertEqual(engine.service_months("2026-01-15", "2026-09-14"), 7)
		self.assertEqual(engine.service_months("2026-01-15", "2026-09-15"), 8)
		self.assertEqual(engine.service_months("2026-12-01", "2026-09-15"), 0)

	def test_service(self):
		self.assertIsNone(engine.check_service(0, None, "2026-11-09"))
		res = engine.check_service(12, "2026-03-09", "2026-11-09")
		self.assertFalse(res["passed"])
		self.assertEqual(res["message"], "You need 12 months of service; you have 8.")
		self.assertTrue(engine.check_service(12, "2025-11-09", "2026-11-09")["passed"])

	def test_service_missing_joining_date(self):
		res = engine.check_service(12, None, "2026-11-09")
		self.assertFalse(res["passed"])
		self.assertEqual(res["message"], "Employee record incomplete: Date of Joining")

	def test_confirmation(self):
		self.assertIsNone(engine.check_confirmation(0, None, "2026-11-09"))
		self.assertTrue(engine.check_confirmation(1, "2026-11-09", "2026-11-09")["passed"])
		future = engine.check_confirmation(1, "2026-12-01", "2026-11-09")
		self.assertFalse(future["passed"])
		self.assertEqual(future["message"], "Loan applications open after your probation is confirmed.")
		missing = engine.check_confirmation(1, None, "2026-11-09")
		self.assertFalse(missing["passed"])
		self.assertIn("Employee record incomplete: Final Confirmation Date", missing["message"])

	def test_age(self):
		self.assertIsNone(engine.check_age(0, 0, None, "2026-11-09"))
		res = engine.check_age(21, 58, "2010-01-01", "2026-11-09")
		self.assertFalse(res["passed"])
		self.assertEqual(res["message"], "Applicant age must be between 21 and 58.")
		self.assertTrue(engine.check_age(21, 58, "1990-11-09", "2026-11-09")["passed"])
		self.assertFalse(engine.check_age(0, 30, "1990-11-09", "2026-11-09")["passed"])
		self.assertEqual(engine.check_age(21, 0, None, "2026-11-09")["message"], "Employee record incomplete: Date of Birth")

	def test_age_birthday_boundary(self):
		self.assertEqual(engine.age_on("2000-11-10", "2026-11-09"), 25)
		self.assertEqual(engine.age_on("2000-11-09", "2026-11-09"), 26)

	def test_separation(self):
		clean = frappe._dict(resignation_letter_date=None, relieving_date=None)
		self.assertTrue(engine.check_separation(clean, None)["passed"])
		for emp, open_sep in (
			(frappe._dict(resignation_letter_date="2026-11-01", relieving_date=None), None),
			(frappe._dict(resignation_letter_date=None, relieving_date="2026-12-31"), None),
			(clean, "HR-EMP-SEP-0001"),
		):
			res = engine.check_separation(emp, open_sep)
			self.assertFalse(res["passed"])
			self.assertEqual(res["message"], "Not allowed while a resignation or separation is in progress.")

	def test_on_leave(self):
		self.assertTrue(engine.check_on_leave(None)["passed"])
		res = engine.check_on_leave({"name": "HR-LAP-1", "from_date": "2026-11-08", "to_date": "2026-11-10"})
		self.assertFalse(res["passed"])
		self.assertTrue(res["message"].startswith("Not allowed while on approved leave ("))

	def test_active_loans(self):
		self.assertTrue(engine.check_active_loans(1, 0)["passed"])
		res = engine.check_active_loans(1, 1)
		self.assertFalse(res["passed"])
		self.assertEqual(res["message"], "You already have 1 active loan(s); the limit is 1.")

	def test_open_applications(self):
		self.assertTrue(engine.check_open_applications(1, [])["passed"])
		res = engine.check_open_applications(1, ["ACC-LOAP-2026-00001"])
		self.assertFalse(res["passed"])
		self.assertEqual(res["message"], "You already have an open application: ACC-LOAP-2026-00001.")
		self.assertTrue(engine.check_open_applications(2, ["ACC-LOAP-2026-00001"])["passed"])

	def test_cooling_off(self):
		self.assertTrue(engine.check_cooling_off(6, None, "2026-11-09")["passed"])
		res = engine.check_cooling_off(6, "2026-09-09", "2026-11-09")
		self.assertFalse(res["passed"])
		self.assertIn("6 months after your last loan closed", res["message"])
		self.assertEqual(res["eligible_from"], "2027-03-09")  # next eligible date (LR-08 report)
		self.assertTrue(engine.check_cooling_off(6, "2026-05-09", "2026-11-09")["passed"])
		self.assertNotIn("eligible_from", engine.check_cooling_off(6, None, "2026-11-09"))

	def test_pick_rule_from_candidates(self):
		"""candidate_rules + pick_rule (used by the Loan Eligibility report to load rules once)."""
		rules = [
			frappe._dict(name="A", priority=1, applicability={"grades": {"G1"}}),
			frappe._dict(name="B", priority=1, applicability={"grades": set()}),
		]
		self.assertEqual(engine.pick_rule(rules, {"grades": "G1"}), "A")  # more specific wins the tie
		self.assertEqual(engine.pick_rule(rules, {"grades": "G2"}), "B")
		self.assertIsNone(engine.pick_rule([], {"grades": "G1"}))

	def test_loans_per_year(self):
		self.assertTrue(engine.check_loans_per_year(2, 1)["passed"])
		res = engine.check_loans_per_year(2, 2)
		self.assertFalse(res["passed"])
		self.assertEqual(res["message"], "Limit of 2 loans per fiscal year reached.")

	def test_result_shape(self):
		res = engine.check_active_loans(1, 0)
		self.assertEqual(set(res), {"check", "label", "passed", "expected", "actual", "message"})
		self.assertEqual(res["message"], "")  # passed checks carry no message


class TestPresentation(UnitTestCase):
	def test_failure_messages_keep_order(self):
		results = [engine.check_active_loans(1, 1), engine.check_status("Active"), engine.check_loans_per_year(1, 1)]
		self.assertEqual(
			engine.failure_messages(results),
			["You already have 1 active loan(s); the limit is 1.", "Limit of 1 loans per fiscal year reached."],
		)

	def test_render_escapes_values(self):
		r = frappe._dict(name="<b>Rule</b>", enforcement="Block")
		results = [engine.check_open_applications(1, ["<script>x</script>"])]
		html = engine.render_results_html(r, results, "Not Eligible")
		self.assertTrue(html.startswith('<div class="loan-eligibility-result">'))
		self.assertNotIn("<script>", html)
		self.assertNotIn("<b>Rule</b>", html)
		self.assertIn("Failed", html)
		self.assertIn("Not Eligible", html)
