# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Unit tests for the Attendance Log Review report (HR-F02 Attendance Management, ClickUp
14yr2e56cae): month period, per-employee summary, off days, report summary cards.

Rows are in-memory dicts; the permission-filtered query itself is covered by
tests/test_phase0_session_log.py.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.report.attendance_log_review.test_attendance_log_review
"""

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.alantech.report.attendance_log_review.attendance_log_review import (
	get_employee_summary,
	get_period,
	get_report_summary,
	get_summary_html,
	is_off_day,
)


def row(employee="E1", status="Present", day_type="Working Day", first_in="2026-03-02 09:00:00",
		log_status="Processed", **extra):
	"""status = attendance status; log_status = the Session Log's own status."""
	values = dict(employee=employee, employee_name=f"Name {employee}", attendance_status=status,
		day_type=day_type, first_in=first_in, overtime_hours=0, late_entry=0, early_exit=0,
		missing_checkout=0, error_log=None, remarks=None, status=log_status)
	values.update(extra)
	return frappe._dict(values)


class UnitTestAttendanceLogReview(UnitTestCase):
	def test_period_is_the_whole_month(self):
		start, end = get_period(frappe._dict(month="February", year=2028))
		self.assertEqual((str(start), str(end)), ("2028-02-01", "2028-02-29"))
		start, end = get_period(frappe._dict(month="November", year="2026"))
		self.assertEqual((str(start), str(end)), ("2026-11-01", "2026-11-30"))

	def test_period_needs_month_and_year(self):
		with self.assertRaises(frappe.ValidationError):
			get_period(frappe._dict(month="March"))

	def test_off_day(self):
		self.assertTrue(is_off_day(row(status="Absent", day_type="Weekly Off", first_in=None)))
		self.assertFalse(is_off_day(row(day_type="Weekly Off")))  # worked on the weekly off
		self.assertFalse(is_off_day(row(status="On Leave", day_type="Holiday", first_in=None)))
		self.assertFalse(is_off_day(row(status="Absent", first_in=None)))  # working day absence

	def test_employee_summary_counts(self):
		data = [
			row(status="Present", overtime_hours=1.5),
			row(status="Half Day"),
			row(status="Absent", first_in=None),
			row(status="On Leave", first_in=None),
			row(status="Absent", day_type="Weekly Off", first_in=None),
			row(status="Present", day_type="Weekly Off", overtime_hours=4),
			row(employee="E2", status="Present"),
		]
		summary = {s.employee: s for s in get_employee_summary(data)}
		e1 = summary["E1"]
		self.assertEqual((e1.present, e1.half_day, e1.absent, e1.on_leave, e1.off_days, e1.logs), (2, 1, 1, 1, 1, 6))
		self.assertEqual(e1.ot_hours, 5.5)
		self.assertEqual(summary["E2"].present, 1)

	def test_processing_error_shown_in_remarks(self):
		failed = row(error_log="No salary slip or Salary Structure Assignment")
		kept = row(error_log="other error", remarks="HR note")
		get_employee_summary([failed, kept])
		self.assertEqual(failed.remarks, "No salary slip or Salary Structure Assignment")
		self.assertEqual(kept.remarks, "HR note")

	def test_report_summary_cards(self):
		data = [
			row(overtime_hours=1.25),
			row(late_entry=1, log_status="Pending Approval"),
			row(employee="E2", missing_checkout=1, overtime_hours=2),
			row(employee="E2", error_log="failed"),
		]
		cards = {c["label"]: c for c in get_report_summary(data)}
		self.assertEqual(cards["Logs"]["value"], 4)
		self.assertEqual(cards["Employees"]["value"], 2)
		self.assertEqual((cards["Pending Approval"]["value"], cards["Pending Approval"]["indicator"]), (1, "Orange"))
		self.assertEqual((cards["Flagged"]["value"], cards["Flagged"]["indicator"]), (3, "Red"))
		self.assertEqual(cards["Total OT Hours"]["value"], 3.25)

	def test_report_summary_all_clear(self):
		cards = {c["label"]: c for c in get_report_summary([row()])}
		self.assertEqual(cards["Flagged"]["indicator"], "Green")
		self.assertEqual(cards["Pending Approval"]["indicator"], "Green")

	def test_summary_html_escapes_names(self):
		start, _end = get_period(frappe._dict(month="March", year=2026))
		html = get_summary_html(get_employee_summary([row(employee_name="<b>X</b>")]), start)
		self.assertIn("&lt;b&gt;X&lt;/b&gt;", html)
		self.assertIn("March 2026", html)
		self.assertEqual(get_summary_html([], start), "")
