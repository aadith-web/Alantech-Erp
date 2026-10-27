# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-002-6 Phase 0: test users, employee creation and user linking as HR Manager.

ClickUp: https://app.clickup.com/t/14yr2e56b3a

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_employee_user

Everything created here uses @example.com addresses and the TEST-P0- employee numbers, and is
removed again in tearDownClass.
"""

import frappe

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.setup.access import FULL_ACCESS_DESIGNATIONS
from alantech_erp.setup.employee_user import create_user

COMPANY = "Alantech Industries India Pvt Ltd"
DEFAULT_SHIFT = "General Shift"
OVERRIDDEN = "erpnext.setup.doctype.employee.employee.create_user"
OUR_CREATE_USER = "alantech_erp.setup.employee_user.create_user"

# roles every desk user carries anyway; not part of the matrix
AUTOMATIC_ROLES = {"All", "Guest", "Desk User"}
PRIVILEGED_ROLES = {"System Manager", "Administrator", "HR Manager", "HR User"}

HR_MANAGER = "p0.hr.manager@example.com"
HR_USER = "p0.hr.user@example.com"
APPROVER = "p0.approver@example.com"
EMP1_EMAIL = "p0.emp1@example.com"
HR_EXEC_EMAIL = "p0.hr.exec@example.com"

TEST_USERS = {
	HR_MANAGER: {"HR Manager", "Employee"},
	HR_USER: {"HR User", "Employee"},
	APPROVER: {"Employee", "Leave Approver"},
}

EMPLOYEE_DESIGNATION = "Fitter"  # an ordinary designation (not MD / HR)
HR_DESIGNATION = "HR Executive"  # a full-access designation


def make_user(email, roles):
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"user_type": "System User",
			"roles": [{"role": r} for r in roles],
		}
	)
	user.insert(ignore_permissions=True)
	frappe.clear_cache(user=email)
	return user


def employee_doc(first_name, number, designation, **extra):
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first_name,
			"last_name": "Test",
			"employee_number": number,
			"gender": "Male",
			"date_of_birth": "1995-01-01",
			"date_of_joining": "2024-01-01",
			"company": COMPANY,
			"status": "Active",
			"designation": designation,
			**extra,
		}
	)


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P0-%"]}, pluck="name")
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	# every user this test ever creates is p0.<something>@example.com
	for email in frappe.get_all("User", filters={"name": ["like", "p0.%@example.com"]}, pluck="name"):
		frappe.db.delete("User Permission", {"user": email})
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	frappe.db.commit()


class TestPhase0EmployeeUser(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		# HRMS v16 removes the Employee role from users without a linked Employee, so every test
		# user gets its own Employee record. No designation: the designation role-profile hook
		# would otherwise replace the roles under test.
		cls.employee_of = {}
		for i, (email, roles) in enumerate(TEST_USERS.items(), start=1):
			make_user(email, roles)
			emp = employee_doc(email.split("@")[0].replace(".", " ").title(), f"TEST-P0-USER{i}", None,
				user_id=email)
			emp.insert(ignore_permissions=True)
			cls.employee_of[email] = emp.name
			frappe.clear_cache(user=email)
		cls.approver_employee = cls.employee_of[APPROVER]
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cleanup()
		frappe.flags.mute_emails = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------- setup checks
	def test_01_masters_exist(self):
		self.assertTrue(frappe.db.exists("Company", COMPANY), "Company missing")
		self.assertTrue(frappe.db.exists("Shift Type", DEFAULT_SHIFT), "Shift Type General Shift missing")
		for designation in (EMPLOYEE_DESIGNATION, HR_DESIGNATION):
			self.assertTrue(frappe.db.exists("Designation", designation), f"Designation {designation} missing")
		self.assertIn(HR_DESIGNATION, FULL_ACCESS_DESIGNATIONS)

	def test_02_create_user_override_registered(self):
		overrides = frappe.get_hooks("override_whitelisted_methods") or {}
		self.assertIn(OUR_CREATE_USER, overrides.get(OVERRIDDEN, []),
			"hooks.py: override_whitelisted_methods for Employee > Create User is missing")

	def test_03_test_users_have_exactly_their_roles(self):
		"""After linking to an Employee (HRMS drops the Employee role from unlinked users)."""
		for email, expected in TEST_USERS.items():
			self.assertEqual(frappe.db.get_value("Employee", self.employee_of[email], "user_id"), email)
			roles = set(frappe.get_roles(email)) - AUTOMATIC_ROLES
			self.assertEqual(roles, expected, f"{email} roles")

	def test_04_default_shift_on_new_employee(self):
		emp = frappe.new_doc("Employee")
		self.assertEqual(emp.default_shift, DEFAULT_SHIFT, "Employee > Default Shift has no default")

	# ---------------------------------------------------------------- as HR Manager
	def create_employee_as_hr_manager(self, first_name, number, designation):
		frappe.set_user(HR_MANAGER)
		emp = employee_doc(first_name, number, designation, reports_to=self.approver_employee)
		emp.insert()  # with HR Manager's permissions, not ignore_permissions
		return emp

	def test_05_hr_manager_creates_employee(self):
		emp = self.create_employee_as_hr_manager("Emp1", "TEST-P0-EMP1", EMPLOYEE_DESIGNATION)
		self.assertEqual(emp.reports_to, self.approver_employee)
		self.assertEqual(emp.default_shift, DEFAULT_SHIFT)
		self.assertEqual(emp.owner, HR_MANAGER)

	def test_06_hr_manager_creates_and_links_user(self):
		emp = self.create_employee_as_hr_manager("Emp1b", "TEST-P0-EMP1B", EMPLOYEE_DESIGNATION)
		user = create_user(emp.name, email=EMP1_EMAIL, create_user_permission=1)
		frappe.set_user("Administrator")

		self.assertEqual(user, EMP1_EMAIL)
		self.assertEqual(frappe.db.get_value("Employee", emp.name, "user_id"), EMP1_EMAIL)

		roles = set(frappe.get_roles(EMP1_EMAIL))
		self.assertIn("Employee", roles)
		self.assertFalse(roles & PRIVILEGED_ROLES, f"ordinary employee got privileged roles: {roles & PRIVILEGED_ROLES}")

		own = frappe.get_all("User Permission", filters={"user": EMP1_EMAIL, "allow": "Employee"}, pluck="for_value")
		self.assertEqual(own, [emp.name], "employee should be restricted to their own Employee record")

		# ---- log in as the employee: sees only their own record
		frappe.set_user(EMP1_EMAIL)
		visible = frappe.get_list("Employee", pluck="name")
		self.assertEqual(visible, [emp.name])
		self.assertFalse(
			frappe.has_permission("Employee", "read", doc=frappe.get_doc("Employee", self.approver_employee),
				user=EMP1_EMAIL)
		)

	def test_07_full_access_designation_not_restricted(self):
		emp = self.create_employee_as_hr_manager("HRExec", "TEST-P0-HREXEC", HR_DESIGNATION)
		create_user(emp.name, email=HR_EXEC_EMAIL, create_user_permission=1)
		frappe.set_user("Administrator")
		restrictions = frappe.get_all("User Permission", filters={"user": HR_EXEC_EMAIL, "allow": "Employee"},
			pluck="for_value")
		self.assertEqual(restrictions, [], "HR / MD designations must not be limited to their own record")

	def test_08_create_user_refused_twice(self):
		emp = self.create_employee_as_hr_manager("Emp1c", "TEST-P0-EMP1C", EMPLOYEE_DESIGNATION)
		create_user(emp.name, email="p0.emp1c@example.com", create_user_permission=1)
		frappe.set_user(HR_MANAGER)
		with self.assertRaises(frappe.ValidationError):
			create_user(emp.name, email="p0.emp1c.second@example.com")
		frappe.set_user("Administrator")
		frappe.db.delete("User Permission", {"user": "p0.emp1c@example.com"})
		frappe.db.set_value("Employee", emp.name, "user_id", None)
		frappe.delete_doc("User", "p0.emp1c@example.com", force=1, ignore_permissions=True)

	# ---------------------------------------------------------------- other roles
	def test_09_hr_user_cannot_create_user(self):
		frappe.set_user("Administrator")
		emp = employee_doc("Emp1d", "TEST-P0-EMP1D", EMPLOYEE_DESIGNATION)
		emp.insert(ignore_permissions=True)
		frappe.set_user(HR_USER)
		with self.assertRaises(frappe.PermissionError):
			create_user(emp.name, email="p0.emp1d@example.com")
