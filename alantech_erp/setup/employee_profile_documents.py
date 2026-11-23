"""Employee profile > Documents: show the Document Type Master "Mandatory at Joining" documents.

The Details tab checklist reads alantech's own Document records (alantech/doctype/document),
through get_mandatory_documents. HRMS's profile page reads its Employee Document rows and its
Employee Document Type list instead, so those required documents never reached the profile
("No documents yet"). This wraps HRMS's get_profile and adds the same rows to
profile["private"]["documents"]. HRMS itself is not changed.

hooks.py override_whitelisted_methods points get_profile here.
"""

import frappe
from hrms.hr.page.employee_profile.employee_profile import get_profile as hrms_get_profile
from hrms.hr.page.employee_profile.employee_profile import get_user_employee

from alantech_erp.alantech.doctype.document.document import get_files, mandatory_document_status

MISSING = "Missing"


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
	return profile
