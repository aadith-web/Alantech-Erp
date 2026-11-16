# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales activities against the database (CRM C10; alantech_erp/sales/activity.py).

Run:
    bench --site <site> run-tests --module alantech_erp.tests.test_sales_activities

Leads / Customers / Deals are written straight to the database (their CRM validations are tested
elsewhere); everything is rolled back after each test.
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.sales import activity as a


class ActivityCase(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.company = frappe.db.get_value("Company", {}, "name")
		self.lead = self.raw("Lead", {"lead_name": "TEST-ACT Lead", "company": self.company})
		self.customer = self.raw("Customer", {"customer_name": "TEST-ACT Customer", "lead_name": self.lead.name})
		self.deal = self.raw(
			"Opportunity",
			{"opportunity_from": "Customer", "party_name": self.customer.name, "customer_name": "TEST-ACT Customer", "company": self.company, "status": "Open"},
		)

	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user("Administrator")

	def raw(self, doctype, values):
		doc = frappe.get_doc({"doctype": doctype, **values})
		doc.name = frappe.generate_hash(length=10)
		doc.db_insert()
		return doc

	def activity(self, type_, ref=None, **values):
		ref = ref or self.lead
		doc = frappe.get_doc(
			{
				"doctype": a.DOCTYPE,
				"activity_type": type_,
				"subject": f"TEST-ACT {type_}",
				"reference_doctype": ref.doctype,
				"reference_name": ref.name,
				**values,
			}
		)
		doc.insert()
		return doc


class TestActivities(ActivityCase):
	def test_call_creates_event_and_needs_summary_to_complete(self):
		call = self.activity("Call", activity_date=add_days(now_datetime(), 1))
		self.assertTrue(call.event)
		event = frappe.get_doc("Event", call.event)
		self.assertEqual(event.event_category, "Call")
		self.assertEqual(event.reference_docname, self.lead.name)
		self.assertEqual(event.owner, "Administrator")

		call.status = "Completed"
		with self.assertRaises(frappe.ValidationError):
			call.save()
		call.reload()
		call.status = "Completed"
		call.summary = "Needs a 50 m3/day STP; send budgetary offer"
		call.save()
		self.assertEqual(frappe.db.get_value("Event", call.event, "status"), "Completed")
		self.assertTrue(call.completed_on)

	def test_follow_up_todo_and_closing_it(self):
		due = add_days(nowdate(), 2)
		meeting = self.activity("Meeting", ref=self.customer, follow_up_date=due)
		todo = frappe.get_doc("ToDo", meeting.todo)
		self.assertEqual(todo.allocated_to, "Administrator")
		self.assertEqual(getdate(todo.date), getdate(due))
		todo.status = "Closed"
		todo.save()
		self.assertEqual(frappe.db.get_value(a.DOCTYPE, meeting.name, "follow_up_done"), 1)

	def test_task_needs_due_date_and_closes_with_todo(self):
		with self.assertRaises(frappe.ValidationError):
			self.activity("Task")
		task = self.activity("Task", ref=self.deal, follow_up_date=add_days(nowdate(), 1))
		self.assertEqual(task.party_name, "TEST-ACT Customer")
		todo = frappe.get_doc("ToDo", task.todo)
		todo.status = "Closed"
		todo.save()
		self.assertEqual(frappe.db.get_value(a.DOCTYPE, task.name, "status"), "Completed")

	def test_note_is_completed_and_wrong_reference_blocked(self):
		note = self.activity("Note", description="Client prefers MBBR")
		self.assertEqual(note.status, "Completed")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": a.DOCTYPE, "activity_type": "Note", "subject": "x", "reference_doctype": "Item", "reference_name": "x"}
			).insert()

	def test_comment_and_email_logged(self):
		comment = frappe.get_doc(
			{"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Lead", "reference_name": self.lead.name, "content": "<p>Spoke to the plant head</p>"}
		).insert(ignore_permissions=True)
		logged = frappe.get_all(a.DOCTYPE, filters={"comment": comment.name}, fields=["activity_type", "subject", "status"])
		self.assertEqual(len(logged), 1)
		self.assertEqual(logged[0].activity_type, "Comment")
		self.assertEqual(logged[0].subject, "Spoke to the plant head")

		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "RFQ for ETP",
				"content": "Please quote",
				"sender": "client@example.com",
				"reference_doctype": "Customer",
				"reference_name": self.customer.name,
			}
		).insert(ignore_permissions=True)
		logged = frappe.get_all(a.DOCTYPE, filters={"communication": comm.name}, fields=["activity_type", "subject"])
		self.assertEqual(len(logged), 1)
		self.assertEqual(logged[0].subject, "Email received: RFQ for ETP")

	def test_summary_panel_customer_includes_lead(self):
		self.activity("Note", description="from lead")
		self.activity("Task", ref=self.customer, follow_up_date=add_days(nowdate(), -1), activity_date=add_days(now_datetime(), -3))
		s = a.get_activity_summary("Customer", self.customer.name)
		self.assertEqual(s["counts"].get("Note"), 1)  # the Lead's note shows on its Customer
		self.assertEqual(s["overdue_count"], 1)

	def test_follow_up_and_complete_api(self):
		call = self.activity("Call")
		res = a.complete_activity(call.name, summary="Agreed site visit", follow_up_date=add_days(nowdate(), 3))
		self.assertEqual(frappe.db.get_value(a.DOCTYPE, call.name, "status"), "Completed")
		nxt = frappe.get_doc(a.DOCTYPE, res["follow_up"])
		self.assertEqual(nxt.activity_type, "Task")
		self.assertEqual(nxt.previous_activity, call.name)
		self.assertEqual(nxt.reference_name, self.lead.name)

	def test_reminder_notification(self):
		self.activity("Task", follow_up_date=nowdate())
		before = frappe.db.count("Notification Log", {"for_user": "Administrator"})
		a.send_follow_up_reminders()
		self.assertGreater(frappe.db.count("Notification Log", {"for_user": "Administrator"}), before)

	def test_timeline_and_report(self):
		self.activity("Meeting", summary="ok", status="Completed")
		items = a.timeline_content("Lead", self.lead.name)
		self.assertTrue(any("TEST-ACT Meeting" in i["content"] for i in items))

		from alantech_erp.alantech.report.sales_activity_summary.sales_activity_summary import execute

		_, data, *_ = execute({"from_date": add_days(nowdate(), -1), "to_date": nowdate()})
		me = next(r for r in data if r.activity_owner == "Administrator")
		self.assertGreaterEqual(me.meeting, 1)

	def test_delete_removes_event_and_todo(self):
		call = self.activity("Call", follow_up_date=add_days(nowdate(), 1))
		event, todo = call.event, call.todo
		call.delete()
		self.assertFalse(frappe.db.exists("Event", event))
		self.assertFalse(frappe.db.exists("ToDo", todo))
