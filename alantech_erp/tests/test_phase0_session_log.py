# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-002-6 Phase 0, Step 3: attendance from check-ins (Session Log).

ClickUp: https://app.clickup.com/t/14yr2e56c9v

Shifts have auto attendance off; a check-out (or the daily scheduler) builds the day's Session Log,
which creates the Attendance. Every user holds only their matrix roles; the check-ins are punched by
the HR User and every permission check runs as the user under test.

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_session_log

Everything created here uses p3.*@example.com addresses and the TEST-P3- employee numbers, and is
removed again in tearDownClass, together with the test public holiday. Session Log Settings are
restored to what they were.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.alantech.doctype.session_log import builder
from alantech_erp.alantech.doctype.session_log.approval import approve_logs, reject_logs
from alantech_erp.setup.employee_user import create_user
from alantech_erp.setup.shifts import DEFAULT_SHIFT, holiday_list_name
from alantech_erp.tests.test_phase0_employee_user import AUTOMATIC_ROLES, COMPANY, employee_doc, make_user

HR_MANAGER = "p3.hr.manager@example.com"
HR_USER = "p3.hr.user@example.com"
APPROVER = "p3.approver@example.com"
EMP1 = "p3.emp1@example.com"

TEST_USERS = {
	HR_MANAGER: {"HR Manager", "Employee"},
	HR_USER: {"HR User", "Employee"},
	APPROVER: {"Employee", "Leave Approver"},
}

TRANSACTIONS = ("Employee Checkin", "Attendance", "Overtime Log")
SETTINGS_FIELDS = (
	"require_log_approval", "log_creation_trigger", "approver_role", "hold_missing_checkout",
	"auto_submit_attendance", "auto_submit_overtime", "lock_after_processing",
)
TEST_HOLIDAY = "TEST-P3 Public Holiday"

# General Shift 09:00-17:00, grace 15 min, half day below 4 h, absent below 2 h (setup/shifts.py).
# One week of emp1, Monday first: (in, out, attendance_status, working_hours, late_entry, early_exit).
# None for out = no check-out; None for a flag = not checked (off days).
WEEK = (
	("09:00", "17:00", "Present", 8.0, 0, 0),
	("09:30", "17:00", "Present", 7.5, 1, 0),  # late entry
	("09:00", "12:00", "Half Day", 3.0, 0, 1),  # early exit, below the half day threshold
	("09:05", None, "Half Day", 0.0, 0, 0),  # missing check-out: held for approval
	("09:00", "13:00", "Present", 4.0, None, None),  # public holiday (added by the test)
	("09:00", "10:00", "Absent", 1.0, None, None),  # below the absent threshold
	("10:00", "14:00", "Present", 4.0, None, None),  # Sunday: weekly off
)
MISSING_CHECKOUT_DAY = 3
HOLIDAY_DAY = 4


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P3-%"]}, pluck="name")
	if employees:
		session_logs = frappe.get_all("Session Log", filters={"employee": ["in", employees]}, pluck="name")
		if session_logs:
			frappe.db.delete("Attendance Log Checkin", {"parent": ["in", session_logs]})
			frappe.db.delete("Session Log", {"name": ["in", session_logs]})
		for doctype in TRANSACTIONS:  # submitted documents: delete_doc would refuse them
			frappe.db.delete(doctype, {"employee": ["in", employees]})
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	for email in frappe.get_all("User", filters={"name": ["like", "p3.%@example.com"]}, pluck="name"):
		frappe.db.delete("User Permission", {"user": email})
		frappe.db.delete("DocShare", {"user": email})
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	frappe.db.delete("Holiday", {"description": TEST_HOLIDAY})
	frappe.db.commit()


def set_settings(**values):
	doc = frappe.get_doc("Session Log Settings")
	doc.update(values)
	doc.save(ignore_permissions=True)


def set_shift_overtime(values):
	"""{shift: (allow_overtime, overtime_type)}; returns the values it replaced."""
	before = {}
	for shift, (allow, overtime_type) in values.items():
		before[shift] = tuple(frappe.db.get_value("Shift Type", shift, ["allow_overtime", "overtime_type"]))
		frappe.db.set_value("Shift Type", shift, {"allow_overtime": allow, "overtime_type": overtime_type})
		frappe.clear_document_cache("Shift Type", shift)
	return before


def overtime_off():
	"""Attendance tests: no Overtime Log (it needs a salary structure, see test_phase0_overtime)."""
	return set_shift_overtime({DEFAULT_SHIFT: (0, None)})


def checkin(employee, time, log_type):
	return frappe.get_doc({"doctype": "Employee Checkin", "employee": employee, "time": time, "log_type": log_type})


def punch(employee, day, time_in, time_out=None):
	"""IN (and OUT) for one day; the OUT builds the Session Log ("On Check-out")."""
	checkin(employee, f"{day} {time_in}:00", "IN").insert()
	if time_out:
		checkin(employee, f"{day} {time_out}:00", "OUT").insert()


def get_log(employee, day):
	name = frappe.db.exists("Session Log", {"employee": employee, "log_date": getdate(day)})
	return frappe.get_doc("Session Log", name) if name else None


def attendance_count(employee, day):
	return frappe.db.count("Attendance", {"employee": employee, "attendance_date": day, "docstatus": ["!=", 2]})


def expected_day_type(day):
	weekly_off = frappe.db.get_value(
		"Holiday", {"parent": holiday_list_name(getdate(day).year), "holiday_date": day}, "weekly_off"
	)
	if weekly_off is None:
		return "Working Day"
	return "Weekly Off" if weekly_off else "Holiday"


def add_public_holiday(day):
	"""A public holiday on a weekday of the test week (removed again in cleanup)."""
	name = holiday_list_name(getdate(day).year)
	if frappe.db.exists("Holiday", {"parent": name, "holiday_date": day}):
		return
	holiday_list = frappe.get_doc("Holiday List", name)
	holiday_list.append("holidays", {"holiday_date": day, "description": TEST_HOLIDAY, "weekly_off": 0})
	holiday_list.save(ignore_permissions=True)


class TestPhase0SessionLog(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		settings = frappe.get_doc("Session Log Settings")
		cls.original_settings = {f: settings.get(f) for f in SETTINGS_FIELDS}
		cls.shift_overtime = overtime_off()
		# Step 3 defaults: approval off, built on check-out, missing check-out held, auto submit
		set_settings(require_log_approval=0, log_creation_trigger=builder.TRIGGER_ON_CHECKOUT,
			approver_role="HR Manager", hold_missing_checkout=1, auto_submit_attendance=1,
			auto_submit_overtime=1, lock_after_processing=1)

		cls.employee_of = {}
		for i, (email, roles) in enumerate(TEST_USERS.items(), start=1):
			make_user(email, roles)
			emp = employee_doc(f"P3 User{i}", f"TEST-P3-USER{i}", None, user_id=email)
			emp.insert(ignore_permissions=True)
			cls.employee_of[email] = emp.name
			frappe.clear_cache(user=email)

		# emp1 reports to the approver and gets a user the way HR creates one (own record only)
		emp1 = employee_doc("P3 Emp1", "TEST-P3-EMP1", None, reports_to=cls.employee_of[APPROVER],
			default_shift=DEFAULT_SHIFT)
		emp1.insert(ignore_permissions=True)
		create_user(emp1.name, email=EMP1, create_user_permission=1)
		cls.emp1 = emp1.name
		emp2 = employee_doc("P3 Emp2", "TEST-P3-EMP2", None, reports_to=cls.employee_of[APPROVER],
			default_shift=DEFAULT_SHIFT)
		emp2.insert(ignore_permissions=True)
		cls.emp2 = emp2.name
		frappe.clear_cache(user=EMP1)

		# the Monday three weeks back: a full past week, apart from the other tests' dates
		base = getdate(today())
		cls.monday = add_days(base, -base.weekday() - 21)
		cls.week = [add_days(cls.monday, i) for i in range(7)]
		add_public_holiday(cls.week[HOLIDAY_DAY])

		# one week of emp1 check-ins, punched by the HR User
		frappe.set_user(HR_USER)
		for day, (time_in, time_out, *_) in zip(cls.week, WEEK):
			punch(cls.emp1, day, time_in, time_out)
		frappe.set_user("Administrator")
		# missing check-out: no OUT punch, so the daily build makes that log
		builder.build_log(cls.emp1, cls.week[MISSING_CHECKOUT_DAY])
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		set_settings(**cls.original_settings)
		set_shift_overtime(cls.shift_overtime)
		cleanup()
		frappe.flags.mute_emails = False
		frappe.flags.session_log_sync = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.session_log_sync = False

	# ---------------------------------------------------------------- setup checks
	def test_01_shifts_have_auto_attendance_off(self):
		shift = frappe.get_doc("Shift Type", DEFAULT_SHIFT)
		self.assertFalse(shift.enable_auto_attendance, "Session Log makes attendance, not HRMS")
		# the expected statuses in WEEK depend on these values
		self.assertEqual((str(shift.start_time), str(shift.end_time)), ("9:00:00", "17:00:00"))
		self.assertEqual((shift.working_hours_threshold_for_half_day,
			shift.working_hours_threshold_for_absent), (4, 2))
		self.assertEqual((shift.late_entry_grace_period, shift.early_exit_grace_period), (15, 15))

	def test_02_users_have_exactly_their_roles(self):
		for email, expected in {**TEST_USERS, EMP1: {"Employee"}}.items():
			roles = set(frappe.get_roles(email)) - AUTOMATIC_ROLES
			self.assertEqual(roles, expected, f"{email} roles")

	# ---------------------------------------------------------------- one week of check-ins
	def test_03_session_log_built_for_every_day(self):
		for day in self.week:
			log = get_log(self.emp1, day)
			self.assertIsNotNone(log, f"no Session Log for {day}")
			self.assertEqual(log.shift, DEFAULT_SHIFT)
			self.assertTrue(log.checkins, f"{day}: check-ins not linked")
			self.assertIsNone(log.error_log, f"{day}: {log.error_log}")

	def test_04_status_hours_late_early(self):
		for day, (_in, _out, status, hours, late, early) in zip(self.week, WEEK):
			log = get_log(self.emp1, day)
			self.assertEqual(log.attendance_status, status, f"{day} status")
			self.assertEqual(log.working_hours, hours, f"{day} working hours")
			if late is not None:
				self.assertEqual(log.late_entry, late, f"{day} late entry")
			if early is not None:
				self.assertEqual(log.early_exit, early, f"{day} early exit")

	def test_05_missing_checkout(self):
		for i, day in enumerate(self.week):
			self.assertEqual(get_log(self.emp1, day).missing_checkout, int(i == MISSING_CHECKOUT_DAY), str(day))
		log = get_log(self.emp1, self.week[MISSING_CHECKOUT_DAY])
		self.assertIsNone(log.last_out)
		self.assertEqual(log.status, "Pending Approval", "a missing check-out is held for review")
		self.assertIsNone(log.attendance)
		self.assertEqual(attendance_count(self.emp1, log.log_date), 0)

	def test_06_weekly_off_and_holiday(self):
		for day in self.week:
			self.assertEqual(get_log(self.emp1, day).day_type, expected_day_type(day), str(day))
		self.assertEqual(get_log(self.emp1, self.week[HOLIDAY_DAY]).day_type, "Holiday")
		self.assertEqual(get_log(self.emp1, self.week[6]).day_type, "Weekly Off")  # Sunday

	# ---------------------------------------------------------------- approval off
	def test_07_approval_off_attendance_created_and_submitted(self):
		for i, day in enumerate(self.week):
			if i == MISSING_CHECKOUT_DAY:
				continue
			log = get_log(self.emp1, day)
			self.assertEqual(log.status, "Processed", f"{day}: {log.remarks}")
			self.assertTrue(log.attendance, f"{day}: no Attendance linked")
			att = frappe.get_doc("Attendance", log.attendance)
			self.assertEqual(att.docstatus, 1, f"{day}: Attendance not submitted")
			self.assertEqual(att.attendance_log, log.name)
			self.assertEqual((att.employee, getdate(att.attendance_date)), (self.emp1, day))
			self.assertEqual(att.status, log.attendance_status)
			self.assertEqual((att.late_entry, att.early_exit), (log.late_entry, log.early_exit))
			self.assertEqual(att.working_hours, log.working_hours)

	def test_08_hr_manager_approves_held_log(self):
		log = get_log(self.emp1, self.week[MISSING_CHECKOUT_DAY])
		frappe.set_user(HR_MANAGER)
		frappe.flags.session_log_sync = True
		self.assertEqual(approve_logs([log.name]), 1)

		frappe.set_user("Administrator")
		log.reload()
		self.assertEqual(log.status, "Processed", log.error_log)
		self.assertEqual(log.approved_by, HR_MANAGER)
		att = frappe.get_doc("Attendance", log.attendance)
		self.assertEqual((att.docstatus, att.status, att.attendance_log), (1, "Half Day", log.name))

	# ---------------------------------------------------------------- approval on
	def test_09_approval_on_log_pending_until_hr_manager_approves(self):
		day = add_days(self.monday, 7)
		set_settings(require_log_approval=1)
		try:
			frappe.set_user(HR_USER)
			punch(self.emp1, day, "09:00", "17:00")
		finally:
			frappe.set_user("Administrator")
			set_settings(require_log_approval=0)

		log = get_log(self.emp1, day)
		self.assertEqual(log.status, "Pending Approval")
		self.assertIsNone(log.attendance)
		self.assertEqual(attendance_count(self.emp1, day), 0, "Attendance created before approval")

		# the approval lists it in Attendance Log Review
		from alantech_erp.alantech.report.attendance_log_review.attendance_log_review import execute

		frappe.set_user(HR_MANAGER)
		_columns, data, *_ = execute({"company": COMPANY, "month": day.strftime("%B"), "year": day.year,
			"employee": self.emp1, "status": "Pending Approval"})
		self.assertIn(log.name, [r.name for r in data])

		frappe.flags.session_log_sync = True
		approve_logs([log.name])
		frappe.set_user("Administrator")
		log.reload()
		self.assertEqual(log.status, "Processed", log.error_log)
		self.assertEqual(frappe.db.get_value("Attendance", log.attendance, ["docstatus", "status"]), (1, "Present"))

	def test_10_hr_manager_rejects_log(self):
		day = add_days(self.monday, 8)
		set_settings(require_log_approval=1)
		try:
			frappe.set_user(HR_USER)
			punch(self.emp1, day, "09:00", "17:00")
		finally:
			frappe.set_user("Administrator")
			set_settings(require_log_approval=0)

		log = get_log(self.emp1, day)
		frappe.set_user(HR_MANAGER)
		with self.assertRaises(frappe.ValidationError, msg="reject without a remark"):
			reject_logs([log.name], "")
		self.assertEqual(reject_logs([log.name], "wrong punch"), 1)
		frappe.set_user("Administrator")
		log.reload()
		self.assertEqual(log.status, "Rejected")
		self.assertIn("wrong punch", log.remarks)
		self.assertEqual(attendance_count(self.emp1, day), 0)

	def test_11_only_approver_role_approves(self):
		log = get_log(self.emp1, self.monday)
		for user in (HR_USER, APPROVER, EMP1):
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError, msg=f"{user} could approve"):
				approve_logs([log.name])
			with self.assertRaises(frappe.PermissionError, msg=f"{user} could reject"):
				reject_logs([log.name], "no")

	# ---------------------------------------------------------------- daily scheduler
	def test_12_daily_scheduler_builds_yesterdays_log(self):
		yesterday = add_days(today(), -1)
		set_settings(log_creation_trigger=builder.TRIGGER_DAILY)
		try:
			frappe.set_user(HR_USER)
			punch(self.emp2, yesterday, "09:00", "17:00")
			frappe.set_user("Administrator")
			self.assertIsNone(get_log(self.emp2, yesterday), "Daily Scheduler: the check-out built the log")

			# build only the test employees' logs, not the real employees who punched yesterday
			get_all = frappe.get_all

			def test_employees_only(doctype, *args, **kwargs):
				rows = get_all(doctype, *args, **kwargs)
				if doctype == "Employee Checkin" and kwargs.get("pluck") == "employee":
					rows = [e for e in rows if e in (self.emp1, self.emp2)]
				return rows

			with patch.object(frappe, "get_all", test_employees_only):
				builder.build_yesterday_logs()
		finally:
			frappe.set_user("Administrator")
			set_settings(log_creation_trigger=builder.TRIGGER_ON_CHECKOUT)

		log = get_log(self.emp2, yesterday)
		self.assertIsNotNone(log, "Daily Scheduler did not build the log")
		self.assertEqual(log.working_hours, 8.0)
		self.assertEqual(log.status, "Processed", log.error_log)
		self.assertTrue(log.attendance)

	# ---------------------------------------------------------------- HR User
	def test_13_hr_user_reads_and_writes_logs(self):
		frappe.set_user(HR_USER)
		names = frappe.get_list("Session Log", filters={"employee": self.emp1}, pluck="name")
		self.assertEqual(len(names), len(self.week) + 2, "HR User does not see all of emp1's logs")

		log = frappe.get_doc("Session Log", get_log(self.emp1, add_days(self.monday, 8)).name)  # Rejected
		self.assertTrue(frappe.has_permission("Session Log", "write", doc=log, user=HR_USER))
		log.remarks = f"{log.remarks}\nchecked by HR User"
		log.save()
		self.assertEqual(log.modified_by, HR_USER)

	def test_14_hr_user_submits_attendance(self):
		day = add_days(self.monday, 9)
		set_settings(auto_submit_attendance=0)
		try:
			frappe.set_user(HR_USER)
			punch(self.emp1, day, "09:00", "17:00")
		finally:
			frappe.set_user("Administrator")
			set_settings(auto_submit_attendance=1)

		log = get_log(self.emp1, day)
		self.assertEqual(log.status, "Processed", log.error_log)
		frappe.set_user(HR_USER)
		att = frappe.get_doc("Attendance", log.attendance)
		self.assertEqual(att.docstatus, 0)
		att.submit()
		self.assertEqual(frappe.db.get_value("Attendance", att.name, "docstatus"), 1)

	# ---------------------------------------------------------------- approver
	def test_15_approver_reads_team_attendance(self):
		names = frappe.get_all("Attendance", filters={"employee": self.emp1, "docstatus": 1}, pluck="name")
		self.assertTrue(names)
		frappe.set_user(APPROVER)
		for name in names:
			self.assertTrue(frappe.has_permission("Attendance", "read", doc=name, user=APPROVER),
				f"approver cannot read emp1's Attendance {name}")
		visible = frappe.get_list("Attendance", filters={"employee": self.emp1}, pluck="name")
		self.assertEqual(set(names) - set(visible), set(), "approver's Attendance list misses emp1's records")

	# ---------------------------------------------------------------- emp1
	def test_16_employee_reads_only_own_logs_and_attendance(self):
		other = get_log(self.emp2, add_days(today(), -1))
		frappe.set_user(EMP1)
		logs = frappe.get_list("Session Log", fields=["name", "employee"])
		self.assertTrue(logs, "emp1 sees none of their Session Logs")
		self.assertEqual({r.employee for r in logs}, {self.emp1}, "emp1 sees other employees' Session Logs")
		self.assertTrue(frappe.has_permission("Session Log", "read", doc=get_log(self.emp1, self.monday), user=EMP1))
		if other:
			self.assertFalse(frappe.has_permission("Session Log", "read", doc=other, user=EMP1))

		attendance = frappe.get_list("Attendance", fields=["name", "employee"])
		self.assertTrue(attendance, "emp1 sees none of their Attendance")
		self.assertEqual({r.employee for r in attendance}, {self.emp1}, "emp1 sees other employees' Attendance")

	def test_17_employee_cannot_edit_logs_or_attendance(self):
		log = get_log(self.emp1, self.week[MISSING_CHECKOUT_DAY])
		att = frappe.get_doc("Attendance", log.attendance)
		frappe.set_user(EMP1)
		self.assertFalse(frappe.has_permission("Session Log", "write", doc=log, user=EMP1))
		self.assertFalse(frappe.has_permission("Attendance", "write", doc=att, user=EMP1))
		log = frappe.get_doc("Session Log", log.name)
		log.remarks = "changed by emp1"
		with self.assertRaises(frappe.PermissionError):
			log.save()
		with self.assertRaises(frappe.PermissionError):
			approve_logs([log.name])

	# ---------------------------------------------------------------- no duplicates
	def test_18_one_session_log_per_employee_and_date(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": "Session Log", "employee": self.emp1, "company": COMPANY,
				"log_date": self.monday}).insert(ignore_permissions=True)

	def test_19_second_checkout_does_not_duplicate_attendance(self):
		frappe.set_user(HR_USER)
		checkin(self.emp1, f"{self.monday} 17:30:00", "OUT").insert()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Session Log", {"employee": self.emp1, "log_date": self.monday}), 1)
		self.assertEqual(attendance_count(self.emp1, self.monday), 1)

	def test_20_existing_attendance_is_not_duplicated(self):
		day = add_days(self.monday, 10)
		frappe.set_user(HR_USER)
		manual = frappe.get_doc({"doctype": "Attendance", "employee": self.emp2, "company": COMPANY,
			"attendance_date": day, "status": "Present"}).insert()
		manual.submit()
		punch(self.emp2, day, "09:00", "17:00")
		frappe.set_user("Administrator")

		log = get_log(self.emp2, day)
		self.assertEqual(attendance_count(self.emp2, day), 1, "a second Attendance was created")
		self.assertEqual(log.status, "Pending Approval")
		self.assertFalse(log.attendance)
		self.assertIn(manual.name, log.remarks)
