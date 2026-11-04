# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from alantech_erp.alantech.doctype.uniform_issue_settings.uniform_issue_settings import (
	LINK_FIELDS,
	get_uniform_defaults,
)
IGNORE_TEST_RECORD_DEPENDENCIES = ["Warehouse", "Item Group", "Account", "Cost Center"]

class IntegrationTestUniformIssueSettings(IntegrationTestCase):
	def setUp(self):
		self.settings = frappe.get_single("Uniform Issue Settings")

	def clear(self):
		for field in LINK_FIELDS:
			self.settings.set(field, None)
		self.settings.reissue_warning_days = 0

	def test_is_single(self):
		self.assertTrue(frappe.get_meta("Uniform Issue Settings").issingle)

	def test_fields_and_links(self):
		meta = frappe.get_meta("Uniform Issue Settings")
		expected = {
			"default_source_warehouse": ("Link", "Warehouse"),
			"uniform_item_group": ("Link", "Item Group"),
			"uniform_expense_account": ("Link", "Account"),
			"default_cost_center": ("Link", "Cost Center"),
			"reissue_warning_days": ("Int", None),
		}
		for fieldname, (fieldtype, options) in expected.items():
			df = meta.get_field(fieldname)
			self.assertEqual(df.fieldtype, fieldtype)
			self.assertEqual(df.options or None, options)
		self.assertEqual(str(meta.get_field("reissue_warning_days").default), "0")

	def test_empty_settings_are_handled(self):
		self.clear()
		self.settings.save()
		defaults = get_uniform_defaults()
		for field in LINK_FIELDS:
			self.assertIsNone(defaults[field])
		self.assertEqual(defaults.reissue_warning_days, 0)
		self.assertFalse(defaults.is_configured)

	def test_negative_reissue_days_rejected(self):
		self.clear()
		self.settings.reissue_warning_days = -1
		self.assertRaises(frappe.ValidationError, self.settings.save)

	def test_values_persist_and_are_returned(self):
		self.clear()
		self.settings.reissue_warning_days = 30
		self.settings.save()
		self.assertEqual(frappe.get_single("Uniform Issue Settings").reissue_warning_days, 30)
		self.assertEqual(get_uniform_defaults().reissue_warning_days, 30)

	def test_disabled_and_group_warehouse_rejected(self):
		group = frappe.db.get_value("Warehouse", {"is_group": 1}, "name")
		if not group:
			self.skipTest("No group warehouse available")
		self.clear()
		self.settings.default_source_warehouse = group
		self.assertRaises(frappe.ValidationError, self.settings.save)

	def test_non_expense_account_rejected(self):
		account = frappe.db.get_value("Account", {"root_type": "Asset", "is_group": 0}, "name")
		if not account:
			self.skipTest("No asset account available")
		self.clear()
		self.settings.uniform_expense_account = account
		self.assertRaises(frappe.ValidationError, self.settings.save)

	def test_company_filter_drops_other_company_values(self):
		row = frappe.db.get_value(
			"Warehouse", {"is_group": 0, "disabled": 0}, ["name", "company"], as_dict=True
		)
		if not row:
			self.skipTest("No warehouse available")
		self.clear()
		self.settings.default_source_warehouse = row.name
		self.settings.save()
		self.assertEqual(get_uniform_defaults(company=row.company).default_source_warehouse, row.name)
		self.assertIsNone(get_uniform_defaults(company="Some Other Company").default_source_warehouse)