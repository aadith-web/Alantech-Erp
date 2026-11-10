# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Checkin validation: no IN without OUT, and a missed check-out blocks the next punch.

ClickUp: https://app.clickup.com/t/14yr2e57879
Code:    alantech_erp/setup/checkin_validation.py, session_log/builder.py (release_corrected_log)

General Shift 09:00-17:00 (8 h) with overtime off, so the missed check-out limit is
max(8 h, Session Log Settings > Missing Check-out Block After = 16 h) = 16 h, unless a test sets it.
Punches are made by the HR User (held by the limit), corrections by the HR Manager (not held).

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_checkin_sequence

Everything created here uses p9.*@example.com addresses and the TEST-P9- employee numbers, and is
removed again in tearDownClass. Shift overtime and Session Log Settings are restored.
"""

import frappe
from frappe.utils import add_days, add_to_date, formatdate, get_datetime, getdate, now_datetime, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.alantech.doctype.session_log import builder
from alantech_erp.setup.checkin_validation import (
	CheckinSequenceError,
	MissingCheckoutError,
	missing_checkout_limit,
)
from alantech_erp.setup.employee_user import create_user
from alantech_erp.setup.shifts import DEFAULT_SHIFT
from alantech_erp.tests.test_phase0_employee_user import COMPANY, employee_doc, make_user
from alantech_erp.tests.test_phase0_session_log import overtime_off, set_settings, set_shift_overtime

HR_MANAGER = "p9.hr.manager@example.com"
HR_USER = "p9.hr.user@example.com"
EMP1 = "p9.emp1@example.com"
# Loan Manager comes with HR Manager (setup/loan_roles.py, HR-F05-x)
TEST_USERS = {HR_MANAGER: {"HR Manager", "Employee", "Loan Manager"}, HR_USER: {"HR User", "Employee"}}
TRANSACTIONS = ("Employee Checkin", "Attendance", "Overtime Log")
OPEN_CHECKIN = "open check-in"
NO_OPEN_CHECKIN = "No open check-in found"


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P9-%"]}, pluck="name")
	if employees:
		session_logs = frappe.get_all("Session Log", filters={"employee": ["in", employees]}, pluck="name")
		if session_logs:
			frappe.db.delete("Attendance Log Checkin", {"parent": ["in", session_logs]})
			frappe.db.delete("Session Log", {"name": ["in", session_logs]})
		for doctype in TRANSACTIONS:  # submitted documents: delete_doc would refuse them
			frappe.db.delete(doctype, {"employee": ["in", employees]})
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	for email in frappe.get_all("User", filters={"name": ["like", "p9.%@example.com"]}, pluck="name"):
		frappe.db.delete("User Permission", {"user": email})
		frappe.db.delete("DocShare", {"user": email})
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	frappe.db.commit()


def checkin(employee, time, log_type, **extra):
	return frappe.get_doc(
		{"doctype": "Employee Checkin", "employee": employee, "time": time, "log_type": log_type, **extra}
	)


class TestPhase0CheckinSequence(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		cls.shift_overtime = overtime_off()
		cls.block_hours = frappe.db.get_single_value("Session Log Settings", "missing_checkout_block_hours")
		set_settings(missing_checkout_block_hours=16, require_log_approval=0, hold_missing_checkout=1,
			log_creation_trigger=builder.TRIGGER_ON_CHECKOUT)
		for i, (email, roles) in enumerate(TEST_USERS.items(), start=1):
			make_user(email, roles)
			employee_doc(f"P9 User{i}", f"TEST-P9-USER{i}", None, user_id=email).insert(ignore_permissions=True)
			frappe.clear_cache(user=email)
		cls.counter = 0
		cls.emp1 = cls.new_employee()
		create_user(cls.emp1, email=EMP1, create_user_permission=1)
		frappe.clear_cache(user=EMP1)
		# a past working week, apart from the other tests' dates
		base = getdate(today())
		cls.monday = add_days(base, -base.weekday() - 70)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		set_shift_overtime(cls.shift_overtime)
		set_settings(missing_checkout_block_hours=cls.block_hours or 16)
		cleanup()
		frappe.flags.mute_emails = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_import = False

	@classmethod
	def new_employee(cls):
		"""A fresh employee for each test, so one test's punches never meet another's."""
		cls.counter += 1
		emp = employee_doc(f"P9 Emp{cls.counter}", f"TEST-P9-EMP{cls.counter}", None, default_shift=DEFAULT_SHIFT)
		emp.insert(ignore_permissions=True)
		return emp.name

	def day(self, offset):
		return add_days(self.monday, offset)

	def punch(self, employee, offset, time, log_type, user=HR_USER, **extra):
		frappe.set_user(user)
		try:
			return checkin(employee, f"{self.day(offset)} {time}:00", log_type, **extra).insert()
		finally:
			frappe.set_user("Administrator")

	def assert_refused(self, exc, text, *args, **kwargs):
		with self.assertRaises(exc) as ctx:
			self.punch(*args, **kwargs)
		self.assertIn(text, str(ctx.exception))

	# ---------------------------------------------------------------- 1. IN / OUT alternate
	def test_01_in_after_in_is_refused(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		self.assert_refused(CheckinSequenceError, OPEN_CHECKIN, emp, 0, "10:00", "IN")

	def test_02_out_without_open_in_is_refused(self):
		emp = self.new_employee()
		self.assert_refused(CheckinSequenceError, NO_OPEN_CHECKIN, emp, 0, "17:00", "OUT")  # first log
		self.punch(emp, 0, "09:00", "IN")
		self.punch(emp, 0, "17:00", "OUT")
		self.assert_refused(CheckinSequenceError, NO_OPEN_CHECKIN, emp, 0, "17:30", "OUT")  # OUT after OUT

	def test_03_in_out_in_out_works(self):
		emp = self.new_employee()
		for time, log_type in (("09:00", "IN"), ("13:00", "OUT"), ("14:00", "IN"), ("17:00", "OUT")):
			doc = self.punch(emp, 0, time, log_type)
			self.assertFalse(doc.sequence_warning)
		self.punch(emp, 1, "09:00", "IN")  # next day
		self.punch(emp, 1, "23:30", "OUT")  # 14.5 h: within the 16 h limit

	def test_04_back_dated_logs_checked_at_their_own_time(self):
		emp = self.new_employee()
		self.punch(emp, 1, "09:00", "IN")  # latest log is an open IN
		# the day before: no log before it, so an OUT there has no open IN (although the latest log is an IN)
		self.assert_refused(CheckinSequenceError, NO_OPEN_CHECKIN, emp, 0, "17:00", "OUT")
		# a missing earlier pair can be added, one log at a time
		self.punch(emp, 0, "09:00", "IN")
		self.punch(emp, 0, "17:00", "OUT")
		self.punch(emp, 1, "17:00", "OUT")

	# ---------------------------------------------------------------- 2. missed check-out
	def test_05_missed_checkout_blocks_next_day(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		message = f"Your check-out for {formatdate(self.day(0))} is missing"
		self.assert_refused(MissingCheckoutError, message, emp, 1, "08:55", "IN")
		# checking out the next morning would hide the missed check-out: also refused
		self.assert_refused(MissingCheckoutError, message, emp, 1, "08:55", "OUT")

	def test_06_hr_manager_corrects_and_next_in_is_allowed(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		builder.build_log(emp, self.day(0))  # the daily build holds the log: missing check-out
		log = frappe.get_doc("Session Log", {"employee": emp, "log_date": self.day(0)})
		self.assertEqual((log.status, log.missing_checkout), ("Pending Approval", 1))

		self.assert_refused(MissingCheckoutError, "is missing", emp, 1, "08:55", "IN")
		self.punch(emp, 0, "18:00", "OUT", user=HR_MANAGER)  # the back-dated correction
		self.punch(emp, 1, "08:55", "IN")  # now allowed

		# the corrected log is recalculated and processed (Require Log Approval is off)
		log.reload()
		self.assertEqual((log.missing_checkout, log.working_hours, log.status), (0, 9.0, "Processed"), log.error_log)
		self.assertEqual(str(log.last_out), f"{self.day(0)} 18:00:00")
		self.assertEqual(frappe.db.get_value("Attendance", log.attendance, ["docstatus", "status"]), (1, "Present"))

	def test_07_corrected_log_waits_for_approval_when_required(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		builder.build_log(emp, self.day(0))
		set_settings(require_log_approval=1)
		try:
			self.punch(emp, 0, "17:00", "OUT", user=HR_MANAGER)
		finally:
			set_settings(require_log_approval=0)
		log = frappe.get_doc("Session Log", {"employee": emp, "log_date": self.day(0)})
		self.assertEqual((log.missing_checkout, log.working_hours, log.status), (0, 8.0, "Pending Approval"))
		self.assertIn("Check-out corrected", log.remarks)

	def test_08_hr_manager_not_held_by_limit_but_by_sequence(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		self.assert_refused(CheckinSequenceError, OPEN_CHECKIN, emp, 1, "09:00", "IN", user=HR_MANAGER)
		self.punch(emp, 1, "07:00", "OUT", user=HR_MANAGER)  # 22 h, beyond the limit: HR may

	# ---------------------------------------------------------------- limit
	def test_09_limit_from_settings_and_overtime_type(self):
		emp = self.new_employee()
		in_time = f"{self.day(0)} 09:00:00"
		self.assertEqual(missing_checkout_limit(emp, in_time), (16, getdate(self.day(0))))
		set_settings(missing_checkout_block_hours=20)
		try:
			self.assertEqual(missing_checkout_limit(emp, in_time)[0], 20)
		finally:
			set_settings(missing_checkout_block_hours=16)

		# shift with an Overtime Type maximum: shift hours + maximum overtime
		ot_type = frappe.db.get_value("Overtime Type", {}, "name")
		if not ot_type:
			self.skipTest("no Overtime Type on this site")
		max_before = frappe.db.get_value("Overtime Type", ot_type, "maximum_overtime_hours_allowed")
		set_shift_overtime({DEFAULT_SHIFT: (1, ot_type)})
		frappe.db.set_value("Overtime Type", ot_type, "maximum_overtime_hours_allowed", 2)
		frappe.clear_document_cache("Overtime Type", ot_type)
		try:
			self.assertEqual(missing_checkout_limit(emp, in_time)[0], 10)
			self.punch(emp, 0, "09:00", "IN")
			self.assert_refused(MissingCheckoutError, "is missing", emp, 0, "19:30", "OUT")
			self.punch(emp, 0, "18:30", "OUT")  # 9.5 h
		finally:
			frappe.db.set_value("Overtime Type", ot_type, "maximum_overtime_hours_allowed", max_before)
			frappe.clear_document_cache("Overtime Type", ot_type)
			overtime_off()

	# ---------------------------------------------------------------- 3. device logs / imports
	def test_10_device_log_saved_and_flagged(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		doc = self.punch(emp, 0, "09:01", "IN", device_id="GATE-1")
		self.assertIn(OPEN_CHECKIN, doc.sequence_warning)

	def test_11_biometric_api_saved_and_flagged(self):
		from hrms.hr.doctype.employee_checkin.employee_checkin import add_log_based_on_employee_field

		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		frappe.set_user(HR_USER)
		doc = add_log_based_on_employee_field(emp, f"{self.day(2)} 09:00:00", device_id="GATE-1",
			log_type="IN", employee_fieldname="name")
		self.assertIn("is missing", doc.sequence_warning)

	def test_12_data_import_saved_and_flagged(self):
		emp = self.new_employee()
		frappe.flags.in_import = True
		doc = self.punch(emp, 0, "17:00", "OUT")
		self.assertIn(NO_OPEN_CHECKIN, doc.sequence_warning)

	# ---------------------------------------------------------------- 4. mobile / API
	def test_13_employee_own_punch_via_api(self):
		"""The mobile app inserts through the REST API; the employee's punches get the current time."""
		frappe.set_user(HR_USER)  # an open IN a minute ago (a second one now would be an HRMS duplicate)
		checkin(self.emp1, add_to_date(now_datetime(), minutes=-1), "IN").insert()
		frappe.set_user(EMP1)
		with self.assertRaises(CheckinSequenceError) as ctx:
			frappe.client.insert({"doctype": "Employee Checkin", "employee": self.emp1, "log_type": "IN"})
		self.assertIn(OPEN_CHECKIN, str(ctx.exception))
		frappe.client.insert({"doctype": "Employee Checkin", "employee": self.emp1, "log_type": "OUT"})

	# ---------------------------------------------------------------- 4. punches edited after saving
	def test_14_log_type_set_after_saving_builds_session_log(self):
		"""HR saves the OUT with Log Type empty, then edits it to OUT: the Session Log is built then
		(builder.on_checkin_update), not only when an OUT is first inserted."""
		emp = self.new_employee()
		self.punch(emp, 6, "10:00", "IN")
		out = self.punch(emp, 6, "14:00", "")
		self.assertFalse(frappe.db.exists("Session Log", {"employee": emp, "log_date": self.day(6)}))

		frappe.set_user(HR_USER)
		out.reload()
		out.log_type = "OUT"
		out.save()
		frappe.set_user("Administrator")

		name = frappe.db.exists("Session Log", {"employee": emp, "log_date": self.day(6)})
		self.assertTrue(name)
		self.assertEqual(frappe.db.get_value("Session Log", name, "working_hours"), 4)

	def test_15_punch_moved_to_another_day_builds_that_day(self):
		"""A pair first saved on the wrong date (today's) and then moved to the real date, IN first:
		the log is built for the new date."""
		emp = self.new_employee()
		punch_in = self.punch(emp, 0, "10:00", "IN")
		out = self.punch(emp, 0, "14:00", "OUT")  # builds day 0
		frappe.set_user(HR_MANAGER)
		for doc in (punch_in, out):
			doc.reload()
			doc.time = f"{self.day(5)} {get_datetime(doc.time).strftime('%H:%M:%S')}"
			doc.save()
		frappe.set_user("Administrator")

		name = frappe.db.exists("Session Log", {"employee": emp, "log_date": self.day(5)})
		self.assertTrue(name)
		self.assertEqual(frappe.db.get_value("Session Log", name, "working_hours"), 4)
