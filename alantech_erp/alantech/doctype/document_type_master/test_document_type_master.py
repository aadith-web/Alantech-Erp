# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Document Type Master (HR-F07 Employee Documents, ClickUp 14yr2e56cak).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.document_type_master.test_document_type_master
"""

import frappe
from frappe.tests import IntegrationTestCase

IGNORE_TEST_RECORD_DEPENDENCIES = ["Country"]


def make_type(name, **values):
	"""A Document Type Master, created or reset to the given values."""
	doc = frappe.get_doc("Document Type Master", name) if frappe.db.exists("Document Type Master", name) else (
		frappe.new_doc("Document Type Master")
	)
	doc.update(
		{
			"document_type_name": name,
			"disabled": 0,
			"number_required": 1,
			"number_format": None,
			"number_pattern": None,
			"number_example": None,
			"number_mandatory": 0,
			"issue_date_required": 1,
			"issue_date_mandatory": 0,
			"expiry_required": 0,
			"expiry_date_mandatory": 0,
			"alert_days_before": 30,
			**values,
		}
	)
	doc.save(ignore_permissions=True)
	return doc


class IntegrationTestDocumentTypeMaster(IntegrationTestCase):
	def test_named_by_document_type_name(self):
		doc = make_type("_Test DTM Name")
		self.assertEqual(doc.name, "_Test DTM Name")

	def test_hidden_date_cannot_be_mandatory(self):
		doc = make_type(
			"_Test DTM Dates",
			issue_date_required=0,
			issue_date_mandatory=1,
			expiry_required=0,
			expiry_date_mandatory=1,
		)
		self.assertEqual(doc.issue_date_mandatory, 0)
		self.assertEqual(doc.expiry_date_mandatory, 0)

	def test_hidden_number_cannot_be_mandatory(self):
		"""ClickUp 14yr2e58dq2: Show Number unticked -> no Number Mandatory, no Number Format."""
		doc = make_type("_Test DTM No Number", number_required=0, number_mandatory=1, number_format="PAN")
		self.assertEqual((doc.number_mandatory, doc.number_format), (0, None))
		doc = make_type("_Test DTM No Number", number_required=1, number_mandatory=1, number_format="PAN")
		self.assertEqual((doc.number_mandatory, doc.number_format), (1, "PAN"))

	def test_shown_date_can_be_mandatory(self):
		doc = make_type("_Test DTM Mandatory", expiry_required=1, expiry_date_mandatory=1, issue_date_mandatory=1)
		self.assertEqual(doc.issue_date_mandatory, 1)
		self.assertEqual(doc.expiry_date_mandatory, 1)

	def test_example_filled_for_known_format(self):
		for number_format, example in (
			("Aadhaar", "2345 6789 0124"),
			("PAN", "ABCPE1234F"),
			("Emirates ID", "784-1990-1234567-6"),
		):
			with self.subTest(number_format=number_format):
				doc = make_type(f"_Test DTM {number_format}", number_format=number_format)
				self.assertEqual(doc.number_example, example)

	def test_own_example_kept(self):
		doc = make_type("_Test DTM Own Example", number_format="PAN", number_example="AAAPA0000A")
		self.assertEqual(doc.number_example, "AAAPA0000A")

	def test_custom_pattern_must_be_valid_regex(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_type("_Test DTM Bad Pattern", number_format="Custom Pattern", number_pattern="[A-Z")
		self.assertIn("not a valid regular expression", str(ctx.exception))

	def test_custom_pattern_saved(self):
		doc = make_type("_Test DTM Pattern", number_format="Custom Pattern", number_pattern="[A-Z]{2}[0-9]{4}")
		self.assertEqual(doc.number_pattern, "[A-Z]{2}[0-9]{4}")

	def test_pattern_cleared_for_other_formats(self):
		doc = make_type("_Test DTM Cleared", number_format="PAN", number_pattern="[0-9]+")
		self.assertFalse(doc.number_pattern)
