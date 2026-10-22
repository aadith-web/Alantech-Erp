# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from alantech_erp.alantech.doctype.session_log.calculation import calculate
from alantech_erp.alantech.doctype.session_log.processing import initial_status, process_log
from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import (
	get_session_log_settings,
)

DOCTYPE = "Session Log"
UNRESTRICTED_ROLES = {"System Manager", "HR Manager", "HR User"}


class SessionLog(Document):
	def validate(self):
		self.validate_locked()
		self.validate_duplicate()
		# recalculate only before HR review starts, so HR's edits are kept
		if self.is_new() or self.status == "Draft":
			calculate(self)
		if self.is_new():
			self.status = initial_status(self)
		if self.status == "Rejected" and not (self.remarks or "").strip():
			frappe.throw(_("Remarks are required to reject a Session Log."))

	def after_insert(self):
		if self.status == "Draft":  # approval OFF and not held
			process_log(self)

	def validate_locked(self):
		"""Processed logs are read-only when Lock After Processing is on (Reopen unlocks them)."""
		if self.is_new() or self.flags.reopening:
			return
		before = self.get_doc_before_save()
		if before and before.status == "Processed" and get_session_log_settings().lock_after_processing:
			frappe.throw(_("Session Log {0} is Processed and locked. Use Reopen to change it.").format(self.name))

	def validate_duplicate(self):
		"""One Session Log per employee per date (the DB index enforces it as well)."""
		existing = frappe.db.exists(
			DOCTYPE,
			{"employee": self.employee, "log_date": self.log_date, "name": ["!=", self.name or ""]},
		)
		if existing:
			frappe.throw(
				_("A Session Log for {0} on {1} already exists: {2}").format(
					frappe.bold(self.employee_name or self.employee),
					frappe.format(self.log_date, "Date"),
					frappe.utils.get_link_to_form(DOCTYPE, existing),
				),
				frappe.DuplicateEntryError,
				title=_("Duplicate Session Log"),
			)

	@frappe.whitelist()
	def recalculate(self):
		if self.status not in ("Draft", "Pending Approval"):
			frappe.throw(_("Only Draft or Pending Approval logs can be recalculated."))
		self.check_permission("write")
		calculate(self)
		self.save()


def on_doctype_update():
	"""Runs on migrate: unique DB index on (employee, log_date)."""
	frappe.db.add_unique(DOCTYPE, ["employee", "log_date"], constraint_name="unique_employee_log_date")


# ---------- permissions: employees see only their own logs ----------

def _is_unrestricted(user):
	return user == "Administrator" or bool(UNRESTRICTED_ROLES & set(frappe.get_roles(user)))


def _own_employees(user):
	return frappe.get_all("Employee", filters={"user_id": user}, pluck="name")


def get_permission_query_conditions(user=None):
	"""Filters the list view, reports and search."""
	user = user or frappe.session.user
	if _is_unrestricted(user):
		return ""
	employees = _own_employees(user)
	if not employees:
		return "1=0"
	values = ", ".join(frappe.db.escape(e) for e in employees)
	return f"`tabSession Log`.`employee` in ({values})"


def has_permission(doc, ptype=None, user=None):
	"""Checks a single record (opening by URL, API)."""
	user = user or frappe.session.user
	if _is_unrestricted(user):
		return True
	return doc.employee in _own_employees(user)
