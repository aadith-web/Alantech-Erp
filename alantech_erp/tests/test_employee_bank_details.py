# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee bank / statutory number formats (setup/employee_bank_details.py).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_bank_details
"""

import frappe

from alantech_erp.setup import employee_bank_details as ebd

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

VALID = {
	"uan_number": "1001 2345 6789",
	"pf_name": "One Two",
	"esic_card_no": "1234567890",
	"ifsc_code": "sbin0001234",
	"alt_ifsc_code": "SBIN0001234",
	"micr_code": "600002003",
	"provident_fund_account": "MHBAN00000640000000125",
	"bank_ac_no": "123456789012",
	"alt_bank_account_holder": "One Two",
	"bank_name": "State Bank of India",
	"alt_bank_branch": "Technopark Branch",
	"iban": "ae07 0331 2345 6789 0123 456",
}

INVALID = {
	"uan_number": "12345",
	"pf_name": "One 2",
	"esic_card_no": "12345678",
	"ifsc_code": "SBIN1001234",
	"alt_ifsc_code": "SBI0001234",
	"micr_code": "fsdfdsfdsdsgdsgdsgdsg03425432532",
	"provident_fund_account": "PF#123",
	"bank_ac_no": "12AB",
	"alt_bank_account_holder": "One@Two",
	"bank_name": "12345",
	"alt_bank_branch": "Branch!",
	"iban": "AE070331234567890123457",  # bad check digit
}


def new_employee(**values):
	doc = frappe.new_doc("Employee")
	doc.update(values)
	return doc


class TestEmployeeBankDetails(TestCase):
	def test_valid_values_normalised(self):
		doc = new_employee(**VALID)
		ebd.validate_bank_details(doc)
		self.assertEqual(doc.uan_number, "100123456789")
		self.assertEqual(doc.ifsc_code, "SBIN0001234")
		self.assertEqual(doc.iban, "AE070331234567890123456")

	def test_each_invalid_value_refused(self):
		for field, value in INVALID.items():
			with self.subTest(field=field):
				self.assertIsNotNone(ebd.check_value(field, ebd.normalise(ebd.RULES[field][0], value)))
				with self.assertRaises(ebd.InvalidBankDetailsError):
					ebd.validate_bank_details(new_employee(**{**VALID, field: value}))

	def test_all_errors_in_one_message(self):
		with self.assertRaises(ebd.InvalidBankDetailsError) as ctx:
			ebd.validate_bank_details(new_employee(**INVALID))
		self.assertEqual(str(ctx.exception).count("<li>"), len(INVALID))

	def test_blank_values_allowed(self):
		ebd.validate_bank_details(new_employee())

	def test_live_check(self):
		self.assertEqual(ebd.check_bank_field("ifsc_code", " sbin0001234 "), {"value": "SBIN0001234", "error": None})
		self.assertTrue(ebd.check_bank_field("micr_code", "12")["error"])
