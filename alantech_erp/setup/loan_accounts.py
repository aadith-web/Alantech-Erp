# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Loan Management flow (HR-F05-x): ledgers and Company settings the employee loan flow needs.

ClickUp: https://app.clickup.com/t/14yr2e57kyk (parent HR-F05 14yr2e56cah)

Lending posts the disbursement, the monthly interest accrual / demand, the salary-slip repayment and
write-offs to the accounts on the Loan Product, and refuses to run without them; it also needs the
Company's Loan Accrual Frequency before a salary slip with a loan EMI can be made.

    execute()  after_migrate, for every company that has a Loan Product. Create-only:
      - ledgers (created when the company has none with that name):
            Employee Loans                 Asset, under Loans and Advances (Assets); account type
                                           Payable, so it can carry the Employee as party (ERPNext
                                           pairs the Employee party type with Payable accounts;
                                           Lending posts the loan account with the applicant)
            Employee Loan Interest Accrued Asset, under Loans and Advances (Assets)
            Interest on Employee Loans     Income, under Indirect Income
            Employee Loan Write Off        Expense, under Indirect Expenses
            Employee Loan Refundable       Liability, under Current Liabilities, account type
                                           Payable (Security Deposit / Customer Refund accounts:
                                           unused by the employee flow, but Lending requires them
                                           once Enable Loan Accounting is on)
      - Loan Product: only EMPTY account fields are filled (FIELD_LEDGER); disbursement and
        repayment use the Company's default bank account, else its default cash account. Fields
        used only by lending businesses and not required by Lending (subsidy, suspense) stay empty.
      - Company: Loan Accrual Frequency = Monthly (payroll is monthly) and Enable Loan Accounting =
        on, set once, only while Loan Accrual Frequency is empty.
    loan_product_before_insert(doc)  Loan Product doc_event: a new product gets the same
                                defaults for every account left blank (before_insert runs before
                                LoanProduct.before_validate, which requires them when loan
                                accounting is on).

The accounts team can rename the ledgers or point the products elsewhere; nothing is overwritten.
"""

import frappe

LOAN, ACCRUED, INCOME, WRITE_OFF, REFUNDABLE, BANK = "loan", "accrued", "income", "write_off", "refundable", "bank"

# key: (account name, parent account name, account type)
LEDGERS = {
	LOAN: ("Employee Loans", "Loans and Advances (Assets)", "Payable"),
	ACCRUED: ("Employee Loan Interest Accrued", "Loans and Advances (Assets)", ""),
	INCOME: ("Interest on Employee Loans", "Indirect Income", ""),
	WRITE_OFF: ("Employee Loan Write Off", "Indirect Expenses", ""),
	REFUNDABLE: ("Employee Loan Refundable", "Current Liabilities", "Payable"),
}

FIELD_LEDGER = {
	"loan_account": LOAN,
	"disbursement_account": BANK,
	"payment_account": BANK,
	"interest_accrued_account": ACCRUED,
	"interest_receivable_account": ACCRUED,
	"penalty_accrued_account": ACCRUED,
	"penalty_receivable_account": ACCRUED,
	"additional_interest_accrued": ACCRUED,
	"additional_interest_receivable": ACCRUED,
	"interest_income_account": INCOME,
	"penalty_income_account": INCOME,
	"additional_interest_income": INCOME,
	"broken_period_interest_recovery_account": INCOME,
	"write_off_recovery_account": INCOME,
	"interest_waiver_account": WRITE_OFF,
	"penalty_waiver_account": WRITE_OFF,
	"additional_interest_waiver": WRITE_OFF,
	"write_off_account": WRITE_OFF,
	# not used by the employee flow, but Lending requires them once loan accounting is on
	"security_deposit_account": REFUNDABLE,
	"customer_refund_account": REFUNDABLE,
}

COMPANY_DEFAULTS = {"loan_accrual_frequency": "Monthly", "enable_loan_accounting": 1}


def execute():
	if not frappe.db.exists("DocType", "Loan Product"):
		return  # Lending not installed
	companies = set(frappe.get_all("Loan Product", pluck="company")) - {None, ""}
	for company in sorted(companies):
		set_company_defaults(company)
		for product in frappe.get_all("Loan Product", filters={"company": company}, pluck="name"):
			values = missing_account_values(frappe.get_doc("Loan Product", product))
			if values:
				frappe.db.set_value("Loan Product", product, values)


def loan_product_before_insert(doc, method=None):
	if doc.company:
		doc.update(missing_account_values(doc))


def missing_account_values(product):
	"""{field: account} for the product's empty account fields."""
	empty = [f for f in FIELD_LEDGER if product.meta.has_field(f) and not product.get(f)]
	if not empty or not product.company:
		return {}
	accounts = {key: ledger(product.company, key) for key in {FIELD_LEDGER[f] for f in empty}}
	return {f: accounts[FIELD_LEDGER[f]] for f in empty if accounts[FIELD_LEDGER[f]]}


def ledger(company, key):
	if key == BANK:
		return frappe.get_cached_value("Company", company, "default_bank_account") or frappe.get_cached_value(
			"Company", company, "default_cash_account"
		)
	account_name, parent_name, account_type = LEDGERS[key]
	existing = frappe.db.get_value("Account", {"company": company, "account_name": account_name}, "name")
	if existing:
		return existing
	parent = frappe.db.get_value(
		"Account", {"company": company, "account_name": parent_name, "is_group": 1}, "name"
	)
	if not parent:
		return None  # a chart without that group: left for the accounts team
	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent,
			"company": company,
			"account_type": account_type,
			"is_group": 0,
		}
	)
	account.flags.ignore_permissions = True
	return account.insert().name


def set_company_defaults(company):
	if not frappe.get_meta("Company").has_field("loan_accrual_frequency"):
		return
	if frappe.db.get_value("Company", company, "loan_accrual_frequency"):
		return  # already set up (by us or by hand): never overwritten
	frappe.db.set_value("Company", company, COMPANY_DEFAULTS)
