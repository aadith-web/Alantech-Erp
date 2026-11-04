# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Uniform Issue: the doctype (ClickUp 14yr2e56y3m), its item filter and validations
(ClickUp 14yr2e56y3n), the Stock Entry made on submit (ClickUp 14yr2e56y3p) and cancelled with
it (ClickUp 14yr2e56y3q). Defaults taken from
Uniform Issue Settings (14yr2e56y3k) are checked here too.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.employee_uniform_issue.test_employee_uniform_issue

The test items and item groups, and stock of SHIRT (a Material Receipt), are created in setUpClass
and rolled back with the rest of the test data, so the tests do not depend on the site's own items.
The stock check in validate is patched, so the validation tests can set any balance; submitting
posts real stock ledger and GL entries from the received stock.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import cint, flt, nowdate

from alantech_erp.alantech.doctype.employee_uniform_issue.employee_uniform_issue import get_item_details

IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Employee",
	"Company",
	"Department",
	"Designation",
	"Warehouse",
	"Item",
	"UOM",
	"Item Group",
	"Stock Entry",
]

STOCK_BALANCE = "alantech_erp.alantech.doctype.employee_uniform_issue.employee_uniform_issue.get_stock_balance"

UNIFORMS = "_Test Uniforms"  # uniform item group (a group)
SHIRTS = "_Test Uniform Shirts"  # child group of UNIFORMS
OTHER_GROUP = "_Test Non Uniform Items"
SHIRT = "_TEST-UNIFORM-SHIRT"  # stock, in SHIRTS, received at BIN_RATE (valuation rate in the Bin)
CAP = "_TEST-UNIFORM-CAP"  # stock, in UNIFORMS, valuation rate on the Item only
NON_STOCK = "_TEST-UNIFORM-SERVICE"
DISABLED = "_TEST-UNIFORM-OLD"
OTHER = "_TEST-NON-UNIFORM"
BIN_RATE = 250
ITEM_RATE = 120
RECEIVED_QTY = 100


def make_item_group(name, parent="All Item Groups", is_group=0):
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": name, "parent_item_group": parent, "is_group": is_group}
		).insert(ignore_permissions=True)


def make_item(code, group, is_stock_item=1, disabled=0, valuation_rate=0):
	if not frappe.db.exists("Item", code):
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code.replace("_TEST-", "Test ").title(),
				"item_group": group,
				"stock_uom": "Nos",
				"is_stock_item": is_stock_item,
				"disabled": disabled,
				"valuation_rate": valuation_rate,
			}
		)
		if frappe.get_meta("Item").has_field("gst_hsn_code"):
			item.gst_hsn_code = "62052000"  # India Compliance: HSN mandatory (men's cotton shirts)
		item.insert(ignore_permissions=True)


class IntegrationTestEmployeeUniformIssue(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		employees = frappe.get_all(
			"Employee",
			filters={"status": "Active"},
			fields=["name", "employee_name", "department", "designation", "company"],
			order_by="creation asc",
			limit=2,
		)
		if len(employees) < 2:
			raise cls.skipTest(cls, "Need two active employees on the site")
		cls.employee, cls.other_employee = employees
		cls.company = cls.employee.company
		cls.warehouse = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 0, "disabled": 0}, "name"
		)
		cls.group_warehouse = frappe.db.get_value("Warehouse", {"company": cls.company, "is_group": 1}, "name")
		if not cls.warehouse:
			raise cls.skipTest(cls, "No warehouse for the employee's company")

		make_item_group(UNIFORMS, is_group=1)
		make_item_group(SHIRTS, parent=UNIFORMS)
		make_item_group(OTHER_GROUP)
		make_item(SHIRT, SHIRTS)
		make_item(CAP, UNIFORMS, valuation_rate=ITEM_RATE)
		make_item(NON_STOCK, UNIFORMS, is_stock_item=0)
		make_item(DISABLED, UNIFORMS, disabled=1)
		make_item(OTHER, OTHER_GROUP)
		receipt = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": cls.company,
				# start of the current fiscal year: before any issue date used below
				"posting_date": get_fiscal_year(nowdate(), company=cls.company)[1],
				"set_posting_time": 1,
				"items": [
					{"item_code": SHIRT, "qty": RECEIVED_QTY, "basic_rate": BIN_RATE, "t_warehouse": cls.warehouse}
				],
			}
		)
		receipt.insert(ignore_permissions=True)
		receipt.submit()

		cls.expense_account = frappe.db.get_value(
			"Account", {"company": cls.company, "root_type": "Expense", "is_group": 0, "disabled": 0}, "name"
		)
		cls.company_cost_center = frappe.get_cached_value("Company", cls.company, "cost_center")
		cls.stock_account = frappe.db.get_value("Warehouse", cls.warehouse, "account") or frappe.get_cached_value(
			"Company", cls.company, "default_inventory_account"
		)

	def setUp(self):
		# plenty of stock unless a test says otherwise
		patcher = patch(STOCK_BALANCE, return_value=1000)
		self.stock = patcher.start()
		self.addCleanup(patcher.stop)
		self.set_settings(group=UNIFORMS)

	def set_settings(self, group=None, warehouse=None, expense_account=True, cost_center=None):
		settings = frappe.get_single("Uniform Issue Settings")
		settings.uniform_item_group = group
		settings.default_source_warehouse = warehouse
		settings.default_cost_center = cost_center
		settings.uniform_expense_account = self.expense_account if expense_account is True else expense_account
		settings.save()

	def make_doc(self, **kwargs):
		doc = frappe.get_doc(
			{
				"doctype": "Employee Uniform Issue",
				"employee": self.employee.name,
				"company": self.company,
				"source_warehouse": self.warehouse,
				"items": [{"item_code": SHIRT, "qty": 2}],
			}
		)
		doc.update(kwargs)
		return doc

	def assert_rejected(self, doc, text):
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert()
		self.assertIn(text, str(ctx.exception))

	# --- 14yr2e56y3m: doctype and child table ------------------------------

	def test_doctype_is_submittable_with_naming_series(self):
		meta = frappe.get_meta("Employee Uniform Issue")
		self.assertTrue(meta.is_submittable)
		self.assertEqual(meta.get_field("naming_series").options.split("\n")[0], "EUI-.YYYY.-.#####")

	def test_header_fields(self):
		meta = frappe.get_meta("Employee Uniform Issue")
		for field in ("issue_date", "employee", "company", "items"):
			self.assertTrue(meta.get_field(field).reqd, field)
		self.assertEqual(meta.get_field("issue_date").default, "Today")
		for field, fetch_from in {
			"employee_name": "employee.employee_name",
			"department": "employee.department",
			"designation": "employee.designation",
		}.items():
			df = meta.get_field(field)
			self.assertEqual(df.fetch_from, fetch_from)
			self.assertTrue(df.read_only, field)
		stock_entry = meta.get_field("stock_entry")
		self.assertEqual((stock_entry.fieldtype, stock_entry.options), ("Link", "Stock Entry"))
		self.assertTrue(stock_entry.read_only)
		self.assertTrue(stock_entry.no_copy)
		for field in ("total_qty", "total_amount"):
			self.assertTrue(meta.get_field(field).read_only, field)
		self.assertEqual(meta.get_field("source_warehouse").options, "Warehouse")

	def test_child_table_fields(self):
		meta = frappe.get_meta("Employee Uniform Issue Item")
		self.assertTrue(meta.istable)
		self.assertTrue(meta.get_field("item_code").reqd)
		self.assertTrue(meta.get_field("qty").reqd)
		self.assertEqual(meta.get_field("item_name").fetch_from, "item_code.item_name")
		self.assertEqual(meta.get_field("uom").fetch_from, "item_code.stock_uom")
		for field in ("rate", "amount"):
			df = meta.get_field(field)
			self.assertEqual(df.fieldtype, "Currency")
			self.assertTrue(df.read_only, field)
		self.assertTrue(meta.get_field("size"))

	def test_create_save_and_naming(self):
		doc = self.make_doc().insert()
		self.assertRegex(doc.name, r"^EUI-\d{4}-\d{5}$")
		self.assertEqual(str(doc.issue_date), nowdate())

	def test_employee_details_fetched(self):
		doc = self.make_doc().insert()
		self.assertEqual(doc.employee_name, self.employee.employee_name)
		self.assertEqual(doc.department, self.employee.department)
		self.assertEqual(doc.designation, self.employee.designation)

	def test_item_details_set(self):
		doc = self.make_doc().insert()
		row = doc.items[0]
		self.assertEqual(row.item_name, frappe.db.get_value("Item", SHIRT, "item_name"))
		self.assertEqual(row.uom, "Nos")

	def test_totals_calculated(self):
		doc = self.make_doc(items=[{"item_code": SHIRT, "qty": 2}, {"item_code": CAP, "qty": 3}]).insert()
		self.assertEqual(doc.total_qty, 5)
		for row in doc.items:
			self.assertEqual(flt(row.amount), flt(row.qty) * flt(row.rate))
		self.assertEqual(flt(doc.total_amount), 2 * BIN_RATE + 3 * ITEM_RATE)

	def test_rate_and_amount_recomputed_on_server(self):
		# read-only in the form; a value sent from the browser is ignored
		doc = self.make_doc(items=[{"item_code": SHIRT, "qty": 2, "rate": 1, "amount": 1}]).insert()
		self.assertEqual(flt(doc.items[0].rate), BIN_RATE)
		self.assertEqual(flt(doc.items[0].amount), 2 * BIN_RATE)

	def test_totals_follow_qty_change(self):
		doc = self.make_doc().insert()
		doc.items[0].qty = 4
		doc.save()
		self.assertEqual(doc.total_qty, 4)
		self.assertEqual(flt(doc.total_amount), 4 * BIN_RATE)

	def test_submit_and_cancel(self):
		doc = self.make_doc().insert()
		doc.submit()
		self.assertEqual(doc.docstatus, 1)
		doc.cancel()
		self.assertEqual(doc.docstatus, 2)

	def test_amend_does_not_copy_stock_entry(self):
		doc = self.make_doc().insert()
		doc.submit()
		doc.cancel()
		doc.stock_entry = "SE-TEST-0001"  # set by the Stock Entry subtask later
		amended = frappe.copy_doc(doc, ignore_no_copy=False)  # like Amend in the form: no_copy fields left out
		amended.amended_from = doc.name
		amended.docstatus = 0
		self.assertFalse(amended.stock_entry)
		amended.insert()
		self.assertEqual(amended.amended_from, doc.name)
		self.assertEqual(amended.docstatus, 0)

	def test_company_defaults_when_empty(self):
		doc = self.make_doc(company=None)
		with patch("frappe.defaults.get_user_default", return_value=self.company):
			doc.insert()
		self.assertEqual(doc.company, self.company)

	# --- defaults from Uniform Issue Settings (14yr2e56y3k) ----------------

	def test_default_warehouse_from_settings(self):
		self.set_settings(group=UNIFORMS, warehouse=self.warehouse)
		doc = self.make_doc(source_warehouse=None).insert()
		self.assertEqual(doc.source_warehouse, self.warehouse)

	def test_chosen_warehouse_not_replaced_by_default(self):
		other = frappe.db.get_value(
			"Warehouse",
			{"company": self.company, "is_group": 0, "disabled": 0, "name": ["!=", self.warehouse]},
			"name",
		)
		if not other:
			self.skipTest("Need a second warehouse")
		self.set_settings(group=UNIFORMS, warehouse=other)
		doc = self.make_doc().insert()
		self.assertEqual(doc.source_warehouse, self.warehouse)

	def test_no_warehouse_anywhere_rejected(self):
		self.assert_rejected(self.make_doc(source_warehouse=None), "Source Warehouse is required")

	# --- 14yr2e56y3n: item filter ------------------------------------------

	def item_filter_results(self):
		"""Same filters as the Item Code query in employee_uniform_issue.js."""
		return set(
			frappe.get_all(
				"Item",
				filters={
					"disabled": 0,
					"is_stock_item": 1,
					"item_group": ["descendants of (inclusive)", UNIFORMS],
				},
				pluck="name",
			)
		)

	def test_item_filter_lists_only_uniform_stock_items(self):
		found = self.item_filter_results()
		self.assertIn(SHIRT, found)  # child group of the uniform group
		self.assertIn(CAP, found)
		for item in (NON_STOCK, DISABLED, OTHER):
			self.assertNotIn(item, found)

	def test_item_filter_group_comes_from_settings(self):
		from alantech_erp.alantech.doctype.uniform_issue_settings.uniform_issue_settings import (
			get_uniform_defaults,
		)

		self.assertEqual(get_uniform_defaults(company=self.company).uniform_item_group, UNIFORMS)

	# --- 14yr2e56y3n: valuation rate ---------------------------------------

	def test_rate_from_warehouse_bin(self):
		self.assertEqual(get_item_details(SHIRT, self.warehouse, _check_permission=False).rate, BIN_RATE)

	def test_rate_falls_back_to_item_valuation_rate(self):
		details = get_item_details(CAP, self.warehouse, _check_permission=False)
		self.assertEqual(details.rate, ITEM_RATE)
		self.assertEqual(details.uom, "Nos")

	def test_rate_without_warehouse(self):
		self.assertEqual(get_item_details(CAP, None, _check_permission=False).rate, ITEM_RATE)
		self.assertEqual(get_item_details(SHIRT, None, _check_permission=False).rate, 0)

	def test_item_details_for_missing_item(self):
		self.assertRaises(frappe.ValidationError, get_item_details, "_TEST-NO-SUCH-ITEM", None, False)

	def test_item_details_needs_permission(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertRaises(frappe.PermissionError, get_item_details, SHIRT, self.warehouse)

	# --- 14yr2e56y3n: validations ------------------------------------------

	def test_zero_qty_rejected(self):
		self.assert_rejected(self.make_doc(items=[{"item_code": SHIRT, "qty": 0}]), "Qty must be greater than 0")

	def test_negative_qty_rejected(self):
		self.assert_rejected(self.make_doc(items=[{"item_code": SHIRT, "qty": -1}]), "Qty must be greater than 0")

	def test_items_required(self):
		self.assertRaises(frappe.ValidationError, self.make_doc(items=[]).insert)

	def test_non_stock_item_rejected(self):
		self.assert_rejected(self.make_doc(items=[{"item_code": NON_STOCK, "qty": 1}]), "is not a stock item")

	def test_disabled_item_rejected(self):
		self.assert_rejected(self.make_doc(items=[{"item_code": DISABLED, "qty": 1}]), "is disabled")

	def test_non_uniform_item_rejected(self):
		self.assert_rejected(self.make_doc(items=[{"item_code": OTHER, "qty": 1}]), "is not a uniform item")

	def test_item_in_child_group_accepted(self):
		self.assertTrue(self.make_doc(items=[{"item_code": SHIRT, "qty": 1}]).insert().name)

	def test_any_stock_item_when_no_group_set(self):
		self.set_settings(group=None)
		self.assertTrue(self.make_doc(items=[{"item_code": OTHER, "qty": 1}]).insert().name)

	def test_insufficient_stock_rejected_with_clear_message(self):
		self.stock.return_value = 1
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_doc(items=[{"item_code": SHIRT, "qty": 2}]).insert()
		message = str(ctx.exception)
		self.assertIn("Insufficient stock", message)
		self.assertIn(SHIRT, message)
		self.assertIn("required 2", message)
		self.assertIn("available 1", message)

	def test_exact_stock_is_enough(self):
		self.stock.return_value = 2
		self.assertTrue(self.make_doc(items=[{"item_code": SHIRT, "qty": 2}]).insert().name)

	def test_repeated_item_rows_are_counted_together(self):
		self.stock.return_value = 4
		doc = self.make_doc(items=[{"item_code": SHIRT, "qty": 3}, {"item_code": SHIRT, "qty": 3}])
		self.assert_rejected(doc, "required 6")

	def test_stock_checked_on_issue_date(self):
		self.make_doc(issue_date="2026-01-15").insert()
		args = self.stock.call_args.args
		self.assertEqual(args[:2], (SHIRT, self.warehouse))
		self.assertEqual(str(args[2]), "2026-01-15")

	def test_inactive_employee_rejected(self):
		frappe.db.set_value("Employee", self.other_employee.name, "status", "Inactive")
		self.addCleanup(frappe.db.set_value, "Employee", self.other_employee.name, "status", "Active")
		self.assert_rejected(self.make_doc(employee=self.other_employee.name), "Active employees")

	def test_group_warehouse_rejected(self):
		if not self.group_warehouse:
			self.skipTest("No group warehouse")
		self.assert_rejected(self.make_doc(source_warehouse=self.group_warehouse), "group warehouse")

	def test_disabled_warehouse_rejected(self):
		frappe.db.set_value("Warehouse", self.warehouse, "disabled", 1)
		self.addCleanup(frappe.db.set_value, "Warehouse", self.warehouse, "disabled", 0)
		self.assert_rejected(self.make_doc(), "is disabled")


	# --- 14yr2e56y3p: Stock Entry (Material Issue) on submit ----------------

	def submitted(self, **kwargs):
		doc = self.make_doc(**kwargs).insert()
		doc.submit()
		return doc

	def test_stock_entry_created_and_submitted(self):
		doc = self.submitted(issue_date=nowdate(), remarks="Two shirts")
		self.assertTrue(doc.stock_entry)
		self.assertEqual(frappe.db.get_value("Employee Uniform Issue", doc.name, "stock_entry"), doc.stock_entry)
		entry = frappe.get_doc("Stock Entry", doc.stock_entry)
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(entry.stock_entry_type, "Material Issue")
		self.assertEqual(entry.purpose, "Material Issue")
		self.assertEqual(entry.company, self.company)
		self.assertEqual(str(entry.posting_date), str(doc.issue_date))
		self.assertIn(self.employee.name, entry.remarks)
		self.assertIn(doc.name, entry.remarks)
		self.assertIn("Two shirts", entry.remarks)
		self.assertEqual(entry.alt_employee, self.employee.name)
		self.assertEqual(entry.alt_employee_uniform_issue, doc.name)

	def test_stock_entry_rows(self):
		doc = self.submitted(items=[{"item_code": SHIRT, "qty": 2}, {"item_code": SHIRT, "qty": 1, "size": "L"}])
		entry = frappe.get_doc("Stock Entry", doc.stock_entry)
		self.assertEqual([(r.item_code, flt(r.qty)) for r in entry.items], [(SHIRT, 2), (SHIRT, 1)])
		for row in entry.items:
			self.assertEqual(row.s_warehouse, self.warehouse)
			self.assertFalse(row.t_warehouse)
			self.assertEqual(row.expense_account, self.expense_account)
			self.assertEqual(row.cost_center, self.company_cost_center)

	def test_cost_center_from_settings(self):
		cost_center = frappe.db.get_value(
			"Cost Center",
			{"company": self.company, "is_group": 0, "disabled": 0, "name": ["!=", self.company_cost_center]},
			"name",
		)
		if not cost_center:
			self.skipTest("Need a second leaf cost center")
		self.set_settings(group=UNIFORMS, cost_center=cost_center)
		entry = frappe.get_doc("Stock Entry", self.submitted().stock_entry)
		self.assertEqual(entry.items[0].cost_center, cost_center)

	def test_stock_ledger_shows_outward_entry(self):
		doc = self.submitted()
		sle = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": doc.stock_entry, "is_cancelled": 0},
			fields=["item_code", "warehouse", "actual_qty", "valuation_rate"],
		)
		self.assertEqual(len(sle), 1)
		self.assertEqual((sle[0].item_code, sle[0].warehouse, flt(sle[0].actual_qty)), (SHIRT, self.warehouse, -2))
		self.assertEqual(flt(sle[0].valuation_rate), BIN_RATE)

	def test_gl_debits_uniform_expense_credits_stock_in_hand(self):
		if not cint(frappe.get_cached_value("Company", self.company, "enable_perpetual_inventory")):
			self.skipTest("Perpetual inventory is off: no GL entries for stock")
		doc = self.submitted()
		gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": doc.stock_entry, "is_cancelled": 0},
			fields=["account", "debit", "credit", "cost_center"],
		)
		by_account = {row.account: row for row in gl}
		amount = 2 * BIN_RATE
		self.assertEqual(flt(by_account[self.expense_account].debit), amount)
		self.assertEqual(by_account[self.expense_account].cost_center, self.company_cost_center)
		self.assertEqual(flt(by_account[self.stock_account].credit), amount)

	def test_missing_expense_account_blocks_submit(self):
		self.set_settings(group=UNIFORMS, expense_account=None)
		doc = self.make_doc().insert()
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.submit()
		self.assertIn("Uniform Expense Account", str(ctx.exception))
		self.assertFalse(
			frappe.db.exists("Stock Entry", {"alt_employee_uniform_issue": doc.name, "docstatus": 1})
		)

	def test_cancel_cancels_stock_entry(self):
		doc = self.submitted()
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Stock Entry", doc.stock_entry, "docstatus"), 2)
		self.assertFalse(
			frappe.db.exists("Stock Ledger Entry", {"voucher_no": doc.stock_entry, "is_cancelled": 0})
		)
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_no": doc.stock_entry, "is_cancelled": 0}))

	# --- 14yr2e56y3q: cancel the Stock Entry with the issue -----------------

	def bin_qty(self):
		return flt(frappe.db.get_value("Bin", {"item_code": SHIRT, "warehouse": self.warehouse}, "actual_qty"))

	def test_cancel_restores_stock_balance(self):
		before = self.bin_qty()
		doc = self.submitted()
		self.assertEqual(self.bin_qty(), before - 2)
		doc.cancel()
		self.assertEqual(self.bin_qty(), before)

	def test_amend_creates_new_stock_entry_on_resubmit(self):
		doc = self.submitted()
		doc.cancel()
		amended = frappe.copy_doc(doc, ignore_no_copy=False)  # like Amend in the form
		amended.amended_from = doc.name
		amended.docstatus = 0
		amended.insert()
		self.assertFalse(amended.stock_entry)
		amended.submit()
		self.assertTrue(amended.stock_entry)
		self.assertNotEqual(amended.stock_entry, doc.stock_entry)
		self.assertEqual(frappe.db.get_value("Stock Entry", amended.stock_entry, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Stock Entry", doc.stock_entry, "docstatus"), 2)
		self.assertEqual(
			frappe.db.get_value("Stock Entry", amended.stock_entry, "alt_employee_uniform_issue"), amended.name
		)

	def test_stock_entry_cannot_be_cancelled_directly(self):
		doc = self.submitted()
		entry = frappe.get_doc("Stock Entry", doc.stock_entry)
		with self.assertRaises(frappe.ValidationError) as ctx:
			entry.cancel()
		self.assertIn(doc.name, str(ctx.exception))
		self.assertEqual(frappe.db.get_value("Stock Entry", doc.stock_entry, "docstatus"), 1)

	def test_other_stock_entries_cancel_normally(self):
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Issue",
				"company": self.company,
				"items": [
					{"item_code": SHIRT, "qty": 1, "s_warehouse": self.warehouse, "expense_account": self.expense_account}
				],
			}
		).insert()
		entry.submit()
		entry.cancel()
		self.assertEqual(entry.docstatus, 2)
