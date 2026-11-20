# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""View Salary Structure popup and its Edit (setup/salary_structure_view.py).

ClickUp: https://app.clickup.com/t/14yr2e586v8 (parent https://app.clickup.com/t/14yr2e586v0)

Covered:
- The view of the active assignment: structure, From Date, Grade, Sub Band, Base; earnings with
  basis ("40% of Gross", "25% of Basic") and full-month amounts (Gross 38,500: Basic 15,400 ...),
  totals and net. No active assignment: refused.
- Can Edit only for the HR Manager; HR User and the employee see the view without Edit.
- An employee sees their own view only.
- Edit (revise): new assignment from a later From Date with the new sub band's gross, which becomes
  the active one; refused for a From Date not after the current one, and for non HR Managers.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_salary_structure_view

Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.utils import add_days, add_months, get_first_day, getdate

from alantech_erp.setup.default_salary_structure import STRUCTURE_NAME
from alantech_erp.setup.salary_structure_button import get_active_assignment
from alantech_erp.setup.salary_structure_popup import SUB_BAND, SalaryStructurePopupError, get_grade_details
from alantech_erp.setup.salary_structure_view import get_salary_structure_view, revise_salary_structure

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11V"
GRADE = "L3-B3"


class TestSalaryStructureView(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("p11v")
		self.addCleanup(frappe.db.rollback, save_point="p11v")
		self.addCleanup(frappe.set_user, "Administrator")
		self.from_date = get_first_day(add_months(getdate(), -2))

	def employee(self, tag, user=None):
		return frappe.get_doc(
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
		).insert(ignore_permissions=True).name

	def assign(self, employee, base=38500, sub_band="C"):
		doc = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": employee,
				"salary_structure": STRUCTURE_NAME,
				"company": COMPANY,
				"from_date": self.from_date,
				"base": base,
				"currency": "INR",
				SUB_BAND: sub_band,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		doc.submit()
		return doc

	def user(self, tag, *roles):
		return frappe.get_doc(
			{
				"doctype": "User",
				"email": f"p11v.{tag}@example.com",
				"first_name": f"{PREFIX} {tag}",
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True).name

	def test_view_rows_amounts_and_totals(self):
		emp = self.employee("View")
		assignment = self.assign(emp)
		view = get_salary_structure_view(emp)
		self.assertEqual(
			(view["assignment"], view["salary_structure"], view["grade"], view["sub_band"], view["base"]),
			(assignment.name, STRUCTURE_NAME, GRADE, "C", 38500),
		)
		earnings = {r["component"]: (r["basis"], r["amount"]) for r in view["earnings"]}
		self.assertEqual(earnings["Basic"], ("40% of Gross", 15400))
		self.assertEqual(earnings["Dearness Allowance"], ("25% of Basic", 3850))
		self.assertEqual(earnings["Transport Allowance"], ("12.5% of Basic", 1925))
		self.assertEqual(view["total_earnings"], 38500)
		self.assertEqual(view["total_deductions"], 0)
		self.assertEqual(view["net"], 38500)
		self.assertIsNone(view["amount_error"])
		self.assertTrue(view["can_edit"])  # Administrator has HR Manager

	def test_assignment_from_mid_month_still_shows_amounts(self):
		"""An assignment from today, the 19th: HRMS previews the month from its 1st, which the
		assignment does not cover, so next month is previewed (reported on HR-EMP-00113)."""
		from unittest.mock import patch

		mid_month = add_days(get_first_day(add_months(getdate(), -3)), 18)  # a 19th, in the past
		self.from_date = mid_month
		emp = self.employee("Mid Month")
		self.assign(emp)
		with patch("alantech_erp.setup.salary_structure_view.today", return_value=mid_month):
			view = get_salary_structure_view(emp)
		self.assertIsNone(view["amount_error"])
		self.assertEqual(view["total_earnings"], 38500)

	def test_preview_date(self):
		from unittest.mock import patch

		from alantech_erp.setup.salary_structure_view import preview_date

		cases = {
			# (today, from_date): posting date
			("2026-11-19", "2026-11-19"): "2026-12-01",  # from mid-month, this month: next month
			("2026-11-19", "2026-11-01"): "2026-11-19",  # from the 1st: this month
			("2026-11-19", "2026-08-19"): "2026-11-19",  # from an earlier month: this month
		}
		for (now, from_date), expected in cases.items():
			with self.subTest(now=now, from_date=from_date), patch(
				"alantech_erp.setup.salary_structure_view.today", return_value=now
			):
				self.assertEqual(preview_date(from_date), getdate(expected))

	def test_no_active_assignment(self):
		with self.assertRaises(frappe.DoesNotExistError):
			get_salary_structure_view(self.employee("None"))

	def test_edit_only_for_hr_manager(self):
		emp = self.employee("Roles")
		self.assign(emp)
		frappe.set_user(self.user("hruser", "HR User", "Employee"))
		self.assertFalse(get_salary_structure_view(emp)["can_edit"])
		with self.assertRaises(frappe.PermissionError):
			revise_salary_structure(emp, "D", add_days(getdate(), 1))
		frappe.set_user(self.user("hrmanager", "HR Manager", "HR User", "Employee"))
		self.assertTrue(get_salary_structure_view(emp)["can_edit"])

	def test_employee_sees_own_only(self):
		user = self.user("employee", "Employee")
		own, other = self.employee("Own", user=user), self.employee("Other")
		self.assign(own)
		self.assign(other)
		frappe.set_user(user)
		view = get_salary_structure_view(own)
		self.assertFalse(view["can_edit"])
		self.assertEqual(view["total_earnings"], 38500)
		with self.assertRaises(frappe.PermissionError):
			get_salary_structure_view(other)

	def test_revise_from_later_date(self):
		emp = self.employee("Revise")
		old = self.assign(emp, base=get_grade_details(GRADE)["sub_bands"][2].gross_amount)
		gross_d = next(r.gross_amount for r in get_grade_details(GRADE)["sub_bands"] if r.sub_band == "D")
		new_from = add_months(self.from_date, 1)

		result = revise_salary_structure(emp, "D", new_from)
		self.assertEqual((result["docstatus"], result["base"]), (1, gross_d))
		self.assertEqual(get_active_assignment(emp).name, result["name"])
		self.assertEqual(frappe.db.get_value("Salary Structure Assignment", old.name, "docstatus"), 1)

		with self.assertRaises(SalaryStructurePopupError):
			revise_salary_structure(emp, "E", new_from)  # not after the current From Date

	def test_revise_with_cost_centers(self):
		"""ClickUp 14yr2e589er: the View shows the split; Edit passes new rows to the new assignment."""
		parent = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 1}, "name", order_by="lft asc")
		a, b = (
			frappe.get_doc(
				{"doctype": "Cost Center", "cost_center_name": f"{PREFIX} {tag}", "company": COMPANY, "parent_cost_center": parent}
			).insert(ignore_permissions=True).name
			for tag in ("A", "B")
		)
		emp = self.employee("RevCC")
		frappe.db.set_value("Employee", emp, "payroll_cost_center", a)
		self.assign(emp, base=get_grade_details(GRADE)["sub_bands"][2].gross_amount)
		self.assertEqual(get_salary_structure_view(emp)["cost_centers"], [{"cost_center": a, "percentage": 100}])

		rows = [{"cost_center": a, "percentage": 70}, {"cost_center": b, "percentage": 30}]
		result = revise_salary_structure(emp, "D", add_months(self.from_date, 1), cost_centers=frappe.as_json(rows))
		self.assertEqual(get_salary_structure_view(emp)["assignment"], result["name"])
		self.assertEqual(get_salary_structure_view(emp)["cost_centers"], rows)
		with self.assertRaises(SalaryStructurePopupError):
			revise_salary_structure(
				emp, "E", add_months(self.from_date, 2), cost_centers=[{"cost_center": a, "percentage": 50}]
			)
