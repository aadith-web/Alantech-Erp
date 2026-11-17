# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee import template: Series pre-filled with HR-EMP-, Employee Number ticked.

ClickUp: https://app.clickup.com/t/14yr2e57mja (parent: https://app.clickup.com/t/14yr2e56b2e)

Covered:
- Series (naming_series) stays mandatory on the Employee form.
- Download Template (blank, Employee, Series chosen) comes with Series pre-filled HR-EMP-
  (setup/employee_import.download_template); other doctypes / exports are unchanged.
- Import skips pre-filled rows the user left unused (Series the only filled cell), so they do not
  fail as employees without a name (setup/employee_import.AlantechDataImport).
- Employee Number is ticked by "Select Mandatory" (in_import_template) but stays optional, also
  after an HR Settings save.
- Data Import with a blank Series cell, or no Series column, and a blank Employee Number creates
  the employee with the default HR-EMP- series and the next E### Employee Number.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_import_template

Data: the import runs with Data Import's per-row commit switched off and is rolled back, so no
employee is kept and no E### number is used up. HR Settings changes are rolled back too.
"""

import csv
import io
import re
from unittest.mock import patch

import frappe

from alantech_erp.setup.employee_import import PREFILLED_ROWS, download_template

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11"


def employee_df(fieldname):
	frappe.clear_cache(doctype="Employee")
	return frappe.get_meta("Employee").get_field(fieldname)


class TestEmployeeImportTemplate(TestCase):
	def rollback_after_test(self, name):
		frappe.db.savepoint(name)
		self.addCleanup(frappe.clear_cache, doctype="Employee")
		self.addCleanup(frappe.db.rollback, save_point=name)

	def test_01_series_mandatory_on_form(self):
		self.assertTrue(employee_df("naming_series").reqd)

	def test_02_employee_number_in_template_but_optional(self):
		df = employee_df("employee_number")
		self.assertTrue(df.in_import_template)
		self.assertFalse(df.reqd)
		self.assertFalse(df.hidden)

	def test_03_hr_settings_save_keeps_template_settings(self):
		self.rollback_after_test("p11_hr_settings")
		settings = frappe.get_single("HR Settings")
		settings.emp_created_by = "Naming Series"
		settings.save(ignore_permissions=True)

		self.assertTrue(employee_df("naming_series").reqd)
		df = employee_df("employee_number")
		self.assertTrue(df.in_import_template)
		self.assertFalse(df.reqd)

	def import_employee(self, csv, tag):
		"""Insert-import csv in this test's transaction; return the Data Import Log rows."""
		file_doc = frappe.get_doc(
			{"doctype": "File", "file_name": f"p11_{tag}.csv", "content": csv, "is_private": 1}
		).insert(ignore_permissions=True)
		data_import = frappe.get_doc(
			{
				"doctype": "Data Import",
				"reference_doctype": "Employee",
				"import_type": "Insert New Records",
				"import_file": file_doc.file_url,
			}
		).insert(ignore_permissions=True)

		# Data Import commits after every row; keep it all in this test's transaction
		with patch.object(frappe.db, "commit"):
			data_import.get_importer().import_data()

		return frappe.get_all(
			"Data Import Log", filters={"data_import": data_import.name}, fields=["success", "messages"]
		)

	def assert_imported_with_defaults(self, first_name, logs):
		self.assertEqual(len(logs), 1, logs)
		self.assertTrue(logs[0].success, logs[0].messages)
		employee = frappe.get_doc("Employee", {"first_name": first_name})
		self.assertEqual(employee.naming_series, "HR-EMP-")
		self.assertTrue(employee.name.startswith("HR-EMP-"), employee.name)
		self.assertRegex(employee.employee_number, re.compile(r"^E\d{3,}$"))

	def test_04_import_with_blank_series_and_employee_number(self):
		self.rollback_after_test("p11_import_blank")
		first_name = f"{PREFIX} Blank"
		csv = (
			"Series,Employee Number,First Name,Company,Gender,Date of Birth,Date of Joining,Status\n"
			f",,{first_name},{COMPANY},Male,1990-01-15,2026-01-05,Active\n"
		)
		self.assert_imported_with_defaults(first_name, self.import_employee(csv, "blank"))

	def test_05_import_without_series_column(self):
		self.rollback_after_test("p11_import_nocol")
		first_name = f"{PREFIX} No Series"
		csv = (
			"First Name,Company,Gender,Date of Birth,Date of Joining,Status\n"
			f"{first_name},{COMPANY},Male,1990-01-15,2026-01-05,Active\n"
		)
		self.assert_imported_with_defaults(first_name, self.import_employee(csv, "nocol"))

	def download_csv(self, doctype, fields, export_records="blank_template"):
		frappe.response.pop("result", None)
		download_template(
			doctype,
			export_fields=frappe.as_json({doctype: fields}),
			export_records=export_records,
			file_type="CSV",
		)
		return list(csv.reader(io.StringIO(frappe.response.pop("result"))))

	def test_06_blank_template_has_series_prefilled(self):
		rows = self.download_csv("Employee", ["naming_series", "first_name", "employee_number"])
		header = rows[0]
		series_col = header.index("Series")
		data = [r for r in rows[1:] if any(r)]
		self.assertEqual(len(data), PREFILLED_ROWS)
		for row in data:
			self.assertEqual(row[series_col], "HR-EMP-")
			self.assertEqual([v for i, v in enumerate(row) if i != series_col], ["", ""])

	def test_07_template_without_series_or_other_doctype_unchanged(self):
		rows = self.download_csv("Employee", ["first_name", "employee_number"])
		self.assertFalse([r for r in rows[1:] if any(r)])
		rows = self.download_csv("Designation", ["designation_name"])
		self.assertFalse([r for r in rows[1:] if any(r)])

	def test_08_import_skips_unused_prefilled_rows(self):
		self.rollback_after_test("p11_import_prefilled")
		first_name = f"{PREFIX} Prefilled"
		csv_text = (
			"Series,Employee Number,First Name,Company,Gender,Date of Birth,Date of Joining,Status\n"
			f"HR-EMP-,,{first_name},{COMPANY},Male,1990-01-15,2026-01-05,Active\n"
			"HR-EMP-,,,,,,,\n"
			"HR-EMP-,,,,,,,\n"
		)
		self.assert_imported_with_defaults(first_name, self.import_employee(csv_text, "prefilled"))
