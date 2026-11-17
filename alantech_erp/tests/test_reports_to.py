# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee > Reports To: managers only (setup/reports_to.py, ClickUp 14yr2e57t0m).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_reports_to

Nothing is kept: each test runs in a savepoint rolled back after it.
"""

import frappe

from alantech_erp import org_structure
from alantech_erp.setup import reports_to as rt
from alantech_erp.tests.test_employee_required import full_employee

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase


def make_user(email, roles, employee=None):
	"""The employee is linked first: HRMS drops the Employee role from a user without one."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	if employee:
		frappe.db.set_value("Employee", employee, "user_id", email)
	user = frappe.get_doc("User", email)
	user.set("roles", [{"role": role} for role in roles])
	user.save(ignore_permissions=True)
	return email


class TestReportsTo(TestCase):
	def setUp(self):
		frappe.db.savepoint("reports_to_test")
		self.addCleanup(frappe.db.rollback, save_point="reports_to_test")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.flags.alt_check_reports_to = True
		self.addCleanup(setattr, frappe.flags, "alt_check_reports_to", False)
		active = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", order_by="creation desc")
		managers = set(rt.manager_employees())
		# two active employees used as plain staff / test subjects
		self.ordinary, self.other = [e for e in active if e not in managers][:2]
		self.manager = sorted(managers)[0]

	def as_staff(self, employee, roles, tag):
		return make_user(f"_test-rt-{tag}@example.com", roles, employee)

	def new_employee(self, **changes):
		email = f"rt-{frappe.generate_hash(length=6)}@example.com"
		return full_employee(first_name="Rttest", personal_email=email, **changes)

	# --- who is a manager -------------------------------------------------
	def test_rule_off_in_other_tests_only(self):
		frappe.flags.alt_check_reports_to = False
		self.assertFalse(rt.rule_active())
		frappe.flags.in_test = False
		try:
			self.assertTrue(rt.rule_active())  # always on outside tests
		finally:
			frappe.flags.in_test = True
		frappe.flags.alt_check_reports_to = True

	def test_manager_roles(self):
		roles = rt.manager_roles()
		self.assertIn("HR Manager", roles)
		self.assertIn("Projects Manager", roles)
		self.assertIn("Leave Approver", roles)
		self.assertNotIn("System Manager", roles)
		self.assertNotIn("Employee", roles)

	def test_role_decides(self):
		for roles, expected in (
			(["Employee"], False),
			(["Employee", "System Manager"], False),  # System Manager alone does not count
			(["Employee", "Projects Manager"], True),
			(["Employee", "Leave Approver"], True),
		):
			with self.subTest(roles=roles):
				self.as_staff(self.ordinary, roles, "role")
				self.assertEqual(rt.is_manager(self.ordinary), expected)

	def test_no_user_or_disabled_user_is_not_a_manager(self):
		user = self.as_staff(self.ordinary, ["Employee", "HR Manager"], "dis")
		self.assertTrue(rt.is_manager(self.ordinary))
		frappe.db.set_value("User", user, "enabled", 0)
		self.assertFalse(rt.is_manager(self.ordinary))
		frappe.db.set_value("Employee", self.ordinary, "user_id", None)
		self.assertFalse(rt.is_manager(self.ordinary))

	# --- dropdown ----------------------------------------------------------
	def test_dropdown_lists_managers_only(self):
		rows = rt.reports_to_query("Employee", "", "name", 0, 500, [["status", "=", "Active"]])
		names = {r[0] for r in rows}
		self.assertTrue(names)
		self.assertEqual(names, set(rt.manager_employees()))
		self.assertNotIn(self.ordinary, names)

	def test_dropdown_search_and_self_excluded(self):
		name = frappe.db.get_value("Employee", self.manager, "employee_name")
		rows = rt.reports_to_query("Employee", name[:4], "name", 0, 50, [["name", "!=", self.manager]])
		self.assertNotIn(self.manager, {r[0] for r in rows})

	# --- save ----------------------------------------------------------------
	def test_ordinary_employee_refused(self):
		emp = self.new_employee(reports_to=self.ordinary)
		with self.assertRaises(rt.ReportsToNotManagerError) as ctx:
			emp.insert(ignore_permissions=True)
		self.assertIn("only a manager can be chosen", str(ctx.exception))

	def test_manager_accepted(self):
		emp = self.new_employee(reports_to=self.manager).insert(ignore_permissions=True)
		self.assertEqual(emp.reports_to, self.manager)

	def test_existing_value_kept_until_changed(self):
		frappe.db.set_value("Employee", self.other, "reports_to", self.ordinary)  # saved before the rule
		emp = frappe.get_doc("Employee", self.other)
		emp.flags.ignore_mandatory = True
		emp.save(ignore_permissions=True)  # other edits still save
		emp.reports_to = self.manager if self.manager != self.other else None
		emp.save(ignore_permissions=True)
		emp.reports_to = self.ordinary
		with self.assertRaises(rt.ReportsToNotManagerError):
			emp.save(ignore_permissions=True)

	# --- organisation structure auto-fill ------------------------------------
	def test_designation_fill_skips_holder_who_is_not_a_manager(self):
		holders = ["HR-X-1", "HR-X-2"]
		original = org_structure._active_holders
		md = rt.manager_employees(frappe.get_all(
			"Employee", filters={"designation": org_structure.TOP_DESIGNATION, "status": "Active"}, pluck="name"))
		self.assertTrue(md)

		def fake_holders(designation, doc):
			if designation == org_structure.TOP_DESIGNATION:
				return md
			return [self.ordinary]  # the parent post is held by someone without a manager role

		org_structure._active_holders = fake_holders
		self.addCleanup(setattr, org_structure, "_active_holders", original)
		designation = frappe.db.get_value("Designation", {"alt_reports_to": ["is", "set"]}, "name")
		doc = frappe._dict(designation=designation, company=None, name="", department=None, reports_to=None)
		org_structure.apply_designation_defaults(doc)
		self.assertEqual(doc.reports_to, md[0])
		self.assertNotEqual(doc.reports_to, holders[0])
