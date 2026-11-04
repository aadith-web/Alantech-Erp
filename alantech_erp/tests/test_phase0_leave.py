# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-002-6 Phase 0, Step 5: leave and attendance requests (allocation, application, approval).

ClickUp: https://app.clickup.com/t/14yr2e56c9x

Leave Approval workflow (setup/leave_workflow.py): the Leave Approver (emp1's Reports To user)
approves first, then the HR Manager approves and the application is submitted. Every user holds
only their matrix roles and every check runs as the user under test (no ignore_permissions).

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_leave

Everything created here uses p5.*@example.com addresses, the TEST-P5- employee numbers and the
TEST-P5 Leave Policy, and is removed again in tearDownClass. The site has no Leave Period yet, so the
test creates one for this year (and removes it) unless one already covers the test dates.
"""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.alantech.doctype.session_log.builder import build_log
from alantech_erp.setup.employee_user import create_user
from alantech_erp.setup.shifts import DEFAULT_SHIFT, holiday_list_name
from alantech_erp.tests.test_phase0_employee_user import AUTOMATIC_ROLES, COMPANY, employee_doc, make_user
from alantech_erp.tests.test_phase0_session_log import get_log, overtime_off, set_shift_overtime

HR_MANAGER = "p5.hr.manager@example.com"
HR_USER = "p5.hr.user@example.com"
APPROVER = "p5.approver@example.com"
EMP1 = "p5.emp1@example.com"

TEST_USERS = {
	HR_MANAGER: {"HR Manager", "Employee"},
	HR_USER: {"HR User", "Employee"},
	APPROVER: {"Employee", "Leave Approver"},
}

POLICY = "TEST-P5 Policy"
CASUAL = "Casual Leave"
SICK = "Sick Leave"
MATERNITY = "Maternity Leave"
ALLOCATION = {CASUAL: 12, MATERNITY: 90}

TRANSACTIONS = (
	"Leave Application", "Leave Allocation", "Leave Ledger Entry", "Leave Policy Assignment",
	"Attendance Request", "Attendance", "Employee Checkin",
)


def cleanup(leave_period=None):
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P5-%"]}, pluck="name")
	if employees:
		session_logs = frappe.get_all("Session Log", filters={"employee": ["in", employees]}, pluck="name")
		if session_logs:
			frappe.db.delete("Attendance Log Checkin", {"parent": ["in", session_logs]})
			frappe.db.delete("Session Log", {"name": ["in", session_logs]})
		applications = frappe.get_all("Leave Application", filters={"employee": ["in", employees]}, pluck="name")
		if applications:
			frappe.db.delete("Workflow Action", {"reference_name": ["in", applications]})
		for doctype in TRANSACTIONS:  # submitted documents: delete_doc would refuse them
			frappe.db.delete(doctype, {"employee": ["in", employees]})
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	for email in frappe.get_all("User", filters={"name": ["like", "p5.%@example.com"]}, pluck="name"):
		frappe.db.delete("User Permission", {"user": email})
		frappe.db.delete("DocShare", {"user": email})
		frappe.db.delete("ToDo", {"allocated_to": email})
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	for policy in frappe.get_all("Leave Policy", filters={"title": POLICY}, pluck="name"):
		frappe.db.delete("Leave Policy Detail", {"parent": policy})
		frappe.db.delete("Leave Policy", {"name": policy})
	if leave_period:
		frappe.db.delete("Leave Period", {"name": leave_period})
	frappe.db.commit()


def working_days(count):
	"""`count` past weekdays that are working days, from 3 weeks back, this year (the Leave Period)."""
	day, days = add_days(today(), -21), []
	while len(days) < count:
		if getdate(day).weekday() < 5 and not frappe.db.exists(
			"Holiday", {"parent": holiday_list_name(getdate(day).year), "holiday_date": day}
		):
			days.append(getdate(day))
		day = add_days(day, -1)
	return days


def leave_application(employee, leave_type, from_date, to_date=None):
	return frappe.get_doc({"doctype": "Leave Application", "employee": employee, "company": COMPANY,
		"leave_type": leave_type, "from_date": from_date, "to_date": to_date or from_date,
		"description": "TEST-P5"})


def attendance_request(employee, day):
	return frappe.get_doc({"doctype": "Attendance Request", "employee": employee, "company": COMPANY,
		"from_date": day, "to_date": day, "reason": "On Duty", "explanation": "TEST-P5"})


def leave_balance(employee, leave_type, day):
	from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

	return get_leave_balance_on(employee, leave_type, day)


class TestPhase0Leave(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		cls.shift_overtime = overtime_off()  # a Session Log here must not need a salary structure

		cls.employee_of = {}
		for i, (email, roles) in enumerate(TEST_USERS.items(), start=1):
			make_user(email, roles)
			emp = employee_doc(f"P5 User{i}", f"TEST-P5-USER{i}", None, user_id=email)
			emp.insert(ignore_permissions=True)
			cls.employee_of[email] = emp.name
			frappe.clear_cache(user=email)

		# emp1 (male) and emp2 (female, no user) report to the approver
		emp1 = employee_doc("P5 Emp1", "TEST-P5-EMP1", None, reports_to=cls.employee_of[APPROVER],
			default_shift=DEFAULT_SHIFT)
		emp1.insert(ignore_permissions=True)
		create_user(emp1.name, email=EMP1, create_user_permission=1)
		cls.emp1 = emp1.name
		emp2 = employee_doc("P5 Emp2", "TEST-P5-EMP2", None, gender="Female",
			reports_to=cls.employee_of[APPROVER], default_shift=DEFAULT_SHIFT)
		emp2.insert(ignore_permissions=True)
		cls.emp2 = emp2.name
		frappe.clear_cache(user=EMP1)

		(cls.leave_day, cls.reject_day, cls.request_day, cls.hr_request_day, cls.hr_leave_day,
			*cls.maternity_days) = sorted(working_days(8), reverse=True)
		year = getdate(today()).year
		cls.period_from, cls.period_to = getdate(f"{year}-01-01"), getdate(f"{year}-12-31")
		cls.created_period = None
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		set_shift_overtime(cls.shift_overtime)
		cleanup(cls.created_period)
		frappe.flags.mute_emails = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------- setup checks
	def test_01_masters_and_workflow(self):
		for leave_type in (CASUAL, SICK, MATERNITY):
			self.assertTrue(frappe.db.exists("Leave Type", leave_type), f"Leave Type {leave_type} missing")
		self.assertEqual(frappe.db.get_value("Leave Type", MATERNITY, ["alt_for_male", "alt_for_female"]), (0, 1),
			"Maternity Leave should be for female employees only")
		self.assertTrue(frappe.db.get_value("Workflow", "Leave Approval", "is_active"), "Leave Approval workflow off")

	def test_02_users_have_exactly_their_roles(self):
		for email, expected in {**TEST_USERS, EMP1: {"Employee"}}.items():
			roles = set(frappe.get_roles(email)) - AUTOMATIC_ROLES
			self.assertEqual(roles, expected, f"{email} roles")

	def test_03_leave_approver_is_reports_to(self):
		for employee in (self.emp1, self.emp2):
			self.assertEqual(frappe.db.get_value("Employee", employee, "leave_approver"), APPROVER)

	# ---------------------------------------------------------------- allocation
	def test_04_hr_manager_creates_leave_period_and_policy(self):
		frappe.set_user(HR_MANAGER)
		existing = frappe.db.get_value("Leave Period", {"company": COMPANY, "is_active": 1,
			"from_date": ["<=", self.maternity_days[-1]], "to_date": [">=", self.leave_day]},
			["name", "from_date", "to_date"], as_dict=True)
		if existing:
			type(self).leave_period = existing.name
			type(self).period_from, type(self).period_to = existing.from_date, existing.to_date
		else:
			period = frappe.get_doc({"doctype": "Leave Period", "company": COMPANY, "is_active": 1,
				"from_date": self.period_from, "to_date": self.period_to}).insert()
			type(self).leave_period = type(self).created_period = period.name
			self.assertEqual(period.owner, HR_MANAGER)

		policy = frappe.get_doc({"doctype": "Leave Policy", "title": POLICY,
			"leave_policy_details": [{"leave_type": t, "annual_allocation": n} for t, n in ALLOCATION.items()]})
		policy.insert()
		policy.submit()
		type(self).policy = policy.name
		self.assertEqual(policy.docstatus, 1)

	def test_05_hr_user_assigns_leave_policy(self):
		"""Allocations from a policy are not blocked by gender (setup/leave_validation.py): emp1 (male)
		gets Maternity Leave too, but cannot apply for it (test_08)."""
		frappe.set_user(HR_USER)
		for employee in (self.emp1, self.emp2):
			assignment = frappe.get_doc({"doctype": "Leave Policy Assignment", "employee": employee,
				"company": COMPANY, "leave_policy": self.policy, "assignment_based_on": "Leave Period",
				"leave_period": self.leave_period, "effective_from": self.period_from,
				"effective_to": self.period_to}).insert()
			assignment.submit()
			self.assertEqual(assignment.owner, HR_USER)

		frappe.set_user("Administrator")
		for employee in (self.emp1, self.emp2):
			allocated = frappe.get_all("Leave Allocation", filters={"employee": employee, "docstatus": 1},
				fields=["leave_type", "new_leaves_allocated"])
			self.assertEqual({a.leave_type for a in allocated}, set(ALLOCATION), f"{employee} allocations")
		self.assertGreater(leave_balance(self.emp1, CASUAL, self.leave_day), 0)

	def test_06_hr_manager_allocates_leave_by_hand(self):
		frappe.set_user(HR_MANAGER)
		allocation = frappe.get_doc({"doctype": "Leave Allocation", "employee": self.emp1, "leave_type": SICK,
			"from_date": self.period_from, "to_date": self.period_to, "new_leaves_allocated": 6}).insert()
		allocation.submit()
		self.assertEqual(allocation.docstatus, 1)

	# ---------------------------------------------------------------- gender rule
	def test_07_maternity_allocation_refused_for_male_allowed_for_female(self):
		"""Next year's dates: this year both already have Maternity Leave from the policy (overlap)."""
		next_year = getdate(today()).year + 1

		def allocation(employee):
			return frappe.get_doc({"doctype": "Leave Allocation", "employee": employee, "leave_type": MATERNITY,
				"from_date": f"{next_year}-01-01", "to_date": f"{next_year}-03-31", "new_leaves_allocated": 10})

		frappe.set_user(HR_MANAGER)
		with self.assertRaisesRegex(frappe.ValidationError, "not applicable"):
			allocation(self.emp1).insert()
		female = allocation(self.emp2).insert()
		female.submit()
		self.assertEqual(female.docstatus, 1)

	def test_08_maternity_application_refused_for_male_allowed_for_female(self):
		frappe.set_user(EMP1)
		with self.assertRaisesRegex(frappe.ValidationError, "not applicable"):
			leave_application(self.emp1, MATERNITY, self.maternity_days[-1]).insert()

		# HR User applies on behalf of emp2 (female)
		frappe.set_user(HR_USER)
		application = leave_application(self.emp2, MATERNITY, self.maternity_days[-1], self.maternity_days[0])
		application.insert()
		self.assertEqual((application.workflow_state, application.owner), ("Pending", HR_USER))

	# ---------------------------------------------------------------- leave application end to end
	def test_09_employee_applies_approver_and_hr_manager_approve(self):
		frappe.set_user(EMP1)
		application = leave_application(self.emp1, CASUAL, self.leave_day).insert()
		self.assertEqual(application.leave_approver, APPROVER)
		self.assertEqual((application.workflow_state, application.status, application.docstatus),
			("Pending", "Open", 0))
		with self.assertRaises(frappe.ValidationError, msg="emp1 approved their own leave"):
			apply_workflow(frappe.get_doc("Leave Application", application.name), "Approve")

		frappe.set_user(APPROVER)
		application = apply_workflow(frappe.get_doc("Leave Application", application.name), "Approve")
		self.assertEqual((application.workflow_state, application.docstatus), ("Pending HR Approval", 0))

		frappe.set_user(HR_MANAGER)
		application = apply_workflow(frappe.get_doc("Leave Application", application.name), "Approve")
		self.assertEqual((application.workflow_state, application.status, application.docstatus),
			("Approved", "Approved", 1))
		type(self).approved_leave = application.name

		frappe.set_user("Administrator")
		attendance = frappe.get_all("Attendance", filters={"employee": self.emp1, "attendance_date": self.leave_day,
			"docstatus": 1}, fields=["status", "leave_type", "leave_application"])
		self.assertEqual(len(attendance), 1)
		self.assertEqual((attendance[0].status, attendance[0].leave_type, attendance[0].leave_application),
			("On Leave", CASUAL, application.name))

	def test_10_approver_rejects_leave(self):
		frappe.set_user(EMP1)
		application = leave_application(self.emp1, CASUAL, self.reject_day).insert()
		frappe.set_user(APPROVER)
		application = apply_workflow(frappe.get_doc("Leave Application", application.name), "Reject")
		self.assertEqual((application.workflow_state, application.status, application.docstatus),
			("Rejected", "Rejected", 1))
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("Attendance", {"employee": self.emp1, "attendance_date": self.reject_day,
			"docstatus": 1}))

	def test_11_employee_cannot_apply_for_another_employee(self):
		frappe.set_user(EMP1)
		with self.assertRaises(frappe.PermissionError):
			leave_application(self.emp2, CASUAL, self.hr_leave_day).insert()

	def test_12_hr_user_applies_leave_on_behalf(self):
		frappe.set_user(HR_USER)
		application = leave_application(self.emp2, CASUAL, self.hr_leave_day).insert()
		self.assertEqual((application.workflow_state, application.leave_approver, application.owner),
			("Pending", APPROVER, HR_USER))

	# ---------------------------------------------------------------- approved leave in Session Log
	def test_13_approved_leave_on_leave_in_session_log(self):
		build_log(self.emp1, self.leave_day)  # the daily build, for a day without check-ins
		log = get_log(self.emp1, self.leave_day)
		self.assertIsNotNone(log, "no Session Log for the leave day")
		self.assertEqual((log.attendance_status, log.leave_type), ("On Leave", CASUAL))
		# the leave already made the Attendance: the log must not create a second one
		self.assertEqual(frappe.db.count("Attendance", {"employee": self.emp1, "attendance_date": self.leave_day,
			"docstatus": ["!=", 2]}), 1)

	# ---------------------------------------------------------------- employee visibility
	def test_14_employee_cannot_see_other_employees_leave(self):
		other = frappe.get_all("Leave Application", filters={"employee": self.emp2}, pluck="name")
		other_allocations = frappe.get_all("Leave Allocation", filters={"employee": self.emp2}, pluck="name")
		self.assertTrue(other and other_allocations)
		frappe.set_user(EMP1)
		visible = frappe.get_list("Leave Application", fields=["name", "employee"])
		self.assertIn(self.approved_leave, [r.name for r in visible])
		self.assertEqual({r.employee for r in visible}, {self.emp1}, "emp1 sees other employees' leave")
		for name in other:
			self.assertFalse(frappe.has_permission("Leave Application", "read", doc=name, user=EMP1))
		for name in other_allocations:
			self.assertFalse(frappe.has_permission("Leave Allocation", "read", doc=name, user=EMP1))

	# ---------------------------------------------------------------- attendance request
	def test_15_employee_requests_attendance_approver_approves(self):
		frappe.set_user(EMP1)
		request = attendance_request(self.emp1, self.request_day).insert()
		with self.assertRaises(frappe.PermissionError, msg="emp1 approved their own attendance request"):
			frappe.get_doc("Attendance Request", request.name).submit()

		frappe.set_user(APPROVER)
		self.assertTrue(frappe.has_permission("Attendance Request", "read", doc=request.name, user=APPROVER),
			"approver cannot see emp1's Attendance Request")
		frappe.get_doc("Attendance Request", request.name).submit()

		frappe.set_user("Administrator")
		attendance = frappe.get_all("Attendance", filters={"employee": self.emp1, "attendance_date": self.request_day,
			"docstatus": 1}, fields=["status", "attendance_request"])
		self.assertEqual(len(attendance), 1)
		self.assertEqual((attendance[0].status, attendance[0].attendance_request), ("Present", request.name))

	def test_15b_approver_cannot_approve_another_teams_request(self):
		"""setup/attendance_request.py: only the employee's own Leave Approver (or HR) approves."""
		frappe.set_user("Administrator")
		outsider = employee_doc("P5 Emp3", "TEST-P5-EMP3", None, default_shift=DEFAULT_SHIFT)
		outsider.insert(ignore_permissions=True)
		self.assertNotEqual(outsider.leave_approver, APPROVER)

		frappe.set_user(HR_USER)
		request = attendance_request(outsider.name, self.request_day).insert()
		frappe.set_user(APPROVER)
		with self.assertRaises(frappe.PermissionError, msg="approver approved another team's request"):
			frappe.get_doc("Attendance Request", request.name).submit()

	def test_16_employee_cannot_request_attendance_for_another_employee(self):
		frappe.set_user(EMP1)
		with self.assertRaises(frappe.PermissionError):
			attendance_request(self.emp2, self.hr_request_day).insert()

	def test_17_hr_user_submits_attendance_request_on_behalf(self):
		frappe.set_user(HR_USER)
		request = attendance_request(self.emp2, self.hr_request_day).insert()
		request.submit()
		self.assertEqual((request.docstatus, request.owner), (1, HR_USER))
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Attendance", {"employee": self.emp2, "attendance_date": self.hr_request_day,
			"attendance_request": request.name, "docstatus": 1}))
