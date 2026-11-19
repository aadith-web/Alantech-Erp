# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Create Salary Structure popup on the Employee form (setup/salary_structure_popup.py).

ClickUp: https://app.clickup.com/t/14yr2e586v6 (parent https://app.clickup.com/t/14yr2e586v0)

Covered:
- Grade details: Default Salary Structure and the grade's enabled sub bands with gross amounts.
- Create: Base = the sub band's Gross Amount, the grade's Default Salary Structure, Sub Band kept,
  submitted (button switches to View) or left as draft.
- An employee without a grade gets the chosen one saved; one with a grade cannot use another.
- Refused: no grade / sub band, sub band not on the grade, grade without Default Salary Structure,
  an assignment (draft too) with the same From Date; a failed submit saves nothing, not the grade.
- A user without create rights on assignments is refused.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_salary_structure_popup

Data: each test runs in a savepoint that is rolled back.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_months, get_first_day, getdate

from alantech_erp.setup.salary_structure_button import get_salary_structure_button
from alantech_erp.setup.salary_structure_popup import (
	SUB_BAND,
	SalaryStructurePopupError,
	create_salary_structure_assignment,
	get_grade_details,
)

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11C"
GRADE = "L3-B3"


class TestSalaryStructurePopup(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("p11c")
		self.addCleanup(frappe.db.rollback, save_point="p11c")
		self.addCleanup(frappe.set_user, "Administrator")
		self.from_date = get_first_day(add_months(getdate(), -1))
		self.gross = {r.sub_band: r.gross_amount for r in get_grade_details(GRADE)["sub_bands"]}
		self.structure = frappe.db.get_value("Employee Grade", GRADE, "default_salary_structure")

	def employee(self, tag, grade=GRADE):
		return frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} {tag}",
				"company": COMPANY,
				"gender": "Female",
				"date_of_birth": "1992-03-10",
				"date_of_joining": add_months(getdate(), -24),
				"status": "Active",
				"grade": grade,
			}
		).insert(ignore_permissions=True)

	def create(self, employee, sub_band="C", grade=GRADE, from_date=None, submit=1):
		return create_salary_structure_assignment(
			employee, grade, sub_band, from_date or self.from_date, submit=submit
		)

	def test_grade_details(self):
		details = get_grade_details(GRADE)
		self.assertEqual(details["salary_structure"], self.structure)
		self.assertEqual([r.sub_band for r in details["sub_bands"]], ["A", "B", "C", "D", "E"])
		self.assertTrue(all(r.gross_amount > 0 for r in details["sub_bands"]))

	def test_disabled_sub_band_not_offered(self):
		frappe.db.set_value("Sub Band", "E", "enabled", 0)
		self.assertNotIn("E", [r.sub_band for r in get_grade_details(GRADE)["sub_bands"]])
		with self.assertRaises(SalaryStructurePopupError):
			self.create(self.employee("Disabled").name, sub_band="E")

	def test_create_submitted(self):
		emp = self.employee("Submit")
		result = self.create(emp.name, sub_band="C")
		doc = frappe.get_doc("Salary Structure Assignment", result["name"])
		self.assertEqual(
			(doc.docstatus, doc.salary_structure, doc.base, doc.get(SUB_BAND), doc.company, getdate(doc.from_date)),
			(1, self.structure, self.gross["C"], "C", COMPANY, self.from_date),
		)
		state = get_salary_structure_button(emp.name)
		self.assertEqual((state["action"], state["assignment"]["name"]), ("view", doc.name))

	def test_create_draft(self):
		emp = self.employee("Draft")
		result = self.create(emp.name, sub_band="A", submit=0)
		self.assertEqual(result["docstatus"], 0)
		self.assertEqual(get_salary_structure_button(emp.name)["action"], "create")

	def test_grade_saved_to_employee_without_grade(self):
		emp = self.employee("No Grade", grade=None)
		self.create(emp.name, sub_band="B")
		self.assertEqual(frappe.db.get_value("Employee", emp.name, "grade"), GRADE)

	def test_other_grade_refused_when_employee_has_one(self):
		emp = self.employee("Has Grade")
		with self.assertRaises(SalaryStructurePopupError):
			self.create(emp.name, grade="L4-B4")

	def test_refusals(self):
		emp = self.employee("Refused").name
		cases = {
			"no grade": dict(grade=None),
			"no sub band": dict(sub_band=None),
			"sub band not on grade": dict(sub_band="Z-not-a-band"),
		}
		for case, kwargs in cases.items():
			with self.subTest(case=case), self.assertRaises(SalaryStructurePopupError):
				self.create(emp, **kwargs)

	def test_grade_without_default_structure(self):
		frappe.db.set_value("Employee Grade", GRADE, "default_salary_structure", None)
		with self.assertRaises(SalaryStructurePopupError):
			self.create(self.employee("No Structure").name)

	def test_same_from_date_refused_also_for_draft(self):
		emp = self.employee("Duplicate").name
		self.create(emp, submit=0)
		with self.assertRaises(SalaryStructurePopupError) as raised:
			self.create(emp, sub_band="D")
		self.assertIn("already has Salary Structure Assignment", str(raised.exception))

	def test_failed_submit_saves_nothing(self):
		"""Request-level atomicity: Frappe rolls the request back on an error; here the savepoint
		inside the test does it, so check that the grade is saved only together with the assignment."""
		emp = self.employee("Fails", grade=None)
		frappe.db.savepoint("p11c_fail")
		with (
			# the payroll-fields check refuses the submit (setup/employee_payroll_fields.py)
			patch(
				"alantech_erp.setup.employee_payroll_fields.salary_structure_assignment_before_submit",
				side_effect=frappe.ValidationError("payroll fields missing"),
			),
			self.assertRaises(frappe.ValidationError),
		):
			self.create(emp.name)
		frappe.db.rollback(save_point="p11c_fail")
		self.assertIsNone(frappe.db.get_value("Employee", emp.name, "grade"))
		self.assertFalse(frappe.db.exists("Salary Structure Assignment", {"employee": emp.name}))

	def test_user_without_create_right_refused(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "p11c.employee@example.com",
				"first_name": f"{PREFIX} User",
				"send_welcome_email": 0,
				"roles": [{"role": "Employee"}],
			}
		).insert(ignore_permissions=True)
		emp = self.employee("Own")
		emp.db_set("user_id", user.name)
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			self.create(emp.name)
