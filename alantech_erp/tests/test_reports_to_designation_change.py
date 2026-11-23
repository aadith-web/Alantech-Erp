# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Reports To follows the Designation, also when already filled (org_structure.apply_designation_defaults).

ClickUp: https://app.clickup.com/t/14yr2e58fq1 - "Reports To field not updating on Designation
change if already auto-filled". Organisation chart: AIS-MS-TP-01 (Organisation Structure, 12 Oct
2026), kept as the Designations' Reports To posts.

Covered:
- Every reporting line of the chart is the Reports To post of its designation.
- Designation changed on a saved employee: Reports To and Department follow the new designation;
  kept when changed by hand in the same save, or when the new designation has no Reports To post;
  cleared on a promotion to Managing Director.
- A new employee with an empty Reports To still gets it from the designation.
- designation_defaults (the form's call): the new designation's values, is_top for the MD.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_reports_to_designation_change

Data: each test runs in a savepoint that is rolled back. Who holds which post is patched
(org_structure.designation_reports_to), so the tests do not depend on the site's employees.
"""

from unittest.mock import patch

import frappe

from alantech_erp import org_structure

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11R"

# AIS-MS-TP-01: designation -> the post it reports to. Where the PDF shows a post twice, the Designation
# setup keeps one: Proposal Engineer under the Managing Director (management page; the sales page puts
# it under Sales Manager Kerala) and Service Engineer under the Aftersales Co-ordinator (aftersales page;
# the sales page puts it under Sales Manager Kerala). The PDF's "Sales Head" is the Sales Director post.
CHART = {
	# management team
	"Finance Manager": "Managing Director",
	"Proposal Engineer": "Managing Director",
	"Sales Director": "Managing Director",
	"HR Manager": "Managing Director",
	"Operations Manager": "Managing Director",
	"Marketing Manager": "Managing Director",
	"HR Executive": "HR Manager",
	"Marketing Executive": "Marketing Manager",
	# finance & purchase
	"Internal Auditor": "Finance Manager",
	"Accounts Head": "Finance Manager",
	"Purchase Manager": "Finance Manager",
	"Audit Executive": "Internal Auditor",
	"Accounts Executive": "Accounts Head",
	"Purchase Executive": "Purchase Manager",
	# sales
	"Sales Manager": "Sales Director",
	"Sales Engineer": "Sales Manager",
	"Jr. Service Engineer": "Service Engineer",
	# operations
	"Production Manager": "Operations Manager",
	"Design Head": "Operations Manager",
	"Process Design Engineer": "Operations Manager",
	"Aftersales Coordinator": "Operations Manager",
	"Sr. Automation Engineer": "Operations Manager",
	"Quality Controller": "Operations Manager",
	"Design Engineer": "Design Head",
	"Jr. Process Design Engineer": "Process Design Engineer",
	"Automation Engineer": "Sr. Automation Engineer",
	"Jr. Quality Controller": "Quality Controller",
	# production
	"Production Supervisor": "Production Manager",
	"Electrical Head": "Production Manager",
	"Electrical Engineer": "Production Manager",
	"Store Keeper": "Production Manager",
	"Logistics Executive": "Production Manager",
	"Fabricator": "Production Supervisor",
	"Machinist": "Production Supervisor",
	"Turner": "Production Supervisor",
	"Welder": "Production Supervisor",
	"Fitter": "Production Supervisor",
	"Helper": "Production Supervisor",
	"Electrician": "Electrical Head",
	"Store Assistant": "Store Keeper",
	# aftersales
	"Process Engineer": "Aftersales Coordinator",
	"Service Engineer": "Aftersales Coordinator",
	"Jr. Process Engineer": "Process Engineer",
}

# designation -> its Reports To in these tests (an employee made in setUp)
POSTS = ("Accounts Executive", "Purchase Executive", "Welder")


class TestReportsToDesignationChange(TestCase):
	def setUp(self):
		frappe.db.savepoint("p11r")
		self.addCleanup(frappe.db.rollback, save_point="p11r")
		# managers stand in for the holders of each post; the manager-only rule is not under test
		self.managers = {post: self.employee(f"Mgr {post}") for post in POSTS}
		patcher = patch.object(
			org_structure, "designation_reports_to", side_effect=lambda doc: self.managers.get(doc.designation)
		)
		patcher.start()
		self.addCleanup(patcher.stop)
		for target in ("alantech_erp.setup.reports_to.rule_active",):
			p = patch(target, return_value=False)
			p.start()
			self.addCleanup(p.stop)

	def employee(self, tag, designation=None, reports_to=None):
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} {tag}",
				"company": COMPANY,
				"gender": "Male",
				"date_of_birth": "1990-01-15",
				"date_of_joining": "2024-01-05",
				"status": "Active",
				"designation": designation,
				"reports_to": reports_to,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def change(self, name, **values):
		doc = frappe.get_doc("Employee", name)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return frappe.db.get_value("Employee", name, ["designation", "reports_to", "department"], as_dict=True)

	def test_chart_is_the_designation_setup(self):
		posts = dict(frappe.get_all("Designation", fields=["name", "alt_reports_to"], as_list=True))
		wrong = {d: (posts.get(d), parent) for d, parent in CHART.items() if posts.get(d) != parent}
		self.assertEqual(wrong, {}, "designation: (Reports To post on the site, post in the chart)")

	def test_new_employee_gets_reports_to(self):
		emp = self.employee("New", designation="Accounts Executive")
		self.assertEqual(frappe.db.get_value("Employee", emp, "reports_to"), self.managers["Accounts Executive"])

	def test_reports_to_follows_designation_change(self):
		emp = self.employee("Change", designation="Accounts Executive")
		after = self.change(emp, designation="Purchase Executive")
		self.assertEqual(after.reports_to, self.managers["Purchase Executive"])
		after = self.change(emp, designation="Welder")
		self.assertEqual(after.reports_to, self.managers["Welder"])

	def test_department_follows_when_untouched(self):
		emp = self.employee("Dept", designation="Accounts Executive")
		before = frappe.db.get_value("Employee", emp, "department")
		after = self.change(emp, designation="Purchase Executive")
		expected = org_structure.designation_department("Purchase Executive", COMPANY)
		if expected:
			self.assertEqual(after.department, expected)
		else:
			self.assertEqual(after.department, before)

	def test_hand_change_in_same_save_kept(self):
		emp = self.employee("Hand", designation="Accounts Executive")
		chosen = self.managers["Welder"]
		after = self.change(emp, designation="Purchase Executive", reports_to=chosen)
		self.assertEqual(after.reports_to, chosen)

	def test_designation_without_rule_keeps_reports_to(self):
		emp = self.employee("No Rule", designation="Accounts Executive")
		unmapped = frappe.db.get_value("Designation", {"alt_reports_to": ["is", "not set"],
			"name": ["!=", org_structure.TOP_DESIGNATION]}, "name")
		if not unmapped:
			self.skipTest("every designation has a Reports To post")
		after = self.change(emp, designation=unmapped)
		self.assertEqual(after.reports_to, self.managers["Accounts Executive"])

	def test_promotion_to_managing_director_clears_reports_to(self):
		emp = self.employee("Promoted", designation="Accounts Executive")
		after = self.change(emp, designation=org_structure.TOP_DESIGNATION)
		self.assertIsNone(after.reports_to)

	def test_designation_defaults_for_the_form(self):
		r = org_structure.designation_defaults("Purchase Executive", COMPANY)
		self.assertEqual(r["reports_to"], self.managers["Purchase Executive"])
		self.assertFalse(r["is_top"])
		r = org_structure.designation_defaults(org_structure.TOP_DESIGNATION, COMPANY)
		self.assertEqual((r["reports_to"], r["is_top"]), (None, True))
