"""Sales activities (CRM C10): the calls and meetings logged on Leads before Sales Activity existed
were Events (Lead > Activity > Call / Meeting). Each becomes a Sales Activity linked to its Event, so
they show in the new Activities panel, list and reports."""

import frappe
from frappe.utils import cstr, strip_html

STATUS = {"Open": "Open", "Completed": "Completed", "Closed": "Completed", "Cancelled": "Cancelled"}


def execute():
	if not frappe.db.exists("DocType", "Sales Activity"):
		return
	frappe.reload_doc("alantech", "doctype", "sales_activity")
	has = frappe.get_meta("Event").has_field
	fields = ["name", "subject", "event_category", "starts_on", "ends_on", "status", "owner", "description",
		"reference_doctype", "reference_docname"]
	fields += [f for f in ("custom_call_type", "custom_call_purpose", "custom_call_result") if has(f)]
	events = frappe.get_all(
		"Event",
		filters={
			"event_category": ["in", ["Call", "Meeting"]],
			"reference_doctype": ["in", ["Lead", "Customer", "Opportunity"]],
			"reference_docname": ["is", "set"],
		},
		fields=fields,
	)
	for ev in events:
		if frappe.db.exists("Sales Activity", {"event": ev.name}):
			continue
		if not frappe.db.exists(ev.reference_doctype, ev.reference_docname):
			continue
		status = STATUS.get(ev.status, "Open")
		summary = cstr(ev.get("custom_call_result")).strip() or strip_html(cstr(ev.description)).strip()
		if status == "Completed" and not summary:
			summary = "(logged before Sales Activities; no summary recorded)"
		doc = frappe.get_doc(
			{
				"doctype": "Sales Activity",
				"activity_type": ev.event_category,
				"subject": cstr(ev.subject)[:140] or ev.event_category,
				"status": status,
				"reference_doctype": ev.reference_doctype,
				"reference_name": ev.reference_docname,
				"activity_owner": ev.owner if frappe.db.get_value("User", ev.owner, "enabled") else "Administrator",
				"activity_date": ev.starts_on,
				"ends_on": ev.ends_on,
				"description": ev.description,
				"summary": summary or None,
				"call_direction": ev.get("custom_call_type") or None,
				"call_purpose": ev.get("custom_call_purpose") if ev.get("custom_call_purpose") in (
					"Prospecting", "Follow-up", "Negotiation", "Demo", "Other") else None,
				"event": ev.name,
			}
		)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True
		doc.insert()
