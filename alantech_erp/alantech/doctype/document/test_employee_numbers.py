# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Aadhaar / PAN number kept equal on the Employee and the employee's documents (Aadhaar stored
"2345 6789 0124" on both)
(employee_numbers.py). ClickUp 14yr2e57r7k.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.document.test_employee_numbers

Test employees, document types and documents are rolled back after each test.
"""

import frappe
from frappe.tests import IntegrationTestCase

from alantech_erp.alantech.doctype.document.employee_numbers import get_employee_number, update_employee
from alantech_erp.alantech.doctype.document.test_document import pdf_bytes
from alantech_erp.alantech.doctype.document_type_master.test_document_type_master import make_type
from alantech_erp.setup.employee_nationality import InvalidIdentityNumberError

IGNORE_TEST_RECORD_DEPENDENCIES = ["Employee", "Company", "Country", "User", "Document Type Master"]

COMPANY = "Alantech Industries India Pvt Ltd"
AADHAAR_TYPE = "_Test Num Aadhaar"
PAN_TYPE = "_Test Num PAN"
OTHER_TYPE = "_Test Num Other"
AADHAAR, AADHAAR_SHOWN = "234567890124", "2345 6789 0124"
AADHAAR_2, AADHAAR_2_SHOWN = "234500000012", "2345 0000 0012"
PAN, PAN_2 = "ABCPE1234F", "ABCPE5678G"


class IntegrationTestEmployeeNumbers(IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint("employee_numbers")
		self.addCleanup(frappe.db.rollback, save_point="employee_numbers")
		make_type(AADHAAR_TYPE, number_format="Aadhaar")
		make_type(PAN_TYPE, number_format="PAN")
		make_type(OTHER_TYPE)
		self.file_url = frappe.get_doc(
			{"doctype": "File", "file_name": "_test_num.pdf", "content": pdf_bytes(), "is_private": 1}
		).insert(ignore_permissions=True).file_url
		self.employee = self.make_employee("One")

	def make_employee(self, name, **values):
		doc = frappe.new_doc("Employee")
		doc.update(
			{
				"first_name": f"TEST-P14 {name}",
				"gender": "Male",
				"date_of_birth": "1990-01-15",
				"date_of_joining": "2026-01-05",
				"company": COMPANY,
				"status": "Active",
				"create_user_automatically": 0,
				**values,
			}
		)
		return doc.insert(ignore_permissions=True).name

	def upload(self, document_type, number=None, employee=None, save=True):
		doc = frappe.get_doc(
			{
				"doctype": "Document",
				"reference_doctype": "Employee",
				"reference_name": employee or self.employee,
				"document_type": document_type,
				"card_number": number,
				"attachments": [{"file": self.file_url}],
			}
		)
		return doc.insert(ignore_permissions=True) if save else doc

	def employee_value(self, field, employee=None):
		return frappe.db.get_value("Employee", employee or self.employee, field)

	def set_employee(self, **values):
		emp = frappe.get_doc("Employee", self.employee)
		emp.update(values)
		emp.save(ignore_permissions=True)
		return emp

	# --- Employee -> new document -----------------------------------------
	def test_new_document_filled_from_employee(self):
		self.set_employee(alt_aadhaar_number=AADHAAR, pan_number=PAN)
		self.assertEqual(get_employee_number(self.employee, AADHAAR_TYPE), AADHAAR_SHOWN)
		self.assertEqual(get_employee_number(self.employee, PAN_TYPE), PAN)
		self.assertIsNone(get_employee_number(self.employee, OTHER_TYPE))
		self.assertEqual(self.upload(AADHAAR_TYPE).card_number, AADHAAR_SHOWN)  # the document's way
		self.assertEqual(self.upload(PAN_TYPE).card_number, PAN)

	def test_typed_number_not_replaced(self):
		self.set_employee(pan_number=PAN)
		self.assertEqual(self.upload(PAN_TYPE, PAN_2).card_number, PAN_2)

	# --- document -> Employee ------------------------------------------------
	def test_approved_document_updates_employee(self):
		self.upload(AADHAAR_TYPE, AADHAAR_SHOWN)  # HR upload: approved at once
		self.assertEqual(self.employee_value("alt_aadhaar_number"), AADHAAR_SHOWN)
		self.upload(PAN_TYPE, "abcpe1234f")
		self.assertEqual(self.employee_value("pan_number"), PAN)

	def test_employee_timeline_note(self):
		doc = self.upload(PAN_TYPE, PAN)
		notes = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Employee", "reference_name": self.employee, "comment_type": "Info"},
			pluck="content",
		)
		self.assertIn(f"PAN Number set to {PAN} from Document {doc.name}.", notes)

	def test_indian_employee_updated_one_number_at_a_time(self):
		frappe.db.set_value("Employee", self.employee, "alt_nationality", "India")
		frappe.flags.alt_check_employee_required = True
		self.addCleanup(setattr, frappe.flags, "alt_check_employee_required", None)
		self.upload(AADHAAR_TYPE, AADHAAR)  # no PAN yet: the Aadhaar + PAN rule does not block it
		self.assertEqual(self.employee_value("alt_aadhaar_number"), AADHAAR_SHOWN)

	def test_pending_or_rejected_document_does_not_update(self):
		doc = self.upload(AADHAAR_TYPE, AADHAAR, save=False)
		doc.approval_status = "Pending Approval"
		update_employee(doc)
		self.assertIsNone(self.employee_value("alt_aadhaar_number"))
		doc.approval_status = "Rejected"
		update_employee(doc)
		self.assertIsNone(self.employee_value("alt_aadhaar_number"))
		doc.approval_status = "Approved"
		update_employee(doc)
		self.assertEqual(self.employee_value("alt_aadhaar_number"), AADHAAR_SHOWN)

	def test_number_changed_on_document_updates_employee(self):
		doc = self.upload(AADHAAR_TYPE, AADHAAR)
		doc.reload()
		doc.card_number = AADHAAR_2
		doc.save(ignore_permissions=True)
		self.assertEqual(self.employee_value("alt_aadhaar_number"), AADHAAR_2_SHOWN)

	def test_other_type_does_not_touch_employee(self):
		self.upload(OTHER_TYPE, "X-123")
		self.assertIsNone(self.employee_value("alt_aadhaar_number"))
		self.assertIsNone(self.employee_value("pan_number"))

	def test_document_with_another_employees_aadhaar_refused(self):
		self.make_employee("Two", alt_aadhaar_number=AADHAAR)
		with self.assertRaises(frappe.DuplicateEntryError):
			self.upload(AADHAAR_TYPE, AADHAAR)

	# --- Employee -> existing documents ---------------------------------------
	def test_employee_change_updates_documents(self):
		aadhaar_doc = self.upload(AADHAAR_TYPE, AADHAAR)
		pan_doc = self.upload(PAN_TYPE, PAN)
		other = self.upload(OTHER_TYPE, "X-123")
		self.set_employee(alt_aadhaar_number=AADHAAR_2, pan_number=PAN_2)
		self.assertEqual(frappe.db.get_value("Document", aadhaar_doc.name, "card_number"), AADHAAR_2_SHOWN)
		self.assertEqual(frappe.db.get_value("Document", pan_doc.name, "card_number"), PAN_2)
		self.assertEqual(frappe.db.get_value("Document", other.name, "card_number"), "X-123")

	def test_rejected_document_not_updated(self):
		doc = self.upload(PAN_TYPE, PAN)
		doc.db_set("approval_status", "Rejected")
		self.set_employee(pan_number=PAN_2)
		self.assertEqual(frappe.db.get_value("Document", doc.name, "card_number"), PAN)

	def test_unchanged_employee_save_leaves_documents(self):
		doc = self.upload(PAN_TYPE, PAN)
		modified = frappe.db.get_value("Document", doc.name, "modified")
		self.set_employee(middle_name="Changed")
		self.assertEqual(frappe.db.get_value("Document", doc.name, "modified"), modified)

	# --- same rules on both sides ----------------------------------------------
	def test_employee_uses_document_rules(self):
		with self.assertRaises(InvalidIdentityNumberError) as raised:
			self.set_employee(alt_aadhaar_number="234567890123")  # wrong check digit
		self.assertIn("check digit does not match", str(raised.exception))
		with self.assertRaises(InvalidIdentityNumberError):
			self.set_employee(pan_number="ABCDE1234F")  # D is not a PAN holder type
