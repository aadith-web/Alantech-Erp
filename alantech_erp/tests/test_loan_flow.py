# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Loan Management flow, Employee & HR Manager (HR-F05-x, ClickUp 14yr2e57kyk; setup/loan_roles.py,
setup/loan_accounts.py): HR Manager is also Loan Manager, the employee loan ledgers / Loan Product
accounts / Company settings, and the whole flow run as an HR Manager:

    Loan Application -> Approved -> Loan (Repay From Salary) -> Loan Disbursement (GL)
    -> repayment schedule -> monthly demand -> Salary Slip loan row (EMI) -> Loan Repayment (GL)

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_flow

Data: an employee of the company that has a submitted Salary Structure Assignment (Repay From
Salary needs one); test users zz.hrf05.*@example.com; test Loan Rule / Loan Product / offset order
with prefix ZZ-HRF05. Everything runs in a savepoint per test and is rolled back. The salary slip
is not submitted (net pay depends on the site's payroll data): its loan row is built and the
repayment it makes on submit (make_loan_repayment_entry) is run directly.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, get_first_day, get_last_day, getdate, today

from alantech_erp.setup import access, loan_accounts, loan_roles

PREFIX = "ZZ-HRF05"


def employee_with_salary_structure():
	rows = frappe.get_all(
		"Salary Structure Assignment",
		filters={"docstatus": 1},
		fields=["employee", "company"],
		order_by="from_date desc",
	)
	for row in rows:
		if frappe.db.get_value("Employee", row.employee, "status") == "Active":
			return row
	return None


def make_product(company, code, **values):
	"""A Loan Product with no accounts: the Loan Product hook fills them (loan_accounts)."""
	order = frappe.get_doc(
		{
			"doctype": "Loan Demand Offset Order",
			"title": f"{PREFIX} {code} Offset",
			"components": [{"demand_type": t} for t in ("Penalty", "Interest", "Principal")],
		}
	).insert()
	return frappe.get_doc(
		{
			"doctype": "Loan Product",
			"product_code": f"{PREFIX}-{code}",
			"product_name": f"{PREFIX} {code}",
			"company": company,
			"rate_of_interest": 4,
			"is_term_loan": 1,  # Repay From Salary needs a term loan (like PL)
			"collection_offset_sequence_for_standard_asset": order.name,
			"collection_offset_sequence_for_sub_standard_asset": order.name,
			**values,
		}
	).insert()


class TestLoanRoles(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("hrf05_roles")
		self.addCleanup(frappe.db.rollback, save_point="hrf05_roles")

	def user(self, key, *roles):
		return frappe.get_doc(
			{
				"doctype": "User",
				"email": f"zz.hrf05.{key}@example.com",
				"first_name": f"ZZ HRF05 {key}",
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)

	def test_hr_manager_gets_loan_manager(self):
		self.assertIn("Loan Manager", frappe.get_roles(self.user("hrm", "HR Manager").name))
		self.assertNotIn("Loan Manager", frappe.get_roles(self.user("hru", "HR User").name))

	def test_role_added_when_hr_manager_given_later(self):
		user = self.user("later", "HR User")
		user.add_roles("HR Manager")
		self.assertIn("Loan Manager", frappe.get_roles(user.name))

	def test_after_migrate_backfills_existing_hr_managers(self):
		user = self.user("backfill", "HR Manager")
		frappe.db.delete("Has Role", {"parent": user.name, "role": "Loan Manager"})
		frappe.clear_cache(user=user.name)
		self.assertNotIn("Loan Manager", frappe.get_roles(user.name))
		loan_roles.execute()
		frappe.clear_cache(user=user.name)
		self.assertIn("Loan Manager", frappe.get_roles(user.name))

	def test_payroll_can_raise_loan_demands(self):
		"""Building a salary slip with a Repay From Salary loan submits a Process Loan Demand as the
		user; Lending grants it to System Manager only, so Loan Manager (every HR Manager) gets it.
		An HR User does not build such slips (the accrual / demand records stay with loan roles)."""
		hr_manager = self.user("hrm", "HR Manager").name
		hr_user = self.user("hru", "HR User").name
		for ptype in ("create", "submit"):
			with self.subTest(ptype=ptype):
				self.assertTrue(frappe.has_permission("Process Loan Demand", ptype, user=hr_manager))
				self.assertTrue(frappe.has_permission("Process Loan Interest Accrual", ptype, user=hr_manager))
				self.assertFalse(frappe.has_permission("Process Loan Demand", ptype, user=hr_user))
				self.assertFalse(frappe.has_permission("Loan Interest Accrual", ptype, user=hr_user))

	def test_hr_role_profiles_include_loan_manager(self):
		for profile in ("ALT HR Manager", "ALT HR Executive", "ALT Managing Director"):
			with self.subTest(profile=profile):
				self.assertIn("Loan Manager", access.EXTRA_PROFILE_ROLES[profile])
				if frappe.db.exists("Role Profile", profile):
					roles = frappe.get_all(
						"Has Role", filters={"parent": profile, "parenttype": "Role Profile"}, pluck="role"
					)
					self.assertIn("Loan Manager", roles)


class TestLoanAccountsSetup(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Loan Product", {}, "company") or frappe.db.get_value(
			"Company", {}, "name"
		)

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("hrf05_accounts")
		self.addCleanup(frappe.db.rollback, save_point="hrf05_accounts")

	def make_product(self, code, **values):
		return make_product(self.company, code, **values)

	def test_ledgers(self):
		expected = {
			loan_accounts.LOAN: ("Asset", "Payable"),
			loan_accounts.ACCRUED: ("Asset", ""),
			loan_accounts.INCOME: ("Income", ""),
			loan_accounts.WRITE_OFF: ("Expense", ""),
			loan_accounts.REFUNDABLE: ("Liability", "Payable"),
		}
		for key, (root_type, account_type) in expected.items():
			with self.subTest(ledger=key):
				name = loan_accounts.ledger(self.company, key)
				self.assertTrue(name)
				values = frappe.db.get_value("Account", name, ["root_type", "account_type", "is_group"], as_dict=True)
				self.assertEqual(values.root_type, root_type)
				self.assertEqual(values.account_type or "", account_type)
				self.assertFalse(values.is_group)
				self.assertEqual(loan_accounts.ledger(self.company, key), name)  # found, not created again
				self.assertEqual(
					frappe.db.count("Account", {"company": self.company, "account_name": loan_accounts.LEDGERS[key][0]}), 1
				)

	def test_new_product_gets_ledgers_for_blank_accounts(self):
		product = self.make_product("NEW")
		for field, key in loan_accounts.FIELD_LEDGER.items():
			with self.subTest(field=field):
				self.assertEqual(product.get(field), loan_accounts.ledger(self.company, key))

	def test_chosen_account_is_kept(self):
		chosen = frappe.db.get_value("Account", {"company": self.company, "root_type": "Income", "is_group": 0, "account_name": ("!=", "Interest on Employee Loans")}, "name")
		product = self.make_product("KEEP", interest_income_account=chosen)
		self.assertEqual(product.interest_income_account, chosen)
		frappe.db.set_value("Loan Product", product.name, "write_off_account", None)
		loan_accounts.execute()
		product.reload()
		self.assertEqual(product.interest_income_account, chosen)  # never overwritten
		self.assertEqual(product.write_off_account, loan_accounts.ledger(self.company, loan_accounts.WRITE_OFF))

	def test_company_settings_set_once(self):
		frappe.db.set_value("Company", self.company, {"loan_accrual_frequency": None, "enable_loan_accounting": 0})
		loan_accounts.set_company_defaults(self.company)
		self.assertEqual(
			frappe.db.get_value("Company", self.company, ["loan_accrual_frequency", "enable_loan_accounting"]),
			("Monthly", 1),
		)
		frappe.db.set_value("Company", self.company, {"loan_accrual_frequency": "Daily", "enable_loan_accounting": 0})
		loan_accounts.set_company_defaults(self.company)
		self.assertEqual(
			frappe.db.get_value("Company", self.company, ["loan_accrual_frequency", "enable_loan_accounting"]),
			("Daily", 0),
		)


class TestLoanFlowAsHRManager(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.emp = employee_with_salary_structure()

	def setUp(self):
		if not self.emp:
			self.skipTest("Needs an active employee with a submitted Salary Structure Assignment")
		frappe.set_user("Administrator")
		frappe.db.savepoint("hrf05_flow")
		self.addCleanup(frappe.db.rollback, save_point="hrf05_flow")
		self.addCleanup(frappe.set_user, "Administrator")

		self.company = self.emp.company
		self.today = getdate(today())
		frappe.db.set_value("Loan Rule", {"enabled": 1}, "enabled", 0)
		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 0)
		loan_accounts.set_company_defaults(self.company)
		frappe.db.set_value("Company", self.company, {"loan_accrual_frequency": "Monthly", "enable_loan_accounting": 1})
		self.product = make_product(self.company, "FLOW")
		frappe.get_doc(
			{
				"doctype": "Loan Rule",
				"rule_name": f"{PREFIX} Open",
				"company": self.company,
				"max_active_loans": 0,
				"max_open_applications": 0,
			}
		).insert()
		self.hr_manager = (
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "zz.hrf05.flow@example.com",
					"first_name": "ZZ HRF05 flow",
					"send_welcome_email": 0,
					"roles": [{"role": "HR Manager"}],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_full_flow(self):
		from hrms.payroll.doctype.salary_slip.salary_slip_loan_utils import (
			make_loan_repayment_entry,
			process_loan_interest_accrual_and_demand,
			set_loan_repayment,
		)
		from lending.loan_management.doctype.loan.loan import make_loan_disbursement
		from lending.loan_management.doctype.loan_application.loan_application import create_loan

		frappe.set_user(self.hr_manager)
		self.assertIn("Loan Manager", frappe.get_roles())

		# 1. application -> approved
		app = frappe.get_doc(
			{
				"doctype": "Loan Application",
				"applicant_type": "Employee",
				"applicant": self.emp.employee,
				"company": self.company,
				"posting_date": self.today,
				"loan_product": self.product.name,
				"loan_amount": 12000,
				"repayment_method": "Repay Over Number of Periods",
				"repayment_periods": 12,
			}
		).insert()
		app.submit()
		app.status = "Approved"
		app.save()

		# 2. Loan with Repay From Salary -> Sanctioned
		loan = create_loan(app.name)
		loan.repay_from_salary = 1
		loan.repayment_start_date = get_last_day(self.today)
		loan.insert()
		loan.submit()
		self.assertEqual(frappe.db.get_value("Loan", loan.name, "status"), "Sanctioned")

		# 3. disbursement: Dr Employee Loans (employee as party) / Cr bank or cash -> Disbursed
		disbursement = make_loan_disbursement(loan.name)
		disbursement.insert()
		disbursement.submit()
		self.assertEqual(frappe.db.get_value("Loan", loan.name, "status"), "Disbursed")
		gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": disbursement.name, "is_cancelled": 0},
			fields=["account", "debit", "credit", "party"],
		)
		loan_ledger = loan_accounts.ledger(self.company, loan_accounts.LOAN)
		self.assertIn(
			{"account": loan_ledger, "debit": 12000.0, "credit": 0.0, "party": self.emp.employee},
			[dict(g) for g in gl],
		)
		self.assertTrue(
			frappe.db.exists("Loan Repayment Schedule", {"loan": loan.name, "docstatus": 1, "status": "Active"})
		)

		# 4. salary slip of the month picks up the EMI
		slip = frappe.new_doc("Salary Slip")
		slip.update(
			{
				"employee": self.emp.employee,
				"company": self.company,
				"posting_date": get_last_day(self.today),
				"start_date": get_first_day(self.today),
				"end_date": get_last_day(self.today),
				"payroll_frequency": "Monthly",
			}
		)
		process_loan_interest_accrual_and_demand(slip)
		set_loan_repayment(slip)
		self.assertEqual(len(slip.loans), 1)
		row = slip.loans[0]
		self.assertEqual(row.loan, loan.name)
		self.assertGreater(row.principal_amount, 0)
		self.assertAlmostEqual(flt(row.total_payment), flt(row.principal_amount + row.interest_amount), 2)
		self.assertEqual(flt(slip.total_loan_repayment), flt(row.total_payment))

		# 5. on slip submit: Loan Repayment, Dr Payroll Payable / Cr Employee Loans
		make_loan_repayment_entry(slip)
		repayment = frappe.get_all(
			"Loan Repayment",
			filters={"against_loan": loan.name, "docstatus": 1},
			fields=["name", "amount_paid"],
		)
		self.assertEqual(len(repayment), 1)
		self.assertEqual(flt(repayment[0].amount_paid), flt(row.total_payment))
		credited = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": repayment[0].name, "is_cancelled": 0, "account": loan_ledger},
			fields=["credit", "party"],
		)
		self.assertTrue(credited and credited[0].party == self.emp.employee)
		self.assertEqual(flt(frappe.db.get_value("Loan", loan.name, "total_amount_paid")), flt(row.total_payment))

	def test_repay_from_salary_needs_salary_structure(self):
		"""HRMS refuses Repay From Salary for an employee without a Salary Structure Assignment."""
		with_ssa = set(frappe.get_all("Salary Structure Assignment", pluck="employee"))
		other = frappe.db.get_value(
			"Employee",
			{"status": "Active", "company": self.company, "name": ("not in", list(with_ssa) or [""])},
			"name",
		)
		if not other:
			self.skipTest("Every employee has a salary structure")
		loan = frappe.new_doc("Loan")
		loan.update(
			{
				"applicant_type": "Employee",
				"applicant": other,
				"company": self.company,
				"loan_product": self.product.name,
				"loan_amount": 1000,
				"repay_from_salary": 1,
			}
		)
		self.assertRaisesRegex(frappe.ValidationError, "no Salary Structure assigned", loan.insert)
