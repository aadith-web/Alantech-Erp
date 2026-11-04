# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-002-6 Phase 0, Step 8: final permission matrix and findings.

ClickUp: https://app.clickup.com/t/14yr2e56ca0

FINAL_MATRIX holds the rights each lane has on every doctype of the flow, as steps 1-7 passed with
them (R read, C create, W write, S submit, X cancel, D delete, A amend, P print; doctype level, so
"own record only" is not visible here: Employee User Permissions and setup/salary_access.py add that
on top, and the step tests check it). A lane is a test user holding only its matrix roles.

Every rule that differs from the standard DocPerms must come from app code, never from Role
Permissions Manager by hand (CODE_PERMS: Custom DocPerm row -> the setup function that creates it).

Findings of steps 1-7 (error -> smallest fix, status):
    Step 2  Employee could not see the holiday calendar -> Holiday List: Employee read
            (setup/shifts.py allow_employees_to_read_holiday_list), fixed
    Step 5  Leave Approver could not approve an Attendance Request -> Attendance Request: Leave Approver
            read / write / submit, limited to their own reportees (setup/attendance_request.py), fixed
    Step 6  Approver read reportees' salary through the Reports To tree -> salary records limited to the
            user's own (setup/salary_access.py, has_permission / query conditions), fixed
    Step 7  HR User could not create a Payroll Entry -> Payroll Entry: HR User read / create / write
            (setup/payroll.py), fixed
    Step 7  Payroll Entry refused to submit: payroll payable account type blank -> set to Payable
            (setup/payroll.py), fixed
    Step 7  Journal Entry: the payroll accrual needs no Accounts role (HRMS uses ignore_permissions);
            the bank entry is a draft only Accounts User can open / submit, open (no role given)

Run all Phase 0 tests (steps 1-8):
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --app alantech_erp
or this step only:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_permission_matrix

The test users are p8.*@example.com (employees TEST-P8-) and are removed again in tearDownClass.
"""

import frappe

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.setup.employee_user import create_user
from alantech_erp.tests.test_phase0_employee_user import AUTOMATIC_ROLES, employee_doc, make_user

HR_MANAGER = "p8.hr.manager@example.com"
HR_USER = "p8.hr.user@example.com"
APPROVER = "p8.approver@example.com"
EMPLOYEE = "p8.emp1@example.com"

LANES = {
	HR_MANAGER: {"HR Manager", "Employee"},
	HR_USER: {"HR User", "Employee"},
	APPROVER: {"Employee", "Leave Approver"},
	EMPLOYEE: {"Employee"},
}

RIGHTS = {"R": "read", "C": "create", "W": "write", "S": "submit", "X": "cancel", "D": "delete", "A": "amend",
	"P": "print"}

# doctype: (HR Manager, HR User, Approver, Employee)
FINAL_MATRIX = {
	"Employee": ("RCWDP", "RCWDP", "RP", "RP"),
	"User Permission": ("", "", "", ""),  # created by the app when an employee is linked to a user
	"Shift Type": ("RCWDP", "RCWP", "RP", "RP"),
	"Overtime Type": ("RCWD", "", "", ""),
	"Holiday List": ("RCWDP", "R", "R", "R"),
	"Shift Assignment": ("RCWSXDAP", "RCWSP", "RP", "RP"),
	"Shift Request": ("RCWSXDAP", "RCWSP", "RCWP", "RCWP"),
	"Employee Checkin": ("RCWDP", "RCWDP", "RCWD", "RCWD"),
	"Attendance": ("RCWSXDP", "RCWSXDP", "RP", "RP"),
	"Attendance Request": ("RCWSXDAP", "RCWSXDAP", "RCWSDP", "RCWDP"),
	"Leave Application": ("RCWSXDAP", "RCWSXDAP", "RCWSXDP", "RCWP"),
	"Leave Allocation": ("RCWSXDAP", "RCWSXDAP", "", ""),
	"Leave Policy Assignment": ("RCWSXDP", "RCWSXDP", "", ""),
	"Session Log": ("RCWDP", "RWP", "RP", "RP"),
	"Overtime Log": ("RCWSXDAP", "RCWP", "", ""),
	"Additional Salary": ("RCWSP", "RCWSP", "", ""),
	"Salary Component": ("RCWDP", "RCWP", "R", "R"),
	"Salary Structure": ("RCWSXDAP", "RCWSXDAP", "", ""),
	"Salary Structure Assignment": ("RCWSXDAP", "RCWSP", "R", "R"),
	"Payroll Entry": ("RCWSXD", "RCW", "", ""),
	"Salary Slip": ("RCWSXDAP", "RCWSP", "RP", "RP"),
	"Journal Entry": ("", "", "", ""),  # bank entry needs Accounts User, see the findings above
}

# (doctype, role): the rights of its Custom DocPerm row and the setup function that creates it
CODE_PERMS = {
	("Holiday List", "Employee"): ("R", "alantech_erp.setup.shifts.allow_employees_to_read_holiday_list"),
	("Attendance Request", "Leave Approver"): ("RWS", "alantech_erp.setup.attendance_request.execute"),
	("Payroll Entry", "HR User"): ("RCW", "alantech_erp.setup.payroll.allow_hr_user_to_prepare_payroll_entry"),
}
MATRIX_ROLES = set().union(*LANES.values())
DOCPERM_FIELDS = ["role", *RIGHTS.values()]


def letters(rights):
	return "".join(letter for letter, right in RIGHTS.items() if right in rights)


def row_rights(row):
	return letters({right for right in RIGHTS.values() if row.get(right)})


def docperm_rows(doctype, table):
	return {r.role: row_rights(r) for r in frappe.get_all(table, filters={"parent": doctype, "permlevel": 0,
		"if_owner": 0, "role": ["in", list(MATRIX_ROLES)]}, fields=DOCPERM_FIELDS)}


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P8-%"]}, pluck="name")
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	for email in frappe.get_all("User", filters={"name": ["like", "p8.%@example.com"]}, pluck="name"):
		frappe.db.delete("User Permission", {"user": email})
		frappe.db.delete("DocShare", {"user": email})
		frappe.delete_doc("User", email, force=1, ignore_permissions=True)
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	frappe.db.commit()


class TestPhase0PermissionMatrix(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		# ERPNext drops the Employee role from a user without an Employee record, so every lane gets one:
		# HR users like on the site (all employees), approver and employee restricted to their own record
		for i, (email, roles) in enumerate(LANES.items(), start=1):
			if email in (HR_MANAGER, HR_USER):
				make_user(email, roles)
				employee_doc(f"P8 User{i}", f"TEST-P8-USER{i}", None, user_id=email).insert(ignore_permissions=True)
			else:
				emp = employee_doc(f"P8 User{i}", f"TEST-P8-USER{i}", None)
				emp.insert(ignore_permissions=True)
				create_user(emp.name, email=email, create_user_permission=1)
				frappe.get_doc("User", email).add_roles(*(roles - {"Employee"}))
			frappe.clear_cache(user=email)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cleanup()
		frappe.flags.mute_emails = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_01_lanes_have_exactly_their_roles(self):
		for email, expected in LANES.items():
			self.assertEqual(set(frappe.get_roles(email)) - AUTOMATIC_ROLES, expected, f"{email} roles")

	def test_02_final_matrix(self):
		"""Every lane has exactly its matrix rights on every doctype of the flow."""
		mismatches = []
		for doctype, expected in FINAL_MATRIX.items():
			for user, rights in zip(LANES, expected):
				frappe.set_user(user)
				actual = letters({r for r in RIGHTS.values() if frappe.has_permission(doctype, r, user=user)})
				if actual != rights:
					mismatches.append(f"{doctype} / {', '.join(sorted(LANES[user]))}: expected {rights or '-'}, got {actual or '-'}")
		self.assertEqual(mismatches, [], "\n" + "\n".join(mismatches))

	def test_03_every_custom_rule_comes_from_code(self):
		"""Custom DocPerm rows that differ from the standard ones for the matrix roles are exactly CODE_PERMS."""
		changed = {}
		for doctype in FINAL_MATRIX:
			if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
				continue
			standard, custom = docperm_rows(doctype, "DocPerm"), docperm_rows(doctype, "Custom DocPerm")
			for role in MATRIX_ROLES:
				if standard.get(role) != custom.get(role):
					changed[(doctype, role)] = custom.get(role)
		expected = {key: rights for key, (rights, _setup) in CODE_PERMS.items()}
		self.assertEqual(changed, expected, "Custom DocPerm rows not created by app code (or missing)")

	def test_04_setup_recreates_each_custom_rule(self):
		"""Each setup function brings its row back on a site without it (as on a fresh migrate)."""
		for (doctype, role), (rights, setup) in CODE_PERMS.items():
			frappe.db.delete("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0})
			frappe.get_attr(setup)()
			self.assertEqual(docperm_rows(doctype, "Custom DocPerm").get(role), rights, f"{setup}: {doctype} / {role}")
			frappe.get_attr(setup)()  # create-only: a second run adds nothing
			self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}), 1)
		frappe.clear_cache()
		frappe.db.commit()

	def test_05_setup_functions_run_after_migrate(self):
		"""A setup function only reaches a fresh site when after_migrate (or what it calls) runs it."""
		hooks = frappe.get_hooks("after_migrate", app_name="alantech_erp")
		for _rights, setup in CODE_PERMS.values():
			module = setup.rsplit(".", 1)[0]
			self.assertTrue(setup in hooks or f"{module}.execute" in hooks, f"{setup} is not run after migrate")
