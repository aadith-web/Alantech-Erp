# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Appraisal "Create Promotion" (setup/appraisal_promotion.py, ClickUp 14yr2e58nc7).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_appraisal_promotion

Unit: the form script is hooked on Appraisal. Integration, with a submitted Appraisal of the site
(skipped when there is none): the new promotion is unsaved and carries the employee, company and
department; nothing is created; a Draft or Cancelled appraisal is refused; a user who may not create
promotions is refused; the promotion still saves once HR fills the date.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import today

from alantech_erp.setup.appraisal_promotion import make_promotion


class UnitTestHook(UnitTestCase):
	def test_form_script_hooked(self):
		self.assertEqual(frappe.get_hooks("doctype_js").get("Appraisal"), ["public/js/appraisal.js"])


class IntegrationTestCreatePromotion(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		names = frappe.get_all("Appraisal", filters={"docstatus": 1}, pluck="name", limit=1)
		if not names:
			raise cls.skipTest(cls, "Need a submitted Appraisal")
		cls.appraisal = frappe.get_doc("Appraisal", names[0])

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("appraisal_promo")
		self.addCleanup(frappe.db.rollback, save_point="appraisal_promo")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_new_promotion_prefilled_not_saved(self):
		before = frappe.db.count("Employee Promotion")
		doc = make_promotion(self.appraisal.name)
		self.assertTrue(doc.is_new())
		self.assertEqual((doc.doctype, doc.employee, doc.company), ("Employee Promotion", self.appraisal.employee, self.appraisal.company))
		department = self.appraisal.department or frappe.db.get_value("Employee", self.appraisal.employee, "department")
		self.assertEqual(doc.department, department)
		self.assertEqual(frappe.db.count("Employee Promotion"), before)  # not created automatically

	def test_hr_completes_and_saves(self):
		doc = make_promotion(self.appraisal.name)
		doc.promotion_date = today()
		doc.insert()
		self.assertEqual(frappe.db.get_value("Employee Promotion", doc.name, "employee"), self.appraisal.employee)

	def test_draft_or_cancelled_refused(self):
		for status in (0, 2):
			frappe.db.set_value("Appraisal", self.appraisal.name, "docstatus", status, update_modified=False)
			with self.assertRaises(frappe.ValidationError) as raised:
				make_promotion(self.appraisal.name)
			self.assertIn("Submit the Appraisal", str(raised.exception))

	def test_user_without_promotion_rights_refused(self):
		from alantech_erp.alantech.doctype.document.test_document import make_user

		frappe.set_user(make_user("_test-appraisal-emp@example.com", ["Employee"]))
		self.assertFalse(frappe.has_permission("Employee Promotion", "create"))
		with self.assertRaises(frappe.PermissionError):
			make_promotion(self.appraisal.name)
