# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales Activity Summary (CRM C10): per activity owner, the calls, meetings, tasks, notes, emails
and comments dated in the period, how many are completed / open, and the follow-ups still pending
and overdue (today). Follows the sales hierarchy: a manager sees their team, an engineer themselves.
"""

import frappe
from frappe import _
from frappe.utils import cint, get_first_day, getdate, nowdate

from alantech_erp.sales.activity import CANCELLED, COMPLETED, OPEN, TASK

TYPES = ("Call", "Meeting", "Task", "Note", "Email", "Comment")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.from_date or get_first_day(nowdate()))
	to_date = getdate(filters.to_date or nowdate())
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	conditions = {"activity_date": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59.999999"]]}
	for key in ("activity_owner", "reference_doctype"):
		if filters.get(key):
			conditions[key] = filters.get(key)
	rows = frappe.get_list(
		"Sales Activity",
		filters=conditions,
		fields=["activity_owner", "activity_type", "status"],
		limit_page_length=0,
	)
	pending_filters = {"status": ["!=", CANCELLED], "follow_up_done": 0, "follow_up_date": ["is", "set"]}
	for key in ("activity_owner", "reference_doctype"):
		if filters.get(key):
			pending_filters[key] = filters.get(key)
	pending = frappe.get_list(
		"Sales Activity",
		filters=pending_filters,
		fields=["activity_owner", "activity_type", "status", "follow_up_date"],
		limit_page_length=0,
	)

	data = {}

	def bucket(owner):
		if owner not in data:
			data[owner] = frappe._dict(
				{"activity_owner": owner, "total": 0, "completed": 0, "open": 0, "pending": 0, "overdue": 0, **{t.lower(): 0 for t in TYPES}}
			)
		return data[owner]

	for r in rows:
		b = bucket(r.activity_owner)
		b[r.activity_type.lower()] = b.get(r.activity_type.lower(), 0) + 1
		if r.status == CANCELLED:
			continue
		b.total += 1
		b.completed += r.status == COMPLETED
		b.open += r.status == OPEN
	today = getdate(nowdate())
	for r in pending:
		if r.activity_type == TASK and r.status != OPEN:
			continue
		b = bucket(r.activity_owner)
		b.pending += 1
		b.overdue += getdate(r.follow_up_date) < today

	result = sorted(data.values(), key=lambda r: (-cint(r.total), r.activity_owner or ""))
	for r in result:
		r.full_name = frappe.utils.get_fullname(r.activity_owner)
	return get_columns(), result, None, get_chart(result), get_summary(result)


def get_columns():
	def count(fieldname, label, width=90):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": "Int", "width": width}

	return [
		{"fieldname": "activity_owner", "label": _("Owner"), "fieldtype": "Link", "options": "User", "width": 200},
		{"fieldname": "full_name", "label": _("Name"), "fieldtype": "Data", "width": 160},
		count("call", "Calls"),
		count("meeting", "Meetings"),
		count("task", "Tasks"),
		count("note", "Notes"),
		count("email", "Emails"),
		count("comment", "Comments"),
		count("total", "Total"),
		count("completed", "Completed", 100),
		count("open", "Open"),
		count("pending", "Follow-ups Pending", 140),
		count("overdue", "Overdue"),
	]


def get_chart(rows):
	rows = rows[:10]
	if not rows:
		return None
	return {
		"data": {
			"labels": [r.full_name or r.activity_owner for r in rows],
			"datasets": [{"name": _(t + "s"), "values": [r[t.lower()] for r in rows]} for t in ("Call", "Meeting", "Task", "Email")],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
	}


def get_summary(rows):
	def total(key):
		return sum(cint(r.get(key)) for r in rows)

	return [
		{"value": total("call"), "label": _("Calls"), "datatype": "Int", "indicator": "blue"},
		{"value": total("meeting"), "label": _("Meetings"), "datatype": "Int", "indicator": "blue"},
		{"value": total("task"), "label": _("Tasks"), "datatype": "Int", "indicator": "blue"},
		{"value": total("completed"), "label": _("Completed"), "datatype": "Int", "indicator": "green"},
		{"value": total("pending"), "label": _("Follow-ups Pending"), "datatype": "Int", "indicator": "orange"},
		{"value": total("overdue"), "label": _("Overdue"), "datatype": "Int", "indicator": "red" if total("overdue") else "green"},
	]
