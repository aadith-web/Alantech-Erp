# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Loan Rule field validations (LR-01, ClickUp 14yr2e57ghc): defaults, validity window,
age range, non-negative limits, override role and duplicate applicability rows.
Nothing is written to the database: documents are built with frappe.new_doc and validate() is
called directly.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.loan_rule.test_loan_rule_validation
"""

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.alantech.doctype.loan_rule.loan_rule import NON_NEGATIVE_FIELDS


def make_rule(**kw):
	doc = frappe.new_doc("Loan Rule")
	doc.update({"rule_name": "  ZZ Test Loan Rule  ", "company": "_Test Company", "enforcement": "Block"})
	doc.update(kw)
	return doc


class TestLoanRuleValidation(UnitTestCase):
	def test_defaults(self):
		doc = make_rule()
		doc.validate()
		self.assertEqual(doc.enabled, 1)
		self.assertEqual(doc.enforcement, "Block")
		self.assertEqual(doc.max_active_loans, 1)
		self.assertEqual(doc.max_open_applications, 1)
		self.assertEqual(doc.priority, 0)
		self.assertEqual(doc.rule_name, "ZZ Test Loan Rule")

	def test_enforcement_options(self):
		options = frappe.get_meta("Loan Rule").get_field("enforcement").options.split("\n")
		self.assertEqual(options, ["Block", "Warn"])

	def test_valid_from_after_valid_upto(self):
		doc = make_rule(valid_from="2026-12-31", valid_upto="2026-01-01")
		self.assertRaisesRegex(frappe.ValidationError, "Valid From cannot be after Valid Upto", doc.validate)

	def test_validity_window_ok(self):
		make_rule(valid_from="2026-06-01", valid_upto="2026-06-01").validate()
		make_rule(valid_from="2026-06-01").validate()
		make_rule(valid_upto="2026-06-01").validate()

	def test_max_age_below_min_age(self):
		doc = make_rule(min_age=40, max_age=30)
		self.assertRaisesRegex(frappe.ValidationError, "Maximum Age cannot be less than Minimum Age", doc.validate)

	def test_age_range_ok(self):
		make_rule(min_age=30, max_age=30).validate()
		make_rule(min_age=21).validate()  # max_age 0 = no upper limit
		make_rule(max_age=58).validate()

	def test_negative_limits(self):
		for field in NON_NEGATIVE_FIELDS:
			with self.subTest(field=field):
				self.assertRaisesRegex(frappe.ValidationError, "cannot be negative", make_rule(**{field: -1}).validate)

	def test_zero_limits_allowed(self):
		make_rule(**{field: 0 for field in NON_NEGATIVE_FIELDS}).validate()

	def test_override_requires_role(self):
		self.assertRaisesRegex(
			frappe.ValidationError, "Override Role is required", make_rule(allow_override=1).validate
		)
		make_rule(allow_override=1, override_role="HR Manager").validate()

	def test_override_role_cleared_when_not_allowed(self):
		doc = make_rule(allow_override=0, override_role="HR Manager")
		doc.validate()
		self.assertIsNone(doc.override_role)

	def test_duplicate_applicability(self):
		doc = make_rule(branches=[{"branch": "ZZ Branch"}, {"branch": "ZZ Branch"}])
		self.assertRaisesRegex(frappe.ValidationError, "Duplicate entries in Branches", doc.validate)

	def test_get_applicability(self):
		doc = make_rule(grades=[{"grade": "G1"}, {"grade": "G2"}], departments=[{"department": "D1"}])
		applicability = doc.get_applicability()
		self.assertEqual(applicability["grades"], {"G1", "G2"})
		self.assertEqual(applicability["departments"], {"D1"})
		self.assertEqual(applicability["loan_products"], set())
		self.assertEqual(doc.get_specificity(), 2)
