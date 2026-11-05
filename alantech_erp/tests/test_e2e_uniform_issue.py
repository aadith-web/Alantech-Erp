# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-F12 Employee Uniform Issue: end-to-end flow.

ClickUp: https://app.clickup.com/t/14yr2e56y3v (parent https://app.clickup.com/t/14yr2e56y3j)

The steps run in order (test_01 ... test_08) and build on each other, like the task's test cases:
    1. Uniform item (stock item in a uniform Item Group) -> Purchase Order -> Purchase Receipt
    2. Employee Uniform Issue -> submit -> stock balance, Stock Ledger and GL
    3. Issue more than is in stock -> error
    4. Same item to the same employee within Re-issue Warning Days -> warning
    5. Cancel the issue -> stock and GL reversed
    6. Amend and resubmit -> a new Stock Entry
    7. Employee Uniform Issue Register and Employee connections
    8. Role permissions with test users (HR User / Stock User prepare, HR / Stock Manager submit)

Nothing is mocked: real stock, Stock Ledger Entries and GL Entries. A warehouse, supplier, item group
and item of its own keep the stock figures independent of the site's data; Uniform Issue Settings are
pointed at them for the test. Everything is rolled back after the class.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_e2e_uniform_issue
"""

import frappe
from frappe.desk.notifications import get_open_count
from frappe.desk.query_report import run as run_report
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, nowdate

from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

GROUP = "_Test E2E Uniforms"
ITEM = "_TEST-E2E-UNIFORM-SHIRT"
SUPPLIER = "_Test E2E Uniform Supplier"
WAREHOUSE_NAME = "_Test E2E Uniform Store"
REPORT = "Employee Uniform Issue Register"
BOUGHT, RATE = 10, 300
REISSUE_DAYS = 30


def make_role_user(role):
	email = f"_test-e2e-uni-{role.replace(' ', '-').lower()}@example.com"
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": f"E2E {role}", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.set("roles", [{"role": role}])
	user.save(ignore_permissions=True)
	return email


class IntegrationTestE2EUniformIssue(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		employee = frappe.get_all(
			"Employee", filters={"status": "Active"}, fields=["name", "employee_name", "company"],
			order_by="creation asc", limit=1,
		)
		if not employee:
			raise cls.skipTest(cls, "Need an active employee on the site")
		cls.employee = employee[0]
		cls.company = cls.employee.company
		abbr = frappe.get_cached_value("Company", cls.company, "abbr")
		cls.expense_account = frappe.db.get_value(
			"Account", {"company": cls.company, "root_type": "Expense", "is_group": 0, "disabled": 0,
			            "account_type": ["not in", ["Stock Adjustment", "Cost of Goods Sold"]]},
		)
		cls.cost_center = frappe.get_cached_value("Company", cls.company, "cost_center")
		if not (cls.expense_account and cls.cost_center):
			raise cls.skipTest(cls, "Company needs an expense account and a default cost center")

		parent_wh = frappe.db.get_value("Warehouse", {"company": cls.company, "is_group": 1, "parent_warehouse": ["is", "not set"]}) \
			or frappe.db.get_value("Warehouse", {"company": cls.company, "is_group": 1})
		cls.warehouse = f"{WAREHOUSE_NAME} - {abbr}"
		if not frappe.db.exists("Warehouse", cls.warehouse):
			frappe.get_doc(
				{"doctype": "Warehouse", "warehouse_name": WAREHOUSE_NAME, "company": cls.company,
				 "parent_warehouse": parent_wh}
			).insert(ignore_permissions=True)
		cls.stock_account = frappe.db.get_value("Warehouse", cls.warehouse, "account") or frappe.get_cached_value(
			"Company", cls.company, "default_inventory_account"
		)

		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.get_doc(
				{"doctype": "Supplier", "supplier_name": SUPPLIER,
				 "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}) or "All Supplier Groups"}
			).insert(ignore_permissions=True)

		# step 1 of the task: a uniform item = a stock item in the uniform Item Group
		if not frappe.db.exists("Item Group", GROUP):
			frappe.get_doc(
				{"doctype": "Item Group", "item_group_name": GROUP, "parent_item_group": "All Item Groups"}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Item", ITEM):
			item = frappe.get_doc(
				{"doctype": "Item", "item_code": ITEM, "item_name": "E2E Uniform Shirt", "item_group": GROUP,
				 "stock_uom": "Nos", "is_stock_item": 1, "is_purchase_item": 1}
			)
			if frappe.get_meta("Item").has_field("gst_hsn_code"):
				item.gst_hsn_code = "62052000"  # India Compliance: HSN mandatory
			item.insert(ignore_permissions=True)

		# India Compliance needs a company billing address on purchase documents; the site may have
		# none yet, so one is made for the test (rolled back with the rest)
		company_addresses = frappe.get_all(
			"Dynamic Link",
			filters={"link_doctype": "Company", "link_name": cls.company, "parenttype": "Address"},
			pluck="parent",
		)
		cls.billing_address = company_addresses and frappe.db.get_value(
			"Address", {"is_your_company_address": 1, "name": ["in", company_addresses]}
		)
		if not cls.billing_address:
			cls.billing_address = frappe.get_doc(
				{"doctype": "Address", "address_title": "_Test E2E Company", "address_type": "Billing",
				 "address_line1": "1 Test Road", "city": "Ahmedabad", "state": "Gujarat", "pincode": "380001",
				 "country": "India", "is_your_company_address": 1,
				 # India Compliance's own test GSTIN (Gujarat); a company address needs one for GST
				 "gstin": "24AAQCA8719H1ZC", "gst_category": "Registered Regular",
				 "links": [{"link_doctype": "Company", "link_name": cls.company}]}
			).insert(ignore_permissions=True).name
		cls.state = frappe._dict()

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		# the settings are re-applied per step: a step that fails must not leave the next one without them
		settings = frappe.get_single("Uniform Issue Settings")
		settings.update(
			{
				"default_source_warehouse": self.warehouse,
				"uniform_item_group": GROUP,
				"uniform_expense_account": self.expense_account,
				"default_cost_center": self.cost_center,
				"reissue_warning_days": REISSUE_DAYS,
			}
		)
		settings.save(ignore_permissions=True)

	# --- helpers ---------------------------------------------------------
	def balance(self):
		return flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": self.warehouse}, "actual_qty"))

	def new_issue(self, qty, **values):
		return frappe.get_doc(
			{
				"doctype": "Employee Uniform Issue",
				"employee": self.employee.name,
				"company": self.company,
				"issue_date": nowdate(),
				"items": [{"item_code": ITEM, "qty": qty, "size": "L"}],
				**values,
			}
		)

	def gl_net(self, voucher_no):
		"""account -> debit - credit over every GL Entry of the voucher (cancelled ones included)."""
		net = {}
		for row in frappe.get_all(
			"GL Entry", filters={"voucher_type": "Stock Entry", "voucher_no": voucher_no},
			fields=["account", "debit", "credit", "cost_center", "is_cancelled"],
		):
			net[row.account] = flt(net.get(row.account)) + flt(row.debit) - flt(row.credit)
		return net

	def require(self, *keys):
		missing = [k for k in keys if not self.state.get(k)]
		if missing:
			self.skipTest(f"Needs an earlier step: {', '.join(missing)}")

	# --- 1. item, Purchase Order, Purchase Receipt -----------------------
	def test_01_buy_uniforms(self):
		item = frappe.get_doc("Item", ITEM)
		self.assertEqual((item.is_stock_item, item.item_group), (1, GROUP))

		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"supplier": SUPPLIER,
				"company": self.company,
				"transaction_date": nowdate(),
				"schedule_date": nowdate(),
				"set_warehouse": self.warehouse,
				"billing_address": self.billing_address,
				"shipping_address": self.billing_address,
				"items": [{"item_code": ITEM, "qty": BOUGHT, "rate": RATE, "warehouse": self.warehouse,
				           "schedule_date": nowdate()}],
			}
		)
		po.insert(ignore_permissions=True)
		po.submit()

		pr = make_purchase_receipt(po.name)
		pr.posting_date = nowdate()
		pr.insert(ignore_permissions=True)
		pr.submit()

		self.assertEqual(self.balance(), BOUGHT)
		self.assertEqual(
			flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": self.warehouse}, "valuation_rate")), RATE
		)
		self.state.receipt = pr.name

	# --- 2. issue and submit: stock, Stock Ledger, GL ---------------------
	def test_02_issue_and_submit(self):
		self.require("receipt")
		doc = self.new_issue(2)
		doc.insert()
		self.assertEqual(doc.source_warehouse, self.warehouse)  # from Uniform Issue Settings
		self.assertEqual(doc.employee_name, self.employee.employee_name)
		self.assertEqual(flt(doc.items[0].rate), RATE)
		self.assertEqual(flt(doc.total_amount), 2 * RATE)
		doc.submit()

		entry = frappe.get_doc("Stock Entry", doc.stock_entry)
		self.assertEqual((entry.docstatus, entry.stock_entry_type), (1, "Material Issue"))
		self.assertEqual(entry.alt_employee_uniform_issue, doc.name)
		self.assertEqual(entry.alt_employee, self.employee.name)
		self.assertEqual(self.balance(), BOUGHT - 2)

		sle = frappe.get_all(
			"Stock Ledger Entry", filters={"voucher_no": entry.name, "is_cancelled": 0},
			fields=["item_code", "warehouse", "actual_qty", "stock_value_difference"],
		)
		self.assertEqual(len(sle), 1)
		self.assertEqual((sle[0].item_code, sle[0].warehouse, flt(sle[0].actual_qty)), (ITEM, self.warehouse, -2))
		self.assertEqual(flt(sle[0].stock_value_difference), -2 * RATE)

		gl = frappe.get_all(
			"GL Entry", filters={"voucher_no": entry.name, "is_cancelled": 0},
			fields=["account", "debit", "credit", "cost_center"],
		)
		debit = [g for g in gl if flt(g.debit)]
		credit = [g for g in gl if flt(g.credit)]
		self.assertEqual([(g.account, flt(g.debit), g.cost_center) for g in debit],
		                 [(self.expense_account, 2 * RATE, self.cost_center)])
		self.assertEqual([(g.account, flt(g.credit)) for g in credit], [(self.stock_account, 2 * RATE)])
		self.state.issue = doc.name
		self.state.entry = entry.name

	# --- 3. more than is in stock -----------------------------------------
	def test_03_issue_more_than_stock(self):
		self.require("issue")
		doc = self.new_issue(BOUGHT)  # 8 left
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert()
		message = str(ctx.exception)
		self.assertIn("Insufficient stock", message)
		self.assertIn(f"required {flt(BOUGHT)}", message)
		self.assertIn(f"available {flt(BOUGHT - 2)}", message)
		self.assertEqual(self.balance(), BOUGHT - 2)

	# --- 4. re-issue warning ------------------------------------------------
	def test_04_reissue_warning(self):
		self.require("issue")
		frappe.clear_messages()
		doc = self.new_issue(1)
		doc.insert()  # a warning, not an error
		warnings = [m for m in frappe.get_message_log() if m.get("title") == "Recent Uniform Issue"]
		self.assertEqual(len(warnings), 1)
		self.assertIn(self.state.issue, warnings[0].message)
		self.assertIn(ITEM, warnings[0].message)
		doc.delete()

		frappe.db.set_single_value("Uniform Issue Settings", "reissue_warning_days", 0)
		frappe.clear_messages()
		self.new_issue(1).insert()
		self.assertFalse([m for m in frappe.get_message_log() if m.get("title") == "Recent Uniform Issue"])

	# --- 5. cancel: stock and GL reversed -----------------------------------
	def test_05_cancel_reverses_stock_and_gl(self):
		self.require("issue", "entry")
		doc = frappe.get_doc("Employee Uniform Issue", self.state.issue)
		doc.cancel()
		self.assertEqual(doc.docstatus, 2)
		self.assertEqual(frappe.db.get_value("Stock Entry", self.state.entry, "docstatus"), 2)
		self.assertEqual(self.balance(), BOUGHT)
		self.assertFalse(
			frappe.get_all("Stock Ledger Entry", filters={"voucher_no": self.state.entry, "is_cancelled": 0})
		)
		self.assertFalse(frappe.get_all("GL Entry", filters={"voucher_no": self.state.entry, "is_cancelled": 0}))
		for account, net in self.gl_net(self.state.entry).items():
			self.assertEqual(flt(net), 0, account)
		self.state.cancelled = doc.name

	# --- 6. amend and resubmit ----------------------------------------------
	def test_06_amend_and_resubmit(self):
		self.require("cancelled")
		cancelled = frappe.get_doc("Employee Uniform Issue", self.state.cancelled)
		amended = frappe.copy_doc(cancelled, ignore_no_copy=True)  # what the form's Amend does
		amended.amended_from = cancelled.name
		amended.docstatus = 0
		amended.insert()
		self.assertFalse(amended.stock_entry)
		self.assertEqual(amended.name, f"{cancelled.name}-1")
		amended.submit()

		self.assertTrue(amended.stock_entry)
		self.assertNotEqual(amended.stock_entry, self.state.entry)
		self.assertEqual(frappe.db.get_value("Stock Entry", amended.stock_entry, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Stock Entry", self.state.entry, "docstatus"), 2)
		self.assertEqual(self.balance(), BOUGHT - 2)
		self.state.amended = amended.name
		self.state.amended_entry = amended.stock_entry

	# --- 7. register report and Employee connections ------------------------
	def test_07_register_and_connections(self):
		self.require("amended")
		filters = {"company": self.company, "from_date": nowdate(), "to_date": nowdate(),
		           "employee": self.employee.name, "item_code": ITEM}
		result = run_report(REPORT, filters=filters)
		columns = [c["fieldname"] for c in result["columns"]]
		rows = [dict(zip(columns, r)) if isinstance(r, list | tuple) else r for r in result["result"][:-1]]
		self.assertEqual([r["name"] for r in rows], [self.state.amended])  # cancelled original not listed
		row = rows[0]
		self.assertEqual(row["stock_entry"], self.state.amended_entry)
		self.assertEqual((flt(row["qty"]), flt(row["rate"]), flt(row["amount"])), (2, RATE, 2 * RATE))
		total = result["result"][-1]
		total = total if isinstance(total, list | tuple) else [total.get(c) for c in columns]
		self.assertEqual(flt(total[columns.index("qty")]), 2)
		self.assertEqual(flt(total[columns.index("amount")]), 2 * RATE)

		data = frappe.get_meta("Employee").get_dashboard_data()
		self.assertIn("Employee Uniform Issue", {d for g in data.transactions for d in g["items"]})
		counts = {c["doctype"]: c["count"] for c in get_open_count("Employee", self.employee.name)["count"]["external_links_found"]}
		self.assertGreaterEqual(counts.get("Employee Uniform Issue", 0), 1)

	# --- 8. role permissions -------------------------------------------------
	def test_08_role_permissions(self):
		self.require("receipt")
		frappe.db.set_single_value("Uniform Issue Settings", "reissue_warning_days", 0)
		for preparer, approver in (("HR User", "HR Manager"), ("Stock User", "Stock Manager")):
			with self.subTest(preparer=preparer, approver=approver):
				prep_user, appr_user = make_role_user(preparer), make_role_user(approver)

				frappe.set_user(prep_user)
				doc = self.new_issue(1)
				doc.insert()
				doc.remarks = f"prepared by {preparer}"
				doc.save()
				with self.assertRaises(frappe.PermissionError):
					doc.submit()

				frappe.set_user(appr_user)
				doc = frappe.get_doc("Employee Uniform Issue", doc.name)
				doc.submit()
				self.assertTrue(doc.stock_entry)

				frappe.set_user(prep_user)
				with self.assertRaises(frappe.PermissionError):
					frappe.get_doc("Employee Uniform Issue", doc.name).cancel()

				frappe.set_user(appr_user)
				frappe.get_doc("Employee Uniform Issue", doc.name).cancel()
				self.assertEqual(frappe.db.get_value("Stock Entry", doc.stock_entry, "docstatus"), 2)
				frappe.set_user("Administrator")
		self.assertEqual(self.balance(), BOUGHT - 2)
