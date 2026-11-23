# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employment State in the Create Salary Structure popup (setup/salary_structure_popup.py).

ClickUp: https://app.clickup.com/t/14yr2e58ft2 (parent https://app.clickup.com/t/14yr2e586v0)

Covered:
- The popup's list: India Payroll's Indian states and union territories, default Kerala.
- The chosen state is saved in India Payroll's Employment State (employment_state) of the new
  assignment; empty falls back to Kerala; a value not on the list is refused.
- Edit Salary Structure (a new assignment from a later date): the popup shows the current state;
  the state chosen there is saved, none sent keeps the current one; an unknown one is refused.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_salary_structure_employment_state

Data: each test runs in a savepoint that is rolled back. Skipped when India Payroll is not installed.
"""

import frappe
from frappe.utils import add_months, get_first_day, getdate

from alantech_erp.setup.salary_structure_popup import (
	EMPLOYMENT_STATE,
	SalaryStructurePopupError,
	create_salary_structure_assignment,
	get_employment_states,
)
from alantech_erp.setup.salary_structure_view import revise_salary_structure

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11ES"
GRADE = "L3-B3"


class TestSalaryStructureEmploymentState(TestCase):
	def setUp(self):
		if "india_payroll" not in frappe.get_installed_apps():
			self.skipTest("India Payroll is not installed")
		frappe.set_user("Administrator")
		frappe.db.savepoint("p11es")
		self.addCleanup(frappe.db.rollback, save_point="p11es")
		self.from_date = get_first_day(add_months(getdate(), -2))
		self.emp = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} State",
				"company": COMPANY,
				"gender": "Female",
				"date_of_birth": "1992-03-10",
				"date_of_joining": add_months(getdate(), -24),
				"status": "Active",
				"grade": GRADE,
			}
		).insert(ignore_permissions=True).name

	def create(self, state=None, from_date=None):
		result = create_salary_structure_assignment(
			self.emp, GRADE, "C", from_date or self.from_date, employment_state=state
		)
		return frappe.db.get_value("Salary Structure Assignment", result["name"], EMPLOYMENT_STATE)

	def test_list_and_default(self):
		options = get_employment_states()
		self.assertEqual(options["default"], "Kerala")
		self.assertEqual(len(options["states"]), 36)  # 28 states and 8 union territories
		for state in ("Kerala", "Karnataka", "Tamil Nadu", "Delhi", "Lakshadweep"):
			self.assertIn(state, options["states"])

	def test_chosen_state_saved(self):
		self.assertEqual(self.create("Karnataka"), "Karnataka")

	def test_empty_falls_back_to_kerala(self):
		self.assertEqual(self.create(None), "Kerala")

	def test_unknown_state_refused(self):
		with self.assertRaises(SalaryStructurePopupError):
			self.create("Dubai")

	def test_edit_keeps_the_state(self):
		self.create("Tamil Nadu")
		result = revise_salary_structure(self.emp, "D", add_months(self.from_date, 1))
		self.assertEqual(
			frappe.db.get_value("Salary Structure Assignment", result["name"], EMPLOYMENT_STATE), "Tamil Nadu"
		)

	def test_edit_saves_the_chosen_state(self):
		"""Edit Salary Structure: the employee moved to another state (shown and changed in the popup)."""
		from alantech_erp.setup.salary_structure_view import get_salary_structure_view

		self.create("Kerala")
		self.assertEqual(get_salary_structure_view(self.emp)["employment_state"], "Kerala")
		result = revise_salary_structure(self.emp, "D", add_months(self.from_date, 1), employment_state="Karnataka")
		self.assertEqual(
			frappe.db.get_value("Salary Structure Assignment", result["name"], EMPLOYMENT_STATE), "Karnataka"
		)

	def test_edit_refuses_unknown_state(self):
		self.create("Kerala")
		with self.assertRaises(SalaryStructurePopupError):
			revise_salary_structure(self.emp, "D", add_months(self.from_date, 1), employment_state="Dubai")
