# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Mandatory Fields: payroll fields (part 2) and the import template (part 1).

ClickUp: https://app.clickup.com/t/14yr2e57mhp

Covered:
- missing_payroll_fields: always-needed fields, bank fields only for Salary Mode Bank (either IFSC
  field), Contract End Date only for Employment Type Contract.
- Confirmation Date filled from Date of Joining + Probation Period, never overwritten.
- Salary Structure Assignment / Payroll Entry submit and a hand-made Salary Slip are refused for an
  employee missing payroll fields (one line per employee); a Payroll Entry slip is not re-checked.
- Every field needed to create an employee is ticked in the import template (in_import_template).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_payroll_fields

Data: TEST-P12 employees, inside a savepoint rolled back after each test.
"""

import frappe
from frappe.utils import getdate

from alantech_erp.setup import employee_payroll_fields as epf
from alantech_erp.setup.employee_validation import REQUIRED_ON_CREATE

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P12"

COMPLETE = {
	"salary_mode": "Cash",
	"pan_number": "ABCDE1234F",
	"grade": "G1",
	"payroll_cost_center": "Main - AIIPL",
	"holiday_list": "HL",
	"alt_pf_gratuity_reference_date": "2026-01-05",
	"final_confirmation_date": "2026-07-05",
	"employment_type": "Full-time",
}


def employee(**values):
	return frappe._dict({**COMPLETE, **values})


class TestMissingPayrollFields(TestCase):
	def test_complete_cash_employee(self):
		self.assertEqual(epf.missing_payroll_fields(employee()), [])

	def test_always_needed(self):
		blank = {field: None for field in epf.PAYROLL_REQUIRED}
		missing = epf.missing_payroll_fields(employee(**blank))
		self.assertEqual(
			missing,
			[
				"Salary Mode",
				"PAN Number",
				"Grade",
				"Payroll Cost Center",
				"Holiday List",
				"PF / Gratuity Reference Date",
				"Confirmation Date",
			],
		)

	def test_bank_fields_only_for_bank(self):
		missing = epf.missing_payroll_fields(employee(salary_mode="Bank"))
		self.assertEqual(missing, ["Bank Name", "Bank Branch", "Bank A/C No.", "IFSC Code"])
		filled = employee(
			salary_mode="Bank", bank_name="SBI", alt_bank_branch="Kochi", bank_ac_no="123", alt_ifsc_code="SBIN0000001"
		)
		self.assertEqual(epf.missing_payroll_fields(filled), [])
		# HRMS's own IFSC field is enough too
		filled.alt_ifsc_code, filled.ifsc_code = None, "SBIN0000001"
		self.assertEqual(epf.missing_payroll_fields(filled), [])

	def test_contract_end_date_only_for_contract(self):
		self.assertEqual(epf.missing_payroll_fields(employee(employment_type="Contract")), ["Contract End Date"])
		self.assertEqual(
			epf.missing_payroll_fields(employee(employment_type="Contract", contract_end_date="2027-01-01")), []
		)

	def test_blank_text_counts_as_missing(self):
		self.assertEqual(epf.missing_payroll_fields(employee(pan_number="  ")), ["PAN Number"])


class TestConfirmationDate(TestCase):
	def test_filled_from_probation(self):
		doc = frappe._dict(date_of_joining="2026-01-31", alt_probation_period=6, final_confirmation_date=None)
		epf.fill_confirmation_date(doc)
		self.assertEqual(getdate(doc.final_confirmation_date), getdate("2026-07-31"))

	def test_not_overwritten_or_without_probation(self):
		doc = frappe._dict(date_of_joining="2026-01-31", alt_probation_period=6, final_confirmation_date="2026-03-01")
		epf.fill_confirmation_date(doc)
		self.assertEqual(doc.final_confirmation_date, "2026-03-01")
		doc = frappe._dict(date_of_joining="2026-01-31", alt_probation_period=0, final_confirmation_date=None)
		epf.fill_confirmation_date(doc)
		self.assertIsNone(doc.final_confirmation_date)


class TestPayrollRefused(TestCase):
	def setUp(self):
		frappe.db.savepoint("p12")
		self.addCleanup(frappe.db.rollback, save_point="p12")
		frappe.flags.alt_check_payroll_fields = True
		self.addCleanup(setattr, frappe.flags, "alt_check_payroll_fields", None)
		self.incomplete = self.make_employee("Incomplete")
		self.complete = self.make_employee(
			"Complete",
			salary_mode="Cash",
			pan_number="ABCDE1234F",
			grade=self.any_record("Employee Grade"),
			payroll_cost_center=frappe.get_cached_value("Company", COMPANY, "cost_center"),
			holiday_list=self.any_record("Holiday List"),
			alt_pf_gratuity_reference_date="2026-01-05",
			alt_probation_period=3,
		)

	def any_record(self, doctype):
		name = frappe.db.get_value(doctype, {}, "name")
		if not name:
			self.skipTest(f"no {doctype} on this site")
		return name

	def make_employee(self, first_name, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} {first_name}",
				"gender": "Male",
				"date_of_birth": "1990-01-15",
				"date_of_joining": "2026-01-05",
				"company": COMPANY,
				"status": "Active",
				"create_user_automatically": 0,
				**values,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def test_probation_fills_confirmation_on_save(self):
		self.assertEqual(
			getdate(frappe.db.get_value("Employee", self.complete, "final_confirmation_date")), getdate("2026-04-05")
		)

	def test_salary_structure_assignment_refused(self):
		with self.assertRaises(epf.PayrollFieldsMissingError) as raised:
			epf.salary_structure_assignment_before_submit(frappe._dict(employee=self.incomplete))
		message = str(raised.exception)
		self.assertIn("assigning a salary structure", message)
		self.assertIn("PAN Number", message)
		epf.salary_structure_assignment_before_submit(frappe._dict(employee=self.complete))

	def test_payroll_entry_lists_each_incomplete_employee(self):
		other = self.make_employee("Incomplete Two")
		rows = [frappe._dict(employee=e) for e in (self.complete, self.incomplete, other, self.incomplete)]
		with self.assertRaises(epf.PayrollFieldsMissingError) as raised:
			epf.payroll_entry_before_submit(frappe._dict(employees=rows))
		message = str(raised.exception)
		self.assertIn("running payroll", message)
		self.assertEqual(message.count("<li>"), 2)  # duplicates once, complete employee not listed
		self.assertNotIn(self.complete, message)
		epf.payroll_entry_before_submit(frappe._dict(employees=[frappe._dict(employee=self.complete)]))

	def test_salary_slip_hand_made_only(self):
		slip = frappe.new_doc("Salary Slip")
		slip.employee = self.incomplete
		with self.assertRaises(epf.PayrollFieldsMissingError):
			epf.salary_slip_validate(slip)
		slip.payroll_entry = "HR-PRUN-TEST"
		epf.salary_slip_validate(slip)

	def test_skipped_in_other_tests(self):
		frappe.flags.alt_check_payroll_fields = None
		epf.salary_structure_assignment_before_submit(frappe._dict(employee=self.incomplete))


class TestImportTemplate(TestCase):
	def test_fields_to_create_ticked(self):
		frappe.clear_cache(doctype="Employee")
		meta = frappe.get_meta("Employee")
		for field in REQUIRED_ON_CREATE + epf.IMPORT_TEMPLATE_FIELDS:
			self.assertTrue(meta.get_field(field).in_import_template, field)

	def test_new_fields_exist(self):
		meta = frappe.get_meta("Employee")
		self.assertEqual(meta.get_field("alt_bank_branch").fieldtype, "Data")
		self.assertEqual(meta.get_field("alt_pf_gratuity_reference_date").fieldtype, "Date")
		self.assertEqual(meta.get_field("alt_probation_period").fieldtype, "Int")
