# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Asset Handover quantities (ClickUp 14yr2e58hbm, parent 14yr2e58az7).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_asset_handover_quantity

Unit: grouped or single asset. Integration, with the site's submitted assets (a grouped one with
Asset Quantity above 1 and a single one, both free; skipped when there are none):
- Issue up to the Available Qty, refused above it; Available Qty goes down; no Asset Movement and
  no Custodian for a grouped asset.
- Receipt up to what the employee holds; cancelling refused when it would make a holding negative.
- Single asset: Quantity must be 1; Asset Movement and Custodian as before.
- Asset picker shows Available / Held quantities; get_asset_details; the employee's assets and the
  Employee Asset Holdings report include the grouped holding with its quantity.

Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import now_datetime

from alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover import (
	asset_query,
	available_qty,
	get_asset_details,
	get_assets_held,
	held_qty,
	is_grouped,
)
from alantech_erp.alantech.report.employee_asset_holdings.employee_asset_holdings import execute as holdings_report

DOCTYPE = "Employee Asset Handover"


class UnitTestGroupedAsset(UnitTestCase):
	def test_grouped_or_single(self):
		self.assertTrue(is_grouped({"asset_quantity": 5}))
		self.assertFalse(is_grouped({"asset_quantity": 1}))
		self.assertFalse(is_grouped({"asset_quantity": None}))


class IntegrationTestAssetHandoverQuantity(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		free = {"docstatus": 1, "custodian": ["is", "not set"], "status": ["not in", ("Sold", "Scrapped", "Out of Order")]}
		cls.grouped = frappe.get_all("Asset", filters={**free, "asset_quantity": [">", 2]},
			fields=["name", "company", "asset_quantity"], limit=1)
		cls.single = frappe.get_all("Asset", filters={**free, "asset_quantity": ["<=", 1]},
			fields=["name", "company"], limit=1)
		if not cls.grouped:
			raise cls.skipTest(cls, "Need a submitted grouped asset (Asset Quantity above 2)")
		cls.grouped = cls.grouped[0]
		employees = frappe.get_all("Employee", filters={"status": "Active", "company": cls.grouped.company},
			pluck="name", order_by="creation", limit=2)
		if len(employees) < 2:
			raise cls.skipTest(cls, "Need two active employees of the asset's company")
		cls.emp_a, cls.emp_b = employees

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("asset_qty")
		self.addCleanup(frappe.db.rollback, save_point="asset_qty")
		# start from what is free now, whatever the site's earlier handovers did
		self.free = available_qty(self.grouped.name)
		if self.free < 3:
			self.skipTest("Need at least 3 free units of the grouped asset")

	def handover(self, employee, rows, transaction_type="Issue", submit=True):
		doc = frappe.get_doc({
			"doctype": DOCTYPE,
			"transaction_type": transaction_type,
			"transaction_date": now_datetime(),
			"employee": employee,
			"location": frappe.db.get_value("Asset", self.grouped.name, "location") if transaction_type == "Receipt" else None,
			"items": [{"asset": asset, "qty": qty} for asset, qty in rows],
		}).insert()
		if submit:
			doc.submit()
		return doc

	def test_issue_up_to_available(self):
		doc = self.handover(self.emp_a, [(self.grouped.name, 2)])
		self.assertEqual(doc.items[0].available_qty, self.free)  # what was free when it was saved
		self.assertFalse(doc.asset_movement)  # grouped: no Asset Movement
		self.assertFalse(frappe.db.get_value("Asset", self.grouped.name, "custodian"))
		self.assertEqual(available_qty(self.grouped.name), self.free - 2)
		self.assertEqual(held_qty(self.grouped.name), {self.emp_a: 2})

	def test_issue_above_available_refused(self):
		with self.assertRaises(frappe.ValidationError) as raised:
			self.handover(self.emp_a, [(self.grouped.name, self.free + 1)], submit=False)
		self.assertIn(f"only {self.free} of asset {self.grouped.name}", str(raised.exception))
		self.handover(self.emp_a, [(self.grouped.name, self.free - 1)])
		with self.assertRaises(frappe.ValidationError):
			self.handover(self.emp_b, [(self.grouped.name, 2)], submit=False)  # only 1 left
		self.handover(self.emp_b, [(self.grouped.name, 1)])
		self.assertEqual(available_qty(self.grouped.name), 0)

	def test_zero_quantity_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.handover(self.emp_a, [(self.grouped.name, 0)], submit=False)

	def test_receipt_up_to_held(self):
		self.handover(self.emp_a, [(self.grouped.name, 2)])
		with self.assertRaises(frappe.ValidationError) as raised:
			self.handover(self.emp_a, [(self.grouped.name, 3)], "Receipt", submit=False)
		self.assertIn("holds only 2", str(raised.exception))
		with self.assertRaises(frappe.ValidationError):
			self.handover(self.emp_b, [(self.grouped.name, 1)], "Receipt", submit=False)  # holds none
		self.handover(self.emp_a, [(self.grouped.name, 1)], "Receipt")
		self.assertEqual(held_qty(self.grouped.name), {self.emp_a: 1})
		self.assertEqual(available_qty(self.grouped.name), self.free - 1)
		self.assertEqual(available_qty(self.grouped.name, "Receipt", self.emp_a), 1)

	def test_cancel_keeps_holdings_consistent(self):
		issue = self.handover(self.emp_a, [(self.grouped.name, 2)])
		receipt = self.handover(self.emp_a, [(self.grouped.name, 2)], "Receipt")
		with self.assertRaises(frappe.ValidationError) as raised:
			frappe.get_doc(DOCTYPE, issue.name).cancel()  # its units were already received back
		self.assertIn("already received back", str(raised.exception))
		frappe.get_doc(DOCTYPE, receipt.name).cancel()
		self.assertEqual(held_qty(self.grouped.name), {self.emp_a: 2})
		frappe.get_doc(DOCTYPE, issue.name).cancel()
		self.assertEqual(available_qty(self.grouped.name), self.free)

	def test_cancel_receipt_refused_when_reissued(self):
		self.handover(self.emp_a, [(self.grouped.name, self.free)])
		receipt = self.handover(self.emp_a, [(self.grouped.name, 1)], "Receipt")
		self.handover(self.emp_b, [(self.grouped.name, 1)])  # the returned unit issued again
		with self.assertRaises(frappe.ValidationError) as raised:
			frappe.get_doc(DOCTYPE, receipt.name).cancel()
		self.assertIn("issued again", str(raised.exception))

	def test_single_asset_quantity_one_and_movement(self):
		if not self.single or self.single[0].company != self.grouped.company:
			self.skipTest("Need a free single asset of the same company")
		name = self.single[0].name
		with self.assertRaises(frappe.ValidationError) as raised:
			self.handover(self.emp_a, [(name, 2)], submit=False)
		self.assertIn("single asset; its Quantity must be 1", str(raised.exception))
		doc = self.handover(self.emp_a, [(name, 1), (self.grouped.name, 2)])
		self.assertTrue(doc.asset_movement)
		self.assertEqual(frappe.get_all("Asset Movement Item", filters={"parent": doc.asset_movement}, pluck="asset"), [name])
		self.assertEqual(frappe.db.get_value("Asset", name, "custodian"), self.emp_a)
		held = {a.asset: a.qty for a in get_assets_held(self.emp_a)}
		self.assertEqual((held.get(name), held.get(self.grouped.name)), (1, 2))

	def test_picker_shows_quantities(self):
		def options(transaction_type, employee=None):
			rows = asset_query("Asset", self.grouped.name, "name", 0, 50,
				{"transaction_type": transaction_type, "employee": employee, "company": self.grouped.company})
			return {r[0]: r for r in rows}

		row = options("Issue")[self.grouped.name]
		self.assertEqual(row[2], f"Available: {self.free}")
		self.assertNotIn(self.grouped.name, options("Receipt", self.emp_a))
		self.handover(self.emp_a, [(self.grouped.name, self.free)])
		self.assertNotIn(self.grouped.name, options("Issue"))  # nothing left
		self.assertEqual(options("Receipt", self.emp_a)[self.grouped.name][2], f"Held: {self.free}")

	def test_asset_details_for_the_row(self):
		d = get_asset_details(self.grouped.name, "Issue", self.emp_a)
		self.assertTrue(d["grouped"])
		self.assertEqual((d["available_qty"], d["asset_quantity"]), (self.free, self.grouped.asset_quantity))
		self.assertTrue(d["asset_name"])
		self.assertEqual(get_asset_details(self.grouped.name, "Receipt", self.emp_a)["available_qty"], 0)

	def test_holdings_report_quantity(self):
		self.handover(self.emp_a, [(self.grouped.name, 2)])
		rows = [r for r in holdings_report({"employee": self.emp_a})[1] if r["asset"] == self.grouped.name]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["qty"], 2)
		self.assertTrue(rows[0]["issued_on"])


class IntegrationTestAssetRowFetch(IntegrationTestCase):
	"""ClickUp 14yr2e58az7: picking an asset fills the row before saving, also for an HR User who
	has no read access on Asset (a fetch_from would fail for them with "Cannot Fetch Values")."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from alantech_erp.alantech.doctype.document.test_document import make_user

		cls.asset = frappe.get_all("Asset", filters={"docstatus": 1, "custodian": ["is", "not set"],
			"status": ["not in", ("Sold", "Scrapped", "Out of Order")]}, fields=["name", "asset_name", "location", "company"],
			limit=1)
		if not cls.asset:
			raise cls.skipTest(cls, "Need a free submitted asset")
		cls.asset = cls.asset[0]
		cls.hr_user = make_user("_test-asset-hru@example.com", ["HR User"])

	def setUp(self):
		frappe.db.savepoint("asset_fetch")
		self.addCleanup(frappe.db.rollback, save_point="asset_fetch")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(self.hr_user)

	def test_hr_user_without_asset_access_gets_the_details(self):
		self.assertFalse(frappe.has_permission("Asset", "read"))
		d = get_asset_details(self.asset.name, "Issue")
		self.assertEqual((d["asset_name"], d["current_location"]), (self.asset.asset_name, self.asset.location))
		self.assertGreaterEqual(d["available_qty"], 1)

	def test_link_check_accepts_the_picked_asset(self):
		"""The form's link check runs the handover's asset query, so the picked asset is kept."""
		from frappe.client import validate_link_and_fetch

		query = "alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover.asset_query"
		previous = getattr(frappe.local, "request", None)
		frappe.local.request = frappe._dict(method="POST")
		self.addCleanup(setattr, frappe.local, "request", previous)
		result = validate_link_and_fetch("Asset", self.asset.name, query=query,
			filters={"transaction_type": "Issue", "company": self.asset.company})
		self.assertEqual(result.get("name"), self.asset.name)

	def test_employee_without_handover_role_refused(self):
		from alantech_erp.alantech.doctype.document.test_document import make_user

		frappe.set_user("Administrator")
		frappe.set_user(make_user("_test-asset-emp@example.com", ["Employee"]))
		with self.assertRaises(frappe.PermissionError):
			get_asset_details(self.asset.name, "Issue")
