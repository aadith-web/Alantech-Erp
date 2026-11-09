# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Unit tests for the Employee Checkin rules (setup/checkin_validation.py; HR-F02 Attendance
Management, ClickUp 14yr2e56cae / 14yr2e57879): IN / OUT alternation, the missed check-out limit and
which punches are flagged instead of refused.

The previous punch, the shift and the settings are mocked; nothing is saved. Real punches by real
users are covered by tests/test_phase0_checkin_sequence.py.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_unit_checkin_rules
"""

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.alantech.doctype.session_log import builder
from alantech_erp.setup import checkin_validation as cv

MODULE = "alantech_erp.setup.checkin_validation"


def at(value):
	return datetime.fromisoformat(value)


def punch(time, log_type, **extra):
	values = dict(employee="EMP-UNIT", time=at(time), log_type=log_type, device_id=None)
	values.update(extra)
	return frappe._dict(values)


def previous(time, log_type):
	return frappe._dict(name="PREV", time=at(time), log_type=log_type)


class UnitTestSequenceRules(UnitTestCase):
	def problem(self, doc, prev, limit=16, hr=False):
		with patch(f"{MODULE}.previous_log", return_value=prev), patch(
			f"{MODULE}.can_skip_missing_checkout_limit", return_value=hr
		), patch(f"{MODULE}.missing_checkout_limit", return_value=(limit, at("2026-03-02 09:00:00").date())):
			return cv.get_sequence_problem(doc)

	def test_first_in_allowed(self):
		self.assertIsNone(self.problem(punch("2026-03-02 09:00:00", "IN"), None))

	def test_in_out_alternate(self):
		self.assertIsNone(self.problem(punch("2026-03-02 17:00:00", "OUT"), previous("2026-03-02 09:00:00", "IN")))
		self.assertIsNone(self.problem(punch("2026-03-03 09:00:00", "IN"), previous("2026-03-02 17:00:00", "OUT")))

	def test_in_after_open_in_refused(self):
		message, exc = self.problem(punch("2026-03-02 10:00:00", "IN"), previous("2026-03-02 09:00:00", "IN"))
		self.assertIs(exc, cv.CheckinSequenceError)
		self.assertIn("You have an open check-in at", message)

	def test_out_without_open_in_refused(self):
		for prev in (None, previous("2026-03-02 12:00:00", "OUT")):
			message, exc = self.problem(punch("2026-03-02 17:00:00", "OUT"), prev)
			self.assertIs(exc, cv.CheckinSequenceError)
			self.assertIn("No open check-in found", message)

	def test_missed_checkout_blocks_in_and_out(self):
		prev = previous("2026-03-02 09:00:00", "IN")
		for log_type in ("IN", "OUT"):
			message, exc = self.problem(punch("2026-03-03 09:00:00", log_type), prev, limit=16)
			self.assertIs(exc, cv.MissingCheckoutError)
			self.assertIn("Your check-out for", message)
			self.assertIn("is missing", message)

	def test_limit_is_exclusive(self):
		prev = previous("2026-03-02 09:00:00", "IN")
		self.assertIsNone(self.problem(punch("2026-03-03 01:00:00", "OUT"), prev, limit=16))  # exactly 16 h
		self.assertTrue(self.problem(punch("2026-03-03 01:01:00", "OUT"), prev, limit=16))

	def test_hr_correction_not_held_by_limit_but_by_sequence(self):
		prev = previous("2026-03-02 09:00:00", "IN")
		self.assertIsNone(self.problem(punch("2026-03-04 09:00:00", "OUT"), prev, hr=True))
		message, exc = self.problem(punch("2026-03-04 09:00:00", "IN"), prev, hr=True)
		self.assertIs(exc, cv.CheckinSequenceError)


class UnitTestValidateHook(UnitTestCase):
	def run_validate(self, doc, problem):
		doc.is_new = lambda: True
		doc.meta = frappe._dict(has_field=lambda f: True)
		doc.set = lambda field, value: doc.__setitem__(field, value)
		with patch(f"{MODULE}.get_sequence_problem", return_value=problem):
			cv.validate(doc)
		return doc

	def test_refused_with_title(self):
		problem = ("No open check-in found.", cv.CheckinSequenceError)
		with self.assertRaises(cv.CheckinSequenceError):
			self.run_validate(punch("2026-03-02 17:00:00", "OUT"), problem)

	def test_device_punch_saved_with_warning(self):
		doc = self.run_validate(punch("2026-03-02 17:00:00", "OUT", device_id="GATE-1"), ("No open check-in found.",
			cv.CheckinSequenceError))
		self.assertEqual(doc.sequence_warning, "No open check-in found.")

	def test_import_saved_with_warning(self):
		frappe.flags.in_import = True
		try:
			doc = self.run_validate(punch("2026-03-02 17:00:00", "OUT"), ("Your check-out is missing.",
				cv.MissingCheckoutError))
		finally:
			frappe.flags.in_import = False
		self.assertEqual(doc.sequence_warning, "Your check-out is missing.")

	def test_warning_cleared_when_sequence_is_fine(self):
		doc = punch("2026-03-02 17:00:00", "OUT", sequence_warning="old")
		self.assertIsNone(self.run_validate(doc, None).sequence_warning)

	def test_other_log_types_ignored(self):
		doc = punch("2026-03-02 17:00:00", "")
		with patch(f"{MODULE}.get_sequence_problem") as check:
			cv.validate(doc)
		check.assert_not_called()


class UnitTestMissingCheckoutLimit(UnitTestCase):
	def limit(self, start, end, max_ot=0, fallback=16, **shift_fields):
		sh = frappe._dict(start_time=start, end_time=end, begin_check_in_before_shift_start_time=60,
			allow_check_out_after_shift_end_time=60, **shift_fields)
		rule = frappe._dict(maximum_overtime_hours_allowed=max_ot) if max_ot is not None else None
		with patch.object(builder, "shift_day", return_value=at("2026-03-02 00:00:00").date()), patch(
			f"{MODULE}.get_shift", return_value=sh
		), patch(f"{MODULE}.get_overtime_rule", return_value=rule), patch(
			f"{MODULE}.get_session_log_settings", return_value=frappe._dict(missing_checkout_block_hours=fallback)
		):
			return cv.missing_checkout_limit("EMP-UNIT", at("2026-03-02 09:00:00"))[0]

	def test_shift_plus_maximum_overtime(self):
		self.assertEqual(self.limit("09:00:00", "17:00:00", max_ot=4), 12)

	def test_settings_fallback_without_maximum(self):
		self.assertEqual(self.limit("09:00:00", "17:00:00", max_ot=0, fallback=16), 16)
		self.assertEqual(self.limit("09:00:00", "17:00:00", max_ot=None, fallback=10), 10)

	def test_never_shorter_than_the_shift(self):
		self.assertEqual(self.limit("09:00:00", "08:59:00", max_ot=0, fallback=16), 24)  # 24 hour shift

	def test_flexible_uses_regular_hours(self):
		limit = self.limit("09:00:00", "17:00:00", max_ot=3, work_mode="Flexible Threshold", regular_hours_per_day=9)
		self.assertEqual(limit, 12)
