# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Document files: type and size rules (document_files.py; ClickUp 14yr2e57a43).

Unit tests, no records are created. Uploads and Document saves are covered in test_document.py
(test_zip_upload_refused ... test_existing_file_rows_not_checked_again).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.document.test_document_files
"""

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.alantech.doctype.document.document_files import (
	ALLOWED_EXTENSIONS,
	MAX_FILE_SIZE,
	MAX_FILE_SIZE_MB,
	DocumentFileError,
	check,
	extension,
	file_restrictions,
	validate_file,
)

MB = 1024 * 1024


class UnitTestDocumentFiles(UnitTestCase):
	def assert_refused(self, name, size, text):
		with self.assertRaises(DocumentFileError) as ctx:
			check(name, size)
		self.assertIn(text, str(ctx.exception))

	def test_limits(self):
		self.assertEqual(MAX_FILE_SIZE_MB, 5)
		self.assertEqual(MAX_FILE_SIZE, 5 * MB)
		self.assertEqual(set(ALLOWED_EXTENSIONS), {"pdf", "jpg", "jpeg", "png"})

	def test_extension_from_name_or_url(self):
		self.assertEqual(extension("scan.PDF"), "pdf")
		self.assertEqual(extension("/private/files/passport front.jpeg"), "jpeg")
		self.assertEqual(extension("/files/visa.png?fid=abc123"), "png")
		self.assertEqual(extension("https://example.com/docs/id.pdf#page=2"), "pdf")
		self.assertEqual(extension("archive.tar.gz"), "gz")
		self.assertEqual(extension("no_extension"), "")
		self.assertEqual(extension(None), "")

	def test_allowed_types_pass(self):
		for name in ("a.pdf", "b.jpg", "c.JPEG", "d.Png", "/private/files/e.pdf"):
			check(name, 1024)  # no exception

	def test_other_types_refused(self):
		for name in ("scan.zip", "scan.rar", "scan.docx", "scan.exe", "scan.csv", "scan.gif", "scan", "scan.pdf.zip"):
			self.assert_refused(name, 1024, "Only PDF, JPG and PNG files are allowed")

	def test_type_message_names_the_file(self):
		self.assert_refused("/private/files/my scan.zip", None, "my scan.zip")

	def test_size_boundary(self):
		check("ok.pdf", MAX_FILE_SIZE)  # exactly 5 MB is allowed
		self.assert_refused("big.pdf", MAX_FILE_SIZE + 1, "Files can be at most 5 MB")

	def test_size_message_shows_size(self):
		self.assert_refused("big.pdf", 16 * MB, "big.pdf</strong> is 16.0 MB")
		self.assert_refused("six.png", int(6.2 * MB), "is 6.2 MB")

	def test_unknown_size_checks_type_only(self):
		check("https://example.com/id.pdf", None)
		check("id.pdf", 0)

	def test_type_checked_before_size(self):
		self.assert_refused("big.zip", 16 * MB, "Only PDF, JPG and PNG")

	def test_upload_dialog_restrictions(self):
		self.assertEqual(
			file_restrictions(),
			{"allowed_file_types": [".pdf", ".jpg", ".jpeg", ".png"], "max_file_size": 5 * MB},
		)

	# --- File hook: only files for a Document --------------------------------
	def file(self, **values):
		doc = frappe.get_doc({"doctype": "File", "file_name": "x.zip", "file_size": 16 * MB, **values})
		return doc

	def test_file_hook_refuses_document_upload(self):
		with self.assertRaises(DocumentFileError):
			validate_file(self.file(attached_to_doctype="Document", attached_to_name="DOC-2026-00001"))

	def test_file_hook_ignores_other_doctypes_and_folders(self):
		validate_file(self.file(attached_to_doctype="Employee", attached_to_name="HR-EMP-00001"))
		validate_file(self.file())  # not attached to anything
		validate_file(self.file(attached_to_doctype="Document", is_folder=1))
