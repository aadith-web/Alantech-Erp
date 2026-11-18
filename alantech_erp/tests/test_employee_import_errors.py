# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee import: all errors of the file listed together (setup/employee_import_check.py).

ClickUp: https://app.clickup.com/t/14yr2e587b3

Covered:
- A file with several errors in one row (missing Branch, invalid email, invalid mobile, underage)
  and errors in several rows lists every error, each with its row and field.
- The same email / Employee Number on two rows of the file is reported on the later row.
- Errors block the import (no row imported, status back to Pending, warnings saved), unless the
  row is skipped; a clean file imports (also covered by test_employee_import_template).
- The check leaves nothing behind: no employee, no E### number used up, no messages.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_import_errors

Data: every test runs in a savepoint that is rolled back; Data Import's per-row commit is patched.
"""

import json
from unittest.mock import patch

import frappe

from alantech_erp.setup.employee_import_check import check_import_file

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11E"
HEADER = "First Name,Company,Gender,Date of Birth,Date of Joining,Status,Personal Email,Mobile\n"


class TestEmployeeImportErrors(TestCase):
	def setUp(self):
		frappe.db.savepoint("p11e")
		self.addCleanup(frappe.db.rollback, save_point="p11e")
		frappe.flags.alt_check_employee_required = True
		self.addCleanup(setattr, frappe.flags, "alt_check_employee_required", False)

	def data_import(self, csv, tag):
		file_doc = frappe.get_doc(
			{"doctype": "File", "file_name": f"p11e_{tag}.csv", "content": csv, "is_private": 1}
		).insert(ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Data Import",
				"reference_doctype": "Employee",
				"import_type": "Insert New Records",
				"import_file": file_doc.file_url,
			}
		).insert(ignore_permissions=True)

	def errors(self, csv, tag):
		"""{(row, fieldname or None): message} of the employee check for the file."""
		import_file = self.data_import(csv, tag).get_importer().import_file
		return {
			(w["row"], (w.get("field") or {}).get("fieldname")): w["message"]
			for w in check_import_file(import_file)
		}

	def test_all_errors_of_all_rows_listed(self):
		csv = HEADER + (
			f"{PREFIX} One,{COMPANY},Male,1990-01-15,2026-01-05,Active,not-an-email,97153123567\n"
			f"{PREFIX} Two,{COMPANY},Female,2015-01-15,2026-01-05,Active,p11e.two@example.com,+971531235678\n"
		)
		errors = self.errors(csv, "many")

		# row 2: missing fields, invalid email and invalid mobile, all at once
		for field in ("branch", "department", "designation", "grade", "employment_type", "alt_nationality"):
			self.assertIn((2, field), errors)
		self.assertIn("not-an-email", errors[(2, "personal_email")])
		self.assertIn("+97153123567", errors[(2, "cell_number")])
		self.assertIn("United Arab Emirates", errors[(2, "cell_number")])
		# row 3: under 18, and the same missing fields
		self.assertIn("at least 18", errors[(3, "date_of_birth")])
		self.assertIn((3, "branch"), errors)
		self.assertNotIn((3, "cell_number"), errors)
		self.assertNotIn((3, "personal_email"), errors)

	def test_duplicate_in_file_reported_on_later_row(self):
		csv = HEADER + (
			f"{PREFIX} A,{COMPANY},Male,1990-01-15,2026-01-05,Active,p11e.same@example.com,+971531235678\n"
			f"{PREFIX} B,{COMPANY},Male,1990-01-15,2026-01-05,Active,P11E.Same@example.com,+971531235679\n"
		)
		errors = self.errors(csv, "dup")
		self.assertIn("row 2", errors[(3, "personal_email")])
		self.assertNotIn("row 3", errors.get((2, "personal_email"), ""))

	def test_existing_employee_number_and_email_listed_with_other_errors(self):
		frappe.flags.alt_check_employee_required = False  # a bare employee is enough here
		existing = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} Existing",
				"company": COMPANY,
				"gender": "Male",
				"date_of_birth": "1990-01-15",
				"date_of_joining": "2026-01-05",
				"status": "Active",
				"employee_number": "P11E-001",
				"personal_email": "p11e.existing@example.com",
			}
		).insert(ignore_permissions=True)
		frappe.flags.alt_check_employee_required = True
		csv = (
			"First Name,Company,Gender,Date of Birth,Date of Joining,Status,Employee Number,Personal Email,Mobile\n"
			f"{PREFIX} New,{COMPANY},Male,1990-01-15,2026-01-05,Active,P11E-001,"
			"p11e.existing@example.com,12345\n"
		)
		errors = self.errors(csv, "existing")
		self.assertIn(existing.name, errors[(2, "employee_number")])
		self.assertIn(existing.name, errors[(2, "personal_email")])
		self.assertIn((2, "cell_number"), errors)
		self.assertIn((2, "branch"), errors)

	def test_reports_to_by_employee_name(self):
		"""Reports To written as the manager's name (as the import accepts) is checked as that
		employee; a name of another row of the file is not checked yet."""
		frappe.flags.alt_check_employee_required = False
		boss = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} Boss",
				"company": COMPANY,
				"gender": "Female",
				"date_of_birth": "1985-01-15",
				"date_of_joining": "2020-01-05",
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		csv = (
			"First Name,Company,Gender,Date of Birth,Date of Joining,Status,Reports to\n"
			f"{PREFIX} Lead,{COMPANY},Male,1990-01-15,2026-01-05,Active,{boss.employee_name}\n"
			f"{PREFIX} Member,{COMPANY},Male,1990-01-15,2026-01-05,Active,{PREFIX} Lead\n"
		)
		with patch("alantech_erp.setup.reports_to.rule_active", return_value=True), patch(
			"alantech_erp.setup.reports_to.is_manager", side_effect=lambda employee: employee == boss.name
		):
			errors = self.errors(csv, "reports_to")
		self.assertNotIn((2, "reports_to"), errors)
		self.assertNotIn((3, "reports_to"), errors)

	def test_errors_block_import_and_leave_nothing_behind(self):
		csv = HEADER + f"{PREFIX} Block,{COMPANY},Male,1990-01-15,2026-01-05,Active,bad-email,12345\n"
		counter = frappe.db.get_value("Series", "alt_employee_number", "current", order_by=None)
		data_import = self.data_import(csv, "block")

		preview = data_import.get_preview_from_template()
		messages = [w["message"] for w in preview.warnings if w.get("row") == 2]
		self.assertTrue(any("bad-email" in m for m in messages), messages)
		self.assertTrue(any("12345" in m for m in messages), messages)

		with patch.object(frappe.db, "commit"):
			data_import.get_importer().import_data()
		data_import.reload()
		self.assertEqual(data_import.status, "Pending")
		self.assertFalse(frappe.db.exists("Employee", {"first_name": f"{PREFIX} Block"}))
		self.assertFalse(frappe.get_all("Data Import Log", filters={"data_import": data_import.name}))
		saved = json.loads(data_import.template_warnings)
		self.assertTrue(any("bad-email" in w["message"] for w in saved))
		self.assertEqual(
			frappe.db.get_value("Series", "alt_employee_number", "current", order_by=None), counter
		)
		self.assertFalse(frappe.local.message_log)
