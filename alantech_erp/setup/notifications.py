# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Bell (notifications dropdown) always shows the logged-in user's own notifications.

ClickUp: https://app.clickup.com/t/14yr2e57crv
Frappe v16 sends the bell's list (notification_log.get_notification_logs) with
    Cache-Control: private, max-age=60, stale-while-revalidate=3600
The browser caches it by URL, and the URL is the same for every user. When one user logs out and
another logs in on the same browser within the hour (an employee uploads a document, then the HR
Manager logs in), the browser shows the previous user's cached list: "No New Notifications",
although the Notification Log for the HR Manager exists.

hooks.py override_whitelisted_methods points the bell at get_notification_logs below: the same
result (same permissions, same fields), but never cacheable. Frappe itself is not changed.
"""

import frappe
from frappe.desk.doctype.notification_log import notification_log

NO_STORE = "no-store, no-cache, must-revalidate, max-age=0"
FRAPPE_METHOD = "frappe.desk.doctype.notification_log.notification_log.get_notification_logs"


@frappe.whitelist()
def get_notification_logs(limit: int = 20):
	# __wrapped__: Frappe's function without its http_cache decorator
	original = getattr(notification_log.get_notification_logs, "__wrapped__", notification_log.get_notification_logs)
	result = original(limit=limit)
	if getattr(frappe.local, "response_headers", None) is not None:
		frappe.local.response_headers.set("Cache-Control", NO_STORE)
	return result
