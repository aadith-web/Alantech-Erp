# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Estimation pricing: free-text Items per Sub Assembly section + Other Expenses (02-Nov change).

    bench --site <site> run-tests --doctype Estimation
"""

import frappe
from frappe.tests import IntegrationTestCase

from alantech_erp.alantech.doctype.estimation.estimation import calculate_pricing

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = ["Customer", "Opportunity", "Item", "Plant Assembly", "Sub Assembly"]


def make(contingency=0, financing=0, include_financing=0, margin=0, basis="Markup on Cost"):
	doc = frappe.new_doc("Estimation")
	doc.update({
		"contingency_pct": contingency, "financing_pct": financing, "include_financing": include_financing,
		"profit_pct": margin, "margin_basis": basis, "no_of_trains": 1,
	})
	return doc


class IntegrationTestEstimation(IntegrationTestCase):
	def test_items_and_expenses_totals(self):
		doc = make()
		doc.append("sections", {"section_title": "RO", "pricing_mode": "Included"})
		doc.append("sections", {"section_title": "Install", "pricing_mode": "Separate Line"})
		doc.append("items", {"section": "RO", "cost_head": "HP pump", "qty": 2, "unit_cost": 100, "addon_pct": 10})
		doc.append("expenses", {"section": "Install", "expense_type": "Manpower", "description": "Commissioning", "qty": 5, "rate": 40})
		doc.append("expenses", {"expense_type": "Transport", "description": "Truck to site", "qty": 1, "rate": 30})
		calculate_pricing(doc)
		self.assertEqual(doc.total_item_cost, 220)  # 200 + 10 %
		self.assertEqual(doc.manpower_cost, 200)
		self.assertEqual(doc.general_cost, 30)
		self.assertEqual(doc.total_other_expenses, 230)
		self.assertEqual(doc.total_cost, 450)
		# no margin: the prices add up to the total cost (untagged transport spread over the sections)
		self.assertAlmostEqual(doc.selling_price, 450, places=2)
		self.assertAlmostEqual(doc.sections[0].selling_price, 220 * 450 / 420, places=2)

	def test_optional_section_left_out(self):
		doc = make(contingency=10, margin=20)
		doc.append("sections", {"section_title": "Main", "pricing_mode": "Included"})
		doc.append("sections", {"section_title": "Extra", "pricing_mode": "Optional"})
		doc.append("items", {"section": "Main", "cost_head": "Skid", "qty": 1, "unit_cost": 1000})
		doc.append("expenses", {"section": "Extra", "expense_type": "Manpower", "description": "AMC", "qty": 1, "rate": 100})
		calculate_pricing(doc)
		self.assertEqual(doc.total_cost, 1000)
		self.assertEqual(doc.total_other_expenses, 0)
		self.assertAlmostEqual(doc.cost_price, 1100, places=2)
		self.assertAlmostEqual(doc.selling_price, 1320, places=2)
		self.assertAlmostEqual(doc.optional_price, 132, places=2)  # contingency + margin only

	def test_expenses_only(self):
		doc = make(margin=10)
		doc.append("expenses", {"expense_type": "Manpower", "description": "Service visit", "qty": 2, "rate": 50})
		calculate_pricing(doc)
		self.assertEqual(doc.total_cost, 100)
		self.assertAlmostEqual(doc.main_price, 110, places=2)
