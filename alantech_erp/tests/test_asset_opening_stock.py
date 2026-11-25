# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Asset Opening Stock for an Existing Asset (setup/asset_opening_stock.py, ClickUp 14yr2e58hv1).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_asset_opening_stock

Unit: Opening Stock counts only for an Existing Asset. Integration, copying a submitted Existing Asset
of the site (skipped when there is none): Opening Stock N gives N assets in total (this one + N - 1
made by the job; in tests the job runs at once), each with the same values and Asset Quantity 1;
cleared for other types; the job never makes too many; the status shown on the form.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from alantech_erp.setup import asset_opening_stock as opening


class UnitTestOpeningStockUnits(UnitTestCase):
	def test_only_existing_asset(self):
		self.assertEqual(opening.units(frappe._dict(asset_type="Existing Asset", alt_opening_stock=10)), 10)
		self.assertEqual(opening.units(frappe._dict(asset_type="Composite Asset", alt_opening_stock=10)), 0)
		self.assertEqual(opening.units(frappe._dict(asset_type="", alt_opening_stock=3)), 0)


class IntegrationTestAssetOpeningStock(IntegrationTestCase):
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
		frappe.db.savepoint("opening_stock")
		self.addCleanup(frappe.db.rollback, save_point="opening_stock")

	def new_asset(self, stock, asset_type="Existing Asset"):
		doc = frappe.copy_doc(frappe.get_doc("Asset", self.template))
		doc.update({"asset_type": asset_type, "alt_opening_stock": stock, "asset_quantity": 3,
			"custodian": None, "asset_name": f"_Test Opening Stock {frappe.generate_hash(length=5)}"})
		return doc.insert()

	def copies(self, asset):
		return frappe.get_all("Asset", filters={"alt_opening_stock_of": asset},
			fields=["name", "docstatus", "asset_name", "net_purchase_amount", "location", "asset_quantity",
				"alt_opening_stock"])

	def test_opening_stock_creates_one_asset_per_unit(self):
		doc = self.new_asset(4)
		self.assertEqual(doc.asset_quantity, 1)  # one asset per unit
		doc.submit()
		copies = self.copies(doc.name)
		self.assertEqual(len(copies) + 1, 4)
		for c in copies:
			self.assertEqual((c.docstatus, c.asset_name, c.location, c.asset_quantity, c.alt_opening_stock),
				(1, doc.asset_name, doc.location, 1, 0))
			self.assertEqual(c.net_purchase_amount, doc.net_purchase_amount)
		self.assertEqual(opening.get_opening_stock_status(doc.name), {"total": 4, "created": 4})

	def test_job_only_makes_what_is_missing(self):
		doc = self.new_asset(3)
		doc.submit()
		self.assertEqual(opening.create_opening_assets(doc.name), 0)
		frappe.get_doc("Asset", self.copies(doc.name)[0].name).cancel()
		self.assertEqual(opening.create_opening_assets(doc.name), 1)
		self.assertEqual(opening.created_count(doc.name), 2)

	def test_one_or_blank_creates_nothing_more(self):
		for stock in (0, 1):
			doc = self.new_asset(stock)
			doc.submit()
			self.assertEqual(self.copies(doc.name), [])

	def test_cleared_for_other_asset_types(self):
		doc = frappe.copy_doc(frappe.get_doc("Asset", self.template))
		doc.update({"asset_type": "", "alt_opening_stock": 5})
		opening.validate(doc)
		self.assertEqual(doc.alt_opening_stock, 0)

	def test_field_shown_only_for_existing_asset(self):
		df = frappe.get_meta("Asset").get_field("alt_opening_stock")
		self.assertIn('asset_type=="Existing Asset"', df.depends_on)
		self.assertEqual((df.fieldtype, df.label, df.no_copy), ("Int", "Opening Stock", 1))
