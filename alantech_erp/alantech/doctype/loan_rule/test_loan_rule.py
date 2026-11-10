# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Loan Rule records (LR-01, ClickUp 14yr2e57ghc): naming by rule_name, saving the six
Table MultiSelect applicability tables against real masters, link validation, rename and
role permissions. Field-level validations are in test_loan_rule_validation.py.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.alantech.doctype.loan_rule.test_loan_rule

Uses the site's existing Company / Department / Branch / Designation / Employment Type /
Employee Grade / Loan Product; missing masters are created. Each test runs in a savepoint that is
rolled back, so nothing is left behind.
"""

import frappe
from frappe.tests import IntegrationTestCase

IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Company",
	"Loan Product",
	"Employment Type",
	"Employee Grade",
	"Designation",
	"Department",
	"Branch",
	"Role",
]

PREFIX = "ZZ LR01"


def company():
	return frappe.db.get_value("Company", {}, "name", order_by="creation asc")


def ensure(doctype, name_field, value, **extra):
	"""Return the master named/titled `value`, creating it if missing (name_field None = Prompt naming)."""
	existing = frappe.db.get_value(doctype, {name_field or "name": value}, "name")
	if existing:
		return existing
	doc = frappe.new_doc(doctype)
	doc.update(extra)
	if name_field:
		doc.set(name_field, value)
	else:
		doc.name = value
	return doc.insert(ignore_permissions=True).name


def masters():
	comp = company()
	return {
		"department": frappe.db.get_value("Department", {"company": comp, "is_group": 0}, "name")
		or ensure("Department", "department_name", f"{PREFIX} Dept", company=comp),
		"branch": ensure("Branch", "branch", f"{PREFIX} Branch"),
		"designation": ensure("Designation", "designation_name", f"{PREFIX} Designation"),
		"employment_type": ensure("Employment Type", "employee_type_name", f"{PREFIX} Permanent"),
		"grade": ensure("Employee Grade", None, f"{PREFIX} Grade"),
		"loan_product": frappe.db.get_value("Loan Product", {"company": comp}, "name"),
	}


def make_rule(**kw):
	doc = frappe.new_doc("Loan Rule")
	doc.update({"rule_name": f"{PREFIX} Staff Loan", "company": company()})
	doc.update(kw)
	return doc


class TestLoanRule(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("loan_rule_test")
		self.addCleanup(frappe.db.rollback, save_point="loan_rule_test")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_named_by_rule_name(self):
		doc = make_rule(rule_name=f"  {PREFIX} Grade A  ").insert()
		self.assertEqual(doc.name, f"{PREFIX} Grade A")

	def test_rule_name_unique(self):
		make_rule().insert()
		self.assertRaises(frappe.DuplicateEntryError, make_rule().insert)

	def test_company_mandatory(self):
		# a blank company is filled from the user's default company on insert, so check the meta
		field = frappe.get_meta("Loan Rule").get_field("company")
		self.assertEqual((field.fieldtype, field.options, field.reqd), ("Link", "Company", 1))

	def test_applicability_tables_saved(self):
		m = masters()
		rows = {
			"departments": [{"department": m["department"]}],
			"branches": [{"branch": m["branch"]}],
			"designations": [{"designation": m["designation"]}],
			"employment_types": [{"employment_type": m["employment_type"]}],
			"grades": [{"grade": m["grade"]}],
		}
		if m["loan_product"]:
			rows["loan_products"] = [{"loan_product": m["loan_product"]}]
		name = make_rule(**rows).insert().name

		saved = frappe.get_doc("Loan Rule", name)
		applicability = saved.get_applicability()
		self.assertEqual(applicability["departments"], {m["department"]})
		self.assertEqual(applicability["branches"], {m["branch"]})
		self.assertEqual(applicability["grades"], {m["grade"]})
		self.assertEqual(saved.get_specificity(), len(rows))
		self.assertEqual(saved.branches[0].doctype, "Loan Rule Branch")

	def test_invalid_link_rejected(self):
		doc = make_rule(branches=[{"branch": f"{PREFIX} No Such Branch"}])
		self.assertRaises(frappe.LinkValidationError, doc.insert)

	def test_rename(self):
		doc = make_rule().insert()
		new = frappe.rename_doc("Loan Rule", doc.name, f"{PREFIX} Renamed")
		self.assertTrue(frappe.db.exists("Loan Rule", new))

	def test_permissions(self):
		perms = {p.role: p for p in frappe.get_meta("Loan Rule").permissions}
		for role in ("HR Manager", "Loan Manager", "System Manager"):
			self.assertTrue(perms[role].write and perms[role].create and perms[role].delete, role)
		self.assertTrue(perms["Employee"].read)
		self.assertFalse(perms["Employee"].write or perms["Employee"].create or perms["Employee"].delete)
