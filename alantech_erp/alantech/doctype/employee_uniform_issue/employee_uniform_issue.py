

"""Employee Uniform Issue: a record of uniform items issued to an employee.

On submit a Material Issue Stock Entry takes the items out of the source warehouse and books them
to the Uniform Expense Account (debit expense, credit the warehouse's stock account); cancelling
this document cancels that Stock Entry. The re-issue warning and register report are separate subtasks.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form, nowtime
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

	def before_submit(self):
		# checked before anything is posted, so a missing account never leaves a half-done submit
		self.get_accounting_defaults()

	def on_submit(self):
		self.make_stock_entry()

	def on_cancel(self):
		# the Stock Entry made on submit is cancelled below, so it must not block this cancel
		self.ignore_linked_doctypes = ("Stock Entry",)
		self.cancel_stock_entry()

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

	# --- Stock Entry -------------------------------------------------------
	def get_accounting_defaults(self):
		"""Uniform Expense Account (required) and cost center from Uniform Issue Settings,
		cost center falling back to the company's default."""
		defaults = get_uniform_defaults(company=self.company)
		if not defaults.uniform_expense_account:
			frappe.throw(
				_("Set the Uniform Expense Account of company {0} in {1} before submitting.").format(
					frappe.bold(self.company), get_link_to_form("Uniform Issue Settings", "Uniform Issue Settings")
				),
				title=_("Uniform Expense Account Missing"),
			)
		cost_center = defaults.default_cost_center or frappe.get_cached_value("Company", self.company, "cost_center")
		return defaults.uniform_expense_account, cost_center

	def make_stock_entry(self):
		expense_account, cost_center = self.get_accounting_defaults()
		entry = frappe.new_doc("Stock Entry")
		entry.update(
			{
				"stock_entry_type": "Material Issue",
				"company": self.company,
				"posting_date": self.issue_date,
				"posting_time": nowtime(),
				"set_posting_time": 1,
				"from_warehouse": self.source_warehouse,
				"remarks": _("Uniform issued to {0} ({1}) against Employee Uniform Issue {2}.").format(
					self.employee_name, self.employee, self.name
				)
				+ (f"\n{self.remarks}" if self.remarks else ""),
				"alt_employee": self.employee,
				"alt_employee_uniform_issue": self.name,
			}
		)
		for row in self.items:
			entry.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": row.qty,
					"uom": row.uom,
					"stock_uom": row.uom,
					"conversion_factor": 1,
					"s_warehouse": self.source_warehouse,
					"expense_account": expense_account,
					"cost_center": cost_center,
				},
			)
		# HR may not have rights on Stock Entry; this document is the permission check
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.submit()
		self.db_set("stock_entry", entry.name)

	def cancel_stock_entry(self):
		if self.stock_entry and frappe.db.get_value("Stock Entry", self.stock_entry, "docstatus") == 1:
			entry = frappe.get_doc("Stock Entry", self.stock_entry)
			entry.flags.ignore_permissions = True
			entry.flags.ignore_links = True
			entry.flags.alt_cancel_from_uniform_issue = True  # see stock_entry_before_cancel
			entry.cancel()  # reverses the stock ledger and GL entries

	def calculate_totals(self):
		self.total_qty = sum(flt(row.qty) for row in self.items)
		self.total_amount = sum(flt(row.amount) for row in self.items)


def stock_entry_before_cancel(doc, method=None):
	"""Stock Entry.before_cancel (hooks.py): a Stock Entry made by a submitted Employee Uniform Issue
	is cancelled through that document only, so the issue never shows uniforms that were put back."""
	issue = doc.get("alt_employee_uniform_issue")
	if not issue or doc.flags.alt_cancel_from_uniform_issue:
		return
	if frappe.db.get_value("Employee Uniform Issue", issue, "docstatus") == 1:
		frappe.throw(
			_("Stock Entry {0} was created by Employee Uniform Issue {1}. Cancel {1} instead; it cancels this Stock Entry too.").format(
				frappe.bold(doc.name), get_link_to_form("Employee Uniform Issue", issue)
			),
			title=_("Cancel the Uniform Issue"),
		)


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