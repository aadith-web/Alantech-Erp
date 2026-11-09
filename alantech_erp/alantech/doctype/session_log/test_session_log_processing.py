# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Unit tests for Session Log processing, approval helpers, settings defaults and the shift day of
a punch (processing.py, approval.py, builder.py, session_log_settings.py; HR-F02 Attendance
Management, ClickUp 14yr2e56cae).

Database reads are replaced with mocks; nothing is saved. Creating the Attendance / Overtime Log
and the approve / reject / reopen actions are covered end to end by tests/test_phase0_session_log.py
and tests/test_phase0_overtime.py.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.session_log.test_session_log_processing
"""

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.alantech.doctype.session_log import builder, processing
from alantech_erp.alantech.doctype.session_log.approval import parse_names
from alantech_erp.alantech.doctype.session_log_settings import session_log_settings
from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import (
	DEFAULT_APPROVER_ROLE,
	DEFAULT_MISSING_CHECKOUT_HOURS,
	TRIGGER_ON_CHECKOUT,
	get_session_log_settings,
)

PROCESSING = "alantech_erp.alantech.doctype.session_log.processing"


def settings(**values):
	base = dict(require_log_approval=False, hold_missing_checkout=True)
	base.update(values)
	return frappe._dict(base)


class UnitTestInitialStatus(UnitTestCase):
	def status(self, missing_checkout=0, **values):
		log = frappe._dict(missing_checkout=missing_checkout, remarks=None)
		with patch(f"{PROCESSING}.get_session_log_settings", return_value=settings(**values)):
			return processing.initial_status(log), log.remarks

	def test_approval_off_is_draft(self):
		self.assertEqual(self.status()[0], "Draft")

	def test_approval_on_is_pending(self):
		self.assertEqual(self.status(require_log_approval=True)[0], "Pending Approval")

	def test_missing_checkout_held_for_review(self):
		status, remarks = self.status(missing_checkout=1)
		self.assertEqual(status, "Pending Approval")
		self.assertIn("Held for review: missing check-out.", remarks)

	def test_missing_checkout_not_held_when_switched_off(self):
		self.assertEqual(self.status(missing_checkout=1, hold_missing_checkout=False)[0], "Draft")


class UnitTestRemarks(UnitTestCase):
	def test_add_remark_once_on_new_lines(self):
		log = frappe._dict(remarks=None)
		processing.add_remark(log, "First")
		processing.add_remark(log, "Second")
		processing.add_remark(log, "First")
		self.assertEqual(log.remarks, "First\nSecond")


class UnitTestOvertimeRate(UnitTestCase):
	EARNINGS = {"Basic": 30000, "House Rent Allowance": 12000, "Conveyance": 3000}

	def ot_settings(self, rules, **values):
		base = dict(
			enable_multiple_ot=0,
			working_hours_per_day=8,
			working_days_base="Fixed 30",
			base_component_method="Custom",
			applicable_overtime_component=[
				frappe._dict(salary_component="Basic"),
				frappe._dict(salary_component="House Rent Allowance"),
			],
			overtime_type_rules=[frappe._dict(r) for r in rules],
		)
		base.update(values)
		return frappe._dict(base)

	def rate(self, ot_type, rules, **values):
		log = frappe._dict(employee="EMP-UNIT", log_date="2026-03-02")
		with patch("frappe.get_cached_doc", return_value=self.ot_settings(rules, **values)), patch(
			f"{PROCESSING}.get_monthly_earnings", return_value=self.EARNINGS
		):
			return processing.get_overtime_rate(log, ot_type)

	NORMAL = {"ot_type": "Normal", "calculation_method": "Salary Derived", "component_method": "Component Wise",
		"rate_multiplier": 1.5}

	def test_salary_derived_component_wise(self):
		# (Basic + HRA) / 30 days / 8 h x 1.5
		self.assertEqual(self.rate("Normal", [self.NORMAL]), 262.5)

	def test_salary_derived_full_salary(self):
		rule = dict(self.NORMAL, component_method="Full Salary")
		self.assertEqual(self.rate("Normal", [rule]), 281.25)  # 45000 / 30 / 8 x 1.5

	def test_base_component_method_all(self):
		self.assertEqual(self.rate("Normal", [self.NORMAL], base_component_method="All"), 281.25)

	def test_fixed_rate(self):
		rule = {"ot_type": "Normal", "calculation_method": "Fixed Rate", "fixed_hourly_rate": 200, "rate_multiplier": 2}
		self.assertEqual(self.rate("Normal", [rule]), 400)

	def test_multiplier_defaults_to_one(self):
		rule = {"ot_type": "Normal", "calculation_method": "Fixed Rate", "fixed_hourly_rate": 150, "rate_multiplier": 0}
		self.assertEqual(self.rate("Normal", [rule]), 150)

	def test_single_ot_uses_normal_rule_for_holidays(self):
		holiday = dict(self.NORMAL, ot_type="Holiday", rate_multiplier=2)
		self.assertEqual(self.rate("Holiday", [self.NORMAL, holiday]), 262.5)
		self.assertEqual(self.rate("Holiday", [self.NORMAL, holiday], enable_multiple_ot=1), 350)

	def test_missing_rule_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.rate("Holiday", [dict(self.NORMAL, ot_type="Normal")], enable_multiple_ot=1)
		self.assertIn("no rule for OT type", str(ctx.exception))

	def test_zero_rate_refused(self):
		rule = {"ot_type": "Normal", "calculation_method": "Fixed Rate", "fixed_hourly_rate": 0, "rate_multiplier": 1}
		with self.assertRaises(frappe.ValidationError):
			self.rate("Normal", [rule])

	def test_component_wise_needs_applicable_components(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.rate("Normal", [self.NORMAL], applicable_overtime_component=[])
		self.assertIn("Applicable Overtime Components", str(ctx.exception))

	def test_working_days_base(self):
		self.assertEqual(processing.get_working_days("Month Days", "2026-02-10"), 28)
		self.assertEqual(processing.get_working_days("Month Days", "2028-02-10"), 29)
		self.assertEqual(processing.get_working_days("Fixed 30", "2026-02-10"), 30)
		self.assertEqual(processing.get_working_days("Year Average", "2026-02-10"), 365 / 12)


class UnitTestShiftDay(UnitTestCase):
	"""builder.shift_day: the date whose shift window holds the punch."""

	def day(self, punch, start, end, before=60, after=300):
		sh = frappe._dict(start_time=start, end_time=end, begin_check_in_before_shift_start_time=before,
			allow_check_out_after_shift_end_time=after)
		with patch.object(builder, "get_shift", return_value=sh):
			return str(builder.shift_day("EMP-UNIT", datetime.fromisoformat(punch)))

	def test_day_shift_punch(self):
		self.assertEqual(self.day("2026-03-02 17:30:00", "09:00:00", "17:00:00"), "2026-03-02")

	def test_night_shift_morning_checkout_is_previous_day(self):
		self.assertEqual(self.day("2026-03-03 06:10:00", "22:00:00", "06:00:00", 30, 60), "2026-03-02")

	def test_24_hour_shift_next_morning_is_previous_day(self):
		self.assertEqual(self.day("2026-03-03 08:30:00", "09:00:00", "08:59:00", 0, 0), "2026-03-02")

	def test_punch_outside_any_window_is_its_own_date(self):
		self.assertEqual(self.day("2026-03-02 03:00:00", "09:00:00", "17:00:00"), "2026-03-02")


class UnitTestParseNames(UnitTestCase):
	def test_json_list_unique_in_order(self):
		self.assertEqual(parse_names('["ATL-2", "ATL-1", "ATL-2"]'), ["ATL-2", "ATL-1"])

	def test_single_name_and_list(self):
		self.assertEqual(parse_names("ATL-1"), ["ATL-1"])
		self.assertEqual(parse_names(["ATL-1", "", None, "ATL-3"]), ["ATL-1", "ATL-3"])

	def test_nothing_selected(self):
		for empty in ([], "[]", None):
			with self.assertRaises(frappe.ValidationError):
				parse_names(empty)


class UnitTestSettingsDefaults(UnitTestCase):
	def defaults(self, **stored):
		with patch.object(session_log_settings.frappe, "get_cached_doc", return_value=frappe._dict(stored)):
			return get_session_log_settings()

	def test_empty_settings_get_defaults(self):
		s = self.defaults()
		self.assertEqual(s.log_creation_trigger, TRIGGER_ON_CHECKOUT)
		self.assertEqual(s.approver_role, DEFAULT_APPROVER_ROLE)
		self.assertEqual(s.missing_checkout_block_hours, DEFAULT_MISSING_CHECKOUT_HOURS)
		self.assertFalse(s.require_log_approval)
		self.assertTrue(s.hold_missing_checkout and s.auto_submit_attendance and s.auto_submit_overtime)
		self.assertTrue(s.lock_after_processing)

	def test_stored_values_win(self):
		s = self.defaults(require_log_approval=1, log_creation_trigger="Daily Scheduler", approver_role="HR User",
			hold_missing_checkout=0, missing_checkout_block_hours=20, auto_submit_attendance=0)
		self.assertTrue(s.require_log_approval)
		self.assertEqual((s.log_creation_trigger, s.approver_role), ("Daily Scheduler", "HR User"))
		self.assertFalse(s.hold_missing_checkout or s.auto_submit_attendance)
		self.assertEqual(s.missing_checkout_block_hours, 20)
