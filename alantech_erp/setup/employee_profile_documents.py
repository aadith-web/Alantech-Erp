"""Employee profile > Documents: show the Document Type Master "Mandatory at Joining" documents.

The Details tab checklist reads alantech's own Document records (alantech/doctype/document),
through get_mandatory_documents. HRMS's profile page reads its Employee Document rows and its
Employee Document Type list instead, so those required documents never reached the profile
("No documents yet"). This wraps HRMS's get_profile and adds the same rows to
profile["private"]["documents"]. HRMS's document actions (upload, ask, review, remove) answer
with HRMS's own private data, so they are wrapped too: the list the page refreshes from keeps
the mandatory rows. HRMS itself is not changed.

hooks.py override_whitelisted_methods points these methods here.
"""

import frappe
from hrms.hr.page.employee_profile.employee_profile import get_profile as hrms_get_profile
from hrms.hr.page.employee_profile.employee_profile import get_user_employee
from hrms.hr.page.employee_profile.employee_profile import remove_document as hrms_remove_document
from hrms.hr.page.employee_profile.employee_profile import request_document as hrms_request_document
from hrms.hr.page.employee_profile.employee_profile import review_document as hrms_review_document
from hrms.hr.page.employee_profile.employee_profile import upload_document as hrms_upload_document

from alantech_erp.alantech.doctype.document.document import get_files, mandatory_document_status

MISSING = "Missing"


def add_mandatory_documents(private: dict, employee: str) -> dict:
	"""Adds the mandatory-at-joining rows to HRMS's private data of `employee`"""
	rows = mandatory_document_status(employee)
	files = get_files([row["document"] for row in rows if row["document"]]) if rows else {}

	documents = private.get("documents") or []
	position = {document.get("document_type"): index for index, document in enumerate(documents)}

	for row in rows:
		attachments = files.get(row["document"]) or []
		item = {
			"document_type": row["document_type"],
			"status": row["status"],
			"attachment": attachments[0]["file"] if attachments else None,
			"document_number": None,
			"expiry_date": None,
			"verified_on": None,
			"due_date": None,
			"remarks": None,
			"has_number": 0,
			"has_expiry": 0,
		}
		index = position.get(row["document_type"])
		if index is None:
			position[row["document_type"]] = len(documents)
			documents.append(item)
		elif documents[index].get("status") == MISSING:
			# an HRMS "Missing" line for the same type gives way to the real status
			documents[index] = item

	private["documents"] = documents
	return private


@frappe.whitelist()
def get_profile(employee: str | None = None) -> dict:
	profile = hrms_get_profile(employee=employee)
	private = profile.get("private")
	if not private:
		# only those who may read the record see the documents, as in HRMS
		return profile

	employee = employee or get_user_employee()
	if not employee:
		return profile

	profile["private"] = add_mandatory_documents(private, employee)
	return profile


def _with_mandatory(private: dict, employee: str | None) -> dict:
	employee = employee or get_user_employee()
	return add_mandatory_documents(private, employee) if employee else private


@frappe.whitelist(methods=["POST"])
def request_document(employee: str, document_type: str, due_date: str | None = None) -> dict:
	"""Ask for a document. The mandatory types come from Document Type Master, but HRMS's request
	needs an Employee Document Type with that name, so one is created from the master first
	(otherwise "Employee Document Type ... not found")."""
	if not frappe.db.exists("Employee Document Type", document_type) and frappe.db.exists(
		"Document Type Master", document_type
	):
		frappe.get_doc({"doctype": "Employee Document Type", "document_type": document_type}).insert(
			ignore_permissions=True
		)
	private = hrms_request_document(employee=employee, document_type=document_type, due_date=due_date)
	return _with_mandatory(private, employee)


@frappe.whitelist(methods=["POST"])
def upload_document(
	document_type: str,
	file_url: str,
	document_number: str | None = None,
	expiry_date: str | None = None,
	employee: str | None = None,
) -> dict:
	private = hrms_upload_document(
		document_type=document_type,
		file_url=file_url,
		document_number=document_number,
		expiry_date=expiry_date,
		employee=employee,
	)
	return _with_mandatory(private, employee)


@frappe.whitelist(methods=["POST"])
def review_document(employee: str, document_type: str, status: str, remarks: str | None = None) -> dict:
	private = hrms_review_document(
		employee=employee, document_type=document_type, status=status, remarks=remarks
	)
	return _with_mandatory(private, employee)


@frappe.whitelist(methods=["POST"])
def remove_document(document_type: str, employee: str | None = None) -> dict:
	private = hrms_remove_document(document_type=document_type, employee=employee)
	return _with_mandatory(private, employee)
