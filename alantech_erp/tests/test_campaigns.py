# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Campaigns against the database (CRM C24, C36; alantech_erp/sales/campaign.py, Campaign ROI).

Run:
    bench --site <site> run-tests --module alantech_erp.tests.test_campaigns

Leads, Quotations and Sales Orders are written straight to the database (their CRM validations are
tested elsewhere); everything is rolled back after each test.
"""

import frappe
from frappe.utils import add_days, flt, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.sales import campaign as c


class CampaignCase(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		if not cls.company:
			raise Exception("No Company on the site: finish the setup wizard first")

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------- builders
	def campaign(self, name, parent=None, budget=0, costs=()):
		doc = frappe.get_doc(
			{
				"doctype": "Campaign",
				"campaign_name": name,
				c.COMPANY_FIELD: self.company,
				c.PARENT_FIELD: parent,
				c.BUDGET_FIELD: budget,
				c.COSTS_FIELD: [
					{"posting_date": today(), "cost_type": "Advertising", "amount": amount} for amount in costs
				],
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def raw(self, doctype, values, docstatus=0):
		doc = frappe.get_doc({"doctype": doctype, **values})
		doc.name = frappe.generate_hash(length=10)
		doc.docstatus = docstatus
		doc.db_insert()
		return doc

	def order(self, utm, amount, docstatus=1):
		return self.raw(
			"Sales Order",
			{
				"customer": "_x",
				"company": self.company,
				"transaction_date": today(),
				"delivery_date": today(),
				c.UTM_FIELD: utm,
				"base_net_total": amount,
				"net_total": amount,
			},
			docstatus,
		)


class TestCampaignRecord(CampaignCase):
	def test_mirror_and_defaults(self):
		doc = self.campaign("TEST-CMP Expo")
		self.assertEqual(doc.get(c.OWNER_FIELD), "Administrator")
		self.assertEqual(doc.get(c.STATUS_FIELD), "Planned")
		self.assertTrue(c.utm_of(doc.name))
		self.assertEqual(c.campaign_of(c.utm_of(doc.name)), doc.name)

	def test_actual_cost_income_roi(self):
		doc = self.campaign("TEST-CMP Mailer", budget=1000, costs=(400, 600))
		self.assertEqual(flt(doc.get(c.ACTUAL_COST_FIELD)), 1000)
		self.order(c.utm_of(doc.name), 3000)
		self.order(c.utm_of(doc.name), 5000, docstatus=2)  # cancelled: not income
		self.order(c.utm_of(doc.name), 7000, docstatus=0)  # draft: not income
		c.refresh_results(doc.name)
		income, roi = frappe.db.get_value("Campaign", doc.name, [c.INCOME_FIELD, c.ROI_FIELD])
		self.assertEqual(flt(income), 3000)
		self.assertEqual(flt(roi), 200)  # (3000 - 1000) / 1000

	def test_cost_must_be_positive(self):
		with self.assertRaises(frappe.ValidationError):
			self.campaign("TEST-CMP Bad Cost", costs=(0,))

	def test_child_campaign_loop_blocked(self):
		parent = self.campaign("TEST-CMP Parent")
		child = self.campaign("TEST-CMP Child", parent=parent.name)
		self.assertEqual(c.descendants(parent.name), [child.name])
		parent.set(c.PARENT_FIELD, child.name)
		with self.assertRaises(frappe.ValidationError):
			parent.save()

	def test_end_before_start_blocked(self):
		doc = frappe.get_doc(
			{
				"doctype": "Campaign",
				"campaign_name": "TEST-CMP Dates",
				"alt_start_date": today(),
				"alt_end_date": add_days(today(), -1),
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)


class TestCarryThrough(CampaignCase):
	def test_lead_to_customer_to_quotation(self):
		utm = c.utm_of(self.campaign("TEST-CMP Flow").name)
		lead = self.raw("Lead", {"lead_name": "TEST-CMP Lead", "company": self.company, c.UTM_FIELD: utm})

		customer = frappe.new_doc("Customer")
		customer.lead_name = lead.name
		c.customer_before_validate(customer)
		self.assertEqual(customer.get(c.CUSTOMER_FIELD), utm)

		customer = self.raw("Customer", {"customer_name": "TEST-CMP Customer", c.CUSTOMER_FIELD: utm})
		quotation = frappe.new_doc("Quotation")
		quotation.quotation_to = "Customer"
		quotation.party_name = customer.name
		c.quotation_validate(quotation)
		self.assertEqual(quotation.get(c.UTM_FIELD), utm)

	def test_chosen_campaign_kept(self):
		first = c.utm_of(self.campaign("TEST-CMP First").name)
		second = c.utm_of(self.campaign("TEST-CMP Second").name)
		customer = self.raw("Customer", {"customer_name": "TEST-CMP Keep", c.CUSTOMER_FIELD: first})
		quotation = frappe.new_doc("Quotation")
		quotation.quotation_to = "Customer"
		quotation.party_name = customer.name
		quotation.set(c.UTM_FIELD, second)
		c.quotation_validate(quotation)
		self.assertEqual(quotation.get(c.UTM_FIELD), second)

	def test_estimation_and_order_from_quotation(self):
		utm = c.utm_of(self.campaign("TEST-CMP Order").name)
		customer = self.raw("Customer", {"customer_name": "TEST-CMP Est", c.CUSTOMER_FIELD: utm})
		estimation = frappe.new_doc("Estimation")
		estimation.customer = customer.name
		c.estimation_campaign(estimation)
		self.assertEqual(estimation.get(c.UTM_FIELD), utm)

		quotation = self.raw("Quotation", {"quotation_to": "Customer", "party_name": "_x", c.UTM_FIELD: utm}, 1)
		order = frappe.new_doc("Sales Order")
		order.customer = "_x"
		order.append("items", {"prevdoc_docname": quotation.name})
		c.sales_order_validate(order)
		self.assertEqual(order.get(c.UTM_FIELD), utm)


class TestCampaignROIReport(CampaignCase):
	def test_parent_rolls_up_child(self):
		from alantech_erp.alantech.report.campaign_roi.campaign_roi import execute

		parent = self.campaign("TEST-CMP Roll Parent", budget=500, costs=(500,))
		child = self.campaign("TEST-CMP Roll Child", parent=parent.name, costs=(250,))
		self.order(c.utm_of(parent.name), 1000)
		self.order(c.utm_of(child.name), 2000)

		_, data, _, _, summary = execute({"company": self.company, "campaign": parent.name})
		rows = {r.campaign: r for r in data}
		self.assertEqual(flt(rows[parent.name].income), 3000)
		self.assertEqual(flt(rows[parent.name].actual_cost), 750)
		self.assertEqual(flt(rows[child.name].income), 2000)
		self.assertEqual(rows[child.name].parent_campaign, parent.name)
		income_card = next(card for card in summary if card["datatype"] == "Currency" and "Income" in card["label"])
		self.assertEqual(flt(income_card["value"]), 3000)  # each campaign counted once
