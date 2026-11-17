# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee form "Create Assignments" check without permission errors (setup/employee_assignments.py).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_assignments
"""

import frappe
from hrms.overrides.employee_master import get_assignable_masters as hrms_get_assignable_masters

from alantech_erp.setup.employee_assignments import get_assignable_masters

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
METHOD = "hrms.overrides.employee_master.get_assignable_masters"


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


class TestEmployeeAssignments(TestCase):
	def setUp(self):
		frappe.db.savepoint("assign_test")
		self.addCleanup(frappe.db.rollback, save_point="assign_test")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_hooked_over_hrms_method(self):
		self.assertEqual(
			frappe.get_hooks("override_whitelisted_methods")[METHOD][-1],
			"alantech_erp.setup.employee_assignments.get_assignable_masters",
		)

	def test_employee_gets_no_permission_error(self):
		employee = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", limit=1)[0]
		user = make_user("_test-assign-emp@example.com", ["Employee"], employee)
		frappe.set_user(user)
		self.assertFalse(frappe.has_permission("Salary Structure", "read"))
		with self.assertRaises(frappe.PermissionError):
			hrms_get_assignable_masters(COMPANY)  # the HRMS bug
		result = get_assignable_masters(COMPANY)
		self.assertEqual(set(result), {"Leave Policy", "Salary Structure", "Shift Schedule"})
		self.assertFalse(result["Salary Structure"])

	def test_hr_manager_gets_hrms_answer(self):
		user = make_user("_test-assign-hrm@example.com", ["HR Manager", "HR User"])
		frappe.set_user(user)
		self.assertEqual(get_assignable_masters(COMPANY), hrms_get_assignable_masters(COMPANY))
