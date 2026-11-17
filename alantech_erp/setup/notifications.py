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


# ---------------------------------------------------------------------- read on view
# ClickUp: https://app.clickup.com/t/14yr2e57yr3
# Frappe v16's bell has no way to mark one notification read (only "Mark all as read"), and its
# count changes only on a new notification. public/js/notification_read.js marks a notification
# read when it is opened from the bell (or its document is opened while the bell lists it unread)
# and sets every bell count to the real number of unread notifications.
READ_EVENT = "alt_notification_read"


def unread_count(user=None):
	return frappe.db.count("Notification Log", {"for_user": user or frappe.session.user, "read": 0})


@frappe.whitelist(methods=["POST"])
def mark_read(names: list[str] | str | None = None, document_type: str | None = None, document_name: str | None = None):
	"""Mark the current user's notifications read: `names`, and/or every unread one about
	`document_type` / `document_name`. Returns the unread count left; other open tabs of the user
	get it through the realtime event READ_EVENT."""
	user = frappe.session.user
	names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else names
	if isinstance(names, str):
		names = [names]
	filters = []
	if names:
		filters.append({"name": ["in", list(names)]})
	if document_type and document_name:
		filters.append({"document_type": document_type, "document_name": document_name})
	changed = []
	for extra in filters:
		changed += frappe.get_all(
			"Notification Log", filters={"for_user": user, "read": 0, **extra}, pluck="name"
		)
	if changed and not frappe.flags.read_only:
		# own notifications only (for_user filter above), so no document permission is needed
		frappe.db.set_value("Notification Log", {"name": ["in", changed]}, "read", 1, update_modified=False)
	count = unread_count(user)
	frappe.publish_realtime(READ_EVENT, {"unread": count, "names": changed}, user=user, after_commit=True)
	return {"unread": count, "names": changed}


@frappe.whitelist(methods=["GET"])
def get_unread_count():
	return unread_count()
