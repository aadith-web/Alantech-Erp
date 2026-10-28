# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-002-6 Phase 0, Step 2: shift assignment, shift request and employee check-in.

ClickUp: https://app.clickup.com/t/14yr2e56c9u

Every user holds only their matrix roles; each check runs as that user (no ignore_permissions).

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_shift_checkin

Everything created here uses p2.*@example.com addresses and the TEST-P2- employee numbers, and is
removed again in tearDownClass.
"""

import frappe
from frappe.utils import add_days, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.setup import approvers
from alantech_erp.setup.employee_user import create_user
from alantech_erp.setup.shifts import DEFAULT_SHIFT, holiday_list_name
from alantech_erp.tests.test_phase0_employee_user import AUTOMATIC_ROLES, COMPANY, employee_doc, make_user

SHIFT = "12 Hour Shift"

HR_MANAGER = "p2.hr.manager@example.com"
HR_USER = "p2.hr.user@example.com"
APPROVER = "p2.approver@example.com"
EMP1 = "p2.emp1@example.com"

TEST_USERS = {
	HR_MANAGER: {"HR Manager", "Employee"},
	HR_USER: {"HR User", "Employee"},
	APPROVER: {"Employee", "Leave Approver"},
}

# shift transactions of the test employees; a check-out also builds Session Log -> Attendance
TRANSACTIONS = ("Employee Checkin", "Shift Request", "Shift Assignment", "Attendance", "Overtime Log")


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P2-%"]}, pluck="name")
	if employees:
		session_logs = frappe.get_all("Session Log", filters={"employee": ["in", employees]}, pluck="name")
		if session_logs:
			frappe.db.delete("Attendance Log Checkin", {"parent": ["in", session_logs]})
			frappe.db.delete("Session Log", {"name": ["in", session_logs]})
		for doctype in TRANSACTIONS:  # submitted documents: delete_doc would refuse them
			frappe.db.delete(doctype, {"employee": ["in", employees]})
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	for email in frappe.get_all("User", filters={"name": ["like", "p2.%@example.com"]}, pluck="name"):
		frappe.db.delete("User Permission", {"user": email})
		frappe.db.delete("DocShare", {"user": email})
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	frappe.db.commit()


def shift_assignment(employee, start, end):
	return frappe.get_doc(
		{
			"doctype": "Shift Assignment",
			"employee": employee,
			"company": COMPANY,
			"shift_type": SHIFT,
			"start_date": start,
			"end_date": end,
		}
	)


def shift_request(employee, start, end, approver):
	return frappe.get_doc(
		{
			"doctype": "Shift Request",
			"employee": employee,
			"company": COMPANY,
			"shift_type": SHIFT,
			"from_date": start,
			"to_date": end,
			"approver": approver,
		}
	)


def checkin(employee, time, log_type):
	return frappe.get_doc({"doctype": "Employee Checkin", "employee": employee, "time": time, "log_type": log_type})


class TestPhase0ShiftCheckin(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		# like Phase 0: every test user gets its own Employee (HRMS v16 drops the Employee role
		# otherwise) and no designation (its role profile would replace the roles under test)
		cls.employee_of = {}
		for i, (email, roles) in enumerate(TEST_USERS.items(), start=1):
			make_user(email, roles)
			emp = employee_doc(f"P2 User{i}", f"TEST-P2-USER{i}", None, user_id=email)
			emp.insert(ignore_permissions=True)
			cls.employee_of[email] = emp.name
			frappe.clear_cache(user=email)

		# emp1 reports to the approver and gets a user the way HR creates one (own record only)
		emp1 = employee_doc("P2 Emp1", "TEST-P2-EMP1", None, reports_to=cls.employee_of[APPROVER])
		emp1.insert(ignore_permissions=True)
		create_user(emp1.name, email=EMP1, create_user_permission=1)
		cls.emp1 = emp1.name
		cls.emp1_default_shift_approver = frappe.db.get_value("Employee", emp1.name, "shift_request_approver")

		# another employee (no user), also under the approver
		emp2 = employee_doc("P2 Emp2", "TEST-P2-EMP2", None, reports_to=cls.employee_of[APPROVER])
		emp2.insert(ignore_permissions=True)
		cls.emp2 = emp2.name

		# the HR Manager approves shift requests. The default is the site's HR Manager
		# (approvers.hr_manager_user, checked in test_03); the test HR Manager stands in for them.
		for name in (cls.emp1, cls.emp2):
			frappe.db.set_value("Employee", name, "shift_request_approver", HR_MANAGER)
		frappe.clear_cache(user=EMP1)

		# dates in the future, apart from each other, so nothing overlaps
		base = getdate(today())
		cls.assignment_dates = (add_days(base, 30), add_days(base, 36))
		cls.hr_user_assignment_dates = (add_days(base, 40), add_days(base, 46))
		cls.request_dates = (add_days(base, 60), add_days(base, 62))
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
		self.assertTrue(frappe.db.exists("Shift Type", SHIFT), f"Shift Type {SHIFT} missing")
		self.assertTrue(frappe.db.exists("Holiday List", holiday_list_name(getdate(today()).year)),
			"this year's Holiday List missing")

	def test_02_users_have_exactly_their_roles(self):
		for email, expected in {**TEST_USERS, EMP1: {"Employee"}}.items():
			roles = set(frappe.get_roles(email)) - AUTOMATIC_ROLES
			self.assertEqual(roles, expected, f"{email} roles")
		own = frappe.get_all("User Permission", filters={"user": EMP1, "allow": "Employee"}, pluck="for_value")
		self.assertEqual(own, [self.emp1], "emp1 should be restricted to their own Employee record")

	def test_03_default_shift_request_approver_is_hr_manager(self):
		"""setup/approvers.py: Shift Request Approver defaults to the HR Manager's user."""
		hr = approvers.hr_manager_user()
		if not hr:
			self.skipTest("no active employee with the HR Manager designation and a user")
		self.assertEqual(self.emp1_default_shift_approver, hr)

	# ---------------------------------------------------------------- masters visible
	def assert_can_read(self, user, doctype, name):
		self.assertTrue(
			frappe.has_permission(doctype, "read", doc=frappe.get_doc(doctype, name), user=user),
			f"{user} cannot read {doctype} {name}",
		)

	def test_04_hr_manager_sees_shift_type_and_holiday_list(self):
		self.assert_can_read(HR_MANAGER, "Shift Type", SHIFT)
		self.assert_can_read(HR_MANAGER, "Holiday List", holiday_list_name(getdate(today()).year))

	def test_05_approver_and_employee_read_shift_type(self):
		for user in (APPROVER, EMP1):
			self.assert_can_read(user, "Shift Type", SHIFT)
			self.assert_can_read(user, "Shift Type", DEFAULT_SHIFT)

	def test_06_approver_and_employee_read_holiday_list(self):
		for user in (APPROVER, EMP1):
			self.assert_can_read(user, "Holiday List", holiday_list_name(getdate(today()).year))

	def test_06b_employee_shows_current_holiday_list(self):
		"""setup/shifts.py: the company's list for this year, read-only on the Employee."""
		expected = holiday_list_name(getdate(today()).year)
		for employee in (self.emp1, self.emp2):
			self.assertEqual(frappe.db.get_value("Employee", employee, "holiday_list"), expected)
		self.assertTrue(frappe.get_meta("Employee").get_field("holiday_list").read_only)

	def test_06c_employee_sees_only_current_holiday_list(self):
		"""setup/shifts.py: next year's list stays hidden from employees; HR sees every list."""
		this_year = getdate(today()).year
		next_list = holiday_list_name(this_year + 1)
		if not frappe.db.exists("Holiday List", next_list):
			self.skipTest(f"{next_list} missing")
		for user in (APPROVER, EMP1):
			frappe.set_user(user)
			self.assertEqual(frappe.get_list("Holiday List", pluck="name"), [holiday_list_name(this_year)])
			self.assertFalse(frappe.has_permission("Holiday List", "read", doc=next_list, user=user))
		frappe.set_user(HR_MANAGER)
		self.assertIn(next_list, frappe.get_list("Holiday List", pluck="name"))

	# ---------------------------------------------------------------- shift assignment
	def test_07_hr_manager_creates_and_submits_shift_assignment(self):
		frappe.set_user(HR_MANAGER)
		doc = shift_assignment(self.emp1, *self.assignment_dates)
		doc.insert()
		doc.submit()
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.owner, HR_MANAGER)

	def test_08_hr_user_creates_and_submits_shift_assignment(self):
		frappe.set_user(HR_USER)
		doc = shift_assignment(self.emp2, *self.hr_user_assignment_dates)
		doc.insert()
		doc.submit()
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.owner, HR_USER)

	def test_09_employee_cannot_create_shift_assignment(self):
		frappe.set_user(EMP1)
		with self.assertRaises(frappe.PermissionError):
			shift_assignment(self.emp1, *self.hr_user_assignment_dates).insert()

	# ---------------------------------------------------------------- shift request
	def test_10_employee_creates_own_shift_request_and_hr_manager_approves(self):
		frappe.set_user(EMP1)
		request = shift_request(self.emp1, *self.request_dates, HR_MANAGER)
		request.insert()
		self.assertEqual(request.status, "Draft")

		frappe.set_user(HR_MANAGER)
		request = frappe.get_doc("Shift Request", request.name)
		self.assertTrue(frappe.has_permission("Shift Request", "submit", doc=request, user=HR_MANAGER),
			"HR Manager cannot submit the Shift Request")
		request.status = "Approved"
		request.submit()

		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Shift Request", request.name, "docstatus"), 1)
		self.assertTrue(
			frappe.db.exists("Shift Assignment", {"shift_request": request.name, "employee": self.emp1,
				"shift_type": SHIFT, "docstatus": 1}),
			"approving the Shift Request did not create a submitted Shift Assignment",
		)

	def test_11_employee_cannot_request_for_another_employee(self):
		frappe.set_user(EMP1)
		with self.assertRaises(frappe.PermissionError):
			shift_request(self.emp2, *self.request_dates, HR_MANAGER).insert()

	def test_12_employee_and_reports_to_cannot_approve_shift_request(self):
		frappe.set_user(EMP1)
		request = shift_request(self.emp1, add_days(self.request_dates[1], 10),
			add_days(self.request_dates[1], 11), HR_MANAGER)
		request.insert()
		for user in (EMP1, APPROVER):  # the Reports To no longer approves shift requests
			frappe.set_user(user)
			doc = frappe.get_doc("Shift Request", request.name)
			doc.status = "Approved"
			with self.assertRaises(frappe.PermissionError, msg=f"{user} could approve"):
				doc.submit()

	def test_13_employee_sees_only_own_shift_requests(self):
		frappe.set_user("Administrator")
		other = shift_request(self.emp2, *self.request_dates, HR_MANAGER).insert()

		frappe.set_user(EMP1)
		visible = frappe.get_list("Shift Request", fields=["name", "employee"])
		self.assertNotIn(other.name, [r.name for r in visible])
		self.assertEqual({r.employee for r in visible} - {self.emp1}, set(),
			"emp1 sees other employees' shift requests")
		self.assertFalse(frappe.has_permission("Shift Request", "read", doc=other, user=EMP1))

	# ---------------------------------------------------------------- employee checkin
	def test_14_employee_checks_in_and_out(self):
		frappe.set_user(EMP1)
		day = add_days(today(), -1)
		check_in = checkin(self.emp1, f"{day} 09:00:00", "IN").insert()
		check_out = checkin(self.emp1, f"{day} 18:00:00", "OUT").insert()
		self.assertEqual((check_in.owner, check_out.owner), (EMP1, EMP1))
		self.assertEqual([check_in.log_type, check_out.log_type], ["IN", "OUT"])
		# session_log/builder.py: the check-out builds the day's Session Log (HRMS stamps an
		# employee's own punches with the current time, so it is the check-out's day)
		self.assertTrue(frappe.db.exists("Session Log", {"employee": self.emp1}),
			"check-out did not create a Session Log")

	def test_14b_hr_checkout_builds_processed_session_log(self):
		frappe.set_user(HR_USER)
		day = add_days(today(), -3)
		checkin(self.emp2, f"{day} 09:00:00", "IN").insert()
		checkin(self.emp2, f"{day} 17:30:00", "OUT").insert()
		frappe.set_user("Administrator")
		log = frappe.db.get_value("Session Log", {"employee": self.emp2, "log_date": day},
			["working_hours", "attendance", "error_log"], as_dict=True)
		self.assertIsNotNone(log, "check-out did not create a Session Log")
		self.assertEqual(log.working_hours, 8.5)
		self.assertIsNone(log.error_log)

	def test_15_employee_cannot_check_in_for_another_employee(self):
		frappe.set_user(EMP1)
		with self.assertRaises(frappe.PermissionError):
			checkin(self.emp2, f"{add_days(today(), -1)} 09:05:00", "IN").insert()

	def test_16_hr_user_checks_in_any_employee(self):
		frappe.set_user(HR_USER)
		day = add_days(today(), -2)
		for employee in (self.emp1, self.emp2):
			doc = checkin(employee, f"{day} 09:00:00", "IN").insert()
			self.assertEqual(doc.owner, HR_USER)
