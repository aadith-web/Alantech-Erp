# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Bell notification marked read when viewed (setup/notifications.mark_read, ClickUp 14yr2e57yr3).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_notification_read

Nothing is kept: each test runs in a savepoint rolled back after it.
"""

import frappe

from alantech_erp.setup import notifications as n

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase


def make_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


class TestNotificationRead(TestCase):
	def setUp(self):
		frappe.db.savepoint("notification_read_test")
		self.addCleanup(frappe.db.rollback, save_point="notification_read_test")
		self.addCleanup(frappe.set_user, "Administrator")
		self.user = make_user("_test-nr-a@example.com")
		self.other = make_user("_test-nr-b@example.com")
		frappe.db.delete("Notification Log", {"for_user": ["in", [self.user, self.other]]})

	def log(self, user, name="ToDo-1", subject="Something needs you"):
		return frappe.get_doc(
			{
				"doctype": "Notification Log", "for_user": user, "from_user": "Administrator",
				"type": "Alert", "document_type": "ToDo", "document_name": name, "subject": subject,
			}
		).insert(ignore_permissions=True).name

	def is_read(self, name):
		return frappe.db.get_value("Notification Log", name, "read")

	def test_marks_one_and_returns_unread_count(self):
		first, second = self.log(self.user), self.log(self.user, "ToDo-2")
		frappe.set_user(self.user)
		self.assertEqual(n.get_unread_count(), 2)
		result = n.mark_read(names=[first])
		self.assertEqual(result, {"unread": 1, "names": [first]})
		self.assertEqual((self.is_read(first), self.is_read(second)), (1, 0))

	def test_name_as_string_or_json(self):
		first, second = self.log(self.user), self.log(self.user, "ToDo-2")
		frappe.set_user(self.user)
		n.mark_read(names=first)
		n.mark_read(names=frappe.as_json([second]))
		self.assertEqual((self.is_read(first), self.is_read(second)), (1, 1))
		self.assertEqual(n.get_unread_count(), 0)

	def test_opening_the_document_marks_its_notifications(self):
		a, b, other_doc = self.log(self.user), self.log(self.user, subject="Again"), self.log(self.user, "ToDo-9")
		frappe.set_user(self.user)
		result = n.mark_read(document_type="ToDo", document_name="ToDo-1")
		self.assertEqual(sorted(result["names"]), sorted([a, b]))
		self.assertEqual(result["unread"], 1)
		self.assertEqual(self.is_read(other_doc), 0)

	def test_other_users_notifications_untouched(self):
		theirs = self.log(self.other)
		frappe.set_user(self.user)
		result = n.mark_read(names=[theirs], document_type="ToDo", document_name="ToDo-1")
		self.assertEqual(result["names"], [])
		self.assertEqual(self.is_read(theirs), 0)

	def test_already_read_not_reported_again(self):
		first = self.log(self.user)
		frappe.set_user(self.user)
		n.mark_read(names=[first])
		self.assertEqual(n.mark_read(names=[first])["names"], [])

	def test_bell_list_shows_it_read(self):
		first = self.log(self.user)
		frappe.set_user(self.user)
		n.mark_read(names=[first])
		logs = n.get_notification_logs(limit=20)["notification_logs"]
		self.assertEqual([log.read for log in logs if log.name == first], [1])
