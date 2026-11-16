# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales Activity: a call, meeting, task, note, email or comment on a Lead, Customer or Deal
(CRM C10). The rules live in alantech_erp/sales/activity.py."""

from frappe.model.document import Document

from alantech_erp.sales import activity


class SalesActivity(Document):
	def validate(self):
		activity.validate(self)

	def on_update(self):
		activity.on_update(self)

	def on_trash(self):
		activity.on_trash(self)
