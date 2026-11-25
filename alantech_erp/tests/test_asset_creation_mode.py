# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Asset Create As: Grouped Asset / Single Asset (setup/asset_creation_mode.py, ClickUp 14yr2e58hv1).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_asset_creation_mode

Unit: the field (one Select, default Grouped Asset, right after Asset Quantity). Integration, copying
a submitted Existing Asset of the site (skipped when there is none):
- Grouped Asset: quantity N stays one asset of quantity N; nothing queued.
- Single Asset: the submit queues the job (after commit, so the submit is not held up); the job leaves
  N assets of quantity 1 sharing the amount, the new ones Split From the first; running it again
  makes nothing more; the status shown on the form.
Data: each test runs in a savepoint that is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import flt

from alantech_erp.setup import asset_creation_mode as mode


class UnitTestCreateAsField(UnitTestCase):
	def test_one_option_default_grouped(self):
		df = frappe.get_meta("Asset").get_field(mode.FIELD)
		self.assertEqual((df.fieldtype, df.label, df.default), ("Select", "Create As", "Grouped Asset"))
		self.assertEqual(df.options.split("\n"), ["Grouped Asset", "Single Asset"])
		order = [f.fieldname for f in frappe.get_meta("Asset").fields]
		self.assertEqual(order[order.index("asset_quantity") + 1], mode.FIELD)


class IntegrationTestAssetCreationMode(IntegrationTestCase):
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
		frappe.db.savepoint("asset_mode")
		self.addCleanup(frappe.db.rollback, save_point="asset_mode")

	def submit(self, qty, create_as, amount=10000):
		doc = frappe.copy_doc(frappe.get_doc("Asset", self.template))
		doc.update({"docstatus": 0, "asset_quantity": qty, mode.FIELD: create_as, "net_purchase_amount": amount,
			"custodian": None, "asset_name": f"_Test Asset Mode {frappe.generate_hash(length=5)}"})
		doc.insert()
		with patch("frappe.enqueue") as enqueue:
			doc.submit()
		return doc, enqueue

	def units(self, asset):
		return frappe.get_all("Asset", filters={"split_from": asset, "docstatus": 1},
			fields=["asset_quantity", "net_purchase_amount", "asset_name", mode.FIELD])

	def test_grouped_asset_is_one_asset(self):
		doc, enqueue = self.submit(10, "Grouped Asset")
		enqueue.assert_not_called()
		self.assertEqual(frappe.db.get_value("Asset", doc.name, "asset_quantity"), 10)
		self.assertEqual(self.units(doc.name), [])

	def test_single_asset_one_per_unit_in_background(self):
		doc, enqueue = self.submit(4, "Single Asset", amount=10000)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["asset"], doc.name)
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		# right after the submit: the first asset exists, the rest still to come
		self.assertEqual(mode.get_single_asset_status(doc.name), {"created": 1, "total": 4, "remaining": 3})

		self.assertEqual(mode.split_into_single_assets(doc.name), 3)  # what the background job does
		first = frappe.get_doc("Asset", doc.name)
		units = self.units(doc.name)
		self.assertEqual((first.asset_quantity, len(units) + 1), (1, 4))
		self.assertEqual({u.asset_quantity for u in units}, {1})
		self.assertEqual({u.asset_name for u in units}, {doc.asset_name})
		total = flt(first.net_purchase_amount) + sum(flt(u.net_purchase_amount) for u in units)
		self.assertAlmostEqual(total, 10000, places=2)
		self.assertAlmostEqual(flt(first.net_purchase_amount), 2500, places=2)
		self.assertEqual(mode.get_single_asset_status(doc.name), {"created": 4, "total": 4, "remaining": 0})

		self.assertEqual(mode.split_into_single_assets(doc.name), 0)  # run again: nothing more
		self.assertEqual(len(self.units(doc.name)), 3)

	def test_single_asset_quantity_one_queues_nothing(self):
		_doc, enqueue = self.submit(1, "Single Asset")
		enqueue.assert_not_called()

	def test_retry_refused_when_nothing_left(self):
		doc, _enqueue = self.submit(3, "Grouped Asset")
		with self.assertRaises(frappe.ValidationError):
			mode.create_remaining_assets(doc.name)
