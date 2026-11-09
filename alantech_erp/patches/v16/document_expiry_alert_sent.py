# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Document.expiry_alert_sent_for for documents already alerted before the field existed.

ClickUp: https://app.clickup.com/t/14yr2e57cqm
send_expiry_alerts now alerts every approved document inside its alert window once per Expiry Date.
Documents inside the window that already got the old "expires in N days" alert (a Notification Log
since the window started) are marked, so they are not alerted a second time after the deploy.
"""

import frappe
from frappe.utils import add_days, cint, getdate, today


def execute():
	run_date = getdate(today())
	for doc_type in frappe.get_all("Document Type Master", fields=["name", "alert_days_before"]):
		days = cint(doc_type.alert_days_before) or 30
		for doc in frappe.get_all(
			"Document",
			filters={
				"document_type": doc_type.name,
				"expiry_date": ["between", [run_date, add_days(run_date, days)]],
			},
			fields=["name", "expiry_date"],
		):
			window_start = add_days(doc.expiry_date, -days)
			alerted = frappe.db.exists(
				"Notification Log",
				{
					"document_type": "Document",
					"document_name": doc.name,
					"subject": ["like", "%expires in%"],
					"creation": [">=", window_start],
				},
			)
			if alerted:
				frappe.db.set_value(
					"Document", doc.name, "expiry_alert_sent_for", doc.expiry_date, update_modified=False
				)
