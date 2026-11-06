# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Document files: only PDF, JPG or PNG, at most 5 MB each.

ClickUp: https://app.clickup.com/t/14yr2e57a43

Checked in three places, so no path gets round it:
    document.js            the upload dialog only offers these types and refuses bigger files
                           (FILE_RESTRICTIONS, sent with the form's __onload)
    validate_file(doc)     File.validate (hooks.py doc_events): an upload for a Document is refused
                           before it is kept, whatever the client (REST API, mobile, desk)
    validate_attachments() Document.validate: each newly added or changed file row; existing rows
                           are not checked again, so an older document can still be edited
"""

import os
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.utils import flt

DOCTYPE = "Document"
ALLOWED_EXTENSIONS = ("pdf", "jpg", "jpeg", "png")
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024


class DocumentFileError(frappe.ValidationError):
	pass


def file_restrictions():
	"""For the upload dialog (frappe.ui.FileUploader restrictions)."""
	return {
		"allowed_file_types": [f".{ext}" for ext in ALLOWED_EXTENSIONS],
		"max_file_size": MAX_FILE_SIZE,
	}


def extension(name):
	path = urlparse(name or "").path
	return os.path.splitext(path)[1].lstrip(".").lower()


def size_mb(size):
	return flt(size / (1024 * 1024), 1)


def check(file_name, size=None):
	"""Throws when the file is of a type or size a Document does not accept."""
	label = os.path.basename(urlparse(file_name or "").path) or file_name
	if extension(file_name) not in ALLOWED_EXTENSIONS:
		frappe.throw(
			_("{0} cannot be uploaded. Only PDF, JPG and PNG files are allowed.").format(frappe.bold(label)),
			DocumentFileError,
			title=_("File Type Not Allowed"),
		)
	if size and size > MAX_FILE_SIZE:
		frappe.throw(
			_("{0} is {1} MB. Files can be at most {2} MB.").format(
				frappe.bold(label), size_mb(size), MAX_FILE_SIZE_MB
			),
			DocumentFileError,
			title=_("File Too Large"),
		)


def validate_file(doc, method=None):
	"""File.validate: uploads made for a Document (its form, or the API)."""
	if doc.is_folder or doc.attached_to_doctype != DOCTYPE:
		return
	if not doc.is_new() and not doc.has_value_changed("file_url"):
		return
	check(doc.file_name or doc.file_url, doc.file_size)


def validate_attachments(doc):
	"""Document.validate: file rows that are new or point to another file than before."""
	before = None if doc.is_new() else doc.get_doc_before_save()
	old_files = {row.file for row in (before.get("attachments") if before else None) or []}
	for row in doc.get("attachments") or []:
		if not row.file or row.file in old_files:
			continue
		check(row.file, stored_size(row.file))


def stored_size(file_url):
	"""Size of the uploaded file behind the URL (None for a link to another site)."""
	sizes = frappe.get_all("File", filters={"file_url": file_url}, pluck="file_size")
	return max((s or 0) for s in sizes) if sizes else None
