# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Expiring soon / expired warnings (document_expiry_warning.py, ClickUp 14yr2e58g46).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.document.test_document_expiry_warning

Unit: the wording. Integration: the form warning (Document onload) for the employee and HR, the
window of the type, Rejected and renewed documents, and the list / Employee form warnings limited to
what the user may see. Test users and types like test_document.py; everything is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, today

from alantech_erp.alantech.doctype.document.document_expiry_warning import (
	get_expiry_warnings,
	message,
	warning_for,
)
from alantech_erp.alantech.doctype.document.test_document import make_user, pdf_bytes
from alantech_erp.alantech.doctype.document_type_master.test_document_type_master import make_type

IGNORE_TEST_RECORD_DEPENDENCIES = ["Employee", "Company", "Country", "User", "Document Type Master"]

PASSPORT = "_Test Warn Passport"  # alert 30 days before
VISA = "_Test Warn Visa"  # alert 60 days before


class UnitTestExpiryWarningMessage(UnitTestCase):
	def test_employee_wording(self):
		self.assertEqual(message("Passport", "X", 20, True), "Your Passport is expiring in 20 days - Please update")
		self.assertEqual(message("Passport", "X", 1, True), "Your Passport expires tomorrow - Please update")
		self.assertEqual(message("Passport", "X", 0, True), "Your Passport expires today - Please update")
		self.assertEqual(message("Passport", "X", -3, True), "Your Passport has expired - Please update immediately")

	def test_hr_wording(self):
		self.assertEqual(
			message("Passport", "Vinitha K V", 20, False), "Passport of Vinitha K V is expiring in 20 days - Please update"
		)
		self.assertEqual(
			message("Passport", "Vinitha K V", -1, False), "Passport of Vinitha K V has expired - Please update immediately"
		)


class IntegrationTestExpiryWarning(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", order_by="creation", limit=2)
		if len(employees) < 2:
			raise cls.skipTest(cls, "Need two active employees on the site")
		cls.emp, cls.other_emp = employees
		cls.emp_user = make_user("_test-warn-emp@example.com", ["Employee"], cls.emp)
		cls.other_user = make_user("_test-warn-other@example.com", ["Employee"], cls.other_emp)
		cls.hr_manager = make_user("_test-warn-hrm@example.com", ["HR Manager"])
		make_type(PASSPORT, expiry_required=1, alert_days_before=30)
		make_type(VISA, expiry_required=1, alert_days_before=60)
		cls.file_url = frappe.get_doc(
			{"doctype": "File", "file_name": "_test_warn_scan.pdf", "content": pdf_bytes(), "is_private": 1}
		).insert(ignore_permissions=True).file_url

	def setUp(self):
		frappe.db.savepoint("warn_test")
		self.addCleanup(frappe.db.rollback, save_point="warn_test")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")

	def make_doc(self, days, employee=None, document_type=PASSPORT, status=None):
		"""Approved document (HR upload) expiring in `days` days (negative: expired)."""
		doc = frappe.get_doc(
			{
				"doctype": "Document",
				"reference_doctype": "Employee",
				"reference_name": employee or self.emp,
				"document_type": document_type,
				"issue_date": add_days(today(), -400),
				"expiry_date": add_days(today(), 365),
				"attachments": [{"file": self.file_url}],
			}
		).insert()
		doc.db_set("expiry_date", add_days(today(), days))
		if status:
			doc.db_set("approval_status", status)
		return frappe.get_doc("Document", doc.name)

	def onload_warning(self, doc, user):
		frappe.set_user(user)
		doc = frappe.get_doc("Document", doc.name)
		doc.run_method("onload")
		return doc.get_onload().get("expiry_warning")

	def test_expiring_soon_for_employee_and_hr(self):
		doc = self.make_doc(20)
		own = self.onload_warning(doc, self.emp_user)
		self.assertEqual((own["status"], own["days_left"]), ("expiring", 20))
		self.assertEqual(own["message"], f"Your {PASSPORT} is expiring in 20 days - Please update")
		hr = self.onload_warning(doc, self.hr_manager)
		self.assertEqual(hr["message"], f"{PASSPORT} of {doc.reference_title} is expiring in 20 days - Please update")

	def test_expired_for_employee_and_hr(self):
		doc = self.make_doc(-5)
		own = self.onload_warning(doc, self.emp_user)
		self.assertEqual(own["status"], "expired")
		self.assertEqual(own["message"], f"Your {PASSPORT} has expired - Please update immediately")
		self.assertIn("has expired - Please update immediately", self.onload_warning(doc, self.hr_manager)["message"])

	def test_window_follows_document_type(self):
		self.assertIsNone(self.onload_warning(self.make_doc(31), self.hr_manager))  # Passport: 30 days
		self.assertIsNotNone(self.onload_warning(self.make_doc(30, employee=self.other_emp), self.hr_manager))
		self.assertIsNotNone(self.onload_warning(self.make_doc(45, document_type=VISA), self.hr_manager))  # 60

	def test_no_warning_for_rejected_or_without_expiry(self):
		self.assertIsNone(warning_for(self.make_doc(-5, status="Rejected")))
		doc = self.make_doc(10)
		doc.db_set("expiry_date", None)
		self.assertIsNone(warning_for(frappe.get_doc("Document", doc.name)))

	def test_pending_document_warned(self):
		self.assertEqual(warning_for(self.make_doc(-1, status="Pending Approval"))["status"], "expired")

	def test_renewed_document_not_warned(self):
		old = self.make_doc(-10)
		new = self.make_doc(300)
		self.assertIsNone(warning_for(old))
		self.assertIsNone(warning_for(new))
		new.db_set("approval_status", "Rejected")  # a rejected renewal does not count
		self.assertIsNotNone(warning_for(old))

	def test_list_warnings_only_for_visible_documents(self):
		mine = self.make_doc(-2)
		soon = self.make_doc(12, document_type=VISA)
		other = self.make_doc(5, employee=self.other_emp)
		later = self.make_doc(200, employee=self.other_emp, document_type=VISA)  # not a renewal of `mine`

		frappe.set_user(self.emp_user)
		names = [w["name"] for w in get_expiry_warnings()]
		self.assertEqual([n for n in names if n in (mine.name, soon.name, other.name, later.name)], [mine.name, soon.name])
		frappe.set_user(self.hr_manager)
		names = {w["name"] for w in get_expiry_warnings()}
		self.assertTrue({mine.name, soon.name, other.name} <= names)
		self.assertNotIn(later.name, names)

	def test_employee_form_warnings_for_one_employee(self):
		mine = self.make_doc(-2)
		other = self.make_doc(5, employee=self.other_emp)
		frappe.set_user(self.hr_manager)
		names = {w["name"] for w in get_expiry_warnings("Employee", self.emp)}
		self.assertIn(mine.name, names)
		self.assertNotIn(other.name, names)
