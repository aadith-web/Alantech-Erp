# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Nationality (Citizen) mandatory; Aadhaar + PAN mandatory for Indian nationals.

ClickUp: https://app.clickup.com/t/14yr2e57r7h, https://app.clickup.com/t/14yr2e57r7k

Covered:
- Nationality field: Link to Country, ticked in the import template.
- New employee refused without Nationality ("Citizen is required. Please select Nationality."),
  saved with it.
- Saved Nationality cannot be cleared on edit; an employee saved before the rule (no Nationality)
  can still be saved by the system with other changes.
- Data Import (Insert New Records) without Nationality fails the row with the same message.
- Nationality India: Aadhaar and PAN mandatory (new employee, changing to India, clearing one);
  other nationalities optional; unchanged older records still saved by the system.
- Aadhaar / PAN formats checked and normalised (spaces removed, PAN upper-cased).
- Aadhaar unique across employees (new and changed values).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_nationality

Data: TEST-P13 employees inside a savepoint rolled back after each test.
"""

from unittest.mock import patch

import frappe

from alantech_erp.setup.employee_nationality import (
	AADHAAR_FIELD,
	FIELD,
	InvalidIdentityNumberError,
	validate_indian_ids,
	validate_nationality,
)

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P13"
MESSAGE = "Citizen is required. Please select Nationality."
INDIA_MESSAGE = "Aadhaar Number and PAN Number are required when Nationality is India."
AADHAAR = "234567890123"
PAN = "ABCDE1234F"


def new_employee(first_name, **values):
	# new_doc, like the form and Data Import (a get_doc dict is only "new" once insert() starts)
	doc = frappe.new_doc("Employee")
	doc.update(
		{
			"first_name": f"{PREFIX} {first_name}",
			"gender": "Male",
			"date_of_birth": "1990-01-15",
			"date_of_joining": "2026-01-05",
			"company": COMPANY,
			"status": "Active",
			"create_user_automatically": 0,
			**values,
		}
	)
	return doc


class TestEmployeeNationality(TestCase):
	def setUp(self):
		frappe.db.savepoint("p13")
		self.addCleanup(frappe.db.rollback, save_point="p13")
		self.addCleanup(setattr, frappe.flags, "alt_check_employee_required", None)

	def check_on(self):
		frappe.flags.alt_check_employee_required = True

	def test_field(self):
		df = frappe.get_meta("Employee").get_field(FIELD)
		self.assertEqual((df.fieldtype, df.options, df.label), ("Link", "Country", "Nationality"))
		self.assertTrue(df.in_import_template)

	def test_new_employee_needs_nationality(self):
		self.check_on()
		doc = new_employee("New")
		with self.assertRaises(frappe.MandatoryError) as raised:
			validate_nationality(doc)
		self.assertIn(MESSAGE, str(raised.exception))
		doc.set(FIELD, "India")
		validate_nationality(doc)

	def test_cannot_be_cleared_on_edit(self):
		doc = new_employee("Edit", **{FIELD: "India"}).insert(ignore_permissions=True)
		self.check_on()
		doc.reload()
		doc.set(FIELD, None)
		with self.assertRaises(frappe.MandatoryError) as raised:
			doc.save(ignore_permissions=True)
		self.assertIn(MESSAGE, str(raised.exception))
		doc.reload()
		doc.set(FIELD, "United Arab Emirates")
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Employee", doc.name, FIELD), "United Arab Emirates")

	def test_older_employee_without_nationality_still_saved(self):
		doc = new_employee("Older").insert(ignore_permissions=True)  # saved before the rule
		self.check_on()
		doc.reload()
		doc.middle_name = "Changed"
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Employee", doc.name, "middle_name"), "Changed")

	def test_skipped_in_other_tests(self):
		new_employee("Bare").insert(ignore_permissions=True)

	def test_data_import_row_without_nationality_fails(self):
		self.check_on()
		csv = (
			"First Name,Company,Gender,Date of Birth,Date of Joining,Status,Nationality\n"
			f"{PREFIX} Import No,{COMPANY},Male,1990-01-15,2026-01-05,Active,\n"
		)
		file_doc = frappe.get_doc(
			{"doctype": "File", "file_name": "p13_nationality.csv", "content": csv, "is_private": 1}
		).insert(ignore_permissions=True)
		data_import = frappe.get_doc(
			{
				"doctype": "Data Import",
				"reference_doctype": "Employee",
				"import_type": "Insert New Records",
				"import_file": file_doc.file_url,
			}
		).insert(ignore_permissions=True)
		# only Nationality is checked here; the other create rules have their own tests. Data Import
		# commits each row and rolls back a failed one; both stay inside this test's savepoint.
		with (
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
			patch("alantech_erp.setup.employee_validation.validate_required_on_create"),
		):
			data_import.get_importer().import_data()
		logs = frappe.get_all(
			"Data Import Log", filters={"data_import": data_import.name}, fields=["success", "messages"]
		)
		self.assertEqual(len(logs), 1, logs)
		self.assertFalse(logs[0].success)
		self.assertIn(MESSAGE, logs[0].messages)


class TestIndianIds(TestCase):
	def setUp(self):
		frappe.db.savepoint("p13_ids")
		self.addCleanup(frappe.db.rollback, save_point="p13_ids")
		frappe.flags.alt_check_employee_required = True
		self.addCleanup(setattr, frappe.flags, "alt_check_employee_required", None)

	def test_field_and_template(self):
		meta = frappe.get_meta("Employee")
		aadhaar = meta.get_field(AADHAAR_FIELD)
		self.assertEqual((aadhaar.fieldtype, aadhaar.label), ("Data", "Aadhaar Number"))
		self.assertEqual(aadhaar.insert_after, FIELD)
		for field in (AADHAAR_FIELD, "pan_number"):
			df = meta.get_field(field)
			self.assertEqual(df.mandatory_depends_on, "eval:doc.alt_nationality == 'India'")
			self.assertTrue(df.in_import_template)

	def test_new_indian_needs_both(self):
		doc = new_employee("Indian", **{FIELD: "India"})
		with self.assertRaises(frappe.MandatoryError) as raised:
			validate_indian_ids(doc)
		self.assertIn(INDIA_MESSAGE, str(raised.exception))
		self.assertIn("Aadhaar Number", str(raised.exception))
		self.assertIn("PAN Number", str(raised.exception))
		doc.set(AADHAAR_FIELD, AADHAAR)
		with self.assertRaises(frappe.MandatoryError) as raised:
			validate_indian_ids(doc)
		self.assertIn("Missing: <strong>PAN Number</strong>", str(raised.exception))
		doc.pan_number = PAN
		validate_indian_ids(doc)

	def test_other_nationality_optional(self):
		validate_indian_ids(new_employee("Emirati", **{FIELD: "United Arab Emirates"}))

	def test_changing_to_india_or_clearing_refused(self):
		frappe.flags.alt_check_employee_required = None
		doc = new_employee("Change", **{FIELD: "United Arab Emirates"}).insert(ignore_permissions=True)
		frappe.flags.alt_check_employee_required = True
		doc.reload()
		doc.set(FIELD, "India")
		with self.assertRaises(frappe.MandatoryError):
			doc.save(ignore_permissions=True)
		doc.reload()
		doc.update({FIELD: "India", AADHAAR_FIELD: AADHAAR, "pan_number": PAN})
		doc.save(ignore_permissions=True)
		doc.reload()
		doc.pan_number = None
		with self.assertRaises(frappe.MandatoryError):
			doc.save(ignore_permissions=True)

	def test_unchanged_older_indian_still_saved(self):
		frappe.flags.alt_check_employee_required = None
		doc = new_employee("Older Indian", **{FIELD: "India"}).insert(ignore_permissions=True)
		frappe.flags.alt_check_employee_required = True
		doc.reload()
		doc.middle_name = "Changed"
		doc.save(ignore_permissions=True)  # Aadhaar / PAN untouched: a system save goes through

	def test_formats_normalised_and_checked(self):
		doc = new_employee("Format", **{FIELD: "India", AADHAAR_FIELD: " 2345 6789-0123 ", "pan_number": " abcde1234f"})
		validate_indian_ids(doc)
		self.assertEqual(doc.get(AADHAAR_FIELD), AADHAAR)
		self.assertEqual(doc.pan_number, PAN)
		for aadhaar in ("123456789012", "23456789012", "23456789012A"):
			doc = new_employee("Bad", **{FIELD: "India", AADHAAR_FIELD: aadhaar, "pan_number": PAN})
			with self.assertRaises(InvalidIdentityNumberError, msg=aadhaar):
				validate_indian_ids(doc)
		for pan in ("ABCD1234F", "ABCDE12345", "12345ABCDE"):
			doc = new_employee("Bad", **{FIELD: "India", AADHAAR_FIELD: AADHAAR, "pan_number": pan})
			with self.assertRaises(InvalidIdentityNumberError, msg=pan):
				validate_indian_ids(doc)

	def test_old_malformed_pan_not_rechecked(self):
		frappe.flags.alt_check_employee_required = None
		doc = new_employee("Old PAN").insert(ignore_permissions=True)
		frappe.db.set_value("Employee", doc.name, "pan_number", "OLD123")
		frappe.flags.alt_check_employee_required = True
		doc.reload()
		doc.middle_name = "Changed"
		doc.save(ignore_permissions=True)

	def test_duplicate_aadhaar_refused(self):
		# checked whether or not the create rules are on (they would also want Branch etc. here)
		frappe.flags.alt_check_employee_required = None
		first = new_employee("Aadhaar One", **{FIELD: "India", AADHAAR_FIELD: AADHAAR, "pan_number": PAN})
		first.insert(ignore_permissions=True)
		# also when typed with spaces, and on another nationality
		second = new_employee("Aadhaar Two", **{FIELD: "United Arab Emirates", AADHAAR_FIELD: "2345 6789 0123"})
		with self.assertRaises(frappe.DuplicateEntryError) as raised:
			second.insert(ignore_permissions=True)
		self.assertIn(f"Aadhaar Number <strong>{AADHAAR}</strong> already belongs to", str(raised.exception))
		self.assertIn(first.name, str(raised.exception))
		# changing an existing employee to that number is refused too; its own number is fine
		other = new_employee("Aadhaar Three").insert(ignore_permissions=True)
		other.reload()
		other.set(AADHAAR_FIELD, AADHAAR)
		with self.assertRaises(frappe.DuplicateEntryError):
			other.save(ignore_permissions=True)
		first.reload()
		first.middle_name = "Changed"
		first.save(ignore_permissions=True)
