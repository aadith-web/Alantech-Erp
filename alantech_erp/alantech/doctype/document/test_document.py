# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Document (HR-F07 Employee Documents, ClickUp 14yr2e56cak): reference and ownership, date and
number rules, the HR Manager approval flow, permissions, expiry alerts and the Document Expiry report.
QA test cases TC-DOC-01 to TC-DOC-18 in the HR-F09 test sheet cover the same ground by hand.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.document.test_document

Two of the site's active employees are linked to test users (user_id set directly, so the Employee
hooks do not run) and test document types are created; all of it is rolled back after the class.
Number formats themselves are covered in test_document_number.py.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from alantech_erp.alantech.doctype.document.document import (
	APPROVED,
	PENDING,
	REJECTED,
	get_files,
	has_permission,
	review_document,
	send_expiry_alerts,
)
from alantech_erp.alantech.doctype.document.document_files import MAX_FILE_SIZE, DocumentFileError
from alantech_erp.alantech.doctype.document_type_master.test_document_type_master import make_type
from alantech_erp.alantech.report.document_expiry.document_expiry import execute as expiry_report

IGNORE_TEST_RECORD_DEPENDENCIES = ["Employee", "Company", "Country", "User", "Document Type Master"]

ID_CARD = "_Test Doc ID Card"  # Aadhaar format, issue date only
PASSPORT = "_Test Doc Passport"  # expiry date mandatory, alert 30 days before
PLAIN = "_Test Doc Plain"  # no format, number mandatory
AADHAAR = "2345 6789 0124"


def pdf_bytes(size=0):
	"""A valid one-page PDF (Frappe parses uploaded PDFs), padded to about `size` bytes."""
	from io import BytesIO

	from pypdf import PdfWriter

	writer = PdfWriter()
	writer.add_blank_page(width=72, height=72)
	if size:
		writer.add_metadata({"/Padding": "x" * size})
	out = BytesIO()
	writer.write(out)
	return out.getvalue()


def image_bytes(fmt):
	from io import BytesIO

	from PIL import Image

	out = BytesIO()
	Image.new("RGB", (8, 8), "white").save(out, fmt)
	return out.getvalue()


def make_user(email, roles, employee=None):
	"""Test user with exactly these roles. The employee is linked first: HRMS drops the Employee
	role from a user who has no linked Employee record."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	if employee:
		frappe.db.set_value("Employee", employee, "user_id", email)
	user = frappe.get_doc("User", email)
	user.set("roles", [{"role": role} for role in roles])
	user.save(ignore_permissions=True)
	return email


class IntegrationTestDocument(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", order_by="creation", limit=3)
		if len(employees) < 3:
			raise cls.skipTest(cls, "Need three active employees on the site")
		cls.emp, cls.other_emp, cls.hr_emp = employees

		cls.emp_user = make_user("_test-doc-emp@example.com", ["Employee"], cls.emp)
		cls.other_user = make_user("_test-doc-other@example.com", ["Employee"], cls.other_emp)
		cls.hr_manager = make_user("_test-doc-hrm@example.com", ["HR Manager", "Employee"], cls.hr_emp)
		cls.hr_manager2 = make_user("_test-doc-hrm2@example.com", ["HR Manager"])
		cls.hr_user = make_user("_test-doc-hru@example.com", ["HR User"])

		make_type(ID_CARD, number_format="Aadhaar")
		make_type(PASSPORT, expiry_required=1, expiry_date_mandatory=1, alert_days_before=30)
		make_type(PLAIN, number_mandatory=1)

		cls.file_url = frappe.get_doc(
			{"doctype": "File", "file_name": "_test_doc_scan.pdf", "content": pdf_bytes(), "is_private": 1}
		).insert(ignore_permissions=True).file_url

	def setUp(self):
		# the class data is rolled back once, at the end: undo each test's own records after it,
		# so a document number or notification from one test never reaches the next
		frappe.db.savepoint("document_test")
		self.addCleanup(frappe.db.rollback, save_point="document_test")
		self.addCleanup(frappe.set_user, "Administrator")

	# --- helpers ---------------------------------------------------------
	def make_doc(self, employee=None, document_type=PASSPORT, user=None, save=True, **values):
		if user:
			frappe.set_user(user)
		doc = frappe.get_doc(
			{
				"doctype": "Document",
				"reference_doctype": "Employee",
				"reference_name": employee or self.emp,
				"document_type": document_type,
				"issue_date": add_days(today(), -10),
				"expiry_date": add_days(today(), 365) if document_type == PASSPORT else None,
				"attachments": [{"file": self.file_url, "description": "front"}],
				**values,
			}
		)
		if save:
			doc.insert()
		return doc

	def as_user(self, user):
		frappe.set_user(user)

	def fresh(self, doc, user):
		"""The document as `user` loads it in a new request (approve()/reject() leave flags on
		the object they ran on, which a real request never sees)."""
		frappe.set_user(user)
		return frappe.get_doc("Document", doc.name)

	def notifications(self, doc, user=None):
		filters = {"document_type": "Document", "document_name": doc.name}
		if user:
			filters["for_user"] = user
		return frappe.get_all("Notification Log", filters=filters, fields=["for_user", "subject"])

	def comments(self, doc):
		return frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Document", "reference_name": doc.name, "comment_type": "Info"},
			pluck="content",
		)

	def assert_refused(self, doc, text, exc=frappe.ValidationError):
		with self.assertRaises(exc) as ctx:
			doc.save() if doc.name else doc.insert()
		self.assertIn(text, str(ctx.exception))

	# --- reference and ownership ----------------------------------------
	def test_employee_reference_details(self):
		doc = self.make_doc()
		self.assertTrue(doc.name.startswith("DOC-"))
		self.assertEqual(doc.employee, self.emp)
		self.assertEqual(doc.reference_title, frappe.db.get_value("Employee", self.emp, "employee_name"))

	def test_other_record_reference(self):
		company = frappe.db.get_value("Employee", self.emp, "company")
		doc = self.make_doc(reference_doctype="Company", reference_name=company)
		self.assertIsNone(doc.employee)
		self.assertEqual(doc.reference_title, company)

	def test_missing_reference_refused(self):
		doc = self.make_doc(save=False, reference_name="_Test No Such Employee")
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_employee_cannot_add_to_another_employee(self):
		# refused by has_permission (generic "no permission") before validate's own message is reached
		doc = self.make_doc(employee=self.other_emp, user=self.emp_user, save=False)
		with self.assertRaises(frappe.PermissionError):
			doc.insert()

	def test_reference_access_message(self):
		# the message validate gives when the permission hook is bypassed
		doc = self.make_doc(employee=self.other_emp, user=self.emp_user, save=False)
		doc.flags.ignore_permissions = True
		self.assert_refused(doc, "only add documents to your own employee record", frappe.PermissionError)

	def test_attachment_required(self):
		doc = self.make_doc(save=False, attachments=[])
		with self.assertRaises(frappe.MandatoryError):
			doc.insert()

	def test_several_files(self):
		doc = self.make_doc(
			attachments=[{"file": self.file_url, "description": "front"}, {"file": self.file_url, "description": "back"}]
		)
		self.assertEqual(len(doc.attachments), 2)

	# --- file type and size (ClickUp 14yr2e57a43) ------------------------
	def make_file(self, name, size=None, attached_to=None):
		if name.lower().endswith(".pdf"):
			content = pdf_bytes(size or 0)
		elif name.lower().endswith((".jpg", ".png")):
			content = image_bytes("JPEG" if name.lower().endswith(".jpg") else "PNG")
		else:
			content = b"x" * (size or 1024)
		values = {"doctype": "File", "file_name": name, "content": content, "is_private": 1}
		if attached_to:
			values.update(attached_to_doctype="Document", attached_to_name=attached_to, attached_to_field="file")
		return frappe.get_doc(values)

	def test_zip_upload_refused(self):
		doc = self.make_doc()
		with self.assertRaises(DocumentFileError) as ctx:
			self.make_file("_test_doc_scan.zip", attached_to=doc.name).insert()
		self.assertIn("Only PDF, JPG and PNG", str(ctx.exception))

	def test_upload_over_5_mb_refused(self):
		doc = self.make_doc()
		with self.assertRaises(DocumentFileError) as ctx:
			self.make_file("_test_doc_big.pdf", size=6 * 1024 * 1024 + 4096, attached_to=doc.name).insert()
		self.assertIn("is 6.0 MB. Files can be at most 5 MB", str(ctx.exception))

	def test_upload_up_to_5_mb_pdf_jpg_png_allowed(self):
		doc = self.make_doc()
		pdf = self.make_file("_test_doc_5mb.pdf", size=MAX_FILE_SIZE - 4096, attached_to=doc.name).insert()
		self.assertLessEqual(pdf.file_size, MAX_FILE_SIZE)
		self.make_file("_test_doc_photo.JPG", attached_to=doc.name).insert()
		self.make_file("_test_doc_photo.png", attached_to=doc.name).insert()

	def test_document_with_zip_row_refused(self):
		"""A file uploaded elsewhere (not attached to the Document) and put in the table by the API."""
		url = self.make_file("_test_doc_other.zip").insert().file_url
		doc = self.make_doc(save=False, attachments=[{"file": url, "description": "front"}])
		with self.assertRaises(DocumentFileError):
			doc.insert()

	def test_document_with_large_pdf_row_refused(self):
		url = self.make_file("_test_doc_other_big.pdf", size=MAX_FILE_SIZE + 1).insert().file_url
		doc = self.make_doc()
		doc.append("attachments", {"file": url, "description": "back"})
		with self.assertRaises(DocumentFileError):
			doc.save()

	def test_existing_file_rows_not_checked_again(self):
		"""A document saved before the rule (with a zip) can still be edited."""
		doc = self.make_doc()
		url = self.make_file("_test_doc_old.zip").insert().file_url
		frappe.db.set_value("Document Attachment", doc.attachments[0].name, "file", url)
		doc.reload()
		doc.remarks = "checked"
		doc.save()

	# --- dates -----------------------------------------------------------
	def test_date_rules_copied_from_type(self):
		doc = self.make_doc(document_type=ID_CARD, card_number=AADHAAR)
		self.assertEqual((doc.issue_date_required, doc.expiry_required), (1, 0))
		self.assertEqual((doc.issue_date_mandatory, doc.expiry_date_mandatory), (0, 0))
		passport = self.make_doc()
		self.assertEqual((passport.expiry_required, passport.expiry_date_mandatory), (1, 1))

	def test_mandatory_expiry_date(self):
		doc = self.make_doc(save=False, expiry_date=None)
		self.assert_refused(doc, f"Expiry Date is mandatory for", frappe.MandatoryError)

	def test_issue_date_not_in_future(self):
		doc = self.make_doc(save=False, issue_date=add_days(today(), 1))
		self.assert_refused(doc, "cannot be in the future")

	def test_expiry_date_not_in_past(self):
		doc = self.make_doc(save=False, expiry_date=add_days(today(), -1))
		self.assert_refused(doc, "cannot be in the past")

	def test_expiry_after_issue(self):
		doc = self.make_doc(save=False, issue_date=add_days(today(), -5), expiry_date=add_days(today(), -5))
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		doc = self.make_doc(save=False, issue_date=today(), expiry_date=today())
		self.assert_refused(doc, "Expiry Date must be after the Issue Date")

	def test_expired_document_can_still_be_edited(self):
		doc = self.make_doc(issue_date=add_days(today(), -400))
		doc.db_set("expiry_date", add_days(today(), -1))
		doc.reload()
		doc.remarks = "renewal applied"
		doc.save()
		self.assertEqual(doc.remarks, "renewal applied")
		doc.expiry_date = add_days(today(), -2)
		self.assert_refused(doc, "cannot be in the past")

	# --- numbers ---------------------------------------------------------
	def test_number_stored_in_one_format(self):
		doc = self.make_doc(document_type=ID_CARD, card_number="234567890124")
		self.assertEqual(doc.card_number, AADHAAR)

	def test_invalid_number_refused(self):
		doc = self.make_doc(save=False, document_type=ID_CARD, card_number="2345 6789 0123")
		self.assert_refused(doc, "check digit does not match")

	def test_duplicate_number_refused_within_type(self):
		first = self.make_doc(document_type=ID_CARD, card_number=AADHAAR)
		doc = self.make_doc(save=False, employee=self.other_emp, document_type=ID_CARD, card_number="234567890124")
		self.assert_refused(doc, first.name, frappe.DuplicateEntryError)

	# --- one person per identity number (ClickUp 14yr2e57c6k) --------------
	def test_number_typed_differently_refused_for_another_employee(self):
		"""A type without a Number Format keeps the number as typed; it is still the same number."""
		first = self.make_doc(document_type=PLAIN, card_number="DL-TEST-123456")
		self.assertEqual(first.number_key, "DLTEST123456")
		for typed in ("DL-TEST-123456", "dl test 123456", "DL/TEST/123456", " DL.TEST.123456 "):
			doc = self.make_doc(save=False, employee=self.other_emp, document_type=PLAIN, card_number=typed)
			self.assert_refused(
				doc, "already exists for another employee. Duplicate not allowed.", frappe.DuplicateEntryError
			)

	def test_duplicate_message_for_hr_names_the_document(self):
		first = self.make_doc(document_type=PLAIN, card_number="DL-TEST-123456")
		doc = self.make_doc(save=False, employee=self.other_emp, document_type=PLAIN, card_number="DL-TEST-123456",
			user=self.hr_user)
		self.assert_refused(doc, first.name, frappe.DuplicateEntryError)

	def test_duplicate_message_for_employee_hides_the_owner(self):
		first = self.make_doc(employee=self.other_emp, document_type=PLAIN, card_number="DL-TEST-123456")
		doc = self.make_doc(save=False, document_type=PLAIN, card_number="DL-TEST-123456", user=self.emp_user)
		with self.assertRaises(frappe.DuplicateEntryError) as ctx:
			doc.insert()
		message = str(ctx.exception)
		self.assertIn("already exists for another employee. Duplicate not allowed.", message)
		self.assertNotIn(first.name, message)
		self.assertNotIn(first.reference_title, message)

	def test_same_number_twice_for_same_employee_refused(self):
		first = self.make_doc(document_type=PLAIN, card_number="DL-TEST-123456")
		doc = self.make_doc(save=False, document_type=PLAIN, card_number="dl-test-123456")
		self.assert_refused(doc, "already exists for this employee", frappe.DuplicateEntryError)
		self.assert_refused(doc, first.name, frappe.DuplicateEntryError)

	def test_changing_number_to_a_used_one_refused(self):
		self.make_doc(document_type=PLAIN, card_number="DL-TEST-123456")
		doc = self.make_doc(employee=self.other_emp, document_type=PLAIN, card_number="DL-TEST-999999")
		doc.card_number = "DL TEST 123456"
		self.assert_refused(doc, "Duplicate not allowed", frappe.DuplicateEntryError)

	def test_rejected_document_does_not_block_the_number(self):
		wrong = self.make_doc(document_type=PLAIN, card_number="DL-TEST-123456", user=self.emp_user)
		self.fresh(wrong, self.hr_manager2).reject("Not this employee's licence")
		doc = self.make_doc(employee=self.other_emp, document_type=PLAIN, card_number="DL-TEST-123456")
		self.assertEqual(doc.number_key, "DLTEST123456")

	def test_check_number_reports_duplicate_while_typing(self):
		from alantech_erp.alantech.doctype.document.document_number import check_number

		self.make_doc(document_type=PLAIN, card_number="DL-TEST-123456")
		result = check_number(PLAIN, "dl test 123456", reference_doctype="Employee", reference_name=self.other_emp)
		self.assertIn("already exists for another employee", result["error"])
		self.assertIsNone(check_number(PLAIN, "DL-TEST-000001")["error"])

	def test_same_number_allowed_for_another_type(self):
		self.make_doc(document_type=ID_CARD, card_number=AADHAAR)
		doc = self.make_doc(employee=self.other_emp, document_type=PLAIN, card_number=AADHAAR)
		self.assertEqual(doc.card_number, AADHAAR)

	def test_resaving_keeps_own_number(self):
		doc = self.make_doc(document_type=ID_CARD, card_number=AADHAAR)
		doc.remarks = "checked"
		doc.save()

	def test_number_mandatory_for_type(self):
		doc = self.make_doc(save=False, document_type=PLAIN)
		self.assert_refused(doc, "Number is mandatory", frappe.MandatoryError)

	def test_number_optional_by_type(self):
		"""ClickUp 14yr2e58dq2: the Number is required only for types with Number Mandatory, and a
		type without Show Number has no Number field (form) and never requires one."""
		from alantech_erp.alantech.doctype.document.document_number import check_number

		doc = self.make_doc()  # Passport: Number shown, not mandatory
		self.assertFalse(doc.card_number)
		self.assertEqual(doc.number_required, 1)
		self.assertEqual((check_number(PASSPORT)["required"], check_number(PASSPORT)["mandatory"]), (1, 0))
		self.assertEqual(check_number(PLAIN)["mandatory"], 1)

		frappe.db.set_value("Document Type Master", PLAIN, {"number_required": 0, "number_mandatory": 1})
		self.assertEqual((check_number(PLAIN)["required"], check_number(PLAIN)["mandatory"]), (0, 0))
		doc = self.make_doc(document_type=PLAIN)
		self.assertEqual(doc.number_required, 0)

	# --- approval status on save ----------------------------------------
	def test_hr_upload_approved(self):
		doc = self.make_doc(user=self.hr_manager2)
		self.assertEqual(doc.approval_status, APPROVED)
		self.assertEqual((doc.submitted_by, doc.reviewed_by), (self.hr_manager2, self.hr_manager2))
		self.assertTrue(doc.reviewed_on)

	def test_hr_user_upload_approved(self):
		doc = self.make_doc(user=self.hr_user)
		self.assertEqual(doc.approval_status, APPROVED)

	def test_employee_upload_pending(self):
		doc = self.make_doc(user=self.emp_user)
		self.assertEqual(doc.approval_status, PENDING)
		self.assertEqual(doc.submitted_by, self.emp_user)
		self.assertFalse(doc.reviewed_by)
		self.assertIn("Waiting for HR Manager approval", " ".join(self.comments(doc)))

	def test_employee_upload_notifies_hr_managers(self):
		doc = self.make_doc(user=self.emp_user)
		notified = {n.for_user for n in self.notifications(doc)}
		self.assertIn(self.hr_manager, notified)
		self.assertIn(self.hr_manager2, notified)
		self.assertNotIn(self.emp_user, notified)
		self.assertIn("needs approval", self.notifications(doc, self.hr_manager)[0].subject)

	# --- duplicate / wrong recipients (ClickUp 14yr2e57q0t) ---------------
	def send_back_for_approval(self, doc):
		"""HR edits (auto-approved), then the employee edits again: Pending Approval once more."""
		doc = self.fresh(doc, self.hr_user)
		doc.remarks = f"checked {frappe.generate_hash(length=4)}"
		doc.save()
		doc = self.fresh(doc, self.emp_user)
		doc.place_of_issue = f"Kochi {frappe.generate_hash(length=4)}"
		doc.save()
		self.assertEqual(doc.approval_status, PENDING)
		return doc

	def needs_approval(self, doc, user):
		return [n for n in self.notifications(doc, user) if "needs approval" in n.subject]

	def test_hr_manager_notified_once_per_employee_change(self):
		doc = self.make_doc(user=self.emp_user)
		self.assertEqual(len(self.needs_approval(doc, self.hr_manager2)), 1)
		doc.save()  # the same object saved again in the same request
		self.assertEqual(len(self.needs_approval(doc, self.hr_manager2)), 1)

	def test_unread_request_not_repeated(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.send_back_for_approval(doc)
		self.assertEqual(len(self.needs_approval(doc, self.hr_manager2)), 1)

		frappe.db.set_value("Notification Log", {"for_user": self.hr_manager2, "document_name": doc.name}, "read", 1)
		self.send_back_for_approval(doc)
		self.assertEqual(len(self.needs_approval(doc, self.hr_manager2)), 2)

	def test_approval_notifies_only_the_employee(self):
		doc = self.make_doc(user=self.emp_user)
		before = {n.for_user for n in self.notifications(doc)}
		doc = self.fresh(doc, self.hr_manager2)
		doc.approve()
		logs = frappe.get_all(
			"Notification Log",
			filters={"document_name": doc.name, "subject": ["like", "%has been approved%"]},
			pluck="for_user",
		)
		self.assertEqual(logs, [self.emp_user])
		self.assertEqual({n.for_user for n in self.notifications(doc)} - before, {self.emp_user})

	def test_rejection_notifies_only_the_employee(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		doc.reject("Scan is blurred")
		logs = frappe.get_all(
			"Notification Log",
			filters={"document_name": doc.name, "subject": ["like", "%has been rejected%"]},
			pluck="for_user",
		)
		self.assertEqual(logs, [self.emp_user])

	def test_one_email_per_recipient_owned_by_administrator(self):
		from alantech_erp.alantech.doctype.document.document import email_configured

		if not email_configured():
			self.skipTest("No outgoing email account on the site")
		doc = self.make_doc(user=self.emp_user)
		queues = frappe.get_all(
			"Email Queue", filters={"reference_doctype": "Document", "reference_name": doc.name},
			fields=["name", "owner"],
		)
		self.assertTrue(queues)
		recipients = []
		for q in queues:
			self.assertEqual(q.owner, "Administrator")
			rows = frappe.get_all("Email Queue Recipient", filters={"parent": q.name}, pluck="recipient")
			self.assertEqual(len(rows), 1)
			recipients += rows
		self.assertEqual(len(recipients), len(set(recipients)))  # nobody emailed twice
		self.assertIn(self.hr_manager2, recipients)
		self.assertNotIn(self.emp_user, recipients)

	def test_hr_managers_own_upload_needs_approval(self):
		doc = self.make_doc(employee=self.hr_emp, user=self.hr_manager)
		self.assertEqual(doc.approval_status, PENDING)
		# the uploader is not notified about their own document
		self.assertFalse(self.notifications(doc, self.hr_manager))
		self.assertTrue(self.notifications(doc, self.hr_manager2))

	def test_approval_fields_not_accepted_from_the_browser(self):
		doc = self.make_doc(
			user=self.emp_user, approval_status=APPROVED, reviewed_by=self.hr_manager, rejection_reason="x"
		)
		self.assertEqual(doc.approval_status, PENDING)
		self.assertFalse(doc.reviewed_by)
		self.assertFalse(doc.rejection_reason)

		doc = self.fresh(doc, self.emp_user)
		doc.approval_status = APPROVED  # no content change: status must stay as it was
		doc.save()
		self.assertEqual(frappe.db.get_value("Document", doc.name, "approval_status"), PENDING)

	def test_employee_edit_after_approval_sends_back(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		doc.approve()

		doc = self.fresh(doc, self.emp_user)
		doc.place_of_issue = "Kochi"
		doc.save()
		self.assertEqual(doc.approval_status, PENDING)
		self.assertIn("Sent back for approval", " ".join(self.comments(doc)))

	def test_employee_file_change_sends_back(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		doc.approve()

		doc = self.fresh(doc, self.emp_user)
		doc.append("attachments", {"file": self.file_url, "description": "back"})
		doc.save()
		self.assertEqual(doc.approval_status, PENDING)

	def test_hr_edit_of_pending_auto_approves(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_user)
		doc.remarks = "checked"
		doc.save()
		self.assertEqual(doc.approval_status, APPROVED)
		self.assertEqual(doc.reviewed_by, self.hr_user)
		self.assertEqual(doc.submitted_by, self.emp_user)  # kept
		self.assertIn("Auto-approved", " ".join(self.comments(doc)))

	def test_save_without_changes_keeps_status(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_user)
		doc.save()
		self.assertEqual(doc.approval_status, PENDING)

	# --- approve / reject ------------------------------------------------
	def test_hr_manager_approves(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		doc.approve()
		doc = self.fresh(doc, self.hr_manager2)
		self.assertEqual(doc.approval_status, APPROVED)
		self.assertEqual(doc.reviewed_by, self.hr_manager2)
		self.assertTrue(doc.reviewed_on)
		self.assertIn("Approved by", " ".join(self.comments(doc)))
		self.assertIn("has been approved", self.notifications(doc, self.emp_user)[0].subject)

	def test_reject_needs_a_reason(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		with self.assertRaises(frappe.ValidationError):
			doc.reject("   ")
		self.assertEqual(frappe.db.get_value("Document", doc.name, "approval_status"), PENDING)

	def test_reject_and_resubmit(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		doc.reject("Scan is blurred")
		doc = self.fresh(doc, self.hr_manager2)
		self.assertEqual(doc.approval_status, REJECTED)
		self.assertEqual(doc.rejection_reason, "Scan is blurred")
		self.assertIn("Scan is blurred", " ".join(self.comments(doc)))
		self.assertIn("has been rejected", self.notifications(doc, self.emp_user)[0].subject)

		doc = self.fresh(doc, self.emp_user)
		doc.append("attachments", {"file": self.file_url, "description": "clear scan"})
		doc.save()
		self.assertEqual(doc.approval_status, PENDING)
		self.assertFalse(doc.reviewed_by)
		self.assertIn("Corrected and resubmitted", " ".join(self.comments(doc)))

	# --- Approval Status set in the form by the HR Manager -------------------
	def test_hr_manager_approves_from_status_field(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		doc.approval_status = APPROVED
		doc.save()
		doc = self.fresh(doc, self.hr_manager2)
		self.assertEqual(doc.approval_status, APPROVED)
		self.assertEqual(doc.reviewed_by, self.hr_manager2)
		self.assertTrue(doc.reviewed_on)
		self.assertIn("Approved by", " ".join(self.comments(doc)))
		self.assertIn("has been approved", self.notifications(doc, self.emp_user)[0].subject)
		self.assertNotIn("Auto-approved", " ".join(self.comments(doc)))

	def test_hr_manager_rejects_from_status_field(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		doc.approval_status = REJECTED
		doc.rejection_reason = "Scan is blurred"
		doc.save()
		doc = self.fresh(doc, self.hr_manager2)
		self.assertEqual(doc.approval_status, REJECTED)
		self.assertEqual(doc.rejection_reason, "Scan is blurred")
		self.assertIn("has been rejected", self.notifications(doc, self.emp_user)[0].subject)

	def test_status_field_reject_needs_a_reason(self):
		doc = self.make_doc(user=self.emp_user)
		doc = self.fresh(doc, self.hr_manager2)
		doc.approval_status = REJECTED
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value("Document", doc.name, "approval_status"), PENDING)

	def test_status_field_ignored_for_non_reviewers(self):
		# HR User (no HR Manager role) and the HR Manager on their own document
		for user, employee, uploader in (
			(self.hr_user, None, self.emp_user),
			(self.hr_manager, self.hr_emp, self.hr_manager),
		):
			with self.subTest(user=user):
				doc = self.make_doc(employee=employee, user=uploader)
				doc = self.fresh(doc, user)
				doc.approval_status = REJECTED
				doc.rejection_reason = "x"
				doc.save()
				self.assertNotEqual(frappe.db.get_value("Document", doc.name, "approval_status"), REJECTED)

	def test_status_field_only_for_pending_documents(self):
		doc = self.make_doc()  # HR upload: Approved
		doc = self.fresh(doc, self.hr_manager2)
		doc.approval_status = REJECTED
		doc.rejection_reason = "x"
		doc.save()
		self.assertEqual(frappe.db.get_value("Document", doc.name, "approval_status"), APPROVED)

	def test_only_hr_manager_reviews(self):
		doc = self.make_doc(user=self.emp_user)
		for user in (self.hr_user, self.emp_user):
			with self.subTest(user=user):
				self.as_user(user)
				with self.assertRaises(frappe.PermissionError):
					frappe.get_doc("Document", doc.name).approve()

	def test_hr_manager_cannot_review_own_document(self):
		doc = self.make_doc(employee=self.hr_emp, user=self.hr_manager)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Document", doc.name).approve()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Document", doc.name).reject("no")
		self.as_user(self.hr_manager2)
		frappe.get_doc("Document", doc.name).approve()
		self.assertEqual(frappe.db.get_value("Document", doc.name, "approval_status"), APPROVED)

	def test_only_pending_documents_reviewed(self):
		doc = self.make_doc(user=self.hr_manager2)  # Approved
		self.as_user(self.hr_manager)
		with self.assertRaises(frappe.ValidationError) as ctx:
			frappe.get_doc("Document", doc.name).reject("late")
		self.assertIn("Only documents with status Pending Approval", str(ctx.exception))

	def test_review_document_from_employee_form(self):
		doc = self.make_doc(user=self.emp_user)
		self.as_user(self.hr_manager2)
		self.assertEqual(review_document(doc.name, "reject", "wrong type"), REJECTED)
		with self.assertRaises(frappe.ValidationError):
			review_document(doc.name, "delete")

	def test_review_document_needs_write_access(self):
		doc = self.make_doc(user=self.emp_user)
		self.as_user(self.other_user)
		with self.assertRaises(frappe.PermissionError):
			review_document(doc.name, "approve")

	# --- permissions -----------------------------------------------------
	def test_employee_sees_only_own_documents(self):
		mine = self.make_doc(user=self.emp_user)
		frappe.set_user("Administrator")
		other = self.make_doc(employee=self.other_emp)

		self.as_user(self.emp_user)
		names = set(frappe.get_list("Document", pluck="name", limit_page_length=0))
		self.assertIn(mine.name, names)
		self.assertNotIn(other.name, names)
		self.assertTrue(has_permission(mine, "read", self.emp_user))
		self.assertFalse(has_permission(other, "read", self.emp_user))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Document", other.name).check_permission("read")

	def test_hr_sees_all_documents(self):
		mine = self.make_doc(user=self.emp_user)
		frappe.set_user("Administrator")
		other = self.make_doc(employee=self.other_emp)
		for user in (self.hr_user, self.hr_manager):
			with self.subTest(user=user):
				self.as_user(user)
				names = set(frappe.get_list("Document", pluck="name", limit_page_length=0))
				self.assertTrue({mine.name, other.name} <= names)

	def test_other_record_documents_follow_record_access(self):
		company = frappe.db.get_value("Employee", self.emp, "company")
		doc = self.make_doc(reference_doctype="Company", reference_name=company)
		self.assertTrue(has_permission(doc, "read", self.hr_user))
		self.assertEqual(
			has_permission(doc, "read", self.emp_user),
			bool(frappe.has_permission("Company", "read", doc=company, user=self.emp_user)),
		)

	def test_left_employee_documents_hidden(self):
		doc = self.make_doc()
		frappe.db.set_value("Employee", self.other_emp, "status", "Left")
		self.addCleanup(frappe.db.set_value, "Employee", self.other_emp, "status", "Active")
		left = self.make_doc(employee=self.other_emp)
		self.as_user(self.hr_manager)
		names = set(frappe.get_list("Document", pluck="name", limit_page_length=0))
		self.assertIn(doc.name, names)
		self.assertNotIn(left.name, names)

	def test_get_files_only_for_readable_documents(self):
		mine = self.make_doc(user=self.emp_user)
		frappe.set_user("Administrator")
		other = self.make_doc(employee=self.other_emp)
		self.as_user(self.emp_user)
		files = get_files([mine.name, other.name])
		self.assertEqual(list(files), [mine.name])
		self.assertEqual(files[mine.name][0], {"file": self.file_url, "description": "front"})

	# --- expiry alerts and report ----------------------------------------
	def expiring(self, days, employee=None, user=None):
		"""Approved (or, with user=employee user, pending) Passport document expiring in `days` days."""
		doc = self.make_doc(employee=employee, user=user, issue_date=add_days(today(), -400))
		frappe.set_user("Administrator")
		doc.db_set("expiry_date", add_days(today(), days))
		return doc

	# --- bell for the HR Manager (ClickUp 14yr2e57crv) -----------------------
	def test_hr_manager_bell_lists_pending_document(self):
		"""What the HR Manager's bell loads after an employee upload: the app's uncached method."""
		from alantech_erp.setup.notifications import get_notification_logs

		doc = self.make_doc(user=self.emp_user)
		frappe.set_user(self.hr_manager2)
		logs = get_notification_logs(limit=20)["notification_logs"]
		mine = [log for log in logs if log.document_name == doc.name]
		self.assertEqual(len(mine), 1)
		self.assertIn("needs approval", mine[0].subject)
		self.assertEqual((mine[0].for_user, mine[0].from_user, mine[0].read), (self.hr_manager2, self.emp_user, 0))
		self.assertGreaterEqual(frappe.db.count("Notification Log", {"for_user": self.hr_manager2, "read": 0}), 1)

		frappe.set_user(self.other_user)  # another user's bell never contains it
		self.assertFalse([log for log in get_notification_logs(limit=20)["notification_logs"]
			if log.document_name == doc.name])

	def test_expiry_alert_before_and_on_expiry_day(self):
		soon = self.expiring(30)  # PASSPORT alerts 30 days before
		due = self.expiring(0, employee=self.other_emp)
		outside = self.expiring(31, employee=self.hr_emp)
		send_expiry_alerts()

		soon_users = {n.for_user for n in self.notifications(soon)}
		self.assertTrue({self.emp_user, self.hr_manager, self.hr_manager2} <= soon_users)
		self.assertIn("expires in 30 days", self.notifications(soon, self.emp_user)[0].subject)
		self.assertIn("expires today", self.notifications(due, self.other_user)[0].subject)
		self.assertFalse(self.notifications(outside))

	# --- alert once for documents already inside the window (ClickUp 14yr2e57cqm) ---
	def test_expiry_alert_for_document_added_inside_window(self):
		"""Added with 6 days left (the 30-day point has passed): alerted on the next run, once."""
		late = self.expiring(6)
		send_expiry_alerts()
		subjects = [n.subject for n in self.notifications(late, self.emp_user)]
		self.assertEqual(len(subjects), 1)
		self.assertIn("expires in 6 days", subjects[0])
		self.assertEqual(str(frappe.db.get_value("Document", late.name, "expiry_alert_sent_for")),
			str(late.expiry_date))

		send_expiry_alerts()  # next day's run (same date here): no second advance alert
		self.assertEqual(len(self.notifications(late, self.emp_user)), 1)

	def test_expiry_alert_wording_for_employee_and_hr(self):
		doc = self.expiring(0)
		send_expiry_alerts()
		own = self.notifications(doc, self.emp_user)
		self.assertEqual(len(own), 1)
		self.assertTrue(own[0].subject.startswith(f"Your {PASSPORT} expires today"))
		self.assertNotIn(doc.reference_title, own[0].subject)
		hr = self.notifications(doc, self.hr_manager2)
		self.assertEqual(len(hr), 1)
		self.assertIn(f"for {doc.reference_title} expires today", hr[0].subject)

	def test_expiry_alert_for_hr_managers_own_document(self):
		doc = self.expiring(3, employee=self.hr_emp)
		send_expiry_alerts()
		own = self.notifications(doc, self.hr_manager)
		self.assertEqual(len(own), 1)  # only the "Your ..." one, not the HR one as well
		self.assertTrue(own[0].subject.startswith(f"Your {PASSPORT} expires in 3 days"))

	def test_expiry_alert_tomorrow_wording(self):
		doc = self.expiring(1)
		send_expiry_alerts()
		self.assertIn("expires tomorrow", self.notifications(doc, self.emp_user)[0].subject)

	def test_expiry_day_alert_even_after_advance_alert(self):
		doc = self.expiring(0)
		doc.db_set("expiry_alert_sent_for", doc.expiry_date)  # advance alert sent earlier
		send_expiry_alerts()
		self.assertIn("expires today", self.notifications(doc, self.emp_user)[0].subject)

	def test_renewed_document_alerted_again(self):
		doc = self.expiring(10)
		send_expiry_alerts()
		self.assertEqual(len(self.notifications(doc, self.emp_user)), 1)
		doc.db_set("expiry_date", add_days(today(), 20))  # renewed / corrected: a new Expiry Date
		send_expiry_alerts()
		subjects = [n.subject for n in self.notifications(doc, self.emp_user)]
		self.assertEqual(len(subjects), 2)
		self.assertTrue(any("expires in 20 days" in s for s in subjects))

	def test_pending_document_alerted_once_approved_inside_window(self):
		doc = self.expiring(12, user=self.emp_user)  # Pending Approval
		send_expiry_alerts()
		self.assertFalse(self.notifications(doc, self.emp_user))
		self.fresh(doc, self.hr_manager2).approve()
		frappe.set_user("Administrator")
		frappe.db.delete("Notification Log", {"document_name": doc.name})  # drop the approval note
		send_expiry_alerts()
		self.assertIn("expires in 12 days", self.notifications(doc, self.emp_user)[0].subject)

	def test_no_expiry_alert_for_pending_or_left(self):
		pending = self.expiring(30, user=self.emp_user)
		left = self.expiring(30, employee=self.other_emp)
		frappe.db.set_value("Employee", self.other_emp, "status", "Left")
		self.addCleanup(frappe.db.set_value, "Employee", self.other_emp, "status", "Active")
		frappe.db.delete("Notification Log", {"document_name": ["in", [pending.name, left.name]]})
		send_expiry_alerts()
		self.assertFalse(self.notifications(pending))
		self.assertFalse(self.notifications(left))

	def report_names(self, **filters):
		return {row.name: row for row in expiry_report(filters)[1]}

	def test_expiry_report(self):
		soon = self.expiring(10)
		later = self.expiring(100, employee=self.other_emp)
		expired = self.expiring(-5, employee=self.hr_emp)
		pending = self.expiring(10, user=self.emp_user)

		rows = self.report_names(document_type=PASSPORT, include_expired=1)
		self.assertIn(soon.name, rows)
		self.assertIn(expired.name, rows)
		self.assertNotIn(later.name, rows)  # default window 90 days
		self.assertNotIn(pending.name, rows)  # approved only
		self.assertEqual(rows[soon.name].days_left, 10)
		self.assertEqual(rows[expired.name].days_left, -5)

		rows = self.report_names(document_type=PASSPORT, include_expired=0, expiring_within_days=120)
		self.assertIn(later.name, rows)
		self.assertNotIn(expired.name, rows)

		self.assertFalse(self.report_names(document_type=PASSPORT, reference_doctype="Company"))

	# --- report list not displayed (ClickUp 14yr2e57cqm) --------------------
	def id_card_expiring(self, days, employee=None, user=None):
		"""QA's Driving License case: the type has Expiry Date switched off, yet the document has one."""
		doc = self.make_doc(employee=employee, user=user, document_type=ID_CARD, card_number=AADHAAR)
		frappe.set_user("Administrator")
		doc.db_set("expiry_date", add_days(today(), days))
		return doc

	def test_expiry_report_lists_type_without_expiry_rule(self):
		doc = self.id_card_expiring(20)
		rows = self.report_names(expiring_within_days=90, include_expired=1)
		self.assertIn(doc.name, rows)
		self.assertEqual(rows[doc.name].days_left, 20)
		self.assertEqual(rows[doc.name].approval_status, APPROVED)

	def test_expiry_report_skips_documents_without_expiry_date(self):
		no_date = self.make_doc(document_type=ID_CARD, card_number=AADHAAR)
		self.assertFalse(no_date.expiry_date)
		self.assertNotIn(no_date.name, self.report_names(include_expired=1))
		self.assertNotIn(no_date.name, self.report_names(include_expired=0))

	def test_expiry_report_explains_pending_documents(self):
		pending = self.expiring(10, user=self.emp_user)
		columns, data, message = expiry_report({"document_type": PASSPORT, "include_expired": 1})
		self.assertNotIn(pending.name, {row.name for row in data})
		self.assertIn("1 document(s) in this range are waiting for HR Manager approval", message)

		rows = self.report_names(document_type=PASSPORT, include_expired=1, approval_status="Approved and Pending")
		self.assertIn(pending.name, rows)
		self.assertEqual(rows[pending.name].approval_status, PENDING)
		self.assertIsNone(expiry_report({"document_type": PASSPORT, "approval_status": "Approved and Pending"})[2])

	def test_expiry_report_never_lists_rejected(self):
		rejected = self.expiring(10, user=self.emp_user)
		self.fresh(rejected, self.hr_manager2).reject("wrong scan")
		frappe.set_user("Administrator")
		rows = self.report_names(document_type=PASSPORT, include_expired=1, approval_status="Approved and Pending")
		self.assertNotIn(rejected.name, rows)

	def test_expiry_report_as_hr_user(self):
		doc = self.expiring(15)
		frappe.set_user(self.hr_user)
		self.assertIn(doc.name, self.report_names(document_type=PASSPORT))

	def test_expiry_alert_for_type_with_expiry_switched_off(self):
		doc = self.id_card_expiring(30)  # alert days 30 (type default)
		days = frappe.db.get_value("Document Type Master", ID_CARD, "alert_days_before") or 30
		frappe.db.set_value("Document", doc.name, "expiry_date", add_days(today(), int(days)))
		send_expiry_alerts()
		self.assertTrue(self.notifications(doc, self.emp_user))

	def test_expiry_report_soonest_first(self):
		self.expiring(20)
		self.expiring(5, employee=self.other_emp)
		days = [row.days_left for row in expiry_report({"document_type": PASSPORT})[1]]
		self.assertEqual(days, sorted(days))
