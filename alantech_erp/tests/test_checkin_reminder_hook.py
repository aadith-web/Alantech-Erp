import unittest
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

EMPLOYEE = "HR-EMP-00079"
USER = "vichu45@yopmail.com"
HOOK = "alantech_erp.api.checkin_reminder.notify_reentry"
GET_SHIFT = "alantech_erp.alantech.doctype.session_log.calculation.get_shift"
GET_WINDOW = "alantech_erp.alantech.doctype.session_log.calculation.get_shift_window"


class TestCheckoutTriggersPopup(unittest.TestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_hook_is_registered(self):
		hooks = frappe.get_hooks("doc_events").get("Employee Checkin", {})
		self.assertIn(HOOK, hooks.get("after_insert", []))

	def test_real_checkout_sends_popup_event(self):
		now = now_datetime()
		start, end = now - timedelta(hours=4), now + timedelta(hours=4)
		window = frappe._dict(
			start=start,
			end=end,
			actual_start=start - timedelta(hours=1),
			actual_end=end + timedelta(hours=1),
		)

		frappe.set_user(USER)
		with (
			patch(GET_SHIFT, return_value=frappe.get_doc("Shift Type", "12 Hour Shift")),
			patch(GET_WINDOW, return_value=window),
			patch("frappe.publish_realtime") as publish,
		):
			self.insert_checkin("IN", now - timedelta(minutes=2))
			self.assertNotIn("checkin_reentry_prompt", [c.args[0] for c in publish.call_args_list if c.args])

			self.insert_checkin("OUT", now - timedelta(minutes=1))

		events = [c.args[0] for c in publish.call_args_list if c.args]
		self.assertIn("checkin_reentry_prompt", events, f"events sent: {events}")

		call = next(c for c in publish.call_args_list if c.args and c.args[0] == "checkin_reentry_prompt")
		self.assertEqual(call.kwargs["user"], USER)
		self.assertEqual(call.args[1]["employee"], EMPLOYEE)

	@staticmethod
	def insert_checkin(log_type, time):
		doc = frappe.get_doc(
			{"doctype": "Employee Checkin", "employee": EMPLOYEE, "log_type": log_type, "time": time}
		)
		doc.insert()
		return doc
