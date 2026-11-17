# Automated tests for api/checkin_reminder.notify_reentry
# Place at: alantech_erp/alantech_erp/tests/test_checkin_reminder.py  (any tests package inside the app works)
# Run:      bench --site alantech.localhost run-tests --module alantech_erp.tests.test_checkin_reminder

import unittest
from datetime import datetime
from unittest.mock import patch

import frappe

from alantech_erp.api.checkin_reminder import get_reentry_status, notify_reentry

USER = "vichu45@yopmail.com"
WINDOW = frappe._dict(start=datetime(2026, 11, 17, 9, 0), end=datetime(2026, 11, 17, 21, 0))

BUILDER = "alantech_erp.alantech.doctype.session_log.builder.shift_day"
GET_SHIFT = "alantech_erp.alantech.doctype.session_log.calculation.get_shift"
GET_WINDOW = "alantech_erp.alantech.doctype.session_log.calculation.get_shift_window"


def make_doc(log_type="OUT", time="2026-11-17 15:37:08", owner=USER):
	return frappe._dict(doctype="Employee Checkin", employee="HR-EMP-00079", log_type=log_type, time=time, owner=owner)


class TestNotifyReentry(unittest.TestCase):
	def run_case(self, doc, shift="12 Hour Shift", user_id=USER):
		"""Run notify_reentry with fakes; return the publish_realtime mock."""
		emp = frappe._dict(user_id=user_id, employee_name="Vishal V V")
		with (
			patch("frappe.db.get_value", return_value=emp),
			patch(BUILDER, return_value=datetime(2026, 11, 17).date()),
			patch(GET_SHIFT, return_value=shift),
			patch(GET_WINDOW, return_value=WINDOW),
			patch("frappe.publish_realtime") as publish,
		):
			notify_reentry(doc)
		return publish

	def test_checkout_inside_shift_prompts(self):
		publish = self.run_case(make_doc())
		publish.assert_called_once()
		event, payload = publish.call_args.args[:2]
		self.assertEqual(event, "checkin_reentry_prompt")
		self.assertEqual(publish.call_args.kwargs["user"], USER)
		self.assertEqual(payload["employee"], "HR-EMP-00079")
		self.assertIn("09:00", payload["shift_end"])  # 09:00 PM

	def test_checkout_after_shift_end_does_not_prompt(self):
		self.run_case(make_doc(time="2026-11-17 21:30:00")).assert_not_called()

	def test_checkout_exactly_at_shift_end_does_not_prompt(self):
		self.run_case(make_doc(time="2026-11-17 21:00:00")).assert_not_called()

	def test_check_in_does_not_prompt(self):
		self.run_case(make_doc(log_type="IN")).assert_not_called()

	def test_checkout_created_by_someone_else_still_prompts(self):
		self.run_case(make_doc(owner="hr@example.com")).assert_called_once()

	def test_no_shift_does_not_prompt(self):
		self.run_case(make_doc(), shift=None).assert_not_called()

	def test_employee_without_user_does_not_prompt(self):
		self.run_case(make_doc(), user_id=None).assert_not_called()


class TestGetReentryStatus(unittest.TestCase):
	"""Page load / refresh: the popup stays on while the last punch is an in-shift OUT."""

	def run_case(self, last, now, shift="12 Hour Shift"):
		emp = frappe._dict(name="HR-EMP-00079", employee_name="Vishal V V")
		with (
			patch("alantech_erp.api.checkin_reminder._employee", return_value=emp),
			patch("frappe.get_all", return_value=[last] if last else []),
			patch("alantech_erp.api.checkin_reminder.now_datetime", return_value=now),
			patch(BUILDER, return_value=datetime(2026, 11, 17).date()),
			patch(GET_SHIFT, return_value=shift),
			patch(GET_WINDOW, return_value=WINDOW),
			patch.object(frappe.local, "session", frappe._dict(user=USER), create=True),
		):
			return get_reentry_status()

	def out(self, time="2026-11-17 15:37:08", owner=USER):
		return frappe._dict(time=time, log_type="OUT", owner=owner)

	def test_shows_again_after_refresh_while_shift_runs(self):
		r = self.run_case(self.out(), now=datetime(2026, 11, 17, 16, 0))
		self.assertEqual(r["show_popup"], 1)
		self.assertIn("09:00", r["shift_end"])

	def test_stops_when_shift_has_ended(self):
		self.assertEqual(self.run_case(self.out(), now=datetime(2026, 11, 17, 21, 0))["show_popup"], 0)

	def test_stops_after_check_in(self):
		last = frappe._dict(time="2026-11-17 16:00:00", log_type="IN", owner=USER)
		self.assertEqual(self.run_case(last, now=datetime(2026, 11, 17, 16, 5))["show_popup"], 0)

	def test_checkout_by_someone_else_still_shows(self):
		r = self.run_case(self.out(owner="Administrator"), now=datetime(2026, 11, 17, 16, 0))
		self.assertEqual(r["show_popup"], 1)

	def test_no_punches_does_not_show(self):
		self.assertEqual(self.run_case(None, now=datetime(2026, 11, 17, 16, 0))["show_popup"], 0)