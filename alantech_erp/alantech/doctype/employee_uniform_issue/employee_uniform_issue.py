

"""Employee Uniform Issue: a record of uniform items issued to an employee.

This subtask only covers the document itself (defaults, rates, totals, submit). The Stock Entry,
re-issue warning and register report are separate subtasks, so stock_entry stays empty here.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from frappe.utils.nestedset import get_descendants_of
from erpnext.stock.utils import get_stock_balance

from alantech_erp.alantech.doctype.uniform_issue_settings.uniform_issue_settings import (
	get_uniform_defaults,
)


class EmployeeUniformIssue(Document):
	def before_validate(self):
		self.set_defaults()

	def validate(self):
		self.validate_employee()
		self.validate_warehouse()
		self.validate_items()
		self.set_rates_and_amounts()
		self.calculate_totals()
		self.validate_stock_availability()

	def set_defaults(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
				"Global Defaults", "default_company"
			)
		if not self.source_warehouse:
			self.source_warehouse = get_uniform_defaults(company=self.company).default_source_warehouse

	def validate_employee(self):
		status = frappe.db.get_value("Employee", self.employee, "status")
		if status != "Active":
			frappe.throw(
				_("Employee {0} is {1}. Uniforms can only be issued to Active employees.").format(
					frappe.bold(self.employee), frappe.bold(_(status or "not found"))
				)
			)

	def validate_warehouse(self):
		if not self.source_warehouse:
			return
		wh = frappe.db.get_value(
			"Warehouse", self.source_warehouse, ["company", "disabled", "is_group"], as_dict=True
		)
		name = frappe.bold(self.source_warehouse)
		if wh.disabled:
			frappe.throw(_("Warehouse {0} is disabled.").format(name))
		if wh.is_group:
			frappe.throw(_("Warehouse {0} is a group warehouse. Select a leaf warehouse.").format(name))
		if wh.company != self.company:
			frappe.throw(_("Warehouse {0} does not belong to company {1}.").format(name, frappe.bold(self.company)))

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Add at least one item."))

		# Uniform items = Uniform Item Group (and its child groups) in Uniform Issue Settings.
		# If no group is configured, any stock item is allowed.
		group = get_uniform_defaults(company=self.company).uniform_item_group
		uniform_groups = {group, *get_descendants_of("Item Group", group, ignore_permissions=True)} if group else None

		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than 0.").format(row.idx))
			item = frappe.db.get_value(
				"Item", row.item_code, ["disabled", "is_stock_item", "item_group"], as_dict=True
			)
			if item.disabled:
				frappe.throw(_("Row #{0}: Item {1} is disabled.").format(row.idx, frappe.bold(row.item_code)))
			if not item.is_stock_item:
				frappe.throw(_("Row #{0}: Item {1} is not a stock item.").format(row.idx, frappe.bold(row.item_code)))
			if uniform_groups and item.item_group not in uniform_groups:
				frappe.throw(
					_("Row #{0}: Item {1} is not a uniform item. It must belong to Item Group {2}.").format(
						row.idx, frappe.bold(row.item_code), frappe.bold(group)
					)
				)

	def set_rates_and_amounts(self):
		"""Rate and Amount are read-only, so always recompute them here."""
		for row in self.items:
			details = get_item_details(row.item_code, self.source_warehouse, _check_permission=False)
			row.item_name = details.item_name
			row.uom = details.uom
			row.rate = details.rate
			row.amount = flt(row.qty) * flt(row.rate)

	def validate_stock_availability(self):
		"""Enough stock in the source warehouse on the issue date, counting repeated items together."""
		if not self.source_warehouse:
			frappe.throw(
				_("Source Warehouse is required to check stock. Set it here or in Uniform Issue Settings.")
			)

		required = {}
		for row in self.items:
			required[row.item_code] = required.get(row.item_code, 0) + flt(row.qty)

		shortages = []
		for item_code, qty in required.items():
			available = flt(get_stock_balance(item_code, self.source_warehouse, self.issue_date))
			if available < qty:
				shortages.append(
					_("Item {0}: required {1}, available {2}").format(
						frappe.bold(item_code), flt(qty), flt(available)
					)
				)

		if shortages:
			frappe.throw(
				_("Insufficient stock in warehouse {0} on {1}:").format(
					frappe.bold(self.source_warehouse), frappe.format(self.issue_date, "Date")
				)
				+ "<br>"
				+ "<br>".join(shortages),
				title=_("Insufficient Stock"),
			)

	def calculate_totals(self):
		self.total_qty = sum(flt(row.qty) for row in self.items)
		self.total_amount = sum(flt(row.amount) for row in self.items)


@frappe.whitelist()
def get_item_details(item_code, warehouse=None, _check_permission=True):
	"""Item name, stock UOM and valuation rate for an item.

	Rate is the valuation rate in the source warehouse (Bin), falling back to the Item's valuation rate, then 0.
	"""
	if _check_permission:
		frappe.has_permission("Employee Uniform Issue", "create", throw=True)

	item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom", "valuation_rate"], as_dict=True)
	if not item:
		frappe.throw(_("Item {0} does not exist.").format(frappe.bold(item_code)))

	rate = 0
	if warehouse:
		rate = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate")
	if not flt(rate):
		rate = item.valuation_rate

	return frappe._dict(item_name=item.item_name, uom=item.stock_uom, rate=flt(rate))