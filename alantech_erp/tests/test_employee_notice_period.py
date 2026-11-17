# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Notice Period created with the employee (ClickUp 14yr2e57r71).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_notice_period

Nothing is kept: each test runs in a savepoint rolled back after it.
"""

import frappe

from alantech_erp.alantech.doctype.employee_notice_period import employee_notice_period as np
from alantech_erp.tests.test_employee_required import full_employee

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

DOCTYPE = np.DOCTYPE


def make_user(email, roles, employee=None):
	"""The employee is linked first: HRMS drops the Employee role from a user without one."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	if employee:
		frappe.db.set_value("Employee", employee, "user_id", email)
	user = frappe.get_doc("User", email)
	user.set("roles", [{"role": role} for role in roles])
	user.save(ignore_permissions=True)
	return email


class TestEmployeeNoticePeriod(TestCase):
	def setUp(self):
		frappe.db.savepoint("notice_test")
		self.addCleanup(frappe.db.rollback, save_point="notice_test")
		self.addCleanup(frappe.set_user, "Administrator")
		np.execute()

	def new_employee(self, **changes):
		email = f"notice-{frappe.generate_hash(length=6)}@example.com"
		return full_employee(first_name="Noticetest", personal_email=email, **changes).insert(ignore_permissions=True)

	def second_employee(self):
		"""Not Indian: no second Aadhaar / PAN needed (they must be unique)."""
		return self.new_employee(alt_nationality="United Arab Emirates", alt_aadhaar_number=None, pan_number=None)

	def record(self, employee):
		return frappe.get_doc(DOCTYPE, {"employee": employee})

	def test_created_with_company_policy_default(self):
		emp = self.new_employee()
		rec = self.record(emp.name)
		self.assertEqual(rec.name, emp.name)  # linked to (named after) the Employee ID
		self.assertEqual(rec.notice_days, 30)
		self.assertEqual(rec.source, np.COMPANY_POLICY)
		self.assertEqual(str(rec.effective_from), str(emp.date_of_joining))
		self.assertEqual(frappe.db.get_value("Employee", emp.name, "notice_number_of_days"), 30)

	def test_default_from_hr_settings(self):
		frappe.db.set_single_value("HR Settings", np.SETTINGS_FIELD, 45)
		emp = self.new_employee()
		self.assertEqual(self.record(emp.name).notice_days, 45)

	def test_notice_typed_on_new_employee_kept(self):
		emp = self.new_employee(notice_number_of_days=60)
		rec = self.record(emp.name)
		self.assertEqual(rec.notice_days, 60)
		self.assertEqual(rec.source, np.MANUAL)

	def test_only_one_record_per_employee(self):
		emp = self.new_employee()
		emp.save()
		self.assertEqual(frappe.db.count(DOCTYPE, {"employee": emp.name}), 1)
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": DOCTYPE, "employee": emp.name, "notice_days": 10}).insert()

	def test_change_on_record_updates_employee(self):
		emp = self.new_employee()
		rec = self.record(emp.name)
		rec.notice_days = 90
		rec.save()
		self.assertEqual(rec.source, np.MANUAL)
		self.assertEqual(frappe.db.get_value("Employee", emp.name, "notice_number_of_days"), 90)

	def test_change_on_employee_updates_record(self):
		emp = self.new_employee()
		emp.reload()
		emp.notice_number_of_days = 60
		emp.save()
		self.assertEqual(self.record(emp.name).notice_days, 60)

		emp.reload()
		emp.notice_number_of_days = 0  # cleared: the notice period still shows
		emp.save()
		self.assertEqual(frappe.db.get_value("Employee", emp.name, "notice_number_of_days"), 60)

	def test_negative_days_refused(self):
		emp = self.new_employee()
		rec = self.record(emp.name)
		rec.notice_days = -5
		with self.assertRaises(frappe.ValidationError):
			rec.save()

	def test_deleted_with_employee(self):
		emp = self.new_employee()
		frappe.delete_doc("Employee", emp.name, force=True)
		self.assertFalse(frappe.db.exists(DOCTYPE, {"employee": emp.name}))

	def test_employee_sees_only_own_record(self):
		emp = self.new_employee()
		other = self.second_employee()
		user = make_user("_test-notice-emp@example.com", ["Employee"], emp.name)
		frappe.set_user(user)
		names = frappe.get_list(DOCTYPE, pluck="name")
		self.assertIn(emp.name, names)
		self.assertNotIn(other.name, names)
		self.assertFalse(frappe.has_permission(DOCTYPE, "read", doc=other.name))
		self.assertFalse(frappe.has_permission(DOCTYPE, "write", doc=emp.name))

	def test_tab_data(self):
		emp = self.new_employee()
		data = np.get_notice_period(emp.name)
		self.assertEqual((data.name, data.notice_days), (emp.name, 30))
