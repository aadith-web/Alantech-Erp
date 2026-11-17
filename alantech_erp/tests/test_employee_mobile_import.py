# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee import: Mobile without "+" (lost by the spreadsheet) is accepted when valid.

LibreOffice / Excel turn +919876798789 into the number 919876798789, so the import file has no
"+". employee_validation.restore_plus_sign puts it back during Data Import only, and only when the
digits are a valid mobile number of their country code. The Employee form stays strict.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_mobile_import
"""

import frappe

from alantech_erp.setup.employee_validation import restore_plus_sign, validate_mobile_number

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase


class FakeEmployee(frappe._dict):
	def is_new(self):
		return True

	def has_value_changed(self, field):
		return True


class TestEmployeeMobileImport(TestCase):
	def tearDown(self):
		frappe.flags.in_import = False

	def test_plus_restored_for_valid_numbers(self):
		cases = {
			"919876798789": "+919876798789",  # India
			"971501234567": "+971501234567",  # UAE
			"919876798789.0": "+919876798789",  # numeric cell read as float
			"00971501234567": "+971501234567",
			"91 98767 98789": "+919876798789",
		}
		for raw, expected in cases.items():
			with self.subTest(raw=raw):
				self.assertEqual(restore_plus_sign(raw), expected)

	def test_left_alone_when_not_a_valid_number(self):
		for raw in ("9876798789", "12345", "abc", "+919876798789", ""):
			with self.subTest(raw=raw):
				self.assertEqual(restore_plus_sign(raw), raw)

	def test_import_accepts_number_without_plus(self):
		frappe.flags.in_import = True
		doc = FakeEmployee(cell_number="919876798789")
		validate_mobile_number(doc)
		self.assertEqual(doc.cell_number, "+91-9876798789")

	def test_import_still_refuses_number_without_country_code(self):
		frappe.flags.in_import = True
		with self.assertRaises(frappe.ValidationError):
			validate_mobile_number(FakeEmployee(cell_number="9876798789"))

	def test_form_still_needs_country_code(self):
		with self.assertRaises(frappe.ValidationError):
			validate_mobile_number(FakeEmployee(cell_number="919876798789"))
