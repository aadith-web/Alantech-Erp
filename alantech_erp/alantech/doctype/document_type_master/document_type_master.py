# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from alantech_erp.alantech.doctype.document.document_number import CUSTOM, FORMATS, validate_pattern


class DocumentTypeMaster(Document):
	def validate(self):
		# a date that is not shown on the document cannot be mandatory
		if not self.issue_date_required:
			self.issue_date_mandatory = 0
		if not self.expiry_required:
			self.expiry_date_mandatory = 0

		if self.number_format == CUSTOM:
			validate_pattern(self.number_pattern)
		else:
			self.number_pattern = None
		if not self.number_example and self.number_format in FORMATS:
			self.number_example = FORMATS[self.number_format]["example"]
