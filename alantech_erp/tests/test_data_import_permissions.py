# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR can open Employee list > Menu > Import (setup/data_import_permissions.py).

Covered:
- after_migrate gives HR Manager / HR User read, write, create on Data Import; Employee nothing.
- An HR Manager creates an Employee import and opens it (what the Import dialog does).
- Imports into doctypes the user cannot import (e.g. Sales Invoice) stay hidden from HR, in the
  list and when opened; System Manager still sees every import.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_data_import_permissions

Data: _test-di-* users and Data Import records inside a savepoint rolled back after each test.
"""

import frappe

from alantech_erp.setup import data_import_permissions as dip

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.add_roles(*roles)
	return email


def make_import(reference_doctype):
	return frappe.get_doc(
		{"doctype": "Data Import", "reference_doctype": reference_doctype, "import_type": "Insert New Records"}
	).insert(ignore_permissions=True)


class TestDataImportPermissions(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		dip.execute()
		cls.hr_manager = make_user("_test-di-hrm@example.com", ["HR Manager"])
		cls.hr_user = make_user("_test-di-hru@example.com", ["HR User"])
		cls.employee = make_user("_test-di-emp@example.com", ["Employee"])

	def setUp(self):
		frappe.db.savepoint("di_test")
		self.addCleanup(frappe.db.rollback, save_point="di_test")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_hr_roles_get_data_import_rights(self):
		for user in (self.hr_manager, self.hr_user):
			for ptype in ("read", "write", "create"):
				with self.subTest(user=user, ptype=ptype):
					self.assertTrue(frappe.has_permission("Data Import", ptype, user=user))
		self.assertFalse(frappe.has_permission("Data Import", "read", user=self.employee))

	def test_execute_keeps_rules_hr_changed(self):
		key = {"parent": "Data Import", "role": "HR User", "permlevel": 0, "if_owner": 0}
		frappe.db.set_value("Custom DocPerm", key, "create", 0)
		dip.execute()
		self.assertEqual(frappe.db.get_value("Custom DocPerm", key, "create"), 0)

	def test_hr_manager_creates_and_opens_employee_import(self):
		frappe.set_user(self.hr_manager)
		doc = frappe.get_doc(
			{"doctype": "Data Import", "reference_doctype": "Employee", "import_type": "Insert New Records"}
		).insert()
		self.assertTrue(frappe.get_doc("Data Import", doc.name).has_permission("read"))
		self.assertIn(doc.name, frappe.get_list("Data Import", pluck="name"))

	def test_hr_cannot_import_other_doctypes(self):
		frappe.set_user(self.hr_manager)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{"doctype": "Data Import", "reference_doctype": "Sales Invoice", "import_type": "Insert New Records"}
			).insert()

	def test_other_imports_hidden_from_hr(self):
		other = make_import("Sales Invoice")
		frappe.set_user(self.hr_manager)
		self.assertNotIn(other.name, frappe.get_list("Data Import", pluck="name"))
		self.assertFalse(frappe.has_permission("Data Import", "read", doc=other.name, user=self.hr_manager))

		frappe.set_user("Administrator")
		self.assertIn(other.name, frappe.get_list("Data Import", pluck="name"))
