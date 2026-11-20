# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Default Salary Structure with the payslip earnings (setup/default_salary_structure.py).

ClickUp: https://app.clickup.com/t/14yr2e586v4 (parent https://app.clickup.com/t/14yr2e586v0)

Covered:
- Formulas from Percentage / Percentage Of: chains down to Gross (base), number format, and the
  errors for a component not in the structure, without a Percentage, or worked out from itself.
- The submitted Default Salary Structure has the 7 earnings, and is the default of every grade.
- Preview Salary Slip for Gross 38,500: Basic 15,400, DA 3,850, HRA 6,160, TA 1,925, MA 1,540,
  SA 1,925, Fixed Variable 7,700, gross pay 38,500.
- HR changes a Percentage on the submitted structure: the formulas follow (Basic 50% -> DA
  base * 50 / 100 * 25 / 100), also those of the rows based on Basic.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_default_salary_structure

Data: each integration test runs in a savepoint that is rolled back (employee, assignment,
structure changes).
"""

import frappe
from frappe.utils import add_months, get_first_day, getdate

from alantech_erp.setup.default_salary_structure import (
	EARNINGS,
	PERCENT,
	PERCENT_OF,
	STRUCTURE_NAME,
	PercentageFormulaError,
	number,
	percentage_formulas,
)

try:  # v16
	from frappe.tests import IntegrationTestCase, UnitTestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase
	from frappe.tests.utils import FrappeTestCase as UnitTestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11S"
GROSS = 38500
EXPECTED = {
	"Basic": 15400,
	"Dearness Allowance": 3850,
	"House Rent Allowance": 6160,
	"Transport Allowance": 1925,
	"Medical Allowance": 1540,
	"Special Allowance": 1925,
	"Fixed Variable": 7700,
}


def row(idx, component, percent=None, of=None):
	return frappe._dict({"idx": idx, "salary_component": component, PERCENT: percent, PERCENT_OF: of})


class TestPercentageFormulas(UnitTestCase):
	def test_chain_down_to_gross(self):
		basic, da, fixed = row(1, "Basic", 40), row(2, "Dearness Allowance", 25, "Basic"), row(3, "Fixed", None)
		formulas = {r.salary_component: f for r, f in percentage_formulas([basic, da, fixed])}
		self.assertEqual(formulas["Basic"], "base * 40 / 100")
		self.assertEqual(formulas["Dearness Allowance"], "base * 40 / 100 * 25 / 100")
		self.assertNotIn("Fixed", formulas)  # no Percentage: keeps its own formula

	def test_number_format(self):
		self.assertEqual(number(40.0), "40")
		self.assertEqual(number(12.5), "12.5")
		self.assertEqual(number("0"), "0")

	def test_payslip_example_adds_up_to_gross(self):
		rows = [row(i, c, p, of) for i, (c, _abbr, p, of) in enumerate(EARNINGS, 1)]
		amounts = {r.salary_component: eval(f, {"base": GROSS}) for r, f in percentage_formulas(rows)}  # noqa: S307
		self.assertEqual(amounts, EXPECTED)
		self.assertEqual(sum(amounts.values()), GROSS)

	def test_errors(self):
		cases = {
			"not in structure": [row(1, "Dearness Allowance", 25, "Basic")],
			"no percentage": [row(1, "Basic"), row(2, "Dearness Allowance", 25, "Basic")],
			"itself": [row(1, "A", 10, "B"), row(2, "B", 10, "A")],
		}
		for case, rows in cases.items():
			with self.subTest(case=case), self.assertRaises(PercentageFormulaError):
				percentage_formulas(rows)


class TestDefaultSalaryStructure(IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint("p11s")
		self.addCleanup(frappe.db.rollback, save_point="p11s")

	def test_structure_and_grades(self):
		structure = frappe.get_doc("Salary Structure", STRUCTURE_NAME)
		self.assertEqual(structure.docstatus, 1)
		self.assertEqual(structure.is_active, "Yes")
		self.assertEqual([r.salary_component for r in structure.earnings], list(EXPECTED))
		self.assertFalse(structure.deductions)
		grades = frappe.get_all("Employee Grade", pluck="default_salary_structure")
		self.assertTrue(grades)
		self.assertEqual(set(grades), {STRUCTURE_NAME})

	def employee_with_assignment(self, base=GROSS):
		from_date = get_first_day(add_months(getdate(), -2))
		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} Payslip",
				"company": COMPANY,
				"gender": "Male",
				"date_of_birth": "1990-01-15",
				"date_of_joining": add_months(from_date, -12),
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		assignment = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": employee.name,
				"salary_structure": STRUCTURE_NAME,
				"company": COMPANY,
				"from_date": from_date,
				"base": base,
				"currency": "INR",
			}
		)
		assignment.flags.ignore_permissions = True
		assignment.insert()
		assignment.submit()
		return employee.name, from_date

	def preview(self, employee, posting_date):
		from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

		slip = make_salary_slip(STRUCTURE_NAME, employee=employee, posting_date=posting_date, for_preview=1)
		# full month: the earnings as the structure gives them, before payment-day proration
		return {e.salary_component: e.default_amount for e in slip.earnings}, slip

	def test_preview_salary_slip_for_38500(self):
		employee, from_date = self.employee_with_assignment()
		earnings, slip = self.preview(employee, add_months(from_date, 1))
		self.assertEqual(earnings, EXPECTED)
		self.assertEqual(sum(earnings.values()), GROSS)

	def test_percentage_changed_after_submit(self):
		structure = frappe.get_doc("Salary Structure", STRUCTURE_NAME)
		basic = next(r for r in structure.earnings if r.salary_component == "Basic")
		basic.set(PERCENT, 50)
		structure.save(ignore_permissions=True)

		formulas = dict(
			frappe.get_all(
				"Salary Detail",
				filters={"parent": STRUCTURE_NAME, "parenttype": "Salary Structure"},
				fields=["salary_component", "formula"],
				as_list=True,
			)
		)
		self.assertEqual(formulas["Basic"], "base * 50 / 100")
		self.assertEqual(formulas["Dearness Allowance"], "base * 50 / 100 * 25 / 100")

		employee, from_date = self.employee_with_assignment()
		earnings, _slip = self.preview(employee, add_months(from_date, 1))
		self.assertEqual(earnings["Basic"], 19250)
		self.assertEqual(earnings["Dearness Allowance"], 4812.5)
