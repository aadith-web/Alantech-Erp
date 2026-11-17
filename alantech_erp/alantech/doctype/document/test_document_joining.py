# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Documents mandatory at joining (Document Type Master > Mandatory at Joining / Only for
Nationality), listed in the Employee Documents section. ClickUp 14yr2e57mhp.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.document.test_document_joining

Test document types and documents are rolled back after each test.
"""

import frappe
from frappe.tests import IntegrationTestCase

from alantech_erp.alantech.doctype.document.document import (
	APPROVED,
	MISSING,
	PENDING,
	REJECTED,
	get_mandatory_documents,
	mandatory_document_status,
	mandatory_document_types,
)
from alantech_erp.alantech.doctype.document.test_document import pdf_bytes
from alantech_erp.alantech.doctype.document_type_master.test_document_type_master import make_type
from alantech_erp.patches.v16.document_types_at_joining import JOINING_DOCUMENTS

IGNORE_TEST_RECORD_DEPENDENCIES = ["Employee", "Company", "Country", "User", "Document Type Master"]

EVERYONE = "_Test Join Photo"
INDIAN = "_Test Join Aadhaar"
OPTIONAL = "_Test Join Optional"
TEST_TYPES = (EVERYONE, INDIAN, OPTIONAL)


class IntegrationTestDocumentJoining(IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint("joining_test")
		self.addCleanup(frappe.db.rollback, save_point="joining_test")
		self.employee = frappe.db.get_value("Employee", {"status": "Active"}, "name")
		if not self.employee:
			self.skipTest("no active employee on the site")
		make_type(EVERYONE, mandatory_at_joining=1)
		make_type(INDIAN, mandatory_at_joining=1, mandatory_for_nationality="India")
		make_type(OPTIONAL, mandatory_at_joining=0)
		self.file_url = frappe.get_doc(
			{"doctype": "File", "file_name": "_test_join.pdf", "content": pdf_bytes(), "is_private": 1}
		).insert(ignore_permissions=True).file_url

	def set_nationality(self, nationality):
		frappe.db.set_value("Employee", self.employee, "alt_nationality", nationality, update_modified=False)

	def status(self):
		return {
			r["document_type"]: r["status"]
			for r in mandatory_document_status(self.employee)
			if r["document_type"] in TEST_TYPES
		}

	def upload(self, document_type, approval_status=None):
		doc = frappe.get_doc(
			{
				"doctype": "Document",
				"reference_doctype": "Employee",
				"reference_name": self.employee,
				"document_type": document_type,
				"attachments": [{"file": self.file_url}],
			}
		).insert(ignore_permissions=True)
		if approval_status:
			doc.db_set("approval_status", approval_status, update_modified=False)
		return doc

	def test_types_by_nationality(self):
		self.assertIn(EVERYONE, mandatory_document_types("India"))
		self.assertIn(INDIAN, mandatory_document_types("India"))
		self.assertIn(EVERYONE, mandatory_document_types("United Arab Emirates"))
		self.assertNotIn(INDIAN, mandatory_document_types("United Arab Emirates"))
		self.assertNotIn(INDIAN, mandatory_document_types(None))
		self.assertNotIn(OPTIONAL, mandatory_document_types("India"))

	def test_disabled_type_not_listed(self):
		make_type(EVERYONE, mandatory_at_joining=1, disabled=1)
		self.assertNotIn(EVERYONE, mandatory_document_types("India"))

	def test_missing_until_uploaded(self):
		self.set_nationality("India")
		self.assertEqual(self.status(), {EVERYONE: MISSING, INDIAN: MISSING})
		doc = self.upload(EVERYONE)  # by HR: approved straight away
		rows = {r["document_type"]: r for r in get_mandatory_documents(self.employee)}
		self.assertEqual(rows[EVERYONE]["status"], APPROVED)
		self.assertEqual(rows[EVERYONE]["document"], doc.name)
		self.assertEqual(rows[INDIAN]["status"], MISSING)

	def test_other_nationality_does_not_need_indian_type(self):
		self.set_nationality("United Arab Emirates")
		self.assertEqual(self.status(), {EVERYONE: MISSING})

	def test_best_document_decides(self):
		self.set_nationality(None)
		self.upload(EVERYONE, REJECTED)
		self.assertEqual(self.status(), {EVERYONE: REJECTED})
		self.upload(EVERYONE, PENDING)
		self.assertEqual(self.status(), {EVERYONE: PENDING})
		self.upload(EVERYONE)
		self.upload(EVERYONE, REJECTED)  # a later rejected copy does not undo the approved one
		self.assertEqual(self.status(), {EVERYONE: APPROVED})

	def test_permission_needed(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			get_mandatory_documents(self.employee)


class IntegrationTestJoiningPatch(IntegrationTestCase):
	def test_site_types_flagged(self):
		"""After the patch: the joining list's mandatory types, Aadhaar / PAN only for India."""
		for name, (mandatory, nationality, _settings) in JOINING_DOCUMENTS.items():
			values = frappe.db.get_value(
				"Document Type Master", name, ["mandatory_at_joining", "mandatory_for_nationality"], as_dict=True
			)
			self.assertIsNotNone(values, name)
			self.assertEqual(values.mandatory_at_joining, mandatory, name)
			self.assertEqual(values.mandatory_for_nationality, nationality, name)
