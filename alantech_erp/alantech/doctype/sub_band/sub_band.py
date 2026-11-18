# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sub Band master (A to E): the sub band of an Employee Grade, picked on its Sub Bands table
(Employee Grade Sub Band) with the gross amount for that grade. ClickUp 14yr2e586v1."""

from frappe.model.document import Document


class SubBand(Document):
	def validate(self):
		self.sub_band = (self.sub_band or "").strip()
