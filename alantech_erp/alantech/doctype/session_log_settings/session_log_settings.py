# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Session Log Settings (Single). Use get_session_log_settings() everywhere else."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

TRIGGER_ON_CHECKOUT = "On Check-out"
TRIGGER_DAILY = "Daily Scheduler"
DEFAULT_APPROVER_ROLE = "HR Manager"
# Employee Checkin: open IN older than this blocks the next punch, when the shift gives no limit
DEFAULT_MISSING_CHECKOUT_HOURS = 16
# Only these roles (and Administrator) may switch Auto Checkout on or off
AUTO_CHECKOUT_ROLES = {"HR Manager", "System Manager"}


class SessionLogSettings(Document):
	def validate(self):
		self.validate_auto_checkout_permission()
		if not self.log_creation_trigger:
			self.log_creation_trigger = TRIGGER_ON_CHECKOUT
		if not self.approver_role:
			self.approver_role = DEFAULT_APPROVER_ROLE
		if not frappe.db.exists("Role", self.approver_role):
			frappe.throw(_("Role {0} does not exist.").format(frappe.bold(self.approver_role)))

	def validate_auto_checkout_permission(self):
		"""Employees can never change Auto Checkout, even through an API call."""
		if not self.has_value_changed("auto_create_missing_checkout"):
			return
		if frappe.session.user == "Administrator" or AUTO_CHECKOUT_ROLES & set(frappe.get_roles()):
			return
		frappe.throw(_("Only HR Manager or System Manager can change Auto Checkout."), frappe.PermissionError)


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
		missing_checkout_block_hours=flt(doc.get("missing_checkout_block_hours")) or DEFAULT_MISSING_CHECKOUT_HOURS,
		auto_submit_attendance=flag("auto_submit_attendance", 1),
		auto_submit_overtime=flag("auto_submit_overtime", 1),
		lock_after_processing=flag("lock_after_processing", 1),
		auto_create_missing_checkout=flag("auto_create_missing_checkout", 1),
	)