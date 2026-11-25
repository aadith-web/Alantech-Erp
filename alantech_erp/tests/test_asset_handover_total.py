# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Asset Handover: Total Assets on the form and in the list (ClickUp 14yr2e58jwz, parent
14yr2e58h6r).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_asset_handover_total

Also (ClickUp 14yr2e58jwx): the table is not mandatory, empty rows are dropped, no asset is refused.

Unit: the total is the number of assets (rows without an asset ignored; Quantity does not count); the field is
read-only, in the list view, after the Assets table. Integration, with a free grouped asset of the
site (skipped when there is none): saved total follows the rows, not the Quantity.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import now_datetime

from alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover import (
	available_qty,
	total_assets,
)


class UnitTestTotalAssets(UnitTestCase):
	def test_number_of_assets(self):
		rows = [frappe._dict(asset="A", qty=3), frappe._dict(asset="B", qty=1), frappe._dict(asset=None, qty=5)]
		self.assertEqual(total_assets(rows), 2)
		self.assertEqual(total_assets([]), 0)

	def test_field(self):
		meta = frappe.get_meta("Employee Asset Handover")
		df = meta.get_field("total_assets")
		self.assertEqual((df.fieldtype, df.label, df.read_only, df.in_list_view), ("Int", "Total Assets", 1, 1))
		order = [f.fieldname for f in meta.fields]
		self.assertEqual(order[order.index("items") + 1], "total_assets")


class IntegrationTestTotalAssets(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		grouped = frappe.get_all("Asset", filters={"docstatus": 1, "custodian": ["is", "not set"], "asset_quantity": [">", 2],
			"status": ["not in", ("Sold", "Scrapped", "Out of Order")]}, fields=["name", "company"], limit=2)
		if not grouped:
			raise cls.skipTest(cls, "Need a free submitted grouped asset")
		cls.assets = grouped
		employee = frappe.get_all("Employee", filters={"status": "Active", "company": grouped[0].company}, pluck="name",
			order_by="creation", limit=1)
		if not employee:
			raise cls.skipTest(cls, "Need an active employee of the asset's company")
		cls.employee = employee[0]

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("handover_total")
		self.addCleanup(frappe.db.rollback, save_point="handover_total")
		if available_qty(self.assets[0].name) < 3:
			self.skipTest("Need 3 free units of the grouped asset")

	def test_total_counts_rows_not_quantity(self):
		rows = [{"asset": self.assets[0].name, "qty": 3}]
		if len(self.assets) > 1 and available_qty(self.assets[1].name) >= 2:
			rows.append({"asset": self.assets[1].name, "qty": 2})
		doc = frappe.get_doc({"doctype": "Employee Asset Handover", "transaction_type": "Issue",
			"transaction_date": now_datetime(), "employee": self.employee, "items": rows}).insert()
		self.assertEqual(doc.total_assets, len(rows))
		doc.items[0].qty = 1
		doc.save()
		self.assertEqual(doc.total_assets, len(rows))  # Quantity does not change it
		if len(rows) > 1:
			doc.remove(doc.items[1])
			doc.save()
			self.assertEqual(doc.total_assets, 1)
		self.assertEqual(frappe.db.get_value("Employee Asset Handover", doc.name, "total_assets"), doc.total_assets)


class IntegrationTestEmptyAssetsTable(IntegrationTestCase):
	"""ClickUp 14yr2e58jwx: the Assets table is not marked mandatory (no red border on a new form);
	empty rows are dropped on save; no asset at all is refused with a clear message."""

	def test_table_not_marked_mandatory(self):
		self.assertFalse(frappe.get_meta("Employee Asset Handover").get_field("items").reqd)

	def test_no_asset_refused(self):
		frappe.set_user("Administrator")
		employee = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)
		if not employee:
			self.skipTest("Need an active employee")
		for items in ([], [{"qty": 1}]):  # no rows; only the empty first row
			doc = frappe.get_doc({"doctype": "Employee Asset Handover", "transaction_type": "Issue",
				"transaction_date": now_datetime(), "employee": employee[0], "items": items})
			with self.assertRaises(frappe.ValidationError) as raised:
				doc.insert()
			self.assertIn("Add at least one asset in the Assets table", str(raised.exception))

	def test_empty_row_dropped(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("handover_empty")
		self.addCleanup(frappe.db.rollback, save_point="handover_empty")
		asset = frappe.get_all("Asset", filters={"docstatus": 1, "custodian": ["is", "not set"], "asset_quantity": [">", 1],
			"status": ["not in", ("Sold", "Scrapped", "Out of Order")]}, fields=["name", "company"], limit=1)
		if not asset or available_qty(asset[0].name) < 1:
			self.skipTest("Need a free grouped asset")
		employee = frappe.get_all("Employee", filters={"status": "Active", "company": asset[0].company}, pluck="name", limit=1)
		doc = frappe.get_doc({"doctype": "Employee Asset Handover", "transaction_type": "Issue",
			"transaction_date": now_datetime(), "employee": employee[0],
			"items": [{"qty": 1}, {"asset": asset[0].name, "qty": 1}]}).insert()
		self.assertEqual([(r.idx, r.asset) for r in doc.items], [(1, asset[0].name)])
		self.assertEqual(doc.total_assets, 1)
