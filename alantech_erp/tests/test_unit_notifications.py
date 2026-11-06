# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""The bell's notification list is never cached by the browser (setup/notifications.py;
ClickUp 14yr2e57crv). Frappe's own endpoint answers with Cache-Control private, max-age=60,
stale-while-revalidate=3600, so after a logout / login on the same browser the next user saw the
previous user's list.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_unit_notifications
"""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from werkzeug.datastructures import Headers

from alantech_erp.setup import notifications


class UnitTestBellNotifications(UnitTestCase):
	def call(self):
		request = frappe._dict(method="GET", path=f"/api/method/{notifications.FRAPPE_METHOD}")
		frappe.local.response_headers = Headers()
		try:
			with patch.object(frappe, "request", request, create=True), patch.object(
				frappe.db, "get_list", return_value=[frappe._dict(name="N1", from_user="Administrator")]
			):
				result = notifications.get_notification_logs(limit=5)
			return result, frappe.local.response_headers.get("Cache-Control")
		finally:
			frappe.local.response_headers = None

	def test_bell_points_to_the_app_method(self):
		self.assertEqual(
			frappe.override_whitelisted_method(notifications.FRAPPE_METHOD),
			"alantech_erp.setup.notifications.get_notification_logs",
		)

	def test_response_is_never_cached(self):
		_result, cache_control = self.call()
		self.assertEqual(cache_control, notifications.NO_STORE)
		self.assertNotIn("max-age=60", cache_control)
		self.assertNotIn("stale-while-revalidate", cache_control)

	def test_same_result_as_frappe(self):
		result, _ = self.call()
		self.assertEqual([log.name for log in result["notification_logs"]], ["N1"])
		self.assertIn("user_info", result)
