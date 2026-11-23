# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Edit Salary Structure: new assignment from a new From Date, or correct (cancel and amend) the
current one (setup/salary_structure_view.revise_salary_structure, mode "new" / "amend").

ClickUp: https://app.clickup.com/t/14yr2e586vb (sign-off point "Edit makes a new assignment from a new
From Date (keeps history); confirm, or ask for cancel-and-amend": both offered, HR picks per edit).

Covered:
- amend: the current assignment is cancelled; an amended copy (amended_from, same From Date) with the
  new sub band's gross, the state and the cost centers is submitted and becomes the active one.
- amend refused once a submitted salary slip uses the assignment (nothing cancelled).
- new (default) unchanged: a later From Date is required, the old assignment stays.
- only the HR Manager; an unknown mode is refused.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_salary_structure_amend

Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.utils import add_months, get_first_day, getdate

from alantech_erp.setup.default_salary_structure import STRUCTURE_NAME
from alantech_erp.setup.salary_structure_button import get_active_assignment
from alantech_erp.setup.salary_structure_popup import (
	SUB_BAND,
	SalaryStructurePopupError,
	create_salary_structure_assignment,
	get_grade_details,
)
from alantech_erp.setup.salary_structure_view import revise_salary_structure

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11AM"
GRADE = "L1-B1"


class TestSalaryStructureAmend(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("p11am")
		self.addCleanup(frappe.db.rollback, save_point="p11am")
		self.addCleanup(frappe.set_user, "Administrator")
		self.from_date = get_first_day(add_months(getdate(), -2))
		self.gross = {r.sub_band: r.gross_amount for r in get_grade_details(GRADE)["sub_bands"]}
		self.emp = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} Amend",
				"company": COMPANY,
				"gender": "Male",
				"date_of_birth": "1990-01-15",
				"date_of_joining": add_months(getdate(), -24),
				"status": "Active",
				"grade": GRADE,
			}
		).insert(ignore_permissions=True).name
		self.current = create_salary_structure_assignment(
			self.emp, GRADE, "A", self.from_date, employment_state="Karnataka"
		)["name"]

	def test_amend_replaces_the_current_assignment(self):
		result = revise_salary_structure(self.emp, "D", mode="amend")
		old = frappe.get_doc("Salary Structure Assignment", self.current)
		new = frappe.get_doc("Salary Structure Assignment", result["name"])
		self.assertEqual(old.docstatus, 2)
		self.assertEqual(result["amended_from"], self.current)
		self.assertEqual(
			(new.docstatus, new.amended_from, getdate(new.from_date), new.base, new.get(SUB_BAND)),
			(1, self.current, self.from_date, self.gross["D"], "D"),
		)
		self.assertEqual(new.get("employment_state"), "Karnataka")  # kept: none chosen
		self.assertEqual(get_active_assignment(self.emp).name, new.name)

	def test_amend_refused_once_a_salary_slip_uses_it(self):
		"""A real salary slip of the assignment's period, made and submitted through HRMS."""
		from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

		slip = make_salary_slip(STRUCTURE_NAME, employee=self.emp, posting_date=add_months(self.from_date, 1))
		slip.flags.ignore_permissions = True
		slip.insert()
		slip.submit()
		with self.assertRaises(SalaryStructurePopupError) as raised:
			revise_salary_structure(self.emp, "D", mode="amend")
		self.assertIn("submitted salary slips already use it", str(raised.exception))
		self.assertIn(slip.name, str(raised.exception))
		self.assertEqual(frappe.db.get_value("Salary Structure Assignment", self.current, "docstatus"), 1)

	def test_new_assignment_unchanged(self):
		with self.assertRaises(SalaryStructurePopupError):
			revise_salary_structure(self.emp, "B", self.from_date)  # not after the current From Date
		result = revise_salary_structure(self.emp, "B", add_months(self.from_date, 1))
		self.assertNotIn("amended_from", result)
		self.assertEqual(frappe.db.get_value("Salary Structure Assignment", self.current, "docstatus"), 1)

	def test_only_hr_manager_and_known_modes(self):
		with self.assertRaises(SalaryStructurePopupError):
			revise_salary_structure(self.emp, "D", mode="rewrite")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "p11am.hruser@example.com",
				"first_name": f"{PREFIX} HR User",
				"send_welcome_email": 0,
				"roles": [{"role": "HR User"}, {"role": "Employee"}],
			}
		).insert(ignore_permissions=True).name
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			revise_salary_structure(self.emp, "D", mode="amend")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Salary Structure Assignment", self.current, "docstatus"), 1)
