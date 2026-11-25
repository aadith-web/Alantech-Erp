# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Asset Handover: Return To Location per asset row (ClickUp 14yr2e58hwg).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_asset_handover_return_location

Unit: the field moved from the form to the Assets table, right after Current Location, required on a
Receipt. Integration, with the site's submitted assets (a single one and a grouped one, both free; two
Locations; skipped otherwise):
- A Receipt row without a Return To Location is refused with the row and asset.
- Rows of one receipt go to different locations; the Asset Movement moves the single asset to its
  row's location and the Asset's Location follows.
- An Issue clears Return To Location.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import now_datetime

DOCTYPE = "Employee Asset Handover"
ITEM = "Employee Asset Handover Item"


class UnitTestReturnLocationField(UnitTestCase):
	def test_field_moved_to_the_table(self):
		self.assertFalse(frappe.get_meta(DOCTYPE).has_field("location"))
		item = frappe.get_meta(ITEM)
		order = [f.fieldname for f in item.fields]
		self.assertEqual(order[order.index("current_location") + 1], "return_location")
		df = item.get_field("return_location")
		self.assertEqual((df.fieldtype, df.options, df.label, df.in_list_view), ("Link", "Location", "Return To Location", 1))
		self.assertIn("Receipt", df.mandatory_depends_on)
		self.assertFalse(df.read_only)


class IntegrationTestReturnLocationPerRow(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		usable = {"docstatus": 1, "status": ["not in", ("Sold", "Scrapped", "Out of Order")]}
		free = {**usable, "custodian": ["is", "not set"]}
		# a single asset, free or already issued to an Active employee (then received from them)
		single = [a for a in frappe.get_all("Asset", filters={**usable, "asset_quantity": ["<=", 1]},
			fields=["name", "company", "location", "custodian"], order_by="custodian asc")
			if not a.custodian or frappe.db.get_value("Employee", a.custodian, "status") == "Active"]
		if not single:
			raise cls.skipTest(cls, "Need a submitted single asset")
		cls.single = single[0]
		grouped = frappe.get_all("Asset", filters={**free, "asset_quantity": [">", 1], "company": cls.single.company},
			fields=["name", "location"], limit=1)
		cls.grouped = grouped[0] if grouped else None
		cls.locations = frappe.get_all("Location", pluck="name", limit=2)
		if len(cls.locations) < 2:
			raise cls.skipTest(cls, "Need two Locations")
		cls.other = next(loc for loc in cls.locations if loc != cls.single.location)
		employee = [cls.single.custodian] if cls.single.custodian else frappe.get_all("Employee",
			filters={"status": "Active", "company": cls.single.company}, pluck="name", order_by="creation", limit=1)
		if not employee:
			raise cls.skipTest(cls, "Need an active employee of the asset's company")
		cls.employee = employee[0]

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("ret_loc")
		self.addCleanup(frappe.db.rollback, save_point="ret_loc")

	def handover(self, transaction_type, rows, submit=True):
		doc = frappe.get_doc({
			"doctype": DOCTYPE,
			"transaction_type": transaction_type,
			"transaction_date": now_datetime(),
			"employee": self.employee,
			"items": [{"asset": a, "qty": q, "return_location": loc} for a, q, loc in rows],
		}).insert()
		if submit:
			doc.submit()
		return doc

	def issue_all(self):
		rows = [] if self.single.custodian else [(self.single.name, 1, None)]
		if self.grouped:
			rows.append((self.grouped.name, 2, None))
		if rows:
			self.handover("Issue", rows)

	def test_issue_clears_return_location(self):
		if not self.grouped:
			self.skipTest("Need a free grouped asset")
		doc = self.handover("Issue", [(self.grouped.name, 1, self.other)], submit=False)
		self.assertFalse(doc.items[0].return_location)

	def test_receipt_row_without_location_refused(self):
		self.issue_all()
		with self.assertRaises(frappe.ValidationError) as raised:
			self.handover("Receipt", [(self.single.name, 1, None)], submit=False)
		self.assertIn(f"Row 1: select the Return To Location for asset {self.single.name}", str(raised.exception))

	def test_each_row_its_own_location(self):
		self.issue_all()
		rows = [(self.single.name, 1, self.other)]
		if self.grouped:
			rows.append((self.grouped.name, 2, self.single.location or self.locations[0]))
		receipt = self.handover("Receipt", rows)
		self.assertEqual([r.return_location for r in receipt.items], [r[2] for r in rows])
		moved = frappe.get_all("Asset Movement Item", filters={"parent": receipt.asset_movement},
			fields=["asset", "target_location"])
		self.assertEqual(moved, [{"asset": self.single.name, "target_location": self.other}])
		self.assertEqual(frappe.db.get_value("Asset", self.single.name, "location"), self.other)
