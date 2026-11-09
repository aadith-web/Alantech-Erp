# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Document numbers: format, check digit and storage format per Document Type Master
(document_number.py; HR-F07 Employee Documents, ClickUp 14yr2e56cak).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.document.test_document_number
"""

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.alantech.doctype.document.document_number import (
	clean_number,
	live_rules,
	luhn_ok,
	number_key,
	verhoeff_ok,
)


def rules(number_format=None, pattern=None, example=None):
	return frappe._dict(number_format=number_format, number_pattern=pattern, number_example=example)


class UnitTestDocumentNumber(UnitTestCase):
	def assert_valid(self, number_format, typed, stored):
		value, error = clean_number("T", typed, rules(number_format))
		self.assertIsNone(error, f"{number_format} {typed}: {error}")
		self.assertEqual(value, stored)

	def assert_invalid(self, number_format, typed, text, pattern=None, example=None):
		value, error = clean_number("T", typed, rules(number_format, pattern, example))
		self.assertTrue(error, f"{number_format} {typed} should be refused")
		self.assertIn(text, error)
		return value

	def test_check_digits(self):
		self.assertTrue(verhoeff_ok("234567890124"))
		self.assertFalse(verhoeff_ok("234567890123"))
		self.assertTrue(luhn_ok("784199012345676"))
		self.assertFalse(luhn_ok("784199012345670"))

	def test_aadhaar(self):
		for typed in ("234567890124", "2345 6789 0124", "2345-6789-0124", " 2345  6789 0124 "):
			with self.subTest(typed=typed):
				self.assert_valid("Aadhaar", typed, "2345 6789 0124")
		self.assert_invalid("Aadhaar", "2345 6789 0123", "check digit does not match")
		self.assert_invalid("Aadhaar", "1234 5678 9012", "It should look like")  # cannot start with 0 or 1
		self.assert_invalid("Aadhaar", "2345 6789 012", "It should look like")  # 11 digits

	def test_pan(self):
		self.assert_valid("PAN", "abcpe1234f", "ABCPE1234F")
		self.assert_valid("PAN", "ABCPE 1234 F", "ABCPE1234F")
		self.assert_invalid("PAN", "ABCDE1234F", "It should look like")  # D is not a holder type
		self.assert_invalid("PAN", "ABCP1234E", "It should look like")

	def test_indian_passport(self):
		self.assert_valid("Indian Passport", "a1234567", "A1234567")
		self.assert_invalid("Indian Passport", "A0234567", "It should look like")  # 2nd char 1-9
		self.assert_invalid("Indian Passport", "A123456", "It should look like")

	def test_indian_driving_licence(self):
		self.assert_valid("Indian Driving Licence", "KL07 20110012345", "KL07 20110012345")
		self.assert_valid("Indian Driving Licence", "kl-07-2011-0012345", "KL07 20110012345")
		self.assert_invalid("Indian Driving Licence", "KL07 18110012345", "It should look like")  # year 18xx

	def test_emirates_id(self):
		self.assert_valid("Emirates ID", "784199012345676", "784-1990-1234567-6")
		self.assert_valid("Emirates ID", "784-1990-1234567-6", "784-1990-1234567-6")
		self.assert_invalid("Emirates ID", "784-1990-1234567-0", "check digit does not match")
		self.assert_invalid("Emirates ID", "785-1990-1234567-6", "It should look like")

	def test_wrong_number_returned_as_typed(self):
		value = self.assert_invalid("Aadhaar", "2345 6789 0123", "check digit")
		self.assertEqual(value, "2345 6789 0123")

	def test_custom_pattern(self):
		value, error = clean_number("T", "AB1234", rules("Custom Pattern", "[A-Z]{2}[0-9]{4}"))
		self.assertEqual((value, error), ("AB1234", None))
		self.assert_invalid("Custom Pattern", "AB123", "It should look like", "[A-Z]{2}[0-9]{4}", "AB1234")
		self.assert_invalid("Custom Pattern", "AB123", "is not a valid T number.", "[A-Z]{2}[0-9]{4}")

	def test_no_format_accepts_anything(self):
		value, error = clean_number("T", "  any  thing 1 ", rules())
		self.assertEqual((value, error), ("any thing 1", None))

	def test_empty_number(self):
		for number_format in (None, "Aadhaar", "PAN"):
			self.assertEqual(clean_number("T", "   ", rules(number_format)), ("", None))
			self.assertEqual(clean_number("T", None, rules(number_format)), ("", None))

	def test_own_example_in_message(self):
		self.assert_invalid("PAN", "XYZ", "AAAPA0000A", example="AAAPA0000A")

	def test_live_rules_for_the_form(self):
		self.assertEqual(
			live_rules(rules("Aadhaar")),
			{"pattern": r"[2-9][0-9]{11}", "compact": 1, "check_digit": "verhoeff"},
		)
		self.assertEqual(live_rules(rules("Emirates ID"))["check_digit"], "luhn")
		self.assertIsNone(live_rules(rules("PAN"))["check_digit"])
		self.assertEqual(live_rules(rules("Custom Pattern", "[0-9]+")), {"pattern": "[0-9]+", "compact": 0})
		self.assertEqual(live_rules(rules()), {})

	def test_number_key_ignores_case_spaces_and_separators(self):
		for typed in ("DL-TEST-123456", "dl test 123456", "DL/TEST/123456", " Dl.Test.123456 ", "DLTEST123456"):
			self.assertEqual(number_key(typed), "DLTEST123456", typed)
		self.assertEqual(number_key("2345 6789 0124"), number_key("234567890124"))
		self.assertNotEqual(number_key("DL-TEST-123456"), number_key("DL-TEST-123457"))
		self.assertIsNone(number_key(""))
		self.assertIsNone(number_key("   "))
		self.assertIsNone(number_key(None))
