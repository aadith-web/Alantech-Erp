# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Unit tests for the Session Log calculation (calculation.py; HR-F02 Attendance Management,
ClickUp 14yr2e56cae): shift window, first IN / last OUT, working hours, late entry / early exit,
missing check-out, attendance status and overtime hours.

No records are created: shifts, check-ins and logs are in-memory dicts. The end-to-end flow
(check-out -> Session Log -> Attendance) is covered by tests/test_phase0_session_log.py, the shift
overtime modes by tests/test_phase0_shift_ot_modes.py.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.session_log.test_session_log_calculation
"""

from datetime import datetime

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.alantech.doctype.session_log.calculation import (
	MISSING_CHECKOUT_STATUS,
	get_overtime_hours,
	get_shift_window,
	get_status,
	outside_shift_hours,
	round_down_hours,
	set_times,
)

DAY = "2026-03-02"  # a Monday


def at(time, day=DAY):
	return datetime.fromisoformat(f"{day} {time}")


def shift(start="09:00:00", end="17:00:00", before=60, after=300, **extra):
	"""General Shift as setup/shifts.py creates it (60 min before, 300 min after, 15 min grace)."""
	values = dict(
		name="Unit Shift",
		start_time=start,
		end_time=end,
		begin_check_in_before_shift_start_time=before,
		allow_check_out_after_shift_end_time=after,
		enable_late_entry_marking=1,
		late_entry_grace_period=15,
		enable_early_exit_marking=1,
		early_exit_grace_period=15,
		working_hours_threshold_for_half_day=4,
		working_hours_threshold_for_absent=2,
	)
	values.update(extra)
	return frappe._dict(values)


def punches(*pairs, day=DAY):
	return [frappe._dict(time=at(t, day), log_type=lt) for t, lt in pairs]


def times(logs, sh=None, session_no=None):
	sh = sh or shift()
	doc = frappe._dict()
	if session_no:
		doc.session_no = session_no
	set_times(doc, logs, sh, get_shift_window(DAY, sh))
	return doc


class UnitTestShiftWindow(UnitTestCase):
	def test_day_shift(self):
		w = get_shift_window(DAY, shift())
		self.assertEqual((w.start, w.end), (at("09:00:00"), at("17:00:00")))
		self.assertEqual(w.actual_start, at("08:00:00"))  # check-in 60 min before
		self.assertEqual(w.actual_end, at("22:00:00"))  # check-out 300 min after

	def test_night_shift_ends_next_day(self):
		w = get_shift_window(DAY, shift("22:00:00", "06:00:00", before=30, after=60))
		self.assertEqual(w.start, at("22:00:00"))
		self.assertEqual(w.end, at("06:00:00", "2026-03-03"))
		self.assertEqual(w.actual_end, at("07:00:00", "2026-03-03"))

	def test_24_hour_shift_stored_as_0859(self):
		w = get_shift_window(DAY, shift("09:00:00", "08:59:00", before=0, after=0))
		self.assertEqual(w.end, at("09:00:00", "2026-03-03"))  # a full 24 hours

	def test_no_shift_is_the_whole_day(self):
		w = get_shift_window(DAY, None)
		self.assertIsNone(w.start)
		self.assertEqual(w.actual_start, at("00:00:00"))
		self.assertEqual(w.actual_end, at("23:59:59"))


class UnitTestTimes(UnitTestCase):
	def test_first_in_last_out_and_hours(self):
		logs = punches(("09:00:00", "IN"), ("13:00:00", "OUT"), ("13:30:00", "IN"), ("17:45:00", "OUT"))
		doc = times(logs)  # Session 1: its own IN-OUT pair
		self.assertEqual((doc.first_in, doc.last_out), (at("09:00:00"), at("13:00:00")))
		self.assertEqual(doc.working_hours, 4)
		self.assertEqual(doc.total_working_hours, 8.25)  # the break is not counted
		self.assertEqual(doc.day_last_out, at("17:45:00"))
		self.assertEqual((doc.missing_checkout, doc.late_entry, doc.early_exit), (0, 0, 0))

	def test_each_in_out_pair_is_a_session(self):
		logs = punches(("09:00:00", "IN"), ("11:00:00", "OUT"), ("14:00:00", "IN"), ("18:00:00", "OUT"))
		first, second = times(logs, session_no=1), times(logs, session_no=2)
		self.assertEqual((first.first_in, first.last_out, first.working_hours), (at("09:00:00"), at("11:00:00"), 2))
		self.assertEqual((second.first_in, second.last_out, second.working_hours), (at("14:00:00"), at("18:00:00"), 4))
		self.assertEqual((first.total_working_hours, second.total_working_hours), (6, 6))  # 2 h + 4 h

	def test_open_last_session_is_a_missing_checkout(self):
		logs = punches(("09:00:00", "IN"), ("11:00:00", "OUT"), ("14:00:00", "IN"))
		first, second = times(logs, session_no=1), times(logs, session_no=2)
		self.assertEqual((first.missing_checkout, second.missing_checkout), (0, 1))
		self.assertEqual((first.day_missing_checkout, first.total_working_hours), (1, 2))
		self.assertEqual(first.early_exit, 0)  # not known until the day is closed

	def test_late_entry_and_early_exit_belong_to_session_1(self):
		logs = punches(("09:16:00", "IN"), ("12:00:00", "OUT"), ("13:00:00", "IN"), ("16:44:00", "OUT"))
		self.assertEqual((times(logs, session_no=1).late_entry, times(logs, session_no=1).early_exit), (1, 1))
		self.assertEqual((times(logs, session_no=2).late_entry, times(logs, session_no=2).early_exit), (0, 0))

	def test_missing_checkout(self):
		doc = times(punches(("09:00:00", "IN")))
		self.assertEqual(doc.missing_checkout, 1)
		self.assertIsNone(doc.last_out)
		self.assertEqual(doc.working_hours, 0)

	def test_out_before_in_counts_as_missing_checkout(self):
		doc = times(punches(("08:30:00", "OUT"), ("09:00:00", "IN")))
		self.assertEqual(doc.missing_checkout, 1)
		self.assertIsNone(doc.last_out)

	def test_no_punches(self):
		doc = times([])
		self.assertIsNone(doc.first_in)
		self.assertEqual((doc.missing_checkout, doc.working_hours), (0, 0))

	def test_device_without_log_type_uses_first_and_last_punch(self):
		doc = times(punches(("09:05:00", ""), ("12:00:00", ""), ("17:05:00", "")))
		self.assertEqual((doc.first_in, doc.last_out), (at("09:05:00"), at("17:05:00")))
		self.assertEqual(times(punches(("09:05:00", ""))).missing_checkout, 1)

	def test_late_entry_after_grace_period(self):
		self.assertEqual(times(punches(("09:15:00", "IN"), ("17:00:00", "OUT"))).late_entry, 0)
		self.assertEqual(times(punches(("09:16:00", "IN"), ("17:00:00", "OUT"))).late_entry, 1)

	def test_early_exit_before_grace_period(self):
		self.assertEqual(times(punches(("09:00:00", "IN"), ("16:45:00", "OUT"))).early_exit, 0)
		self.assertEqual(times(punches(("09:00:00", "IN"), ("16:44:00", "OUT"))).early_exit, 1)

	def test_marking_switched_off_on_shift(self):
		sh = shift(enable_late_entry_marking=0, enable_early_exit_marking=0)
		doc = times(punches(("11:00:00", "IN"), ("12:00:00", "OUT")), sh)
		self.assertEqual((doc.late_entry, doc.early_exit), (0, 0))


class UnitTestStatus(UnitTestCase):
	def status(self, sh=None, leave=None, **doc):
		values = {"log_date": DAY, "first_in": at("09:00:00"), "missing_checkout": 0, "working_hours": 8}
		values.update(doc)
		return get_status(frappe._dict(values), sh if sh is not None else shift(), leave)

	def test_present(self):
		self.assertEqual(self.status(), ("Present", None))

	def test_absent_without_check_in(self):
		self.assertEqual(self.status(first_in=None, working_hours=0), ("Absent", None))

	def test_missing_checkout_is_half_day(self):
		self.assertEqual(self.status(missing_checkout=1, working_hours=0), (MISSING_CHECKOUT_STATUS, None))

	def test_shift_hour_thresholds(self):
		self.assertEqual(self.status(working_hours=1.99)[0], "Absent")  # below 2 h
		self.assertEqual(self.status(working_hours=3.5)[0], "Half Day")  # below 4 h
		self.assertEqual(self.status(working_hours=4)[0], "Present")

	def test_no_thresholds_without_shift(self):
		self.assertEqual(self.status(sh=False, working_hours=0.5)[0], "Present")

	def test_approved_leave(self):
		leave = frappe._dict(leave_type="Casual Leave", half_day=0, half_day_date=None)
		self.assertEqual(self.status(leave=leave, first_in=None), ("On Leave", "Casual Leave"))

	def test_half_day_leave_only_on_its_date(self):
		leave = frappe._dict(leave_type="Casual Leave", half_day=1, half_day_date=DAY)
		self.assertEqual(self.status(leave=leave), ("Half Day", "Casual Leave"))
		leave.half_day_date = "2026-03-03"  # half day is another day of a longer leave
		self.assertEqual(self.status(leave=leave), ("On Leave", "Casual Leave"))


class UnitTestOvertimeHours(UnitTestCase):
	RULE = frappe._dict(applicable_for_weekend=1, applicable_for_public_holiday=0, maximum_overtime_hours_allowed=0)

	def ot(self, first, last, day_type="Working Day", rule=None, **shift_fields):
		sh = shift(**{"early_checkin_mode": "OT", "late_checkout_mode": "OT", **shift_fields})
		doc = frappe._dict(day_type=day_type, first_in=at(first), last_out=at(last))
		doc.working_hours = round((doc.last_out - doc.first_in).total_seconds() / 3600, 2)
		return get_overtime_hours(doc, rule or self.RULE, get_shift_window(DAY, sh), sh)

	def test_fixed_shift_early_and_late(self):
		self.assertEqual(self.ot("08:30:00", "19:00:00"), 2.5)

	def test_no_overtime_inside_shift_or_without_hours(self):
		self.assertEqual(self.ot("09:00:00", "17:00:00"), 0)
		doc = frappe._dict(day_type="Working Day", working_hours=0, first_in=None, last_out=None)
		self.assertEqual(get_overtime_hours(doc, self.RULE, get_shift_window(DAY, shift()), shift()), 0)

	def test_weekly_off_and_holiday_follow_the_rule(self):
		self.assertEqual(self.ot("10:00:00", "14:00:00", day_type="Weekly Off"), 4)
		self.assertEqual(self.ot("10:00:00", "14:00:00", day_type="Holiday"), 0)  # not applicable

	def test_flexible_short_day_is_not_negative(self):
		self.assertEqual(self.ot("09:00:00", "14:00:00", work_mode="Flexible Threshold", regular_hours_per_day=8), 0)

	def test_maximum_then_rounding(self):
		rule = frappe._dict(self.RULE, maximum_overtime_hours_allowed=2.2)
		self.assertEqual(self.ot("09:00:00", "20:00:00", rule=rule, round_ot_minutes_to="30"), 2)

	def test_outside_shift_needs_both_punches(self):
		window = get_shift_window(DAY, shift())
		settings = frappe._dict(early_checkin_ot=True, late_checkout_ot=True)
		self.assertEqual(outside_shift_hours(frappe._dict(first_in=at("08:00:00"), last_out=None), window, settings), 0)

	def test_whole_day_before_shift_counts_once(self):
		window = get_shift_window(DAY, shift())
		settings = frappe._dict(early_checkin_ot=True, late_checkout_ot=True)
		doc = frappe._dict(first_in=at("08:00:00"), last_out=at("08:45:00"))
		self.assertEqual(outside_shift_hours(doc, window, settings), 0.75)


class UnitTestRounding(UnitTestCase):
	def test_round_down(self):
		self.assertEqual(round_down_hours(52 / 60, 0), 0.87)
		self.assertEqual(round_down_hours(52 / 60, 15), 0.75)
		self.assertEqual(round_down_hours(52 / 60, 30), 0.5)
		self.assertEqual(round_down_hours(52 / 60, 60), 0)
		self.assertEqual(round_down_hours(2.5, 30), 2.5)  # already a multiple

	def test_floating_point_edge(self):
		self.assertEqual(round_down_hours(0.1, 6), 0.1)  # 0.1 h is 5.999999 min in floating point
