# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Loan Product: generated Product Code (setup/loan_product_code.py).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_product_code

Unit: the series. Integration: a new product without a code gets the next LP-#### (also its name),
numbers go up, a code given (Data Import) is kept, and the form field is read-only / not mandatory.
Data: each test runs in a savepoint that is rolled back.
"""

import re

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from alantech_erp.setup import loan_product_code
from alantech_erp.tests.test_loan_flow import make_product


class UnitTestProductCodeSeries(UnitTestCase):
	def test_series(self):
		self.assertEqual(loan_product_code.SERIES, "LP-.####")


class IntegrationTestLoanProductCode(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Loan Product", {}, "company") or frappe.db.get_value("Company", {}, "name")

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("lp_code")
		self.addCleanup(frappe.db.rollback, save_point="lp_code")

	def new(self, **values):
		tag = frappe.generate_hash(length=5)
		return make_product(self.company, tag, product_code=values.get("product_code", ""))

	def test_blank_code_generated(self):
		first = self.new()
		self.assertRegex(first.product_code, r"^LP-\d{4}$")
		self.assertEqual(first.name, first.product_code)
		second = self.new()
		number = lambda d: int(re.search(r"\d+$", d.name).group())  # noqa: E731
		self.assertEqual(number(second), number(first) + 1)

	def test_given_code_kept(self):
		self.assertEqual(self.new(product_code="TEST-LPCODE-X").name, "TEST-LPCODE-X")

	def test_skips_a_code_already_used(self):
		taken = self.new()
		frappe.db.sql("update tabSeries set current = current - 1 where name = 'LP-'")
		self.assertNotEqual(self.new().name, taken.name)

	def test_form_field_read_only(self):
		loan_product_code.execute()
		frappe.clear_cache(doctype="Loan Product")
		df = frappe.get_meta("Loan Product").get_field("product_code")
		self.assertEqual((df.read_only, df.reqd), (1, 0))

	def test_links_show_product_name(self):
		loan_product_code.execute()
		frappe.clear_cache(doctype="Loan Product")
		meta = frappe.get_meta("Loan Product")
		self.assertEqual((meta.title_field, meta.show_title_field_in_link), ("product_name", 1))
		product = self.new()
		self.assertEqual(frappe.get_cached_value("Loan Product", product.name, "product_name"), product.product_name)
