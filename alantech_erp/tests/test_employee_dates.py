# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Offer Date / Date of Joining / Probation Period / Confirmation Date (setup/employee_dates.py).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_dates

Unit: the expected Confirmation Date. Integration: the rules on a real Employee save (new and
changed), and an unrelated edit of an employee with older inconsistent dates is not blocked.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import getdate

from alantech_erp.setup.employee_dates import EmployeeDateError, expected_confirmation, inconsistent_employees

PREFIX = "TEST-EDATES"


class UnitTestExpectedConfirmation(UnitTestCase):
	def test_joining_plus_months(self):
		self.assertEqual(expected_confirmation("2026-01-05", 3), getdate("2026-04-05"))
		self.assertEqual(expected_confirmation("2026-01-31", 1), getdate("2026-02-28"))  # month end
		self.assertIsNone(expected_confirmation("2026-01-05", 0))
		self.assertIsNone(expected_confirmation(None, 3))


class IntegrationTestEmployeeDates(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("edates")
		self.addCleanup(frappe.db.rollback, save_point="edates")
		self.company = frappe.db.get_value("Company", {}, "name")

	def make(self, **values):
		return frappe.get_doc({
			"doctype": "Employee",
			"first_name": f"{PREFIX} {frappe.generate_hash(length=5)}",
			"gender": "Male",
			"date_of_birth": "1990-01-15",
			"date_of_joining": "2026-01-05",
			"company": self.company,
			"status": "Active",
			"create_user_automatically": 0,
			**values,
		}).insert(ignore_permissions=True)

	def assert_refused(self, text, **values):
		with self.assertRaises(EmployeeDateError) as raised:
			self.make(**values)
		self.assertIn(text, str(raised.exception))

	def test_offer_date_on_or_before_joining(self):
		self.assert_refused("cannot be after the Date of Joining", scheduled_confirmation_date="2026-01-06")
		self.assertEqual(str(self.make(scheduled_confirmation_date="2026-01-05").scheduled_confirmation_date), "2026-01-05")
		self.make(scheduled_confirmation_date="2025-12-01")

	def test_confirmation_after_joining(self):
		self.assert_refused("must be after the Date of Joining", final_confirmation_date="2026-01-05")
		self.assert_refused("must be after the Date of Joining", final_confirmation_date="2025-12-31")
		self.make(final_confirmation_date="2026-01-06")

	def test_probation_fills_and_must_match(self):
		doc = self.make(alt_probation_period=3)
		self.assertEqual(getdate(doc.final_confirmation_date), getdate("2026-04-05"))
		self.assert_refused("Confirmation Date must be", alt_probation_period=6, final_confirmation_date="2026-03-01")
		self.make(alt_probation_period=6, final_confirmation_date="2026-07-05")  # matches

	def test_confirmation_follows_joining_and_probation_changes(self):
		doc = self.make(alt_probation_period=3)
		doc.date_of_joining = "2026-02-01"
		doc.save(ignore_permissions=True)
		self.assertEqual(getdate(doc.final_confirmation_date), getdate("2026-05-01"))
		doc.alt_probation_period = 6
		doc.save(ignore_permissions=True)
		self.assertEqual(getdate(doc.final_confirmation_date), getdate("2026-08-01"))
		doc.final_confirmation_date = "2026-09-01"  # by hand while a probation is set
		with self.assertRaises(EmployeeDateError):
			doc.save(ignore_permissions=True)

	def test_clearing_probation_allows_any_later_confirmation(self):
		doc = self.make(alt_probation_period=3)
		doc.alt_probation_period = 0
		doc.final_confirmation_date = "2026-10-01"
		doc.save(ignore_permissions=True)
		self.assertEqual(getdate(doc.final_confirmation_date), getdate("2026-10-01"))

	def test_unrelated_edit_of_older_record_not_blocked(self):
		doc = self.make()
		frappe.db.set_value("Employee", doc.name, "scheduled_confirmation_date", "2026-03-01")  # older bad data
		doc = frappe.get_doc("Employee", doc.name)
		doc.middle_name = "X"
		doc.save(ignore_permissions=True)  # not blocked
		self.assertIn(doc.name, [e["name"] for e in inconsistent_employees()])
		doc.scheduled_confirmation_date = "2026-02-01"  # touching the date: checked
		with self.assertRaises(EmployeeDateError):
			doc.save(ignore_permissions=True)
