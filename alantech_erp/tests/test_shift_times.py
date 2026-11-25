# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Shift Type: 24-hour and overnight shifts can be saved (setup/shift_times.py, ClickUp 14yr2e58jzh).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_shift_times

Unit: shift length (next day when the end is at or before the start) and fitting the check-in /
check-out buffers under 24 hours. Integration: the reported steps (09:00 to 09:00, On-Site, default
buffers) save as 09:00-08:59 with buffers 0 and the Session Log window is 24 hours; 09:00-08:59 typed
directly saves; an overnight shift keeps its buffers; a day shift is unchanged.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import get_time

from alantech_erp.setup.shift_times import fit_buffers, shift_minutes

PREFIX = "_Test Shift Times"


class UnitTestShiftTimes(UnitTestCase):
	def test_shift_minutes(self):
		self.assertEqual(shift_minutes("09:00:00", "17:00:00"), 480)
		self.assertEqual(shift_minutes("21:00:00", "06:00:00"), 540)  # next day
		self.assertEqual(shift_minutes("09:00:00", "08:59:00"), 1439)
		self.assertEqual(shift_minutes("09:00:00", "09:00:00"), 1440)

	def test_fit_buffers(self):
		self.assertEqual(fit_buffers(480, 60, 60), (60, 60))  # fits: unchanged
		self.assertEqual(fit_buffers(1439, 60, 60), (0, 0))  # 24-hour shift
		self.assertEqual(fit_buffers(1320, 60, 60), (60, 59))  # 22 h: after reduced first
		self.assertEqual(fit_buffers(1380, 90, 60), (59, 0))


class IntegrationTestShiftTimes(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("shift_times")
		self.addCleanup(frappe.db.rollback, save_point="shift_times")

	def make(self, start, end, **values):
		return frappe.get_doc({
			"doctype": "Shift Type",
			"name": f"{PREFIX} {frappe.generate_hash(length=5)}",
			"start_time": start,
			"end_time": end,
			"work_mode": "Fixed Shift",
			**values,
		}).insert()

	def test_reported_24_hour_shift_saves(self):
		doc = self.make("09:00:00", "09:00:00")  # default buffers 60 / 60, as in the report
		self.assertEqual(get_time(doc.end_time), get_time("08:59:00"))
		self.assertEqual((doc.begin_check_in_before_shift_start_time, doc.allow_check_out_after_shift_end_time), (0, 0))

		from alantech_erp.alantech.doctype.session_log.calculation import get_shift_window

		window = get_shift_window("2026-11-25", doc)
		self.assertEqual((window.end - window.start).total_seconds(), 24 * 3600)

	def test_end_one_minute_before_start_saves(self):
		doc = self.make("09:00:00", "08:59:00")
		self.assertEqual((doc.begin_check_in_before_shift_start_time, doc.allow_check_out_after_shift_end_time), (0, 0))

	def test_overnight_and_day_shifts_keep_buffers(self):
		night = self.make("21:00:00", "06:00:00", begin_check_in_before_shift_start_time=60,
			allow_check_out_after_shift_end_time=120)
		self.assertEqual((night.begin_check_in_before_shift_start_time, night.allow_check_out_after_shift_end_time), (60, 120))
		day = self.make("09:00:00", "17:00:00")
		self.assertEqual(get_time(day.end_time), get_time("17:00:00"))
		self.assertEqual((day.begin_check_in_before_shift_start_time, day.allow_check_out_after_shift_end_time), (60, 60))

	def test_long_shift_buffers_fitted(self):
		doc = self.make("06:00:00", "04:00:00")  # 22 hours with 60 / 60
		self.assertEqual((doc.begin_check_in_before_shift_start_time, doc.allow_check_out_after_shift_end_time), (60, 59))
