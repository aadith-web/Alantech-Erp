"""Sales activities (CRM requirement C10; D2 for the call summary).

Calls, meetings, tasks, notes, emails and comments on a Lead, Customer or Deal (Opportunity) are
one list of Sales Activity records, each with its date, owner and follow-up due date.

  Call / Meeting  scheduled or logged; a calendar Event is kept in step (owner's calendar, the
                  record as participant) so calendar sync (C32 / C33) can pick it up. Completing it
                  needs the Outcome / Summary (decision D2: no closing a call without a summary).
  Task            something to do by the follow-up (due) date; a ToDo for the owner.
  Note            a note on the record (completed when saved).
  Email           logged by itself for every email sent or received on the record.
  Comment         logged by itself for every comment added on the record's timeline.

Follow-up due date: a ToDo for the activity owner (closing the ToDo marks the follow-up done / the
task completed), a daily reminder of what is due and overdue, and "Follow-up" on the activity
opens the next one with the same record.

Access follows the sales hierarchy (sales/hierarchy.py): engineers see their own and the ones
assigned to them, managers their team's, the Sales Director everything.
"""

import frappe
from frappe import _
from frappe.utils import (
	add_to_date,
	cint,
	cstr,
	get_datetime,
	get_link_to_form,
	getdate,
	now_datetime,
	nowdate,
	strip_html,
)

DOCTYPE = "Sales Activity"
REFERENCE_DOCTYPES = ("Lead", "Customer", "Opportunity")

CALL, MEETING, TASK, NOTE, EMAIL, COMMENT = "Call", "Meeting", "Task", "Note", "Email", "Comment"
SCHEDULED_TYPES = (CALL, MEETING)  # have an Event
LOGGED_TYPES = (NOTE, EMAIL, COMMENT)  # completed as soon as they are saved
OPEN, COMPLETED, CANCELLED = "Open", "Completed", "Cancelled"

EVENT_STATUS = {OPEN: "Open", COMPLETED: "Completed", CANCELLED: "Cancelled"}

# the record's "owner" field: received emails / comments by others go to this user
RECORD_OWNER_FIELD = {"Lead": "lead_owner", "Customer": "account_manager", "Opportunity": "opportunity_owner"}
RECORD_TITLE_FIELD = {"Lead": ("company_name", "lead_name"), "Customer": ("customer_name",), "Opportunity": ("customer_name", "title")}


# --------------------------------------------------------------------------- helpers
def record_title(doctype, name):
	fields = RECORD_TITLE_FIELD.get(doctype, ())
	if not name or not fields:
		return name
	values = frappe.db.get_value(doctype, name, list(fields), as_dict=True) or {}
	for field in fields:
		if values.get(field):
			return values[field]
	return name


def record_owner(doctype, name):
	field = RECORD_OWNER_FIELD.get(doctype)
	user = field and frappe.db.get_value(doctype, name, field)
	return user or frappe.db.get_value(doctype, name, "owner")


def _enabled_user(user):
	return bool(user) and user not in ("Guest",) and bool(frappe.db.get_value("User", user, "enabled"))


# --------------------------------------------------------------------------- Sales Activity controller logic
def validate(doc):
	if doc.reference_doctype not in REFERENCE_DOCTYPES:
		frappe.throw(_("An activity is logged on a Lead, Customer or Deal."), title=_("Not Allowed"))
	if not frappe.db.exists(doc.reference_doctype, doc.reference_name):
		frappe.throw(_("{0} {1} does not exist.").format(_(doc.reference_doctype), frappe.bold(doc.reference_name)))
	doc.party_name = record_title(doc.reference_doctype, doc.reference_name)
	if not doc.activity_owner:
		doc.activity_owner = frappe.session.user
	if not doc.activity_date:
		doc.activity_date = now_datetime()

	if doc.activity_type in LOGGED_TYPES and doc.is_new() and doc.status == OPEN:
		doc.status = COMPLETED
	if doc.ends_on and get_datetime(doc.ends_on) < get_datetime(doc.activity_date):
		frappe.throw(_("Ends On cannot be before the activity date."), title=_("Invalid Dates"))
	if doc.activity_type in SCHEDULED_TYPES and not doc.ends_on:
		doc.ends_on = add_to_date(doc.activity_date, minutes=30)
	if doc.follow_up_date and getdate(doc.follow_up_date) < getdate(doc.activity_date):
		frappe.throw(_("The follow-up due date cannot be before the activity date."), title=_("Invalid Dates"))
	if doc.activity_type == TASK and not doc.follow_up_date:
		frappe.throw(_("Set the due date (Follow-up Due Date) of the task."), title=_("Due Date Missing"))
	if doc.contact_person:
		_check_contact(doc)

	if doc.status == COMPLETED:
		# D2: a call or meeting is closed only with what came out of it
		if doc.activity_type in SCHEDULED_TYPES and not cstr(doc.summary).strip():
			frappe.throw(
				_("Enter the Outcome / Summary of the {0} before completing it.").format(_(doc.activity_type).lower()),
				title=_("Summary Required"),
			)
		if not doc.completed_on:
			doc.completed_on = now_datetime()
			doc.completed_by = frappe.session.user
		if doc.activity_type == TASK:
			doc.follow_up_done = 1
	else:
		doc.completed_on = doc.completed_by = None


def _check_contact(doc):
	linked = frappe.db.exists(
		"Dynamic Link",
		{"parenttype": "Contact", "parent": doc.contact_person, "link_doctype": doc.reference_doctype, "link_name": doc.reference_name},
	)
	if not linked:
		frappe.throw(
			_("Contact {0} is not linked to {1} {2}.").format(
				frappe.bold(doc.contact_person), _(doc.reference_doctype), frappe.bold(doc.reference_name)
			),
			title=_("Wrong Contact"),
		)


def on_update(doc):
	sync_event(doc)
	sync_todo(doc)


def on_trash(doc):
	for doctype, field in (("Event", "event"), ("ToDo", "todo")):
		name = doc.get(field)
		if name and frappe.db.exists(doctype, name):
			frappe.db.set_value(DOCTYPE, doc.name, field, None, update_modified=False)
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


# --------------------------------------------------------------------------- calendar Event (Call / Meeting)
def sync_event(doc):
	if doc.activity_type not in SCHEDULED_TYPES:
		return
	event = frappe.get_doc("Event", doc.event) if doc.event and frappe.db.exists("Event", doc.event) else None
	if event is None:
		event = frappe.new_doc("Event")
		event.event_type = "Private"
		event.owner = doc.activity_owner
	event.update(
		{
			"subject": doc.subject,
			"event_category": doc.activity_type,
			"starts_on": doc.activity_date,
			"ends_on": doc.ends_on,
			"status": EVENT_STATUS.get(doc.status, "Open"),
			"description": doc.description or doc.summary,
			"reference_doctype": doc.reference_doctype,
			"reference_docname": doc.reference_name,
		}
	)
	if not event.get("event_participants"):
		event.append(
			"event_participants",
			{"reference_doctype": doc.reference_doctype, "reference_docname": doc.reference_name},
		)
	event.flags.ignore_permissions = True
	event.save()
	# the activity owner's calendar, and the attendees can see it too
	if event.owner != doc.activity_owner:
		frappe.db.set_value("Event", event.name, "owner", doc.activity_owner, update_modified=False)
	for row in doc.get("attendees") or []:
		if row.user and row.user != doc.activity_owner:
			frappe.share.add("Event", event.name, row.user, read=1, notify=0, flags={"ignore_share_permission": True})
	if doc.event != event.name:
		doc.db_set("event", event.name, update_modified=False)


# --------------------------------------------------------------------------- ToDo (follow-up / task)
def sync_todo(doc):
	"""One ToDo per activity for its owner while the follow-up (or task) is pending."""
	pending = bool(doc.follow_up_date) and doc.status != CANCELLED and not cint(doc.follow_up_done)
	if doc.activity_type == TASK:
		pending = doc.status == OPEN
	todo = frappe.get_doc("ToDo", doc.todo) if doc.todo and frappe.db.exists("ToDo", doc.todo) else None

	if not pending:
		if todo and todo.status == "Open":
			todo.status = "Closed" if doc.status != CANCELLED or cint(doc.follow_up_done) else "Cancelled"
			todo.flags.from_sales_activity = True
			todo.save(ignore_permissions=True)
		return
	if not _enabled_user(doc.activity_owner):
		return

	label = _("Task") if doc.activity_type == TASK else _("Follow up")
	description = _("{0}: {1} ({2} {3})").format(label, doc.subject, _(doc.reference_doctype), doc.party_name or doc.reference_name)
	if todo is None or todo.status != "Open":
		todo = frappe.new_doc("ToDo")
		todo.update({"reference_type": DOCTYPE, "reference_name": doc.name, "assigned_by": frappe.session.user})
	todo.update(
		{
			"allocated_to": doc.activity_owner,
			"date": doc.follow_up_date,
			"description": description,
			"priority": doc.priority or "Medium",
			"status": "Open",
		}
	)
	todo.flags.from_sales_activity = True
	todo.save(ignore_permissions=True)
	if doc.todo != todo.name:
		doc.db_set("todo", todo.name, update_modified=False)


def todo_on_update(todo, method=None):
	"""Closing the ToDo from the ToDo list: the task is completed / the follow-up done."""
	if todo.reference_type != DOCTYPE or todo.flags.from_sales_activity or todo.status != "Closed":
		return
	if not todo.reference_name or not frappe.db.exists(DOCTYPE, todo.reference_name):
		return
	activity = frappe.get_doc(DOCTYPE, todo.reference_name)
	if activity.todo != todo.name:
		return
	if activity.activity_type == TASK and activity.status == OPEN:
		activity.status = COMPLETED
	elif not cint(activity.follow_up_done):
		activity.follow_up_done = 1
	else:
		return
	activity.flags.ignore_permissions = True
	activity.save()


# --------------------------------------------------------------------------- automatic logging (Email, Comment)
def _reference_of_communication(comm):
	if comm.reference_doctype in REFERENCE_DOCTYPES and comm.reference_name:
		return comm.reference_doctype, comm.reference_name
	for link in comm.get("timeline_links") or []:
		if link.link_doctype in REFERENCE_DOCTYPES and link.link_name:
			return link.link_doctype, link.link_name
	return None, None


def communication_after_insert(comm, method=None):
	"""Every email sent or received on a Lead / Customer / Deal is an Email activity."""
	if comm.communication_type != "Communication" or comm.communication_medium != "Email":
		return
	doctype, name = _reference_of_communication(comm)
	if not doctype or frappe.db.exists(DOCTYPE, {"communication": comm.name}):
		return
	sent = comm.sent_or_received == "Sent"
	# sent: whoever sent it; received: the record's owner (Lead Owner / Account Manager / Deal Owner)
	owner = frappe.session.user if sent and _enabled_user(frappe.session.user) else record_owner(doctype, name)
	_log(
		EMAIL,
		doctype,
		name,
		subject=(_("Email sent: {0}") if sent else _("Email received: {0}")).format(comm.subject or _("(no subject)")),
		owner=owner,
		date=comm.communication_date or comm.creation,
		description=comm.content,
		communication=comm.name,
	)


def comment_after_insert(comment, method=None):
	"""Every comment on a Lead / Customer / Deal timeline is a Comment activity."""
	if comment.comment_type != "Comment" or comment.reference_doctype not in REFERENCE_DOCTYPES:
		return
	if frappe.db.exists(DOCTYPE, {"comment": comment.name}):
		return
	text = strip_html(cstr(comment.content)).strip()
	_log(
		COMMENT,
		comment.reference_doctype,
		comment.reference_name,
		subject=(text[:120] + ("..." if len(text) > 120 else "")) or _("Comment"),
		owner=comment.comment_email if _enabled_user(comment.comment_email) else frappe.session.user,
		date=comment.creation,
		description=comment.content,
		comment=comment.name,
	)


def _log(activity_type, doctype, name, subject, owner, date, description=None, **links):
	if not name or not frappe.db.exists(doctype, name):
		return None
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"activity_type": activity_type,
			"subject": cstr(subject)[:140],
			"status": COMPLETED,
			"reference_doctype": doctype,
			"reference_name": name,
			"activity_owner": owner if _enabled_user(owner) else record_owner(doctype, name),
			"activity_date": date or now_datetime(),
			"description": description,
			**links,
		}
	)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True
	doc.insert()
	return doc.name


# --------------------------------------------------------------------------- record views (Lead / Customer / Deal)
def references_for(doctype, name):
	"""The records whose activities show on this one: a Customer also shows its Lead's history."""
	refs = [(doctype, name)]
	if doctype == "Customer":
		lead = frappe.db.get_value("Customer", name, "lead_name")
		if lead:
			refs.append(("Lead", lead))
	return refs


def activities_of(doctype, name, limit=None, fields=None):
	rows = []
	for dt, dn in references_for(doctype, name):
		rows += frappe.get_list(
			DOCTYPE,
			filters={"reference_doctype": dt, "reference_name": dn},
			fields=fields
			or [
				"name",
				"activity_type",
				"subject",
				"status",
				"activity_owner",
				"activity_date",
				"follow_up_date",
				"follow_up_done",
				"summary",
				"reference_doctype",
				"reference_name",
			],
			order_by="activity_date desc",
			limit_page_length=limit or 0,
		)
	rows.sort(key=lambda r: get_datetime(r.activity_date), reverse=True)
	return rows[:limit] if limit else rows


@frappe.whitelist()
def get_activity_summary(doctype: str, name: str):
	"""Form panel on Lead / Customer / Deal: what is pending and the latest activities."""
	if doctype not in REFERENCE_DOCTYPES:
		frappe.throw(_("Not allowed"))
	frappe.has_permission(doctype, "read", name, throw=True)
	rows = activities_of(doctype, name)
	today = getdate(nowdate())
	pending = []
	for r in rows:
		if r.status == CANCELLED:
			continue
		due = None
		if r.activity_type == TASK and r.status == OPEN:
			due = r.follow_up_date
		elif r.activity_type in SCHEDULED_TYPES and r.status == OPEN:
			due = r.activity_date
		elif r.follow_up_date and not cint(r.follow_up_done):
			due = r.follow_up_date
		if due:
			r.due = getdate(due)
			r.overdue = r.due < today
			pending.append(r)
	pending.sort(key=lambda r: r.due)
	counts = {}
	for r in rows:
		if r.status != CANCELLED:
			counts[r.activity_type] = counts.get(r.activity_type, 0) + 1
	last = next((r for r in rows if r.status == COMPLETED), None)
	return {
		"pending": pending[:10],
		"pending_count": len(pending),
		"overdue_count": sum(1 for r in pending if r.overdue),
		"recent": rows[:8],
		"counts": counts,
		"last_contact": last and last.activity_date,
		"can_create": frappe.has_permission(DOCTYPE, "create"),
	}


@frappe.whitelist()
def complete_activity(name: str, summary: str | None = None, follow_up_date: str | None = None, follow_up_subject: str | None = None):
	"""Complete an activity from the record's panel; optionally plan the next follow-up."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("write")
	if summary:
		doc.summary = summary
	if doc.activity_type in (TASK, *SCHEDULED_TYPES):
		doc.status = COMPLETED
	doc.follow_up_done = 1 if doc.follow_up_date else doc.follow_up_done
	doc.save()
	next_name = None
	if follow_up_date:
		next_name = make_follow_up(doc.name, follow_up_date, follow_up_subject)
	return {"name": doc.name, "follow_up": next_name}


@frappe.whitelist()
def make_follow_up(source_name: str, follow_up_date: str, subject: str | None = None, activity_type: str | None = None):
	"""The next activity (a Task by default) on the same record, due on `follow_up_date`."""
	source = frappe.get_doc(DOCTYPE, source_name)
	source.check_permission("read")
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"activity_type": activity_type or TASK,
			"subject": subject or _("Follow up: {0}").format(source.subject)[:140],
			"reference_doctype": source.reference_doctype,
			"reference_name": source.reference_name,
			"contact_person": source.contact_person,
			"activity_owner": source.activity_owner,
			"activity_date": now_datetime() if getdate(follow_up_date) >= getdate(nowdate()) else follow_up_date,
			"follow_up_date": follow_up_date,
			"previous_activity": source.name,
			"priority": source.priority,
		}
	)
	if doc.activity_type in SCHEDULED_TYPES:
		doc.activity_date = get_datetime(f"{getdate(follow_up_date)} 10:00:00")
	doc.insert()
	if source.follow_up_date and not cint(source.follow_up_done):
		source.db_set("follow_up_done", 1)
		sync_todo(source)
	return doc.name


# --------------------------------------------------------------------------- timeline
TIMELINE_ICONS = {CALL: "call", MEETING: "calendar", TASK: "todo", NOTE: "notes"}


def timeline_content(doctype, docname):
	"""Calls, meetings, tasks and notes on the record's timeline (emails and comments are there already)."""
	if doctype not in REFERENCE_DOCTYPES:
		return []
	items = []
	rows = frappe.get_all(
		DOCTYPE,
		filters={"reference_doctype": doctype, "reference_name": docname, "activity_type": ["in", list(TIMELINE_ICONS)]},
		fields=["name", "activity_type", "subject", "status", "activity_owner", "activity_date", "summary", "follow_up_date", "creation"],
		order_by="activity_date desc",
		limit_page_length=100,
	)
	for r in rows:
		status = "" if r.activity_type == NOTE else f" · {_(r.status)}"
		follow = f" · {_('Follow-up')} {frappe.format(r.follow_up_date, {'fieldtype': 'Date'})}" if r.follow_up_date else ""
		summary = f"<div class='text-muted small'>{frappe.utils.escape_html(r.summary)}</div>" if r.summary else ""
		items.append(
			{
				"icon": TIMELINE_ICONS[r.activity_type],
				"creation": str(r.activity_date or r.creation),
				"content": (
					f"<div><b>{_(r.activity_type)}</b> {get_link_to_form(DOCTYPE, r.name, frappe.utils.escape_html(r.subject))}"
					f"<span class='text-muted'> · {frappe.utils.escape_html(frappe.utils.get_fullname(r.activity_owner))}{status}{follow}</span>"
					f"{summary}</div>"
				),
			}
		)
	return items


# --------------------------------------------------------------------------- daily reminder
def send_follow_up_reminders():
	"""Each owner gets one notification listing their activities due today and overdue."""
	today = getdate(nowdate())
	rows = frappe.get_all(
		DOCTYPE,
		filters={"status": ["!=", CANCELLED], "follow_up_done": 0, "follow_up_date": ["<=", today]},
		fields=["name", "activity_owner", "subject", "follow_up_date", "activity_type", "status", "party_name"],
	)
	by_owner = {}
	for r in rows:
		if r.activity_type == TASK and r.status != OPEN:
			continue
		by_owner.setdefault(r.activity_owner, []).append(r)
	for owner, items in by_owner.items():
		if not _enabled_user(owner):
			continue
		overdue = [r for r in items if getdate(r.follow_up_date) < today]
		lines = "".join(
			f"<li>{frappe.utils.escape_html(r.subject)} ({frappe.utils.escape_html(r.party_name or '')})"
			f"{' - ' + _('overdue') if r in overdue else ''}</li>"
			for r in sorted(items, key=lambda r: r.follow_up_date)[:20]
		)
		subject = _("{0} sales follow-ups due today ({1} overdue)").format(len(items), len(overdue))
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": owner,
				"type": "Alert",
				"document_type": DOCTYPE,
				"document_name": items[0].name,
				"subject": subject,
				"email_content": f"<ul>{lines}</ul>",
			}
		).insert(ignore_permissions=True)
