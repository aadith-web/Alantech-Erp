# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales Person from Employee (alantech_erp.sales.sales_person).

Run:
    bench --site <site> run-tests --module alantech_erp.tests.test_sales_person

Uses TEST-SP- employee numbers; everything is rolled back after each test.
"""

import frappe

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.sales.sales_person import is_sales_department, root_sales_person, sales_person_of


def _company():
	from alantech_erp.setup.shifts import COMPANY

	return COMPANY if frappe.db.exists("Company", COMPANY) else frappe.db.get_value("Company", {}, "name")


def _department(name, company):
	return frappe.db.get_value("Department", {"department_name": name, "company": company}, "name")


class TestSalesPerson(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _company()
		cls.sales = _department("Sales", cls.company)
		cls.marketing = _department("Marketing", cls.company)
		if not (cls.sales and cls.marketing):
			raise Exception("Run bench migrate first: Sales / Marketing departments are missing")

	def tearDown(self):
		frappe.db.rollback()

	def make_employee(self, number, first, designation, department, reports_to=None, last="Tester"):
		emp = frappe.get_doc(
			{
				"doctype": "Employee",
				"employee_number": f"TEST-SP-{number}",
				"first_name": first,
				"last_name": last,
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": "2024-01-01",
				"company": self.company,
				"designation": designation,
				"department": department,
				"reports_to": reports_to,
			}
		)
		emp.insert(ignore_permissions=True)
		return emp

	def test_01_sales_employee_gets_sales_person(self):
		emp = self.make_employee("01", "Spone", "Sales Engineer", self.sales)
		name = sales_person_of(emp.name)
		self.assertTrue(name)
		sp = frappe.get_doc("Sales Person", name)
		self.assertEqual(sp.sales_person_name, emp.employee_name)
		self.assertEqual(sp.department, self.sales)
		self.assertEqual(sp.enabled, 1)
		self.assertEqual(sp.is_group, 0)

	def test_02_other_department_gets_none(self):
		emp = self.make_employee("02", "Sptwo", "Marketing Executive", self.marketing)
		self.assertFalse(sales_person_of(emp.name))
		self.assertFalse(is_sales_department(self.marketing))

	def test_03_tree_follows_reports_to(self):
		head = self.make_employee("03", "Sphead", "Sales Manager", self.sales)
		rep = self.make_employee("04", "Sprep", "Sales Engineer", self.sales, reports_to=head.name)
		head_sp, rep_sp = sales_person_of(head.name), sales_person_of(rep.name)
		self.assertEqual(frappe.db.get_value("Sales Person", head_sp, "is_group"), 1)
		self.assertEqual(frappe.db.get_value("Sales Person", rep_sp, "parent_sales_person"), head_sp)

	def test_04_manager_outside_sales_means_root(self):
		boss = self.make_employee("05", "Spboss", "Marketing Manager", self.marketing)
		rep = self.make_employee("06", "Sprep2", "Sales Engineer", self.sales, reports_to=boss.name)
		self.assertEqual(
			frappe.db.get_value("Sales Person", sales_person_of(rep.name), "parent_sales_person"),
			root_sales_person(),
		)

	def test_05_leaving_sales_disables_and_returning_enables(self):
		emp = self.make_employee("07", "Spmove", "Sales Engineer", self.sales)
		name = sales_person_of(emp.name)
		emp.reload()
		emp.department = self.marketing
		emp.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Sales Person", name, "enabled"), 0)

		emp.reload()
		emp.department = self.sales
		emp.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Sales Person", name, "enabled"), 1)
		self.assertEqual(sales_person_of(emp.name), name)  # same record, not a new one

	def test_06_left_employee_disabled(self):
		emp = self.make_employee("08", "Spleft", "Sales Engineer", self.sales)
		emp.reload()
		emp.status = "Left"
		emp.relieving_date = "2026-01-31"
		emp.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Sales Person", sales_person_of(emp.name), "enabled"), 0)

	def test_07_same_name_gets_unique_sales_person(self):
		first = self.make_employee("09", "Spsame", "Sales Engineer", self.sales, last="Twin")
		second = self.make_employee("10", "Spsame", "Sales Engineer", self.sales, last="Twin")
		self.assertEqual(sales_person_of(first.name), "Spsame Twin")
		self.assertEqual(sales_person_of(second.name), f"Spsame Twin - {second.name}")

	def test_08_delete_employee_not_blocked(self):
		emp = self.make_employee("11", "Spdel", "Sales Engineer", self.sales)
		name = sales_person_of(emp.name)
		frappe.delete_doc("Employee", emp.name, ignore_permissions=True, force=True)
		self.assertIsNone(frappe.db.get_value("Sales Person", name, "employee"))
