# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee form: Create / View Salary Structure button (setup/salary_structure_button.py).

ClickUp: https://app.clickup.com/t/14yr2e586v5 (parent https://app.clickup.com/t/14yr2e586v0)

Covered:
- No assignment, a draft, a cancelled one, or only a future-dated one: "create", with the
  employee, company, grade's Default Salary Structure and Default Base Pay, From Date today.
- A submitted assignment from today or earlier: "view" with it; of several, the latest From Date.
- A user who may not create assignments gets no button for an employee without one; an employee
  sees "view" for their own assignment only, and is refused another employee.
- Submit and cancel send the realtime event to the Employee's open form.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_salary_structure_button

Data: each test runs in a savepoint that is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, get_first_day, getdate, today

from alantech_erp.setup.default_salary_structure import STRUCTURE_NAME
from alantech_erp.setup.salary_structure_button import EVENT, get_salary_structure_button

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11B"
GRADE = "L3-B3"


class TestSalaryStructureButton(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("p11b")
		self.addCleanup(frappe.db.rollback, save_point="p11b")
		self.addCleanup(frappe.set_user, "Administrator")

	def employee(self, tag, user=None):
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": f"{PREFIX} {tag}",
					"company": COMPANY,
					"gender": "Male",
					"date_of_birth": "1990-01-15",
					"date_of_joining": add_months(getdate(), -24),
					"status": "Active",
					"grade": GRADE,
					"user_id": user,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def assignment(self, employee, from_date, submit=True, base=30000):
		doc = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": employee,
				"salary_structure": STRUCTURE_NAME,
				"company": COMPANY,
				"from_date": from_date,
				"base": base,
				"currency": "INR",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def test_create_without_active_assignment(self):
		employee = self.employee("None")
		state = get_salary_structure_button(employee)
		self.assertEqual(state["action"], "create")
		grade = frappe.db.get_value(
			"Employee Grade", GRADE, ["default_salary_structure", "default_base_pay"], as_dict=True
		)
		expected = {"employee": employee, "company": COMPANY, "from_date": today()}
		if grade.default_salary_structure:
			expected["salary_structure"] = grade.default_salary_structure
		if grade.default_base_pay:
			expected["base"] = grade.default_base_pay
		self.assertEqual(state["new_assignment"], expected)

	def test_draft_cancelled_or_future_is_not_active(self):
		employee = self.employee("Not Active")
		self.assignment(employee, get_first_day(getdate()), submit=False)  # draft
		self.assignment(employee, add_days(getdate(), 10))  # future
		cancelled = self.assignment(employee, add_months(getdate(), -3))
		cancelled.cancel()
		self.assertEqual(get_salary_structure_button(employee)["action"], "create")

	def test_view_latest_active_assignment(self):
		employee = self.employee("Active")
		self.assignment(employee, add_months(getdate(), -6), base=25000)
		latest = self.assignment(employee, getdate(), base=30000)  # today counts as active
		self.assignment(employee, add_days(getdate(), 5), base=35000)  # future: not yet
		state = get_salary_structure_button(employee)
		self.assertEqual(state["action"], "view")
		self.assertEqual(state["assignment"]["name"], latest.name)
		self.assertEqual(state["assignment"]["base"], 30000)

	def test_employee_sees_only_own_and_cannot_create(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "p11b.employee@example.com",
				"first_name": f"{PREFIX} User",
				"send_welcome_email": 0,
				"roles": [{"role": "Employee"}],
			}
		).insert(ignore_permissions=True)
		own = self.employee("Own", user=user.name)
		other = self.employee("Other")
		self.assignment(other, add_months(getdate(), -1))

		frappe.set_user(user.name)
		self.assertEqual(get_salary_structure_button(own)["action"], None)  # no assignment, no create right
		with self.assertRaises(frappe.PermissionError):
			get_salary_structure_button(other)

		frappe.set_user("Administrator")
		mine = self.assignment(own, add_months(getdate(), -1))
		frappe.set_user(user.name)
		state = get_salary_structure_button(own)
		self.assertEqual((state["action"], state["assignment"]["name"]), ("view", mine.name))

	def test_submit_and_cancel_notify_open_form(self):
		employee = self.employee("Notify")
		with patch("frappe.publish_realtime") as publish:
			doc = self.assignment(employee, add_months(getdate(), -1))
			doc.cancel()
		calls = [c for c in publish.call_args_list if c.args and c.args[0] == EVENT]
		self.assertEqual(len(calls), 2)
		for call in calls:
			self.assertEqual(call.args[1], {"employee": employee})
			self.assertEqual((call.kwargs["doctype"], call.kwargs["docname"]), ("Employee", employee))
			self.assertTrue(call.kwargs["after_commit"])
