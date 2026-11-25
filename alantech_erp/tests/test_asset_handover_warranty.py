# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Asset Handover: Warranty, Warranty Expiry and Handover Date (ClickUp 14yr2e58k7e).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_asset_handover_warranty

Unit: expired or not; the fields (Asset Warranty / Warranty Expiry Date, the row columns, "Handover
Date"). Integration, with a free grouped asset of the site (skipped when there is none): picking the
asset gives its warranty; saving copies it to the row; issuing an expired-warranty asset is allowed
with a warning; the employee's assets and the Employee Asset Holdings report show the expiry.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, getdate, now_datetime, today

from alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover import (
	available_qty,
	get_asset_details,
	get_assets_held,
	warranty_expired,
)
from alantech_erp.alantech.report.employee_asset_holdings.employee_asset_holdings import execute as holdings_report


class UnitTestWarranty(UnitTestCase):
	def test_expired(self):
		self.assertTrue(warranty_expired(add_days(today(), -1)))
		self.assertFalse(warranty_expired(today()))  # valid through its last day
		self.assertFalse(warranty_expired(None))
		self.assertTrue(warranty_expired("2026-01-01", "2026-06-01"))

	def test_fields(self):
		asset = frappe.get_meta("Asset")
		self.assertEqual(asset.get_field("alt_warranty").label, "Warranty")
		self.assertEqual(asset.get_field("alt_warranty_expiry_date").fieldtype, "Date")
		item = frappe.get_meta("Employee Asset Handover Item")
		self.assertTrue(item.get_field("warranty_expiry_date").in_list_view)
		self.assertTrue(item.get_field("warranty").read_only)
		self.assertEqual(frappe.get_meta("Employee Asset Handover").get_field("transaction_date").label, "Handover Date")


class IntegrationTestHandoverWarranty(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		grouped = frappe.get_all("Asset", filters={"docstatus": 1, "custodian": ["is", "not set"], "asset_quantity": [">", 1],
			"status": ["not in", ("Sold", "Scrapped", "Out of Order")]}, fields=["name", "company"], limit=1)
		if not grouped:
			raise cls.skipTest(cls, "Need a free submitted grouped asset")
		cls.asset = grouped[0]
		employee = frappe.get_all("Employee", filters={"status": "Active", "company": cls.asset.company}, pluck="name",
			order_by="creation", limit=1)
		if not employee:
			raise cls.skipTest(cls, "Need an active employee of the asset's company")
		cls.employee = employee[0]

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("handover_warranty")
		self.addCleanup(frappe.db.rollback, save_point="handover_warranty")
		if available_qty(self.asset.name) < 1:
			self.skipTest("Need a free unit of the grouped asset")

	def set_warranty(self, expiry):
		frappe.db.set_value("Asset", self.asset.name, {"alt_warranty": "2 years onsite", "alt_warranty_expiry_date": expiry})

	def issue(self):
		frappe.clear_messages()
		return frappe.get_doc({"doctype": "Employee Asset Handover", "transaction_type": "Issue",
			"transaction_date": now_datetime(), "employee": self.employee,
			"items": [{"asset": self.asset.name, "qty": 1}]}).insert()

	def test_details_and_row_show_warranty(self):
		expiry = add_days(today(), 200)
		self.set_warranty(expiry)
		d = get_asset_details(self.asset.name, "Issue")
		self.assertEqual((d["warranty"], getdate(d["warranty_expiry_date"]), d["warranty_expired"]),
			("2 years onsite", getdate(expiry), False))
		doc = self.issue()
		self.assertEqual((doc.items[0].warranty, getdate(doc.items[0].warranty_expiry_date)), ("2 years onsite", getdate(expiry)))
		self.assertFalse([m for m in frappe.get_message_log() if "warranty" in str(m.get("message", "")).lower()])

	def test_expired_warranty_warned_not_blocked(self):
		self.set_warranty(add_days(today(), -10))
		self.assertTrue(get_asset_details(self.asset.name, "Issue")["warranty_expired"])
		doc = self.issue()  # allowed
		self.assertTrue(doc.name)
		messages = [str(m.get("message", "")) for m in frappe.get_message_log()]
		self.assertTrue(any("warranty of asset" in m and "expired on" in m for m in messages), messages)

	def test_held_assets_and_report_show_expiry(self):
		expiry = add_days(today(), 30)
		self.set_warranty(expiry)
		self.issue().submit()
		held = {a.asset: a for a in get_assets_held(self.employee)}
		self.assertEqual(getdate(held[self.asset.name].warranty_expiry_date), getdate(expiry))
		rows = [r for r in holdings_report({"employee": self.employee})[1] if r["asset"] == self.asset.name]
		self.assertEqual(getdate(rows[0]["warranty_expiry_date"]), getdate(expiry))
