# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales forecast and commission against the database (sales/forecast.py, sales/commission.py,
Sales Forecast, Commission Plan, Commission Payout).

Run:
    bench --site <site> run-tests --module alantech_erp.tests.test_sales_performance

Builds a small Sales Person tree (TEST-SPF ...) and writes orders / Deals / invoices straight to
the database (the CRM validations of Customer and Quotation are tested elsewhere); everything is
rolled back after each test.
"""

import frappe
from frappe.utils import add_days, flt, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.sales import commission, forecast

MANAGER, ENG_A, ENG_B = "TEST-SPF Manager", "TEST-SPF Eng A", "TEST-SPF Eng B"


def _company():
	return frappe.db.get_value("Company", {}, "name")


class SalesPerformanceCase(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _company()
		if not cls.company:
			raise Exception("No Company on the site: finish the setup wizard first")
		cls.abbr = frappe.get_cached_value("Company", cls.company, "abbr")
		cls.start, cls.end = forecast.period_bounds(forecast.MONTH, today())

	def setUp(self):
		frappe.set_user("Administrator")
		settings = frappe.get_single(forecast.SETTINGS)
		settings.update(
			{
				"won_source": "Sales Order",
				"period_type": "Month",
				"enable_commission": 1,
				"default_basis": "Sales Invoice",
				"payout_method": "Journal Entry",
			}
		)
		settings.flags.ignore_mandatory = True
		settings.save()
		from frappe.utils.nestedset import get_root_of

		root = get_root_of("Sales Person")
		self.sales_person(MANAGER, root, is_group=1)
		self.sales_person(ENG_A, MANAGER)
		self.sales_person(ENG_B, MANAGER)
		from alantech_erp.sales.hierarchy import clear_cache

		clear_cache()

	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------- builders
	def sales_person(self, name, parent, is_group=0):
		if frappe.db.exists("Sales Person", name):
			return name
		frappe.get_doc(
			{
				"doctype": "Sales Person",
				"sales_person_name": name,
				"parent_sales_person": parent,
				"is_group": is_group,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		return name

	def set_target(self, person, amount):
		fy = forecast._fiscal_year_of(getdate(today()), self.company)
		if not frappe.db.exists("Monthly Distribution", "TEST-SPF Even"):
			dist = frappe.new_doc("Monthly Distribution")
			dist.distribution_id = "TEST-SPF Even"
			dist.get_months()  # twelve equal months
			dist.insert()
		sp = frappe.get_doc("Sales Person", person)
		sp.set("targets", [])
		sp.append(
			"targets",
			{
				"fiscal_year": fy,
				"target_amount": amount,
				"distribution_id": "TEST-SPF Even",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 1}, "name"),
			},
		)
		sp.save(ignore_permissions=True)

	def raw_doc(self, doctype, values, team, docstatus=1):
		"""A submitted Sales Order / Sales Invoice written straight to the database."""
		doc = frappe.get_doc({"doctype": doctype, "company": self.company, "docstatus": docstatus, **values})
		doc.name = frappe.generate_hash(length=10)
		for person, pct in team:
			doc.append("sales_team", {"sales_person": person, "allocated_percentage": pct})
		doc.db_insert()
		for row in doc.sales_team:
			row.db_insert()
		for row in doc.get("items") or []:
			row.db_insert()
		return doc

	def deal(self, person, amount, category, probability=50, closing=None):
		doc = frappe.get_doc(
			{
				"doctype": "Opportunity",
				"opportunity_from": "Customer",
				"party_name": "_x",
				"company": self.company,
				"status": "Open",
				"opportunity_amount": amount,
				"base_opportunity_amount": amount,
				"probability": probability,
				"expected_closing": closing or today(),
				forecast.SALES_PERSON_FIELD: person,
				forecast.CATEGORY_FIELD: category,
			}
		)
		doc.name = frappe.generate_hash(length=10)
		doc.db_insert()
		return doc


class TestForecast(SalesPerformanceCase):
	def test_forecast_rolls_up(self):
		self.set_target(ENG_A, 1200000)  # no distribution: 100,000 a month
		self.raw_doc(
			"Sales Order",
			{"transaction_date": today(), "base_net_total": 60000, "net_total": 60000, "customer": "_x"},
			[(ENG_A, 50), (ENG_B, 50)],
		)
		self.deal(ENG_A, 20000, forecast.COMMIT, 90)
		self.deal(ENG_A, 10000, forecast.BEST_CASE, 60)
		self.deal(ENG_B, 40000, forecast.PIPELINE, 10)
		self.deal(ENG_B, 99999, forecast.COMMIT, closing=add_days(self.end, 5))  # next period
		self.deal(ENG_B, 99999, forecast.OMITTED)

		rows = {r.name: r for r in forecast.get_forecast(self.company, self.start, self.end, MANAGER)}
		a, b, m = rows[ENG_A], rows[ENG_B], rows[MANAGER]
		self.assertAlmostEqual(a.target, 100000, delta=1)
		self.assertEqual((a.closed_won, a.commit_amount, a.best_case), (30000, 20000, 10000))
		self.assertEqual(a.forecast, 50000)
		self.assertAlmostEqual(a.achievement_pct, 30, delta=0.01)
		self.assertEqual((b.closed_won, b.pipeline, b.commit_amount), (30000, 40000, 0))
		self.assertEqual((m.closed_won, m.commit_amount, m.pipeline), (60000, 20000, 40000))
		self.assertAlmostEqual(m.weighted_pipeline, 20000 * 0.9 + 10000 * 0.6 + 40000 * 0.1)
		self.assertAlmostEqual(m.target, 100000, delta=1)  # team sum

	def test_sales_forecast_document(self):
		self.raw_doc(
			"Sales Order",
			{"transaction_date": today(), "base_net_total": 10000, "net_total": 10000, "customer": "_x"},
			[(ENG_A, 100)],
		)
		doc = frappe.get_doc(
			{
				"doctype": "Sales Forecast",
				"company": self.company,
				"sales_person": MANAGER,
				"period_type": "Month",
				"period_start": today(),
			}
		)
		doc.insert()
		self.assertEqual([r.sales_person for r in doc.details], [MANAGER, ENG_A, ENG_B])
		self.assertEqual(doc.details[1].indent, 1)
		self.assertEqual(doc.total_closed_won, 10000)
		doc.details[1].manager_adjusted = 25000
		doc.save()
		doc.fill_details()  # refresh keeps the manager's figure
		self.assertEqual(doc.details[1].manager_adjusted, 25000)
		doc.submit()
		again = frappe.copy_doc(doc)
		self.assertRaises(frappe.ValidationError, again.insert)

	def test_deal_category_follows_stage(self):
		stage = frappe.db.get_value("Sales Stage", {forecast.CATEGORY_FIELD: forecast.COMMIT}, "name")
		if not stage:
			stage = frappe.get_doc({"doctype": "Sales Stage", "stage_name": "TEST-SPF Commit"}).insert().name
			frappe.db.set_value(
				"Sales Stage",
				stage,
				{forecast.CATEGORY_FIELD: forecast.COMMIT, forecast.STAGE_PROBABILITY_FIELD: 90},
			)
		opp = frappe.new_doc("Opportunity")
		opp.sales_stage = stage
		opp.status = "Open"
		forecast.opportunity_validate(opp)
		self.assertEqual((opp.get(forecast.CATEGORY_FIELD), opp.probability), (forecast.COMMIT, 90))
		opp.status = "Lost"
		forecast.opportunity_validate(opp)
		self.assertEqual(opp.get(forecast.CATEGORY_FIELD), forecast.OMITTED)
		self.assertEqual(
			forecast.stage_values(stage, "Open"),
			{forecast.CATEGORY_FIELD: forecast.COMMIT, "probability": 90},
		)


class TestCommission(SalesPerformanceCase):
	def invoice(self, amount, team, posting_date=None, is_return=0, group=None):
		group = group or frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": "_x",
				"posting_date": posting_date or today(),
				"is_return": is_return,
				"base_net_total": amount,
				"grand_total": amount,
				"items": [{"item_code": "_x", "item_group": group, "base_net_amount": amount, "qty": 1}],
			}
		)
		doc.name = frappe.generate_hash(length=10)
		for person, pct in team:
			doc.append("sales_team", {"sales_person": person, "allocated_percentage": pct})
		commission.on_sales_invoice_submit(doc)
		return doc

	def make_plan(self, **kw):
		values = {
			"doctype": "Commission Plan",
			"plan_name": "TEST-SPF Plan",
			"company": self.company,
			"basis": "Sales Invoice",
			"calculation_method": "Tiered (Incremental)",
			"slabs": [
				{"from_value": 0, "to_value": 100000, "rate": 2},
				{"from_value": 100000, "to_value": 0, "rate": 4},
			],
			"members": [{"sales_person": ENG_A}],
		}
		values.update(kw)
		return frappe.get_doc(values).insert()

	def accounts(self):
		parent = frappe.db.get_value(
			"Account",
			{
				"company": self.company,
				"root_type": "Liability",
				"is_group": 1,
				"account_type": ["in", ["", None]],
			},
			"name",
		)
		payable = frappe.db.get_value(
			"Account", {"account_name": "TEST-SPF Commission Payable", "company": self.company}
		)
		if not payable:
			payable = (
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": "TEST-SPF Commission Payable",
						"company": self.company,
						"parent_account": parent,
						"is_group": 0,
					}
				)
				.insert()
				.name
			)
		expense = frappe.db.get_value(
			"Account", {"company": self.company, "root_type": "Expense", "is_group": 0}, "name"
		)
		return expense, payable

	def test_ledger_split_and_reversal(self):
		inv = self.invoice(10000, [(ENG_A, 60), (ENG_B, 40)])
		entries = frappe.get_all(
			commission.LEDGER, filters={"voucher_no": inv.name}, fields=["sales_person", "base_amount"]
		)
		self.assertEqual({e.sales_person: e.base_amount for e in entries}, {ENG_A: 6000, ENG_B: 4000})
		commission.on_cancel(inv)
		total = sum(frappe.get_all(commission.LEDGER, filters={"voucher_no": inv.name}, pluck="base_amount"))
		self.assertEqual(total, 0)

	def test_plan_overlap_blocked(self):
		self.make_plan()
		self.assertRaises(frappe.ValidationError, self.make_plan, plan_name="TEST-SPF Plan 2")

	def test_payout_tiered_and_journal_entry(self):
		self.make_plan()
		self.invoice(150000, [(ENG_A, 100)])
		self.invoice(-10000, [(ENG_A, 100)], is_return=1)  # credit note, clawed back
		expense, payable = self.accounts()
		payout = frappe.get_doc(
			{
				"doctype": "Commission Payout",
				"company": self.company,
				"period_type": "Month",
				"period_start": today(),
				"posting_date": today(),
				"payout_method": "Journal Entry",
				"expense_account": expense,
				"payable_account": payable,
			}
		)
		payout.get_commission()
		row = next(r for r in payout.details if r.sales_person == ENG_A)
		self.assertEqual(row.base_amount, 140000)
		self.assertEqual(row.commission_amount, 2000 + 1600)  # 2% of 100k + 4% of 40k
		row.adjustment = 400
		payout.insert()
		payout.submit()
		self.assertEqual(payout.total_payable, 4000)
		self.assertTrue(payout.journal_entry)
		self.assertEqual(frappe.db.get_value("Journal Entry", payout.journal_entry, "total_debit"), 4000)
		unpaid = commission.unpaid_entries(ENG_A, "Sales Invoice", self.start, self.end, self.company)
		self.assertEqual(unpaid, [])

		payout.cancel()
		self.assertEqual(frappe.db.get_value("Journal Entry", payout.journal_entry, "docstatus"), 2)
		self.assertEqual(
			len(commission.unpaid_entries(ENG_A, "Sales Invoice", self.start, self.end, self.company)), 2
		)

	def test_submit_blocked_when_commission_changed(self):
		self.make_plan(calculation_method="Flat Rate", rate=5, slabs=[])
		self.invoice(1000, [(ENG_A, 100)])
		expense, payable = self.accounts()
		payout = frappe.get_doc(
			{
				"doctype": "Commission Payout",
				"company": self.company,
				"period_type": "Month",
				"period_start": today(),
				"posting_date": today(),
				"sales_person": ENG_A,
				"payout_method": "Journal Entry",
				"expense_account": expense,
				"payable_account": payable,
			}
		)
		payout.get_commission()
		payout.insert()
		self.invoice(1000, [(ENG_A, 100)])  # arrives after Get Commission
		self.assertRaises(frappe.ValidationError, payout.submit)

	def test_payment_received_basis(self):
		inv = self.invoice(10000, [(ENG_A, 100)])
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": self.company,
				"posting_date": today(),
				"references": [
					{
						"reference_doctype": "Sales Invoice",
						"reference_name": inv.name,
						"allocated_amount": 2500,
					}
				],
			}
		)
		pe.name = frappe.generate_hash(length=10)
		inv.db_insert()  # the payment reads the invoice from the database
		for row in inv.items + inv.sales_team:
			row.parent = inv.name
			row.db_insert()
		commission.on_payment_entry_submit(pe)
		paid = frappe.get_all(
			commission.LEDGER,
			filters={"voucher_no": pe.name},
			fields=["basis", "base_amount", "against_voucher"],
		)
		self.assertEqual(len(paid), 1)
		self.assertEqual(
			(paid[0].basis, flt(paid[0].base_amount), paid[0].against_voucher),
			("Payment Received", 2500, inv.name),
		)
