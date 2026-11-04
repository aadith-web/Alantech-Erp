# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Uniform Issue Settings (Single): defaults for Employee Uniform Issue.

Other code should call get_uniform_defaults() rather than reading the fields directly, e.g. in the
future Employee Uniform Issue:

	from alantech_erp.alantech.doctype.uniform_issue_settings.uniform_issue_settings import (
		get_uniform_defaults,
	)

	defaults = get_uniform_defaults(company=self.company)
	self.source_warehouse = self.source_warehouse or defaults.default_source_warehouse
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

SETTINGS = "Uniform Issue Settings"
LINK_FIELDS = (
	"default_source_warehouse",
	"uniform_item_group",
	"uniform_expense_account",
	"default_cost_center",
)
# Link fields whose target belongs to a company
COMPANY_FIELDS = {
	"default_source_warehouse": "Warehouse",
	"uniform_expense_account": "Account",
	"default_cost_center": "Cost Center",
}


class UniformIssueSettings(Document):
	def validate(self):
		self.validate_reissue_warning_days()
		self.validate_warehouse()
		self.validate_item_group()
		self.validate_account()
		self.validate_cost_center()
		self.validate_company_consistency()

	def validate_reissue_warning_days(self):
		self.reissue_warning_days = cint(self.reissue_warning_days)
		if self.reissue_warning_days < 0:
			frappe.throw(_("Re-issue Warning Days cannot be negative. Use 0 to disable the warning."))

	def validate_warehouse(self):
		if not self.default_source_warehouse:
			return
		wh = self._get_linked("Warehouse", self.default_source_warehouse, ["disabled", "is_group"])
		if wh.disabled:
			frappe.throw(_("Warehouse {0} is disabled.").format(frappe.bold(self.default_source_warehouse)))
		if wh.is_group:
			frappe.throw(
				_("Warehouse {0} is a group warehouse. Select a leaf warehouse.").format(
					frappe.bold(self.default_source_warehouse)
				)
			)

	def validate_item_group(self):
		if self.uniform_item_group:
			self._get_linked("Item Group", self.uniform_item_group, ["name"])

	def validate_account(self):
		if not self.uniform_expense_account:
			return
		acc = self._get_linked(
			"Account", self.uniform_expense_account, ["disabled", "is_group", "root_type"]
		)
		name = frappe.bold(self.uniform_expense_account)
		if acc.disabled:
			frappe.throw(_("Account {0} is disabled.").format(name))
		if acc.is_group:
			frappe.throw(_("Account {0} is a group account. Select a ledger account.").format(name))
		if acc.root_type != "Expense":
			frappe.throw(_("Account {0} must be an Expense account.").format(name))

	def validate_cost_center(self):
		if not self.default_cost_center:
			return
		cc = self._get_linked("Cost Center", self.default_cost_center, ["disabled", "is_group"])
		name = frappe.bold(self.default_cost_center)
		if cc.disabled:
			frappe.throw(_("Cost Center {0} is disabled.").format(name))
		if cc.is_group:
			frappe.throw(_("Cost Center {0} is a group. Select a leaf cost center.").format(name))

	def validate_company_consistency(self):
		"""Warehouse, Account and Cost Center must all belong to the same company.

		The settings are global and have no company field, so the company context comes from
		whichever of these is set. Nothing to check if fewer than two are set.
		"""
		companies = {}
		for fieldname, doctype in COMPANY_FIELDS.items():
			value = self.get(fieldname)
			company = frappe.db.get_value(doctype, value, "company") if value else None
			if company:
				companies[fieldname] = company

		if len(set(companies.values())) > 1:
			details = ", ".join(
				"{0}: {1}".format(self.meta.get_label(f), frappe.bold(c)) for f, c in companies.items()
			)
			frappe.throw(
				_("Default Source Warehouse, Uniform Expense Account and Default Cost Center must belong to the same company. {0}").format(details)
			)

	def _get_linked(self, doctype, name, fields):
		values = frappe.db.get_value(doctype, name, fields, as_dict=True)
		if not values:
			frappe.throw(_("{0} {1} does not exist.").format(_(doctype), frappe.bold(name)))
		return values


@frappe.whitelist()
def get_uniform_defaults(company=None):
	"""Uniform issue defaults, safe to call when nothing is configured.

	Always returns all five keys: unset links are None and reissue_warning_days is an int
	(0 = warning disabled). is_configured is False when no link field is set.

	If company is given, link values that belong to another company are dropped, so a
	document for company B never picks up a warehouse/account/cost center of company A.
	The defaults are not sensitive and are needed by users who cannot open the settings
	form (e.g. HR User), so this does not check permission on the settings.
	"""
	defaults = frappe._dict({field: None for field in LINK_FIELDS})
	defaults.reissue_warning_days = 0

	try:
		settings = frappe.get_single(SETTINGS)
	except frappe.DoesNotExistError:
		# DocType not migrated yet
		defaults.is_configured = False
		return defaults

	for field in LINK_FIELDS:
		defaults[field] = settings.get(field) or None
	defaults.reissue_warning_days = max(cint(settings.get("reissue_warning_days")), 0)

	if company:
		for field, doctype in COMPANY_FIELDS.items():
			value = defaults[field]
			if value and frappe.db.get_value(doctype, value, "company") != company:
				defaults[field] = None

	defaults.is_configured = any(defaults[field] for field in LINK_FIELDS)
	return defaults