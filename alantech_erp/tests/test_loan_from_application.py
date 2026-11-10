# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Loan only from an Approved Loan Application (HR-F05-x, ClickUp 14yr2e57kyk; loan_rules/loan.py,
public/js/loan_list.js): a Loan without an application, from an application that is not Approved,
for another applicant / product, above the approved amount, or a second Loan for one application is
refused; the Loan list's "Approved Applications" lists the Approved applications without a Loan.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_from_application

Data: as test_loan_permissions (two active employees, prefix ZZ-LR05, savepoint rolled back).
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, today

from alantech_erp.loan_rules import loan as loan_rule
from alantech_erp.loan_rules.loan import (
	LoanWithoutApplicationError,
	approved_applications_without_loan,
	loans_awaiting_disbursement,
)

# module import: importing the TestCase class itself would make the runner collect that suite here
from alantech_erp.tests import test_loan_permissions as lr09


class TestLoanFromApplication(IntegrationTestCase):
	set_employee = lr09.TestLoanPermissions.set_employee
	make_product = lr09.TestLoanPermissions.make_product
	make_rule = lr09.TestLoanPermissions.make_rule
	application = lr09.TestLoanPermissions.application
	raw = lr09.TestLoanPermissions.raw
	loan = lr09.TestLoanPermissions.loan
	user = lr09.TestLoanPermissions.user

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.emp = lr09.lr05.pick_employee()
		cls.other = cls.emp and frappe.db.get_value(
			"Employee", {"status": "Active", "name": ("!=", cls.emp.name), "company": cls.emp.company}, "name"
		)

	def setUp(self):
		if not (self.emp and self.other):
			self.skipTest("Needs two active employees of one company")
		frappe.set_user("Administrator")
		frappe.db.savepoint("loan_from_app")
		self.addCleanup(frappe.db.rollback, save_point="loan_from_app")
		self.addCleanup(frappe.set_user, "Administrator")
		self.today = getdate(today())
		self.company = self.emp.company
		self.counter = 0
		frappe.db.set_value("Loan Rule", {"enabled": 1}, "enabled", 0)
		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 0)
		self.product = self.make_product("PL")

	def approved(self, applicant=None, status="Approved", docstatus=1, amount=10000):
		return self.raw(
			"Loan Application",
			applicant_type="Employee",
			applicant=applicant or self.emp.name,
			company=self.company,
			loan_product=self.product,
			posting_date=self.today,
			status=status,
			docstatus=docstatus,
			loan_amount=amount,
		)

	def new_loan(self, **values):
		doc = frappe.new_doc("Loan")
		doc.update(
			{
				"applicant_type": "Employee",
				"applicant": self.emp.name,
				"company": self.company,
				"loan_product": self.product,
				"loan_amount": 10000,
				**values,
			}
		)
		return doc

	def assert_refused(self, doc, message):
		self.assertRaisesRegex(LoanWithoutApplicationError, message, loan_rule.validate, doc)

	# ---------------------------------------------------------------- server rule

	def test_manual_loan_refused_on_save(self):
		"""Add Loan without an application: the Loan doc_event stops the insert."""
		self.assertRaisesRegex(
			LoanWithoutApplicationError, "only from an Approved Loan Application", self.new_loan().insert
		)

	def test_application_must_be_approved(self):
		for status, docstatus in (("Open", 1), ("Rejected", 1), ("Open", 0), ("Approved", 2)):
			with self.subTest(status=status, docstatus=docstatus):
				app = self.approved(status=status, docstatus=docstatus)
				self.assert_refused(self.new_loan(loan_application=app), "is not Approved")

	def test_same_applicant_company_product(self):
		app = self.approved()
		other_product = self.make_product("OTH")
		self.assert_refused(self.new_loan(loan_application=app, applicant=self.other), "Applicant must be the same")
		self.assert_refused(
			self.new_loan(loan_application=app, loan_product=other_product), "Loan Product must be the same"
		)

	def test_amount_not_above_approved(self):
		app = self.approved(amount=10000)
		self.assert_refused(self.new_loan(loan_application=app, loan_amount=10001), "cannot be more than")
		loan_rule.validate(self.new_loan(loan_application=app, loan_amount=10000))  # equal: allowed
		loan_rule.validate(self.new_loan(loan_application=app, loan_amount=8000))  # lower: allowed

	def test_one_loan_per_application(self):
		app = self.approved()
		existing = self.raw(
			"Loan",
			applicant_type="Employee",
			applicant=self.emp.name,
			company=self.company,
			loan_product=self.product,
			loan_application=app,
			loan_amount=10000,
			status="Sanctioned",
			docstatus=1,
		)
		self.assert_refused(self.new_loan(loan_application=app), f"already has Loan .*{existing}")
		frappe.db.set_value("Loan", existing, "docstatus", 2)  # a cancelled Loan frees the application
		loan_rule.validate(self.new_loan(loan_application=app))

	def test_draft_loan_saved_again_is_not_checked_against_itself(self):
		app = self.approved()
		name = self.raw(
			"Loan",
			applicant_type="Employee",
			applicant=self.emp.name,
			company=self.company,
			loan_product=self.product,
			loan_application=app,
			loan_amount=10000,
			status="Sanctioned",
			docstatus=0,
		)
		loan_rule.validate(frappe.get_doc("Loan", name))

	def test_cancel_not_checked(self):
		doc = self.new_loan()
		doc.docstatus = 2
		loan_rule.validate(doc)

	# ---------------------------------------------------------------- Loan list

	def test_approved_applications_without_loan(self):
		waiting = self.approved()
		used = self.approved()
		self.raw(
			"Loan",
			applicant_type="Employee",
			applicant=self.emp.name,
			company=self.company,
			loan_product=self.product,
			loan_application=used,
			loan_amount=10000,
			status="Sanctioned",
			docstatus=1,
		)
		open_app = self.approved(status="Open")
		draft = self.approved(status="Approved", docstatus=0)
		names = [d.name for d in approved_applications_without_loan()]
		self.assertIn(waiting, names)
		for name in (used, open_app, draft):
			self.assertNotIn(name, names)
		row = next(d for d in approved_applications_without_loan() if d.name == waiting)
		self.assertEqual((row.applicant, row.loan_product, row.loan_amount), (self.emp.name, self.product, 10000))

	def test_list_respects_read_rights(self):
		"""An employee (not loan staff) sees only their own approved applications."""
		mine = self.approved(applicant=self.other)
		theirs = self.approved(applicant=self.emp.name)
		frappe.set_user(self.user("emp", "Employee"))  # linked to self.other
		names = [d.name for d in approved_applications_without_loan()]
		self.assertIn(mine, names)
		self.assertNotIn(theirs, names)

	def test_hooks_wired(self):
		from frappe import get_hooks

		self.assertIn("alantech_erp.loan_rules.loan.validate", get_hooks("doc_events")["Loan"]["validate"])
		self.assertIn("public/js/loan_list.js", get_hooks("doctype_list_js")["Loan"])
		self.assertIn("public/js/loan_disbursement_list.js", get_hooks("doctype_list_js")["Loan Disbursement"])

	# ---------------------------------------------------------------- Loan Disbursement list

	def sanctioned(self, status="Sanctioned", docstatus=1, disbursed=0, applicant=None):
		return self.raw(
			"Loan",
			applicant_type="Employee",
			applicant=applicant or self.emp.name,
			company=self.company,
			loan_product=self.product,
			loan_amount=10000,
			disbursed_amount=disbursed,
			status=status,
			docstatus=docstatus,
		)

	def test_loans_awaiting_disbursement(self):
		waiting = self.sanctioned()
		partly = self.sanctioned(status="Partially Disbursed", disbursed=4000)
		excluded = [
			self.sanctioned(docstatus=0),  # draft
			self.sanctioned(status="Disbursed", disbursed=10000),
			self.sanctioned(status="Closed", disbursed=10000),
			self.sanctioned(status="Partially Disbursed", disbursed=10000),  # nothing left
			self.sanctioned(docstatus=2),  # cancelled
		]
		rows = {d.name: d for d in loans_awaiting_disbursement()}
		self.assertEqual(rows[waiting].pending_amount, 10000)
		self.assertEqual(rows[partly].pending_amount, 6000)
		for name in excluded:
			self.assertNotIn(name, rows)

	def test_disbursement_list_respects_read_rights(self):
		mine = self.sanctioned(applicant=self.other)
		theirs = self.sanctioned()
		frappe.set_user(self.user("emp2", "Employee"))  # linked to self.other
		names = [d.name for d in loans_awaiting_disbursement()]
		self.assertIn(mine, names)
		self.assertNotIn(theirs, names)
