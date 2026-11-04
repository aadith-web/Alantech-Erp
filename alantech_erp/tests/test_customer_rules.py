# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""CRM-F04 Customer Creation Management (alantech_erp.sales.customer / customer_unique).

Run:
    bench --site <site> run-tests --module alantech_erp.tests.test_customer_rules

Uses "TEST-CUST" customers; everything is rolled back after each test.
"""

import frappe

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.sales.customer_unique import email_key, mobile_key, name_key


def _value(doctype):
	return (
		frappe.db.get_value(doctype, {"is_group": 0}, "name")
		if frappe.get_meta(doctype).has_field("is_group")
		else frappe.db.get_value(doctype, {}, "name")
	)


def _customer(name, mobile, email, **extra):
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": _value("Customer Group"),
			"territory": _value("Territory"),
			"industry": frappe.db.get_value("Industry Type", {}, "name"),
			"alt_tax_type": "Overseas",
			"default_currency": frappe.db.get_value("Currency", {"enabled": 1}, "name"),
			"mobile_no": mobile,
			"email_id": email,
		}
	)
	doc.update(extra)
	return doc


class TestKeys(TestCase):
	def test_mobile_key(self):
		self.assertEqual(mobile_key("+91-98470 12345"), "+919847012345")
		self.assertEqual(mobile_key("0091 9847012345"), "+919847012345")
		self.assertEqual(mobile_key("09847012345", "IN"), "+919847012345")
		self.assertIsNone(mobile_key("  "))

	def test_email_key(self):
		self.assertEqual(email_key("  Sales@ABC.com "), "sales@abc.com")

	def test_name_key(self):
		self.assertEqual(name_key("ABC Water Pvt. Ltd."), name_key("abc water private limited"))
		self.assertEqual(name_key("SC Alpha L.L.C."), name_key("SC Alpha LLC"))
		self.assertNotEqual(name_key("ABC Water"), name_key("ABC Waste"))


class TestCustomerRules(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.get_meta("Customer").has_field("alt_mobile_key"):
			raise Exception("Run bench migrate first: Customer alt_mobile_key is missing")
		if not frappe.db.get_value("Industry Type", {}, "name"):
			frappe.get_doc({"doctype": "Industry Type", "industry": "TEST-CUST Industry"}).insert()

	def test_mobile_and_email_mandatory(self):
		with self.assertRaises(frappe.ValidationError):
			_customer("TEST-CUST No Mobile", None, "nomobile@test-cust.example").insert()
		with self.assertRaises(frappe.ValidationError):
			_customer("TEST-CUST No Email", "+971-501110001", None).insert()

	def test_mobile_needs_country_code(self):
		with self.assertRaises(frappe.ValidationError):
			_customer("TEST-CUST No Code", "501110002", "nocode@test-cust.example").insert()

	def test_duplicate_mobile_blocked(self):
		_customer("TEST-CUST One", "+971-501110003", "one@test-cust.example").insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			# same number written differently
			_customer("TEST-CUST Two", "00971 50 111 0003", "two@test-cust.example").insert()

	def test_duplicate_email_blocked(self):
		_customer("TEST-CUST Three", "+971-501110004", "three@test-cust.example").insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			_customer("TEST-CUST Four", "+971-501110005", " THREE@test-cust.example ").insert()

	def test_duplicate_company_name_blocked(self):
		_customer("TEST-CUST Same Name LLC", "+971-501110006", "same1@test-cust.example").insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			_customer("test-cust same name llc", "+971-501110007", "same2@test-cust.example").insert()

	def test_individual_same_name_allowed(self):
		_customer(
			"TEST-CUST Person", "+971-501110008", "p1@test-cust.example", customer_type="Individual"
		).insert()
		_customer(
			"TEST-CUST Person", "+971-501110009", "p2@test-cust.example", customer_type="Individual"
		).insert()

	def test_disabled_customer_counts(self):
		_customer("TEST-CUST Disabled", "+971-501110010", "disabled@test-cust.example", disabled=1).insert()
		with self.assertRaises(frappe.DuplicateEntryError):
			_customer("TEST-CUST New", "+971-501110010", "new@test-cust.example").insert()

	def test_company_needs_territory_and_industry(self):
		doc = _customer("TEST-CUST No Industry", "+971-501110011", "noind@test-cust.example", industry=None)
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		_customer(
			"TEST-CUST Individual No Industry",
			"+971-501110012",
			"indiv@test-cust.example",
			customer_type="Individual",
			industry=None,
		).insert()

	def test_overseas_needs_currency(self):
		with self.assertRaises(frappe.ValidationError):
			_customer(
				"TEST-CUST No Currency", "+971-501110013", "nocur@test-cust.example", default_currency=None
			).insert()

	def test_stage_cannot_be_set_by_hand(self):
		doc = _customer(
			"TEST-CUST Stage", "+971-501110014", "stage@test-cust.example", alt_customer_stage="Customer"
		)
		doc.insert()
		self.assertEqual(doc.alt_customer_stage, "Account")
		doc.alt_customer_stage = "Customer"
		doc.save()
		self.assertEqual(frappe.db.get_value("Customer", doc.name, "alt_customer_stage"), "Account")
