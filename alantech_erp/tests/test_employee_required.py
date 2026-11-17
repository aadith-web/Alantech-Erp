# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Fields needed to create an employee (employee_validation.validate_required_on_create), and the
minimum age of 18 on the Date of Joining (employee_validation.validate_minimum_age).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_required

Nothing is kept: inserts are rolled back after each test.
"""

import frappe

from alantech_erp.setup.employee_validation import UnderageEmployeeError, age_on

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"


def full_employee(**changes):
	"""A new employee with every required field, copied from an existing active one."""
	ref = frappe.get_all(
		"Employee",
		filters={
			"company": COMPANY, "status": "Active", "designation": ["!=", "Managing Director"],
			"branch": ["is", "set"], "employment_type": ["is", "set"], "reports_to": ["is", "set"],
			"department": ["is", "set"],
		},
		fields=["designation", "department", "branch", "reports_to", "employment_type"],
		limit=1,
	)[0]
	values = {
		"doctype": "Employee",
		"first_name": "Reqtest",
		"gender": "Male",
		"date_of_birth": "1995-01-01",
		"date_of_joining": "2024-01-01",
		"company": COMPANY,
		"status": "Active",
		"cell_number": "+91-9847012345",
		"personal_email": "reqtest@example.com",
		"create_user_automatically": 0,
		"default_shift": "General Shift",
		"grade": frappe.db.get_value("Employee Grade", {}, "name"),
		"alt_nationality": "India",  # mandatory too (setup/employee_nationality.py)
		"alt_aadhaar_number": "234567890124",  # Indian nationals: Aadhaar + PAN
		"pan_number": "ABCPE1234F",
		**ref,
		**changes,
	}
	return frappe.get_doc(values)


class TestEmployeeRequired(TestCase):
	def setUp(self):
		frappe.flags.alt_check_employee_required = True

	def tearDown(self):
		frappe.flags.alt_check_employee_required = False
		frappe.db.rollback()

	def test_complete_employee_is_created(self):
		self.assertTrue(full_employee().insert(ignore_permissions=True).name)

	def test_missing_fields_are_listed(self):
		emp = full_employee(branch=None, employment_type=None)
		with self.assertRaises(frappe.MandatoryError) as e:
			emp.insert(ignore_permissions=True)
		self.assertIn("Branch", str(e.exception))
		self.assertIn("Employment Type", str(e.exception))

	def test_grade_needed(self):
		with self.assertRaises(frappe.MandatoryError) as e:
			full_employee(grade=None).insert(ignore_permissions=True)
		self.assertIn("Grade", str(e.exception))

	def test_email_needed(self):
		with self.assertRaises(frappe.MandatoryError):
			full_employee(personal_email=None).insert(ignore_permissions=True)

	def test_existing_employee_still_saves(self):
		emp = full_employee().insert(ignore_permissions=True)
		emp.db_set("branch", None)
		emp.reload()
		emp.save(ignore_permissions=True)  # no error: only new employees are checked


class TestEmployeeMinimumAge(TestCase):
	"""Checked in every test run (no flag): no test employee is under 18."""

	def tearDown(self):
		frappe.db.rollback()

	def test_age_on(self):
		self.assertEqual(age_on("2008-01-05", "2026-01-04"), 17)
		self.assertEqual(age_on("2008-01-05", "2026-01-05"), 18)
		# born on 29 February: the birthday is 28 February in other years
		self.assertEqual(age_on("2008-02-29", "2026-02-27"), 17)
		self.assertEqual(age_on("2008-02-29", "2026-02-28"), 18)

	def test_under_18_on_joining_refused(self):
		emp = full_employee(date_of_birth="2008-01-06", date_of_joining="2026-01-05")
		with self.assertRaises(UnderageEmployeeError) as e:
			emp.insert(ignore_permissions=True)
		message = str(e.exception)
		self.assertIn("at least 18 years old on the Date of Joining", message)
		self.assertIn("they are 17", message)

	def test_18th_birthday_on_joining_allowed(self):
		emp = full_employee(date_of_birth="2008-01-05", date_of_joining="2026-01-05")
		self.assertTrue(emp.insert(ignore_permissions=True).name)

	def test_changing_dates_checked_on_edit(self):
		emp = full_employee(date_of_birth="2000-01-01", date_of_joining="2024-01-01").insert(ignore_permissions=True)
		emp.reload()
		emp.date_of_birth = "2010-01-01"
		with self.assertRaises(UnderageEmployeeError):
			emp.save(ignore_permissions=True)
		emp.reload()
		emp.date_of_joining = "2017-01-01"  # joined at 17
		with self.assertRaises(UnderageEmployeeError):
			emp.save(ignore_permissions=True)

	def test_older_record_with_other_changes_still_saved(self):
		emp = full_employee(date_of_birth="2000-01-01", date_of_joining="2024-01-01").insert(ignore_permissions=True)
		emp.db_set("date_of_birth", "2010-01-01")  # bad date saved before this rule
		emp.reload()
		emp.middle_name = "Changed"
		emp.save(ignore_permissions=True)
