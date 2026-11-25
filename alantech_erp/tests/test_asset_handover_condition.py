# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Asset Handover: Condition (Good / Damaged) on every asset row (ClickUp 14yr2e58jx0,
parent 14yr2e58h6r).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_asset_handover_condition

Unit: Condition is a mandatory Good / Damaged dropdown, default Good, on every handover (no longer
only a Receipt with inspection). Integration, with a free grouped asset of the site (skipped when
there is none): Issue rows get Good by default and keep Damaged with details; Damaged without details
is refused; a Damaged return creates an Asset Repair without the inspection tick; a Good row has no
damage details.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import now_datetime

from alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover import available_qty

DOCTYPE = "Employee Asset Handover"


class UnitTestConditionField(UnitTestCase):
	def test_condition_dropdown_on_every_row(self):
		df = frappe.get_meta("Employee Asset Handover Item").get_field("condition")
		self.assertEqual((df.fieldtype, df.options.split("\n"), df.default, df.reqd), ("Select", ["Good", "Damaged"], "Good", 1))
		self.assertFalse(df.depends_on)  # not only a Receipt with inspection
		self.assertIn("Damaged", frappe.get_meta("Employee Asset Handover Item").get_field("issue_description").mandatory_depends_on)


class IntegrationTestHandoverCondition(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		grouped = frappe.get_all("Asset", filters={"docstatus": 1, "custodian": ["is", "not set"], "asset_quantity": [">", 1],
			"status": ["not in", ("Sold", "Scrapped", "Out of Order")]}, fields=["name", "company", "location"], limit=1)
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
		frappe.db.savepoint("handover_cond")
		self.addCleanup(frappe.db.rollback, save_point="handover_cond")
		if available_qty(self.asset.name) < 2:
			self.skipTest("Need 2 free units of the grouped asset")

	def handover(self, transaction_type, condition=None, details=None, submit=True, **values):
		row = {"asset": self.asset.name, "qty": 1, "issue_description": details}
		if condition:
			row["condition"] = condition
		if transaction_type == "Receipt":
			row["return_location"] = self.asset.location
		doc = frappe.get_doc({"doctype": DOCTYPE, "transaction_type": transaction_type, "transaction_date": now_datetime(),
			"employee": self.employee, "items": [row], **values}).insert()
		if submit:
			doc.submit()
		return doc

	def test_issue_defaults_to_good(self):
		doc = self.handover("Issue", submit=False)
		self.assertEqual(doc.items[0].condition, "Good")

	def test_issue_records_damaged_with_details(self):
		doc = self.handover("Issue", "Damaged", "Scratch on the lid")
		self.assertEqual((doc.items[0].condition, doc.items[0].issue_description), ("Damaged", "Scratch on the lid"))
		self.assertFalse(doc.items[0].asset_repair)  # an Issue only records it

	def test_damaged_needs_details(self):
		with self.assertRaises(frappe.ValidationError) as raised:
			self.handover("Issue", "Damaged", submit=False)
		self.assertIn("Damage Details", str(raised.exception))

	def test_damaged_return_creates_repair_without_inspection(self):
		self.handover("Issue")
		receipt = self.handover("Receipt", "Damaged", "Screen cracked", inspection_required=0)
		repair = frappe.db.get_value("Employee Asset Handover Item", {"parent": receipt.name}, "asset_repair")
		self.assertTrue(repair)
		self.assertEqual(frappe.db.get_value("Asset Repair", repair, "alt_responsible_employee"), self.employee)

	def test_good_row_drops_damage_details(self):
		doc = self.handover("Issue", "Good", "left over text", submit=False)
		self.assertFalse(doc.items[0].issue_description)
