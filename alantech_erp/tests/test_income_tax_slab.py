# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Income Tax Slab filled on Salary Structure Assignment (setup/income_tax_slab.py).

ClickUp: https://app.clickup.com/t/14yr2e589ev (parent https://app.clickup.com/t/14yr2e586v0)

Covered:
- The slab in force on the From Date: Effective From on or before it, the latest of several;
  disabled / draft / other company's slabs are not picked.
- Filled on save when empty; a slab chosen by hand is kept; a slab the hook picked follows a
  changed From Date on the draft; none applies: blank and a message.
- Filled before HRMS's own check, so a structure with a tax component saves without a slab typed in.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_income_tax_slab

Data: test slabs are dated 2031-2033 so the site's slabs never match first; every test runs in a
savepoint that is rolled back.
"""

import frappe
from frappe.utils import add_months, getdate

from alantech_erp.setup.default_salary_structure import STRUCTURE_NAME
from alantech_erp.setup.income_tax_slab import get_applicable_slab

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

COMPANY = "Alantech Industries India Pvt Ltd"
PREFIX = "TEST-P11T"


class TestIncomeTaxSlab(TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("p11t")
		self.addCleanup(frappe.db.rollback, save_point="p11t")
		self.s2031 = self.slab("2031-04-01")
		self.s2032 = self.slab("2032-04-01")
		self.s2033_disabled = self.slab("2033-01-01", disabled=1)
		self.s2033_draft = self.slab("2033-02-01", submit=False)
		# another company's slab (its currency is fetched from its company, so a currency mismatch
		# cannot be made for the same company)
		self.other_company = frappe.db.get_value("Company", {"name": ["!=", COMPANY]}, "name")
		self.s2033_other = self.slab("2033-03-01", company=self.other_company) if self.other_company else None
		self.employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"{PREFIX} Slab",
				"company": COMPANY,
				"gender": "Male",
				"date_of_birth": "1990-01-15",
				"date_of_joining": "2024-01-05",
				"status": "Active",
			}
		).insert(ignore_permissions=True).name

	def slab(self, effective_from, disabled=0, submit=True, company=COMPANY):
		name = f"{PREFIX} {effective_from}{' off' if disabled else ''}{' other' if company != COMPANY else ''}"
		doc = frappe.get_doc(
			{
				"doctype": "Income Tax Slab",
				"__newname": name,
				"effective_from": effective_from,
				"company": company,
				"disabled": disabled,
				"slabs": [{"from_amount": 0, "to_amount": 0, "percent_deduction": 0}],
			}
		)
		doc.insert(ignore_permissions=True)
		if submit:
			doc.submit()
		return doc.name

	def assignment(self, from_date, slab=None):
		doc = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": self.employee,
				"salary_structure": STRUCTURE_NAME,
				"company": COMPANY,
				"from_date": from_date,
				"base": 30000,
				"currency": "INR",
				"income_tax_slab": slab,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc

	def test_slab_in_force_on_the_date(self):
		cases = {
			"2031-03-31": None,  # before every test slab: the site's own latest slab
			"2031-04-01": self.s2031,
			"2032-03-31": self.s2031,
			"2032-04-01": self.s2032,
			"2034-06-30": self.s2032,  # disabled, draft and other company's slabs of 2033 are skipped
		}
		for day, expected in cases.items():
			with self.subTest(day=day):
				slab = get_applicable_slab(day, COMPANY, "INR")
				if expected:
					self.assertEqual(slab, expected)
				else:
					self.assertNotIn(slab, {self.s2031, self.s2032})
		if self.s2033_other:
			currency = frappe.db.get_value("Company", self.other_company, "default_currency")
			self.assertEqual(get_applicable_slab("2034-06-30", self.other_company, currency), self.s2033_other)

	def test_filled_on_save(self):
		doc = self.assignment("2032-05-01")
		self.assertEqual(doc.income_tax_slab, self.s2032)

	def test_hand_choice_kept(self):
		doc = self.assignment("2032-05-01", slab=self.s2031)
		self.assertEqual(doc.income_tax_slab, self.s2031)
		doc.from_date = "2032-06-01"
		doc.save()
		self.assertEqual(doc.income_tax_slab, self.s2031)

	def test_auto_slab_follows_changed_from_date(self):
		doc = self.assignment("2032-05-01")
		self.assertEqual(doc.income_tax_slab, self.s2032)
		doc.from_date = "2031-10-01"
		doc.save()
		self.assertEqual(doc.income_tax_slab, self.s2031)

	def test_no_slab_message(self):
		frappe.db.set_value("Income Tax Slab", {"docstatus": 1}, "disabled", 1)  # none applies now
		frappe.clear_messages()
		doc = self.assignment("2032-05-01")
		self.assertFalse(doc.income_tax_slab)
		messages = " ".join(str(m) for m in frappe.get_message_log())
		self.assertIn("No Income Tax Slab applies", messages)
		frappe.clear_messages()

	def test_structure_with_tax_component_needs_no_typed_slab(self):
		"""HRMS refuses an empty slab when the structure has a tax component; the hook runs first."""
		component = frappe.db.get_value("Salary Component", {"variable_based_on_taxable_salary": 1}, "name")
		if not component and frappe.db.exists("Salary Component", "Income Tax"):
			# rolled back with the test's savepoint
			frappe.db.set_value("Salary Component", "Income Tax", "variable_based_on_taxable_salary", 1)
			component = "Income Tax"
		if not component:
			self.skipTest("no income tax component on this site")
		structure = frappe.copy_doc(frappe.get_doc("Salary Structure", STRUCTURE_NAME))
		# set(), not attribute access: inside a class `structure.__newname` is name-mangled
		structure.set("__newname", f"{PREFIX} Taxed Structure")
		structure.append("deductions", {"salary_component": component, "abbr": frappe.db.get_value(
			"Salary Component", component, "salary_component_abbr")})
		structure.insert(ignore_permissions=True)
		structure.submit()
		doc = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": self.employee,
				"salary_structure": structure.name,
				"company": COMPANY,
				"from_date": add_months(getdate("2032-04-01"), 1),
				"base": 30000,
				"currency": "INR",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		self.assertEqual(doc.income_tax_slab, self.s2032)

	def test_popup_shows_the_slab_that_is_saved(self):
		"""Create / Edit popups preview the slab; View shows the saved one (same rule)."""
		from alantech_erp.setup.income_tax_slab import get_slab_for_popup
		from alantech_erp.setup.salary_structure_view import get_salary_structure_view

		self.assertEqual(get_slab_for_popup("2032-05-01", COMPANY), self.s2032)
		self.assertEqual(get_slab_for_popup("2031-06-01", COMPANY), self.s2031)
		doc = self.assignment("2032-05-01")
		doc.submit()
		from unittest.mock import patch

		with patch("alantech_erp.setup.salary_structure_button.today", return_value="2032-06-01"):
			view = get_salary_structure_view(self.employee)
		self.assertEqual(view["income_tax_slab"], get_slab_for_popup("2032-05-01", COMPANY))
