# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Auto Create Missing Checkout: the midnight scheduler adds the missing OUT at shift end.

Code: alantech_erp/setup/auto_checkout.py

General Shift 09:00-17:00 (midpoint 13:00). Test days are in the past, so the shift has ended; the
"shift still running" case passes an earlier `now` to create_checkout().
Leave is patched in (get_approved_leave), so no Leave Allocation / workflow is needed here.

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_auto_checkout

Everything created here uses the TEST-PC- employee numbers and is removed in tearDownClass.
Session Log Settings and the shift overtime are restored.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, get_datetime, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.alantech.doctype.session_log import builder
from alantech_erp.setup import auto_checkout as ac
from alantech_erp.setup.shifts import DEFAULT_SHIFT
from alantech_erp.tests.test_phase0_employee_user import employee_doc
from alantech_erp.tests.test_phase0_session_log import overtime_off, set_settings, set_shift_overtime

DT = "Employee Checkin"
TRANSACTIONS = (DT, "Attendance", "Overtime Log")
LEAVE_PATCH = "alantech_erp.setup.auto_checkout.get_approved_leave"
NIGHT_SHIFT = "TEST-PC Night Shift"


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-PC-%"]}, pluck="name")
	if employees:
		session_logs = frappe.get_all("Session Log", filters={"employee": ["in", employees]}, pluck="name")
		if session_logs:
			frappe.db.delete("Attendance Log Checkin", {"parent": ["in", session_logs]})
			frappe.db.delete("Session Log", {"name": ["in", session_logs]})
		for doctype in TRANSACTIONS:  # submitted documents: delete_doc would refuse them
			frappe.db.delete(doctype, {"employee": ["in", employees]})
		frappe.db.delete("Comment", {"reference_doctype": DT, "comment_type": "Comment", "content": ["like", f"%{ac.NOTE}%"]})
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	if frappe.db.exists("Shift Type", NIGHT_SHIFT):  # after the employees: they link to it
		frappe.delete_doc("Shift Type", NIGHT_SHIFT, force=1, ignore_permissions=True)
	frappe.db.commit()


class TestAutoCheckoutLogic(TestCase):
	"""get_checkout_time / is_half_day: no database needed."""

	def window(self):
		return frappe._dict(start=get_datetime("2026-01-05 09:00:00"), end=get_datetime("2026-01-05 17:00:00"))

	def leave(self, half_day=1, half_day_date=None):
		return frappe._dict(leave_type="Casual Leave", half_day=half_day, half_day_date=half_day_date)

	def at(self, time):
		return get_datetime(f"2026-01-05 {time}:00")

	def test_no_leave_is_shift_end(self):
		self.assertEqual(ac.get_checkout_time(self.at("09:30"), self.window(), None, "2026-01-05"), self.at("17:00"))

	def test_full_day_leave_gives_nothing(self):
		leave = self.leave(half_day=0)
		self.assertIsNone(ac.get_checkout_time(self.at("10:00"), self.window(), leave, "2026-01-05"))

	def test_half_day_morning_in_leaves_at_midpoint(self):
		leave = self.leave(half_day=1, half_day_date="2026-01-05")
		self.assertEqual(ac.get_checkout_time(self.at("10:00"), self.window(), leave, "2026-01-05"), self.at("13:00"))

	def test_half_day_afternoon_in_leaves_at_shift_end(self):
		leave = self.leave(half_day=1, half_day_date="2026-01-05")
		for time in ("13:00", "14:00"):
			self.assertEqual(ac.get_checkout_time(self.at(time), self.window(), leave, "2026-01-05"), self.at("17:00"))

	def test_half_day_on_another_date_is_a_full_day_leave_today(self):
		leave = self.leave(half_day=1, half_day_date="2026-01-06")
		self.assertIsNone(ac.get_checkout_time(self.at("10:00"), self.window(), leave, "2026-01-05"))


class TestAutoCheckout(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		frappe.get_doc(  # 22:00-06:00 night shift; cleanup() removes it
			{"doctype": "Shift Type", "__newname": NIGHT_SHIFT, "start_time": "22:00:00", "end_time": "06:00:00"}
		).insert(ignore_permissions=True)
		cls.shift_overtime = overtime_off()
		frappe.clear_cache()
		cls.settings = frappe.db.get_value(
			"Session Log Settings", None, ["require_log_approval", "log_creation_trigger", "auto_create_missing_checkout"],
			as_dict=True,
		)
		set_settings(require_log_approval=0, log_creation_trigger=builder.TRIGGER_ON_CHECKOUT, auto_create_missing_checkout=1)
		cls.counter = 0
		base = getdate(today())
		cls.monday = add_days(base, -base.weekday() - 77)  # a past week, apart from the other tests' dates
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		set_shift_overtime(cls.shift_overtime)
		set_settings(**{k: v for k, v in cls.settings.items() if v is not None})
		cleanup()
		frappe.flags.mute_emails = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------- helpers
	@classmethod
	def new_employee(cls, shift=DEFAULT_SHIFT):
		cls.counter += 1
		extra = {"default_shift": shift} if shift else {}
		emp = employee_doc(f"PC Emp{cls.counter}", f"TEST-PC-EMP{cls.counter}", None, **extra)
		emp.insert(ignore_permissions=True)
		if not shift:  # make sure nothing filled a default shift in
			frappe.db.set_value("Employee", emp.name, "default_shift", None)
		return emp.name

	def day(self, offset=0):
		return add_days(self.monday, offset)

	def punch(self, employee, offset, time, log_type):
		return frappe.get_doc(
			{"doctype": DT, "employee": employee, "time": f"{self.day(offset)} {time}:00", "log_type": log_type}
		).insert(ignore_permissions=True)

	def run_job(self, employee, offset=0, now_time="23:00"):
		"""create_checkout() as the scheduler calls it, with `now` on the test day."""
		ac.create_checkout(employee, get_datetime(f"{self.day(offset)} {now_time}:00"))

	def auto_outs(self, employee):
		return frappe.get_all(
			DT, filters={"employee": employee, "alt_auto_created": 1}, fields=["name", "time", "log_type"], order_by="time"
		)

	def at(self, offset, time):
		return get_datetime(f"{self.day(offset)} {time}:00")

	# ---------------------------------------------------------------- tests
	def test_01_last_in_gets_out_at_shift_end(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:30", "IN")
		self.run_job(emp)
		outs = self.auto_outs(emp)
		self.assertEqual(len(outs), 1)
		self.assertEqual((outs[0].log_type, get_datetime(outs[0].time)), ("OUT", self.at(0, "17:00")))

	def test_02_audit_comment_is_added(self):
		emp = self.new_employee()
		self.punch(emp, 1, "09:30", "IN")
		self.run_job(emp, 1)
		name = self.auto_outs(emp)[0].name
		self.assertTrue(
			frappe.db.exists("Comment", {"reference_doctype": DT, "reference_name": name, "content": ["like", f"%{ac.NOTE}%"]})
		)

	def test_03_last_out_is_left_alone(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		self.punch(emp, 0, "16:00", "OUT")
		self.run_job(emp)
		self.assertEqual(self.auto_outs(emp), [])

	def test_04_no_checkin_creates_nothing(self):
		emp = self.new_employee()
		self.run_job(emp)
		self.assertEqual(frappe.db.count(DT, {"employee": emp}), 0)

	def test_05_multiple_pairs_only_unpaired_last_in_gets_out(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:00", "IN")
		self.punch(emp, 0, "12:00", "OUT")
		self.punch(emp, 0, "13:00", "IN")
		self.run_job(emp)
		outs = self.auto_outs(emp)
		self.assertEqual(len(outs), 1)
		self.assertEqual(get_datetime(outs[0].time), self.at(0, "17:00"))
		self.assertEqual(frappe.db.count(DT, {"employee": emp}), 4)

	def test_06_rerun_creates_no_duplicate(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:30", "IN")
		self.run_job(emp)
		self.run_job(emp)
		self.run_job(emp)
		self.assertEqual(len(self.auto_outs(emp)), 1)
		self.assertEqual(frappe.db.count(DT, {"employee": emp}), 2)

	def test_07_no_shift_is_skipped(self):
		emp = self.new_employee(shift=None)
		self.punch(emp, 0, "09:30", "IN")
		self.run_job(emp)
		self.assertEqual(self.auto_outs(emp), [])

	def test_08_shift_still_running_waits(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:30", "IN")
		self.run_job(emp, now_time="15:00")  # shift ends 17:00
		self.assertEqual(self.auto_outs(emp), [])
		self.run_job(emp, now_time="17:30")  # next run, shift is over
		self.assertEqual(len(self.auto_outs(emp)), 1)

	def test_09_in_after_shift_end_is_skipped(self):
		emp = self.new_employee()
		self.punch(emp, 0, "18:00", "IN")
		self.run_job(emp)
		self.assertEqual(self.auto_outs(emp), [])

	def test_10_half_day_leave_morning_in_gets_midpoint(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:30", "IN")
		leave = frappe._dict(leave_type="Casual Leave", half_day=1, half_day_date=self.day(0))
		with patch(LEAVE_PATCH, return_value=leave):
			self.run_job(emp)
		self.assertEqual(get_datetime(self.auto_outs(emp)[0].time), self.at(0, "13:00"))

	def test_11_half_day_leave_afternoon_in_gets_shift_end(self):
		emp = self.new_employee()
		self.punch(emp, 0, "13:30", "IN")
		leave = frappe._dict(leave_type="Casual Leave", half_day=1, half_day_date=self.day(0))
		with patch(LEAVE_PATCH, return_value=leave):
			self.run_job(emp)
		self.assertEqual(get_datetime(self.auto_outs(emp)[0].time), self.at(0, "17:00"))

	def test_12_full_day_leave_creates_nothing(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:30", "IN")
		leave = frappe._dict(leave_type="Casual Leave", half_day=0, half_day_date=None)
		with patch(LEAVE_PATCH, return_value=leave):
			self.run_job(emp)
		self.assertEqual(self.auto_outs(emp), [])

	def test_13_setting_off_scheduler_does_nothing(self):
		emp = self.new_employee()
		self.punch(emp, 0, "09:30", "IN")
		set_settings(auto_create_missing_checkout=0)
		try:
			ac.auto_create_missing_checkout()
		finally:
			set_settings(auto_create_missing_checkout=1)
		self.assertEqual(self.auto_outs(emp), [])

	def test_14_auto_out_rebuilds_session_log(self):
		emp = self.new_employee()
		self.punch(emp, 2, "09:30", "IN")
		self.run_job(emp, 2)
		log = frappe.db.get_value(
			"Session Log", {"employee": emp, "log_date": self.day(2)}, ["missing_checkout", "last_out"], as_dict=True
		)
		self.assertIsNotNone(log, "no Session Log was built from the auto check-out")
		self.assertEqual(log.missing_checkout, 0)
		self.assertEqual(get_datetime(log.last_out), self.at(2, "17:00"))

	# ------------------------------------------------ night shift (22:00 to 06:00 next morning)
	def test_15_night_shift_waits_for_shift_end_then_creates_out(self):
		emp = self.new_employee(shift=NIGHT_SHIFT)
		self.punch(emp, 3, "22:00", "IN")
		self.run_job(emp, 4, "00:00")  # the midnight run: shift still going
		self.assertEqual(self.auto_outs(emp), [])
		self.run_job(emp, 4, "05:59")  # one minute before the end
		self.assertEqual(self.auto_outs(emp), [])
		self.run_job(emp, 4, "13:00")  # a later run: shift is over
		outs = self.auto_outs(emp)
		self.assertEqual(len(outs), 1)
		self.assertEqual((outs[0].log_type, get_datetime(outs[0].time)), ("OUT", self.at(4, "06:00")))

	def test_16_night_shift_rerun_creates_no_duplicate(self):
		emp = self.new_employee(shift=NIGHT_SHIFT)
		self.punch(emp, 3, "22:00", "IN")
		self.run_job(emp, 4, "13:00")
		self.run_job(emp, 4, "13:00")
		self.run_job(emp, 5, "00:00")  # the next midnight run
		self.assertEqual(len(self.auto_outs(emp)), 1)
		self.assertEqual(frappe.db.count(DT, {"employee": emp}), 2)

	def test_17_night_shift_late_in_after_midnight_uses_the_same_shift(self):
		emp = self.new_employee(shift=NIGHT_SHIFT)
		self.punch(emp, 4, "00:30", "IN")  # 30 minutes late for the shift that started on day 3
		self.run_job(emp, 4, "13:00")
		outs = self.auto_outs(emp)
		self.assertEqual(len(outs), 1)
		self.assertEqual(get_datetime(outs[0].time), self.at(4, "06:00"))  # not 06:00 on day 5

	def test_18_night_shift_auto_out_rebuilds_session_log(self):
		emp = self.new_employee(shift=NIGHT_SHIFT)
		self.punch(emp, 3, "22:00", "IN")
		self.run_job(emp, 4, "13:00")
		log = frappe.db.get_value(
			"Session Log", {"employee": emp, "log_date": self.day(3)}, ["missing_checkout", "last_out"], as_dict=True
		)
		self.assertIsNotNone(log, "no Session Log was built for the night shift")
		self.assertEqual(log.missing_checkout, 0)
		self.assertEqual(get_datetime(log.last_out), self.at(4, "06:00"))