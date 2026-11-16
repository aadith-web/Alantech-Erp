# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales Performance Settings: forecast source and period, commission switch and payout defaults."""

import frappe
from frappe.model.document import Document


class SalesPerformanceSettings(Document):
	def on_update(self):
		frappe.clear_document_cache(self.doctype, self.name)
