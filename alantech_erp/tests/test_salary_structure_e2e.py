# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""End to end: Employee Grade, Sub Band & Salary Structure from the Employee form.

ClickUp: https://app.clickup.com/t/14yr2e586vb (Testing, bug fixes and HR sign-off; parent
https://app.clickup.com/t/14yr2e586v0). One flow per checklist line of the task, on the real grades
(L1-B1 to L10-B10), the Default Salary Structure and HRMS's own salary slip preview, run as users
holding only the HR Manager / HR User roles:

1. No assignment: Create Salary Structure; active assignment: View Salary Structure.
2. Grade not set on the Employee: the one chosen in the popup is saved.
3. Sub band fills the grade's gross amount: L1-B1 A 16,000, L9-B9 D 1,08,750 (and every level).
4. The assignment has Base = gross and the grade's structure; Preview Salary Slip matches the
   formulas (Basic 40% of Gross, DA / HRA / TA / MA / SA / Fixed Variable % of Basic).
5. Edit only for the HR Manager.
6. Edge cases: sub band missing in the grade, a grade without sub bands, duplicate From Date,
   employee without a company, a grade whose structure belongs to another company.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_salary_structure_e2e

Data: every test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.utils import add_months, flt, get_first_day, getdate

from alantech_erp.setup.default_salary_structure import EARNINGS, STRUCTURE_NAME
from alantech_erp.setup.salary_structure_button import get_salary_structure_button
from alantech_erp.setup.salary_structure_popup import (
	SUB_BAND,
	SalaryStructurePopupError,
	create_salary_structure_assignment,
	get_grade_details,
)
from alantech_erp.setup.salary_structure_view import get_salary_structure_view, revise_salary_structure

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11E2E"

# PDF "Employee Grade, Level & Salary Band" Ver1, section 3 (ClickUp 14yr2e586v3): gross of sub band A..E
PDF_GROSS = {
	"L1-B1": (16000, 16500, 17000, 17500, 18000),
	"L9-B9": (75000, 86250, 97500, 108750, 120000),
	"L10-B10": (120000, 140000, 160000, 180000, 200000),
}


def expected_earnings(gross):
	"""The Default Salary Structure's formulas worked out by hand: {component: amount}."""
	basic = flt(gross) * 40 / 100
	amounts = {}
	for component, _abbr, percent, of in EARNINGS:
		amounts[component] = flt(gross) * percent / 100 if not of else basic * percent / 100
	return amounts


class TestSalaryStructureEndToEnd(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("p11e2e")
		self.addCleanup(frappe.db.rollback, save_point="p11e2e")
		self.addCleanup(frappe.set_user, "Administrator")
		self.from_date = get_first_day(add_months(getdate(), -2))
		self.hr_manager = self.user("hrmanager", "HR Manager", "HR User", "Employee")
		self.hr_user = self.user("hruser", "HR User", "Employee")

	def user(self, tag, *roles):
		return frappe.get_doc(
			{
				"doctype": "User",
				"email": f"p11e2e.{tag}@example.com",
				"first_name": f"{PREFIX} {tag}",
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True).name

	def employee(self, tag, grade=None, company=COMPANY):
		return frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} {tag}",
				"company": company,
				"gender": "Female",
				"date_of_birth": "1991-07-01",
				"date_of_joining": add_months(getdate(), -24),
				"status": "Active",
				"grade": grade,
			}
		).insert(ignore_permissions=True).name

	def preview(self, employee):
		from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

		slip = make_salary_slip(
			STRUCTURE_NAME, employee=employee, posting_date=add_months(self.from_date, 1), for_preview=1
		)
		return {row.salary_component: row.default_amount for row in slip.earnings}

	# 1 ------------------------------------------------------------------------------------
	def test_1_button_create_then_view(self):
		emp = self.employee("Button", grade="L1-B1")
		frappe.set_user(self.hr_manager)
		self.assertEqual(get_salary_structure_button(emp)["action"], "create")
		result = create_salary_structure_assignment(emp, "L1-B1", "A", self.from_date)
		state = get_salary_structure_button(emp)
		self.assertEqual((state["action"], state["assignment"]["name"]), ("view", result["name"]))

	# 2 ------------------------------------------------------------------------------------
	def test_2_grade_chosen_in_popup_saved_to_employee(self):
		emp = self.employee("No Grade")
		frappe.set_user(self.hr_manager)
		create_salary_structure_assignment(emp, "L9-B9", "D", self.from_date)
		self.assertEqual(frappe.db.get_value("Employee", emp, "grade"), "L9-B9")

	# 3 ------------------------------------------------------------------------------------
	def test_3_sub_band_gross_matches_the_pdf(self):
		for grade, amounts in PDF_GROSS.items():
			gross = {r.sub_band: r.gross_amount for r in get_grade_details(grade)["sub_bands"]}
			with self.subTest(grade=grade):
				self.assertEqual(tuple(gross[b] for b in "ABCDE"), amounts)
		# every level L1..L10 has the five sub bands and the Default Salary Structure
		for grade in frappe.get_all("Employee Grade", filters={"name": ["like", "L%-B%"]}, pluck="name"):
			details = get_grade_details(grade)
			with self.subTest(grade=grade):
				self.assertEqual([r.sub_band for r in details["sub_bands"]], list("ABCDE"))
				self.assertEqual(details["salary_structure"], STRUCTURE_NAME)

	# 4 ------------------------------------------------------------------------------------
	def test_4_assignment_and_preview_salary_slip(self):
		frappe.set_user(self.hr_manager)
		for tag, grade, sub_band, gross in (("L1A", "L1-B1", "A", 16000), ("L9D", "L9-B9", "D", 108750)):
			frappe.set_user("Administrator")
			emp = self.employee(tag, grade=grade)
			frappe.set_user(self.hr_manager)
			result = create_salary_structure_assignment(emp, grade, sub_band, self.from_date)
			doc = frappe.get_doc("Salary Structure Assignment", result["name"])
			with self.subTest(grade=grade, sub_band=sub_band):
				self.assertEqual(
					(doc.docstatus, doc.base, doc.salary_structure, doc.get(SUB_BAND)),
					(1, gross, STRUCTURE_NAME, sub_band),
				)
				earnings = self.preview(emp)
				self.assertEqual(earnings, expected_earnings(gross))
				self.assertEqual(sum(earnings.values()), gross)
				view = get_salary_structure_view(emp)
				self.assertEqual(view["total_earnings"], gross)

	# 5 ------------------------------------------------------------------------------------
	def test_5_edit_only_for_hr_manager(self):
		emp = self.employee("Edit", grade="L1-B1")
		frappe.set_user(self.hr_manager)
		create_salary_structure_assignment(emp, "L1-B1", "A", self.from_date)
		self.assertTrue(get_salary_structure_view(emp)["can_edit"])

		frappe.set_user(self.hr_user)
		self.assertFalse(get_salary_structure_view(emp)["can_edit"])
		with self.assertRaises(frappe.PermissionError):
			revise_salary_structure(emp, "B", add_months(self.from_date, 1))

		frappe.set_user(self.hr_manager)
		result = revise_salary_structure(emp, "B", add_months(self.from_date, 1))
		self.assertEqual(frappe.db.get_value("Salary Structure Assignment", result["name"], "base"), 16500)

	# 6 ------------------------------------------------------------------------------------
	def test_6a_sub_band_missing_in_grade(self):
		emp = self.employee("Missing Band", grade="L1-B1")
		frappe.db.delete("Employee Grade Sub Band", {"parent": "L1-B1", "sub_band": "E"})
		frappe.set_user(self.hr_manager)
		self.assertNotIn("E", [r.sub_band for r in get_grade_details("L1-B1")["sub_bands"]])
		with self.assertRaises(SalaryStructurePopupError) as raised:
			create_salary_structure_assignment(emp, "L1-B1", "E", self.from_date)
		self.assertIn("is not on Grade", str(raised.exception))

	def test_6b_grade_without_sub_bands(self):
		grade = next(
			(g for g in frappe.get_all("Employee Grade", pluck="name") if not get_grade_details(g)["sub_bands"]),
			None,
		)
		if not grade:
			self.skipTest("every grade has sub bands")
		emp = self.employee("Empty Grade", grade=grade)
		frappe.set_user(self.hr_manager)
		with self.assertRaises(SalaryStructurePopupError):
			create_salary_structure_assignment(emp, grade, "A", self.from_date)

	def test_6c_duplicate_from_date(self):
		emp = self.employee("Duplicate", grade="L1-B1")
		frappe.set_user(self.hr_manager)
		create_salary_structure_assignment(emp, "L1-B1", "A", self.from_date)
		with self.assertRaises(SalaryStructurePopupError) as raised:
			create_salary_structure_assignment(emp, "L1-B1", "B", self.from_date)
		self.assertIn("already has Salary Structure Assignment", str(raised.exception))

	def test_6d_employee_without_company(self):
		emp = self.employee("No Company", grade="L1-B1")
		frappe.db.set_value("Employee", emp, "company", None)  # e.g. an old or imported record
		frappe.set_user(self.hr_manager)
		with self.assertRaises(SalaryStructurePopupError) as raised:
			create_salary_structure_assignment(emp, "L1-B1", "A", self.from_date)
		self.assertIn("Company", str(raised.exception))

	def test_6e_grade_structure_of_another_company(self):
		"""The grade's structure belongs to another company than the employee (rolled back)."""
		emp = self.employee("Other Company", grade="L1-B1")
		frappe.db.set_value("Salary Structure", STRUCTURE_NAME, "company", "Another Company Pvt Ltd")
		frappe.set_user(self.hr_manager)
		with self.assertRaises(SalaryStructurePopupError) as raised:
			create_salary_structure_assignment(emp, "L1-B1", "A", self.from_date)
		self.assertIn("belongs to", str(raised.exception))
