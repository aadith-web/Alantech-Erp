

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

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


class IntegrationTestEmployeeUniformIssue(IntegrationTestCase):
	def setUp(self):
		self.employee = frappe.db.get_value(
			"Employee", {"status": "Active"}, ["name", "employee_name", "department", "designation", "company"], as_dict=True
		)
		self.item = frappe.db.get_value("Item", {"is_stock_item": 1, "disabled": 0}, ["name", "item_group"], as_dict=True)
		if not (self.employee and self.item):
			self.skipTest("Need an active Employee and a stock Item on the site")
		self.company = self.employee.company
		self.warehouse = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 0, "disabled": 0}, "name"
		)
		if not self.warehouse:
			self.skipTest("No warehouse for the employee's company")

		# The real stock balance depends on site data, so fix it here (plenty of stock by default)
		patcher = patch(STOCK_BALANCE, return_value=1000)
		self.stock = patcher.start()
		self.addCleanup(patcher.stop)

		# Start with no uniform item group so any stock item is allowed
		self.set_settings(group=None)

	def set_settings(self, group=None, warehouse=None):
		settings = frappe.get_single("Uniform Issue Settings")
		settings.uniform_item_group = group
		settings.default_source_warehouse = warehouse
		settings.default_cost_center = None
		settings.uniform_expense_account = None
		settings.save()

	def make_doc(self, **kwargs):
		doc = frappe.get_doc(
			{
				"doctype": "Employee Uniform Issue",
				"employee": self.employee.name,
				"company": self.company,
				"source_warehouse": self.warehouse,
				"items": [{"item_code": self.item.name, "qty": 2}],
			}
		)
		doc.update(kwargs)
		return doc

	# --- previous subtask -------------------------------------------------

	def test_create_save_and_naming(self):
		doc = self.make_doc().insert()
		self.assertRegex(doc.name, r"^EUI-\d{4}-\d{5}$")
		self.assertEqual(doc.issue_date, frappe.utils.nowdate())

	def test_employee_details_fetched(self):
		doc = self.make_doc().insert()
		self.assertEqual(doc.employee_name, self.employee.employee_name)
		self.assertEqual(doc.department, self.employee.department)
		self.assertEqual(doc.designation, self.employee.designation)

	def test_totals_calculated(self):
		doc = self.make_doc(items=[{"item_code": self.item.name, "qty": 2}, {"item_code": self.item.name, "qty": 3}]).insert()
		self.assertEqual(doc.total_qty, 5)
		for row in doc.items:
			self.assertEqual(flt(row.amount), flt(row.qty) * flt(row.rate))
		self.assertEqual(flt(doc.total_amount), sum(flt(r.amount) for r in doc.items))

	def test_default_warehouse_from_settings(self):
		self.set_settings(warehouse=self.warehouse)
		doc = self.make_doc(source_warehouse=None).insert()
		self.assertEqual(doc.source_warehouse, self.warehouse)

	def test_zero_qty_rejected(self):
		doc = self.make_doc(items=[{"item_code": self.item.name, "qty": 0}])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_items_required(self):
		doc = self.make_doc(items=[])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_submit(self):
		doc = self.make_doc().insert()
		doc.submit()
		self.assertEqual(doc.docstatus, 1)
		self.assertFalse(doc.stock_entry)

	# --- item filter and validations --------------------------------------

	def test_insufficient_stock_rejected_with_clear_message(self):
		self.stock.return_value = 1
		doc = self.make_doc(items=[{"item_code": self.item.name, "qty": 2}])
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert()
		self.assertIn("Insufficient stock", str(ctx.exception))

	def test_repeated_item_rows_are_counted_together(self):
		self.stock.return_value = 4
		doc = self.make_doc(items=[{"item_code": self.item.name, "qty": 3}, {"item_code": self.item.name, "qty": 3}])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_stock_checked_on_issue_date(self):
		doc = self.make_doc(issue_date="2026-01-15").insert()
		args = self.stock.call_args.args
		self.assertEqual(args[:2], (self.item.name, self.warehouse))
		self.assertEqual(str(args[2]), "2026-01-15")

	def test_non_uniform_item_rejected(self):
		other_group = frappe.db.get_value(
			"Item Group", {"is_group": 0, "name": ["!=", self.item.item_group]}, "name"
		)
		if not other_group:
			self.skipTest("Need a second leaf Item Group")
		self.set_settings(group=other_group)
		self.assertRaises(frappe.ValidationError, self.make_doc().insert)

	def test_uniform_item_accepted(self):
		self.set_settings(group=self.item.item_group)
		doc = self.make_doc().insert()
		self.assertTrue(doc.name)

	def test_inactive_employee_rejected(self):
		inactive = frappe.db.get_value("Employee", {"status": ["!=", "Active"]}, "name")
		if not inactive:
			self.skipTest("No non-active employee on the site")
		doc = self.make_doc(employee=inactive)
		self.assertRaises(frappe.ValidationError, doc.insert)