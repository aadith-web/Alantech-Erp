# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Lending Settings > Require Loan Rule (LR-02, ClickUp 14yr2e57ghd; setup/loan_rule_settings.py):
the field exists after migrate, is off by default, re-running setup keeps the saved value, and
is_loan_rule_required() follows the setting.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_rule_settings

Each test runs in a savepoint that is rolled back, so the site's setting is left as it was.
"""

import frappe
from frappe.tests import IntegrationTestCase

from alantech_erp.setup.loan_rule_settings import (
	FIELDNAME,
	NO_RULE_MESSAGE,
	SETTINGS_DOCTYPE,
	execute,
	is_loan_rule_required,
	no_rule_message,
)

def set_setting(value):
	frappe.db.set_single_value(SETTINGS_DOCTYPE, FIELDNAME, value)


class TestLoanRuleSettings(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("loan_rule_settings")
		self.addCleanup(frappe.db.rollback, save_point="loan_rule_settings")

	def test_field_on_lending_settings(self):
		field = frappe.get_meta(SETTINGS_DOCTYPE).get_field(FIELDNAME)
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Check")
		self.assertEqual(field.label, "Require Loan Rule")
		self.assertEqual(str(field.default), "0")
		self.assertTrue(frappe.db.exists("Custom Field", f"{SETTINGS_DOCTYPE}-{FIELDNAME}"))

	def test_off_by_default(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS_DOCTYPE, "field": FIELDNAME})
		self.assertFalse(is_loan_rule_required())
		self.assertEqual(frappe.get_single(SETTINGS_DOCTYPE).get(FIELDNAME) or 0, 0)

	def test_follows_setting(self):
		set_setting(1)
		self.assertTrue(is_loan_rule_required())
		set_setting(0)
		self.assertFalse(is_loan_rule_required())

	def test_saved_from_settings_form(self):
		doc = frappe.get_single(SETTINGS_DOCTYPE)
		doc.set(FIELDNAME, 1)
		doc.save()
		self.assertTrue(is_loan_rule_required())

	def test_setup_rerun_keeps_value(self):
		set_setting(1)
		execute()
		self.assertTrue(is_loan_rule_required())
		self.assertEqual(
			frappe.db.count("Custom Field", {"dt": SETTINGS_DOCTYPE, "fieldname": FIELDNAME}), 1
		)

	def test_no_rule_message(self):
		self.assertEqual(NO_RULE_MESSAGE, "No loan policy covers you for this loan product. Contact HR.")
		self.assertEqual(no_rule_message(), NO_RULE_MESSAGE)
