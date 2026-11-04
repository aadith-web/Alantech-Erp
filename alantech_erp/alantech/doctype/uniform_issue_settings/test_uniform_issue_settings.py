# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Uniform Issue Settings (ClickUp 14yr2e56y3k). The defaults it gives a new Employee Uniform Issue
are tested in test_employee_uniform_issue.py.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.uniform_issue_settings.test_uniform_issue_settings
"""

from unittest.mock import patch

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

	# --- a complete configuration ------------------------------------------

	def valid_values(self):
		company = frappe.db.get_value("Company", {}, "name")
		values = {
			"default_source_warehouse": frappe.db.get_value(
				"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name"
			),
			"uniform_item_group": frappe.db.get_value("Item Group", {}, "name"),
			"uniform_expense_account": frappe.db.get_value(
				"Account", {"company": company, "root_type": "Expense", "is_group": 0, "disabled": 0}, "name"
			),
			"default_cost_center": frappe.db.get_value(
				"Cost Center", {"company": company, "is_group": 0, "disabled": 0}, "name"
			),
		}
		if not all(values.values()):
			self.skipTest("Need a leaf warehouse, expense account and cost center of one company")
		return company, values

	def test_full_settings_save_and_are_returned(self):
		company, values = self.valid_values()
		self.clear()
		self.settings.update({**values, "reissue_warning_days": 15})
		self.settings.save()
		defaults = get_uniform_defaults(company=company)
		for field, value in values.items():
			self.assertEqual(defaults[field], value)
		self.assertEqual(defaults.reissue_warning_days, 15)
		self.assertTrue(defaults.is_configured)

	def test_settings_can_be_cleared(self):
		_company, values = self.valid_values()
		self.clear()
		self.settings.update(values)
		self.settings.save()
		self.clear()
		self.settings.save()
		self.assertFalse(get_uniform_defaults().is_configured)

	def test_reissue_days_text_becomes_int(self):
		self.clear()
		self.settings.reissue_warning_days = "7"
		self.settings.save()
		self.assertEqual(self.settings.reissue_warning_days, 7)

	# --- rejected values ---------------------------------------------------

	def test_disabled_warehouse_rejected(self):
		warehouse = frappe.db.get_value("Warehouse", {"is_group": 0, "disabled": 0}, "name")
		if not warehouse:
			self.skipTest("No warehouse available")
		frappe.db.set_value("Warehouse", warehouse, "disabled", 1)
		self.addCleanup(frappe.db.set_value, "Warehouse", warehouse, "disabled", 0)
		self.clear()
		self.settings.default_source_warehouse = warehouse
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.settings.save()
		self.assertIn("is disabled", str(ctx.exception))

	def test_group_expense_account_rejected(self):
		account = frappe.db.get_value("Account", {"root_type": "Expense", "is_group": 1}, "name")
		if not account:
			self.skipTest("No group expense account available")
		self.clear()
		self.settings.uniform_expense_account = account
		self.assertRaises(frappe.ValidationError, self.settings.save)

	def test_group_cost_center_rejected(self):
		cost_center = frappe.db.get_value("Cost Center", {"is_group": 1}, "name")
		if not cost_center:
			self.skipTest("No group cost center available")
		self.clear()
		self.settings.default_cost_center = cost_center
		self.assertRaises(frappe.ValidationError, self.settings.save)

	def test_disabled_cost_center_rejected(self):
		cost_center = frappe.db.get_value("Cost Center", {"is_group": 0, "disabled": 0}, "name")
		if not cost_center:
			self.skipTest("No cost center available")
		frappe.db.set_value("Cost Center", cost_center, "disabled", 1)
		self.addCleanup(frappe.db.set_value, "Cost Center", cost_center, "disabled", 0)
		self.clear()
		self.settings.default_cost_center = cost_center
		self.assertRaises(frappe.ValidationError, self.settings.save)

	def test_missing_item_group_rejected(self):
		self.clear()
		self.settings.uniform_item_group = "_Test No Such Item Group"
		self.assertRaises(frappe.ValidationError, self.settings.save)

	def test_mixed_companies_rejected(self):
		company, values = self.valid_values()
		other = frappe.db.get_value("Company", {"name": ["!=", company]}, "name")
		other_cc = other and frappe.db.get_value("Cost Center", {"company": other, "is_group": 0}, "name")
		if not other_cc:
			self.skipTest("Needs a second company with a cost center")
		self.clear()
		self.settings.default_source_warehouse = values["default_source_warehouse"]
		self.settings.default_cost_center = other_cc
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.settings.save()
		self.assertIn("same company", str(ctx.exception))

	# --- get_uniform_defaults ----------------------------------------------

	def test_defaults_before_migrate(self):
		with patch("frappe.get_single", side_effect=frappe.DoesNotExistError):
			defaults = get_uniform_defaults()
		self.assertFalse(defaults.is_configured)
		self.assertEqual(defaults.reissue_warning_days, 0)

	def test_defaults_open_to_users_without_settings_access(self):
		self.clear()
		self.settings.reissue_warning_days = 5
		self.settings.save()
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertEqual(get_uniform_defaults().reissue_warning_days, 5)
