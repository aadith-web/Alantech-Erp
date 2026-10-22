# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Approve / reject / reopen Session Logs. Only users with the approver role (Session Log Settings).

    approve_logs(names)          queue approval + processing (frappe.enqueue)
    reject_logs(names, reason)   reject with a remark; nothing is created
    reopen_log(name)             cancel linked Attendance / Overtime Log, back to Pending Approval
"""

import json

import frappe
from frappe import _
from frappe.utils import now, now_datetime

from alantech_erp.alantech.doctype.session_log.processing import add_remark, process_log
from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import (
	get_session_log_settings,
)

DT = "Session Log"
APPROVABLE = ("Draft", "Pending Approval", "Approved")  # Approved = approved earlier but processing failed
REJECTABLE = ("Draft", "Pending Approval", "Approved")
REOPENABLE = ("Processed", "Rejected")
DONE_EVENT = "session_log_approval_done"


def check_approver(user=None):
	user = user or frappe.session.user
	role = get_session_log_settings().approver_role
	if user != "Administrator" and role not in frappe.get_roles(user):
		frappe.throw(
			_("Only users with the {0} role can approve, reject or reopen Session Logs.").format(frappe.bold(role)),
			frappe.PermissionError,
		)


def parse_names(names):
	if isinstance(names, str):
		names = json.loads(names) if names.strip().startswith("[") else [names]
	names = [n for n in (names or []) if n]
	if not names:
		frappe.throw(_("Select at least one Session Log."))
	return list(dict.fromkeys(names))  # unique, keep order


# ---------------------------------------------------------------- approve
@frappe.whitelist()
def approve_logs(names):
	"""Approve Selected / Approve All. Runs in the background; returns how many logs were queued."""
	check_approver()
	names = parse_names(names)
	sync = bool(frappe.flags.session_log_sync)  # tests run it straight away, without committing
	frappe.enqueue(
		"alantech_erp.alantech.doctype.session_log.approval.approve_and_process",
		queue="long",
		timeout=3600,
		now=sync,
		enqueue_after_commit=not sync,
		names=names,
		user=frappe.session.user,
		commit=not sync,
	)
	return len(names)


def approve_and_process(names, user, commit=True):
	"""Background job: approve each log and create its Attendance / Overtime Log.
	A failure on one log is written to that log's error_log and does not stop the others."""
	processed = failed = skipped = 0
	for name in names:
		frappe.db.savepoint("approve_session_log")
		try:
			log = frappe.get_doc(DT, name)
			if log.status not in APPROVABLE:
				skipped += 1
				continue
			if log.status != "Approved":
				log.status = "Approved"
				log.approved_by = user
				log.approved_on = now_datetime()
				log.save(ignore_permissions=True)
			if process_log(log):
				processed += 1
			else:
				failed += 1
		except Exception as e:
			frappe.db.rollback(save_point="approve_session_log")
			frappe.db.set_value(DT, name, "error_log", f"{now()}: {e}", update_modified=False)
			frappe.log_error(title=f"Session Log {name}: approval failed", reference_doctype=DT, reference_name=name)
			frappe.clear_messages()
			failed += 1
		if commit:
			frappe.db.commit()

	frappe.publish_realtime(
		DONE_EVENT, {"processed": processed, "failed": failed, "skipped": skipped}, user=user, after_commit=commit
	)
	return {"processed": processed, "failed": failed, "skipped": skipped}


# ---------------------------------------------------------------- reject
@frappe.whitelist()
def reject_logs(names, reason):
	check_approver()
	names = parse_names(names)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A remark is required to reject."))

	rejected = 0
	for name in names:
		log = frappe.get_doc(DT, name)
		if log.status not in REJECTABLE:
			continue
		log.status = "Rejected"
		log.approved_by = frappe.session.user
		log.approved_on = now_datetime()
		add_remark(log, _("Rejected: {0}").format(reason))
		log.save(ignore_permissions=True)
		rejected += 1
	return rejected


# ---------------------------------------------------------------- reopen (optional)
@frappe.whitelist()
def reopen_log(name):
	"""Cancel the linked Attendance and Overtime Log and set the log back to Pending Approval."""
	check_approver()
	log = frappe.get_doc(DT, name)
	if log.status not in REOPENABLE:
		frappe.throw(_("Only Processed or Rejected logs can be reopened."))

	for doctype, field in (("Overtime Log", "overtime"), ("Attendance", "attendance")):
		linked = log.get(field)
		if not linked or not frappe.db.exists(doctype, linked):
			continue
		doc = frappe.get_doc(doctype, linked)
		if doc.get("attendance_log") != log.name:
			continue  # not created by this log (e.g. existing attendance): leave it alone
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()
		elif doc.docstatus == 0:
			frappe.delete_doc(doctype, linked, ignore_permissions=True)
		log.set(field, None)

	log.status = "Pending Approval"
	log.approved_by = None
	log.approved_on = None
	log.error_log = None
	add_remark(log, _("Reopened by {0} on {1}.").format(frappe.session.user, frappe.format(now_datetime(), "Datetime")))
	log.flags.reopening = True
	log.save(ignore_permissions=True)
	return log.status
