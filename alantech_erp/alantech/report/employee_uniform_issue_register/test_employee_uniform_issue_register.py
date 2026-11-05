# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Uniform Issue Register report (ClickUp 14yr2e56y3t).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.report.employee_uniform_issue_register.test_employee_uniform_issue_register

Issues are dated mid fiscal year, clear of issues the site already has, and every test filters on
that date range so only its own records are counted.
"""

from unittest.mock import patch

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.desk.query_report import run
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from alantech_erp.alantech.doctype.employee_uniform_issue.test_employee_uniform_issue import (
	STOCK_BALANCE,
	make_item,
	make_item_group,
)
from alantech_erp.alantech.report.employee_uniform_issue_register.employee_uniform_issue_register import (
	execute,
)


REPORT = "Employee Uniform Issue Register"
GROUP = "_Test Register Uniforms"
SHIRT = "_TEST-REGISTER-SHIRT"
TROUSER = "_TEST-REGISTER-TROUSER"
PARENT_DEPT = "_Test Register Ops"
CHILD_DEPT = "_Test Register Ops Floor"


def make_department(name, parent, company):
	existing = frappe.db.get_value("Department", {"department_name": name, "company": company})
	if existing:
		return existing
	return frappe.get_doc(
		{"doctype": "Department", "department_name": name, "parent_department": parent, "company": company,
		 "is_group": 1}
	).insert(ignore_permissions=True).name


class IntegrationTestEmployeeUniformIssueRegister(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		employees = frappe.get_all(
			"Employee", filters={"status": "Active"}, fields=["name", "company"], order_by="creation asc", limit=2
		)
		if len(employees) < 2:
			raise cls.skipTest(cls, "Need two active employees on the site")
		cls.employee, cls.other_employee = employees[0].name, employees[1].name
		cls.company = employees[0].company
		cls.warehouse = frappe.db.get_value("Warehouse", {"company": cls.company, "is_group": 0, "disabled": 0})
		if not cls.warehouse:
			raise cls.skipTest(cls, "No warehouse for the employee's company")

		make_item_group(GROUP)
		make_item(SHIRT, GROUP)
		make_item(TROUSER, GROUP)
		fy_start = get_fiscal_year(nowdate(), company=cls.company)[1]
		receipt = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": cls.company,
				"posting_date": fy_start,
				"set_posting_time": 1,
				"items": [
					{"item_code": code, "qty": 100, "basic_rate": rate, "t_warehouse": cls.warehouse}
					for code, rate in ((SHIRT, 200), (TROUSER, 300))
				],
			}
		)
		receipt.insert(ignore_permissions=True)
		receipt.submit()

		root = frappe.db.get_value("Department", {"is_group": 1, "parent_department": ["in", ("", None)]}) or "All Departments"
		cls.parent_dept = make_department(PARENT_DEPT, root, cls.company)
		cls.child_dept = make_department(CHILD_DEPT, cls.parent_dept, cls.company)

		settings = frappe.get_single("Uniform Issue Settings")
		settings.uniform_item_group = None
		settings.default_source_warehouse = None
		settings.default_cost_center = None
		settings.reissue_warning_days = 0
		settings.uniform_expense_account = frappe.db.get_value(
			"Account", {"company": cls.company, "root_type": "Expense", "is_group": 0, "disabled": 0}
		)
		settings.save()

		# a window of our own, clear of issues the site already has around today
		cls.start = add_days(fy_start, 150)
		cls.end = add_days(cls.start, 10)

	def setUp(self):
		patcher = patch(STOCK_BALANCE, return_value=1000)
		patcher.start()
		self.addCleanup(patcher.stop)

	def issue(self, days=0, employee=None, items=None, submit=True, department=None):
		employee = employee or self.employee
		if department:
			# the issue takes its department from the employee on every save
			old = frappe.db.get_value("Employee", employee, "department")
			frappe.db.set_value("Employee", employee, "department", department)
			self.addCleanup(frappe.db.set_value, "Employee", employee, "department", old)
		doc = frappe.get_doc(
			{
				"doctype": "Employee Uniform Issue",
				"employee": employee,
				"company": self.company,
				"issue_date": add_days(self.start, days),
				"source_warehouse": self.warehouse,
				"items": items or [{"item_code": SHIRT, "qty": 2, "size": "M"}],
			}
		)
		doc.insert()
		if submit:
			doc.submit()
			# rolled back per class, not per test: cancel so later tests start from an empty window
			self.addCleanup(lambda: doc.reload().docstatus == 1 and doc.cancel())
		return doc

	def rows(self, **filters):
		filters = {"company": self.company, "from_date": self.start, "to_date": self.end, **filters}
		return execute(filters)[1]

	def test_columns(self):
		columns = execute({"company": self.company, "from_date": self.start, "to_date": self.end})[0]
		self.assertEqual(
			[c["label"] for c in columns],
			["EUI No", "Issue Date", "Employee", "Employee Name", "Department", "Item Code", "Item Name",
			 "Size", "Qty", "Rate", "Amount", "Stock Entry"],
		)

	def test_one_row_per_item_with_issue_details(self):
		doc = self.issue(items=[{"item_code": SHIRT, "qty": 2, "size": "M"}, {"item_code": TROUSER, "qty": 1, "size": "32"}])
		doc.reload()
		rows = self.rows()
		self.assertEqual([r.item_code for r in rows], [SHIRT, TROUSER])
		shirt = rows[0]
		self.assertEqual(shirt.name, doc.name)
		self.assertEqual(shirt.employee, doc.employee)
		self.assertEqual(shirt.employee_name, doc.employee_name)
		self.assertEqual(shirt.size, "M")
		self.assertEqual(flt(shirt.qty), 2)
		self.assertEqual(flt(shirt.rate), flt(doc.items[0].rate))
		self.assertEqual(flt(shirt.amount), flt(doc.items[0].amount))
		self.assertEqual(shirt.stock_entry, doc.stock_entry)
		self.assertTrue(shirt.stock_entry)

	def test_only_submitted_records(self):
		submitted = self.issue()
		draft = self.issue(submit=False)
		cancelled = self.issue()
		cancelled.cancel()
		names = {r.name for r in self.rows()}
		self.assertEqual(names, {submitted.name})
		self.assertNotIn(draft.name, names)

	def test_date_filters(self):
		first = self.issue(days=0)
		last = self.issue(days=10)
		self.assertEqual({r.name for r in self.rows()}, {first.name, last.name})
		self.assertEqual({r.name for r in self.rows(from_date=add_days(self.start, 1))}, {last.name})
		self.assertEqual({r.name for r in self.rows(to_date=add_days(self.end, -1))}, {first.name})

	def test_from_date_after_to_date_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.rows(from_date=self.end, to_date=self.start)

	def test_employee_filter(self):
		mine = self.issue()
		other = self.issue(employee=self.other_employee)
		self.assertEqual({r.name for r in self.rows(employee=self.employee)}, {mine.name})
		self.assertEqual({r.name for r in self.rows(employee=self.other_employee)}, {other.name})

	def test_item_filter(self):
		doc = self.issue(items=[{"item_code": SHIRT, "qty": 1}, {"item_code": TROUSER, "qty": 1}])
		rows = self.rows(item_code=TROUSER)
		self.assertEqual([(r.name, r.item_code) for r in rows], [(doc.name, TROUSER)])

	def test_department_filter_includes_sub_departments(self):
		in_parent = self.issue(department=self.parent_dept)
		in_child = self.issue(employee=self.other_employee, department=self.child_dept)
		self.assertEqual({r.name for r in self.rows(department=self.parent_dept)}, {in_parent.name, in_child.name})
		self.assertEqual({r.name for r in self.rows(department=self.child_dept)}, {in_child.name})

	def test_company_filter(self):
		doc = self.issue()
		self.assertIn(doc.name, {r.name for r in self.rows()})
		other_company = frappe.db.get_value("Company", {"name": ["!=", self.company]})
		if other_company:
			self.assertFalse(self.rows(company=other_company))

	def test_total_row_for_qty_and_amount(self):
		self.issue(items=[{"item_code": SHIRT, "qty": 2}, {"item_code": TROUSER, "qty": 3}])
		self.issue(employee=self.other_employee, items=[{"item_code": SHIRT, "qty": 1}])
		rows = self.rows()

		self.assertTrue(frappe.db.get_value("Report", REPORT, "add_total_row"))
		result = run(REPORT, filters={"company": self.company, "from_date": self.start, "to_date": self.end})
		columns = [c["fieldname"] for c in result["columns"]]
		total = result["result"][-1]
		self.assertEqual(len(result["result"]), len(rows) + 1)
		self.assertEqual(flt(total[columns.index("qty")]), 6)
		self.assertEqual(flt(total[columns.index("amount")]), sum(flt(r.amount) for r in rows))
		rate = next(c for c in result["columns"] if c["fieldname"] == "rate")
		self.assertTrue(rate.get("disable_total"))  # the report view shows no total for Rate
