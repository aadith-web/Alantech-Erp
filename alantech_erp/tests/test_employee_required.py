# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Fields needed to create an employee (employee_validation.validate_required_on_create).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_required

Nothing is kept: inserts are rolled back after each test.
"""

import frappe

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

	def test_email_needed(self):
		with self.assertRaises(frappe.MandatoryError):
			full_employee(personal_email=None).insert(ignore_permissions=True)

	def test_existing_employee_still_saves(self):
		emp = full_employee().insert(ignore_permissions=True)
		emp.db_set("branch", None)
		emp.reload()
		emp.save(ignore_permissions=True)  # no error: only new employees are checked
