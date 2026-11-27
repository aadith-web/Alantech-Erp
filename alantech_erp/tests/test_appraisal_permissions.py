# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee filling an Appraisal: no "Insufficient Permission for Designation"
(setup/appraisal_permissions.py).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_appraisal_permissions

Integration: a user with only the Employee role can pass the link check the Appraisal form makes
(frappe.client.validate_link_and_fetch) for Designation, KRA and Employee Feedback Criteria, but
still cannot read those records (select only).
"""

import frappe
from frappe.tests import IntegrationTestCase

from alantech_erp.setup.appraisal_permissions import DOCTYPES


class IntegrationTestEmployeeAppraisalLinks(IntegrationTestCase):
	def setUp(self):
		from alantech_erp.alantech.doctype.document.test_document import make_user

		frappe.set_user("Administrator")
		frappe.db.savepoint("appraisal_links")
		self.addCleanup(frappe.db.rollback, save_point="appraisal_links")
		self.addCleanup(frappe.set_user, "Administrator")
		employee = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", order_by="creation", limit=1)
		if not employee:
			self.skipTest("Need an active employee")
		# HRMS keeps the Employee role only on a user linked to an Employee
		self.user = make_user("_test-appraisal-links@example.com", ["Employee"], employee[0])
		self.assertIn("Employee", frappe.get_roles(self.user))
		previous = getattr(frappe.local, "request", None)
		frappe.local.request = frappe._dict(method="POST")
		self.addCleanup(setattr, frappe.local, "request", previous)

	def test_link_check_passes_but_no_read(self):
		from frappe.client import validate_link_and_fetch

		checked = 0
		for doctype in DOCTYPES:
			name = frappe.db.get_value(doctype, {}, "name")
			if not name:
				continue
			frappe.set_user(self.user)
			self.assertTrue(frappe.has_permission(doctype, "select"), doctype)
			self.assertFalse(frappe.has_permission(doctype, "read"), doctype)
			self.assertEqual(validate_link_and_fetch(doctype, name).get("name"), name, doctype)
			frappe.set_user("Administrator")
			checked += 1
		if not checked:
			self.skipTest("No Designation / KRA / Employee Feedback Criteria records")
