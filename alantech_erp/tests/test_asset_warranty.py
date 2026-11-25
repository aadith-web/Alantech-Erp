# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Asset Warranty period and Warranty Expiry Date (setup/asset_warranty.py, ClickUp 14yr2e58k7e).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_asset_warranty

Unit: a Warranty text (import / API) is read in years / months and written back neatly; expiry =
purchase + period; the Years / Months dropdowns. Integration, copying a submitted Existing Asset of the
site (skipped when there is none): the dropdowns give the Warranty text and the expiry from the
Purchase Date; a Warranty text alone fills the dropdowns; a wrong text is refused; changing the period
on a submitted asset recalculates; clearing the dropdowns clears the Warranty; without a period a
typed expiry is kept.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import getdate

from alantech_erp.setup.asset_warranty import WarrantyError, expiry, label, parse


class UnitTestWarrantyPeriod(UnitTestCase):
	def test_parse(self):
		for text, period in {
			"2 years": (2, 0), "2 Years": (2, 0), "1 year": (1, 0), "6 months": (0, 6), "1 Month": (0, 1),
			"1 year 6 months": (1, 6), "1 yr and 3 mos": (1, 3), "2y 6m": (2, 6), " 18 months ": (0, 18),
		}.items():
			self.assertEqual(parse(text), period, text)
		for text in ("", "2", "two years", "2 weeks", "0 years", "onsite", "2 years onsite", "-1 year"):
			self.assertIsNone(parse(text), text)

	def test_label_and_expiry(self):
		self.assertEqual((label(2, 0), label(1, 6), label(0, 1)), ("2 Years", "1 Year 6 Months", "1 Month"))
		self.assertEqual(expiry("2026-11-01", 2, 0), getdate("2028-11-01"))
		self.assertEqual(expiry("2026-01-31", 0, 1), getdate("2026-02-28"))
		self.assertIsNone(expiry(None, 1, 0))

	def test_pickers(self):
		meta = frappe.get_meta("Asset")
		years, months = meta.get_field("alt_warranty_years"), meta.get_field("alt_warranty_months")
		self.assertEqual((years.fieldtype, years.options.split("\n")[1:]), ("Select", [str(n) for n in range(1, 31)]))
		self.assertEqual((months.fieldtype, months.options.split("\n")[1:]), ("Select", [str(n) for n in range(1, 12)]))
		self.assertTrue(meta.get_field("alt_warranty").read_only)


class IntegrationTestAssetWarranty(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		template = frappe.get_all("Asset", filters={"docstatus": 1, "asset_type": "Existing Asset",
			"calculate_depreciation": 0}, pluck="name", limit=1)
		if not template:
			raise cls.skipTest(cls, "Need a submitted Existing Asset without depreciation")
		cls.template = template[0]

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("asset_warranty")
		self.addCleanup(frappe.db.rollback, save_point="asset_warranty")

	def new_asset(self, **values):
		doc = frappe.copy_doc(frappe.get_doc("Asset", self.template))
		doc.update({"docstatus": 0, "custodian": None, "asset_quantity": 1, "purchase_date": "2026-11-01",
			"available_for_use_date": "2026-11-07", "alt_warranty": None, "alt_warranty_expiry_date": None,
			"alt_warranty_years": None, "alt_warranty_months": None,
			"asset_name": f"_Test Warranty {frappe.generate_hash(length=5)}", **values})
		return doc.insert()

	def test_pickers_give_text_and_expiry(self):
		doc = self.new_asset(alt_warranty_years="1", alt_warranty_months="6", alt_warranty_expiry_date="2027-01-28")
		self.assertEqual((doc.alt_warranty, getdate(doc.alt_warranty_expiry_date)), ("1 Year 6 Months", getdate("2028-05-01")))

	def test_text_alone_fills_pickers(self):
		doc = self.new_asset(alt_warranty="2 years", alt_warranty_expiry_date="2027-01-28")
		self.assertEqual((doc.alt_warranty, doc.alt_warranty_years, doc.alt_warranty_months), ("2 Years", "2", None))
		self.assertEqual(getdate(doc.alt_warranty_expiry_date), getdate("2028-11-01"))

	def test_wrong_warranty_refused(self):
		with self.assertRaises(WarrantyError) as raised:
			self.new_asset(alt_warranty="2 years onsite")
		self.assertIn("Warranty must be a period in years and / or months", str(raised.exception))

	def test_change_on_submitted_asset(self):
		doc = self.new_asset(alt_warranty_years="1")
		doc.submit()
		doc.alt_warranty_months = "6"
		doc.save()
		self.assertEqual((doc.alt_warranty, getdate(doc.alt_warranty_expiry_date)), ("1 Year 6 Months", getdate("2028-05-01")))
		doc.alt_warranty_years = doc.alt_warranty_months = None  # cleared on the form
		doc.save()
		self.assertFalse(doc.alt_warranty)

	def test_typed_expiry_kept_without_warranty(self):
		doc = self.new_asset(alt_warranty_expiry_date="2027-03-31")
		self.assertEqual(getdate(doc.alt_warranty_expiry_date), getdate("2027-03-31"))
