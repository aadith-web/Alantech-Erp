# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Session Log Settings (Single). Use get_session_log_settings() everywhere else."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

TRIGGER_ON_CHECKOUT = "On Check-out"
TRIGGER_DAILY = "Daily Scheduler"
DEFAULT_APPROVER_ROLE = "HR Manager"


class SessionLogSettings(Document):
	def validate(self):
		if not self.log_creation_trigger:
			self.log_creation_trigger = TRIGGER_ON_CHECKOUT
		if not self.approver_role:
			self.approver_role = DEFAULT_APPROVER_ROLE
		if not frappe.db.exists("Role", self.approver_role):
			frappe.throw(_("Role {0} does not exist.").format(frappe.bold(self.approver_role)))


@frappe.whitelist()
def get_session_log_settings():
	"""Settings for the session log subtasks, with defaults filled in.

	approver_role is always returned: held logs (missing check-out) need an approver
	even when Require Log Approval is off.
	"""
	doc = frappe.get_cached_doc("Session Log Settings")

	def flag(field, default):
		value = doc.get(field)
		return bool(default if value is None else cint(value))

	return frappe._dict(
		require_log_approval=flag("require_log_approval", 0),
		log_creation_trigger=doc.log_creation_trigger or TRIGGER_ON_CHECKOUT,
		approver_role=doc.approver_role or DEFAULT_APPROVER_ROLE,
		hold_missing_checkout=flag("hold_missing_checkout", 1),
		auto_submit_attendance=flag("auto_submit_attendance", 1),
		auto_submit_overtime=flag("auto_submit_overtime", 1),
		lock_after_processing=flag("lock_after_processing", 1),
	)
