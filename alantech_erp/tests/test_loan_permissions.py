# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Employee Loan Rules — roles and permissions (LR-09, ClickUp 14yr2e57ghn; setup/loan_permissions.py,
loan_rules/loan_application.py): Loan Rule rights per role, Loan Eligibility report roles, HR rights
on Loan Application / Loan Product / Loan, employees limited to their own applications and loans
(list, single record, save), the server-only override stamp, and the setup re-run.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_loan_permissions

Data: one active employee without loan applications (as test_loan_rule_eligibility) and a second
active employee; test users zz.lr09.*@example.com, Loan Rules / Loan Product / applications / loans
with prefix ZZ-LR05, all in a savepoint per test that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, getdate, today

from alantech_erp.loan_rules.loan_application import CHECK_RESULT_FIELDS
from alantech_erp.setup import loan_permissions
from alantech_erp.setup.loan_application_fields import NOT_ELIGIBLE
from alantech_erp.setup.loan_permissions import (
	PERMISSIONS,
	OwnLoanApplicationOnlyError,
	execute,
	has_permission,
)

# module import: importing the TestCase class itself would make the runner collect that suite here
from alantech_erp.tests import test_loan_rule_eligibility as lr05


class TestLoanPermissions(IntegrationTestCase):
	set_employee = lr05.TestLoanRuleEligibility.set_employee
	make_product = lr05.TestLoanRuleEligibility.make_product
	make_rule = lr05.TestLoanRuleEligibility.make_rule
	application = lr05.TestLoanRuleEligibility.application
	raw = lr05.TestLoanRuleEligibility.raw
	loan = lr05.TestLoanRuleEligibility.loan

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.emp = lr05.pick_employee()
		cls.other = cls.emp and frappe.db.get_value(
			"Employee", {"status": "Active", "name": ("!=", cls.emp.name), "company": cls.emp.company}, "name"
		)

	def setUp(self):
		if not (self.emp and self.other):
			self.skipTest("Needs two active employees of one company")
		frappe.set_user("Administrator")
		frappe.db.savepoint("lr09")
		self.addCleanup(frappe.db.rollback, save_point="lr09")
		self.addCleanup(frappe.set_user, "Administrator")

		self.today = getdate(today())
		self.company = self.emp.company
		self.counter = 0
		frappe.db.set_value("Loan Rule", {"enabled": 1}, "enabled", 0)
		frappe.db.set_single_value("Lending Settings", "require_loan_rule", 0)
		self.set_employee(
			status="Active",
			date_of_joining=add_months(self.today, -24),
			final_confirmation_date=add_months(self.today, -18),
			date_of_birth=add_months(self.today, -30 * 12),
			relieving_date=None,
			resignation_letter_date=None,
		)
		self.product = self.make_product("PL")

	def user(self, key, *roles, employee=None):
		"""Roles are added after the Employee link: ERPNext's validate_employee_role removes the
		Employee role from a user no Employee record points to. A user given the Employee role is
		linked to the second employee unless employee says otherwise."""
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"zz.lr09.{key}@example.com",
				"first_name": f"ZZ LR09 {key}",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		employee = employee or ("Employee" in roles and self.other)
		if employee:
			frappe.db.set_value("Employee", employee, "user_id", user.name, update_modified=False)
		user.add_roles(*roles)
		self.assertTrue(set(roles) <= set(frappe.get_roles(user.name)))
		return user.name

	def raw_application(self, applicant):
		return self.raw(
			"Loan Application",
			applicant_type="Employee",
			applicant=applicant,
			company=self.company,
			loan_product=self.product,
			posting_date=self.today,
			status="Open",
			docstatus=0,
			loan_amount=1000,
		)

	# ---------------------------------------------------------------- Loan Rule and report

	def test_loan_rule_rights(self):
		hr_manager = self.user("hrm", "HR Manager")
		loan_manager = self.user("lm", "Loan Manager")
		employee = self.user("emp", "Employee")
		for user in (hr_manager, loan_manager):
			for ptype in ("read", "write", "create", "delete", "report"):
				with self.subTest(user=user, ptype=ptype):
					self.assertTrue(frappe.has_permission("Loan Rule", ptype, user=user))
		self.assertTrue(frappe.has_permission("Loan Rule", "read", user=employee))
		for ptype in ("write", "create", "delete", "report"):
			with self.subTest(user=employee, ptype=ptype):
				self.assertFalse(frappe.has_permission("Loan Rule", ptype, user=employee))

	def test_report_roles(self):
		report = frappe.get_doc("Report", "Loan Eligibility")
		self.assertEqual({r.role for r in report.roles}, {"System Manager", "HR Manager", "Loan Manager"})
		self.assertEqual(report.ref_doctype, "Loan Rule")

	# ---------------------------------------------------------------- Lending doctypes

	def test_hr_rights_on_loan_application(self):
		hr_manager = self.user("hrm", "HR Manager")
		hr_user = self.user("hru", "HR User")
		for ptype in ("read", "write", "create", "submit", "cancel", "amend"):
			with self.subTest(role="HR Manager", ptype=ptype):
				self.assertTrue(frappe.has_permission("Loan Application", ptype, user=hr_manager))
		for ptype in ("read", "write", "create"):
			with self.subTest(role="HR User", ptype=ptype):
				self.assertTrue(frappe.has_permission("Loan Application", ptype, user=hr_user))
		for ptype in ("submit", "cancel", "delete"):
			with self.subTest(role="HR User", ptype=ptype):
				self.assertFalse(frappe.has_permission("Loan Application", ptype, user=hr_user))
		# level 1 (status / approval fields): HR Manager writes, HR User only reads
		self.assertEqual(
			frappe.db.get_value(
				"Custom DocPerm",
				{"parent": "Loan Application", "role": "HR Manager", "permlevel": 1},
				["read", "write"],
			),
			(1, 1),
		)
		self.assertEqual(
			frappe.db.get_value(
				"Custom DocPerm", {"parent": "Loan Application", "role": "HR User", "permlevel": 1}, ["read", "write"]
			),
			(1, 0),
		)

	def test_loan_product_and_loan_read(self):
		for role in ("HR Manager", "HR User", "Employee"):
			with self.subTest(role=role):
				user = self.user(role.lower().replace(" ", ""), role)
				self.assertTrue(frappe.has_permission("Loan Product", "read", user=user))
				# an HR Manager is also a Loan Manager (setup/loan_roles.py) and sets up Loan Products
				self.assertEqual(frappe.has_permission("Loan Product", "write", user=user), role == "HR Manager")
				self.assertTrue(frappe.has_permission("Loan", "read", user=user))
				# HR Manager creates and sanctions Loans; HR User and Employee only read them
				self.assertEqual(frappe.has_permission("Loan", "write", user=user), role == "HR Manager")

	def test_loan_application_form_settings_readable(self):
		"""Lending's form script reads Loan Origination Settings.employee_loans on every load."""
		for role in ("HR Manager", "HR User", "Employee", "Loan Manager"):
			with self.subTest(role=role):
				frappe.set_user("Administrator")
				user = self.user(role.lower().replace(" ", ""), role)
				self.assertTrue(frappe.has_permission("Loan Origination Settings", "read", user=user))
				self.assertFalse(frappe.has_permission("Loan Origination Settings", "write", user=user))
				frappe.set_user(user)
				frappe.client.get_single_value("Loan Origination Settings", "employee_loans")  # no error

	def test_hr_roles_read_every_master_the_loan_form_links_to(self):
		"""The Loan form validates and fetches its Link fields; each target must be readable, or the
		form stops with 'Insufficient Permission for <doctype>'."""
		targets = {
			df.options
			for df in frappe.get_meta("Loan").fields
			if df.fieldtype == "Link" and df.options and df.options != "User"
		}
		self.assertTrue(set(loan_permissions.LOAN_MASTERS) <= targets)
		for role in ("HR Manager", "HR User"):
			user = self.user(role.lower().replace(" ", ""), role)
			for doctype in sorted(targets):
				with self.subTest(role=role, doctype=doctype):
					self.assertTrue(
						frappe.has_permission(doctype, "read", user=user)
						or frappe.has_permission(doctype, "select", user=user)
					)
			frappe.set_user(user)
			for doctype in loan_permissions.LOAN_MASTERS:
				frappe.get_list(doctype, limit=1)  # the link search / validation runs the same check
			frappe.set_user("Administrator")

	def test_hr_manager_creates_loan_from_approved_application(self):
		"""Create > Loan on an Approved application, then submit the Loan, as an HR Manager."""
		from lending.loan_management.doctype.loan_application.loan_application import create_loan

		hr_manager = self.user("hrm", "HR Manager")
		for ptype in ("read", "write", "create", "submit", "cancel", "amend"):
			with self.subTest(ptype=ptype):
				self.assertTrue(frappe.has_permission("Loan", ptype, user=hr_manager))
		self.assertFalse(frappe.has_permission("Loan", "create", user=self.user("hru", "HR User")))

		# the Loan takes its accounts from the Loan Product
		def account(**filters):
			return frappe.db.get_value("Account", dict(company=self.company, is_group=0, **filters), "name")

		accounts = {
			"loan_account": account(root_type="Asset", account_type=("not in", ["Bank", "Cash"])),
			"payment_account": account(account_type=("in", ["Bank", "Cash"])),
			"interest_income_account": account(root_type="Income"),
			"penalty_income_account": account(root_type="Income"),
		}
		if not all(accounts.values()):
			self.skipTest("Needs Asset, Bank / Cash and Income accounts for the company")
		product = self.product
		frappe.db.set_value("Loan Product", product, accounts)
		self.make_rule()
		app = self.application(
			loan_product=product, loan_amount=10000, repayment_method="Repay Over Number of Periods",
			repayment_periods=12,
		).insert()
		app.submit()
		app.status = "Approved"
		app.save()

		frappe.set_user(hr_manager)
		loan = create_loan(app.name)
		self.assertEqual(loan.loan_application, app.name)
		self.assertEqual(loan.applicant, self.emp.name)
		loan.insert()
		loan.submit()
		self.assertEqual(loan.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Loan", loan.name, "owner"), hr_manager)

	# ---------------------------------------------------------------- own records only

	def test_employee_sees_only_own_applications_and_loans(self):
		mine = self.raw_application(self.emp.name)
		theirs = self.raw_application(self.other)
		my_loan = self.loan()
		their_loan = self.raw(
			"Loan",
			applicant_type="Employee",
			applicant=self.other,
			company=self.company,
			loan_product=self.product,
			posting_date=self.today,
			status="Disbursed",
			loan_amount=10000,
			docstatus=1,
		)
		user = self.user("emp", "Employee", employee=self.emp.name)
		frappe.set_user(user)
		apps = frappe.get_list("Loan Application", pluck="name")
		self.assertIn(mine, apps)
		self.assertNotIn(theirs, apps)
		loans = frappe.get_list("Loan", pluck="name")
		self.assertIn(my_loan, loans)
		self.assertNotIn(their_loan, loans)
		self.assertTrue(frappe.has_permission("Loan Application", "read", doc=mine, user=user))
		self.assertFalse(frappe.has_permission("Loan Application", "read", doc=theirs, user=user))
		self.assertFalse(frappe.has_permission("Loan Application", "write", doc=theirs, user=user))
		self.assertFalse(frappe.has_permission("Loan", "read", doc=their_loan, user=user))

	def test_user_without_employee_record_sees_none(self):
		"""Such a user cannot hold the Employee role (ERPNext removes it), so no Loan Application
		access at all; the query condition still matches nothing should another role grant it."""
		user = self.user("nolink", "Loan Officer")  # a Lending role that is not loan staff here
		self.assertEqual(loan_permissions.loan_application_query_conditions(user), "1=0")
		self.assertEqual(loan_permissions.loan_query_conditions(user), "1=0")
		doc = frappe.get_doc("Loan Application", self.raw_application(self.emp.name))
		self.assertFalse(has_permission(doc, "read", user=user))

	def test_staff_see_every_application(self):
		mine = self.raw_application(self.emp.name)
		theirs = self.raw_application(self.other)
		for role in ("HR Manager", "HR User", "Loan Manager"):
			with self.subTest(role=role):
				frappe.set_user("Administrator")
				frappe.set_user(self.user(role.lower().replace(" ", ""), role))
				apps = frappe.get_list("Loan Application", pluck="name")
				self.assertIn(mine, apps)
				self.assertIn(theirs, apps)

	def test_employee_applies_only_for_themselves(self):
		self.make_rule()
		user = self.user("emp", "Employee", employee=self.emp.name)
		frappe.set_user(user)
		with self.assertRaises(OwnLoanApplicationOnlyError) as ctx:
			self.application(applicant=self.other).insert(ignore_permissions=True)
		self.assertIn("only for yourself", str(ctx.exception))
		app = self.application().insert(ignore_permissions=True)  # own application
		self.assertEqual(app.applicant, self.emp.name)

	def test_hr_user_applies_for_any_employee(self):
		self.make_rule()
		frappe.set_user(self.user("hru", "HR User"))
		app = self.application().insert(ignore_permissions=True)
		self.assertEqual(app.applicant, self.emp.name)

	def test_new_empty_document_allowed(self):
		"""has_permission lets the form open a new application; the applicant is checked on save."""
		user = self.user("emp", "Employee", employee=self.emp.name)
		self.assertTrue(has_permission(frappe.new_doc("Loan Application"), "create", user=user))

	# ---------------------------------------------------------------- override stamp (server only)

	def test_override_stamp_cannot_be_written_without_override(self):
		self.make_rule(min_service_months=36, enforcement="Warn")
		app = self.application(overridden_by="Administrator", override_reason="forged").insert()
		self.assertEqual(app.eligibility_status, NOT_ELIGIBLE)
		self.assertFalse(app.overridden_by)
		self.assertFalse(app.overridden_on)
		self.assertFalse(app.override_reason)

	def test_override_stamp_kept_after_submit(self):
		self.make_rule(min_service_months=36, allow_override=1, override_role="HR Manager")
		app = self.application(rule_override=1, override_reason="Medical emergency").insert()
		app.submit()
		stamped = {f: app.get(f) for f in ("overridden_by", "overridden_on", "override_reason")}
		self.assertEqual(stamped["overridden_by"], "Administrator")
		app.reload()
		app.update({"overridden_by": "Guest", "override_reason": "changed later"})
		app.save()
		app.reload()
		for field, value in stamped.items():
			with self.subTest(field=field):
				self.assertEqual(str(app.get(field)), str(value))
		self.assertTrue({"overridden_by", "overridden_on", "override_reason"} <= set(CHECK_RESULT_FIELDS))

	# ---------------------------------------------------------------- setup

	def test_setup_is_create_only_and_idempotent(self):
		execute()
		execute()
		for doctype, role, permlevel in PERMISSIONS:
			with self.subTest(doctype=doctype, role=role, permlevel=permlevel):
				self.assertEqual(
					frappe.db.count(
						"Custom DocPerm",
						{"parent": doctype, "role": role, "permlevel": permlevel, "if_owner": 0},
					),
					1,
				)
		# a right HR removed in Role Permissions Manager stays removed
		key = {"parent": "Loan Application", "role": "HR User", "permlevel": 0, "if_owner": 0}
		frappe.db.set_value("Custom DocPerm", key, "export", 0)
		execute()
		self.assertEqual(frappe.db.get_value("Custom DocPerm", key, "export"), 0)

	def test_staff_roles(self):
		self.assertTrue(
			{"HR Manager", "HR User", "Loan Manager", "System Manager"} <= loan_permissions.LOAN_STAFF_ROLES
		)
		self.assertNotIn("Employee", loan_permissions.LOAN_STAFF_ROLES)
