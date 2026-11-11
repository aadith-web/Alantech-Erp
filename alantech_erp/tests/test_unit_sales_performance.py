# Copyright (c) 2026, JincyTricta and Contributors
# See license.txt
"""Sales forecast and commission, pure logic (sales/forecast.py, sales/commission.py): periods,
roll-up of the Sales Person tree, and every commission calculation. No database writes.

Run:
    bench --site <site> run-tests --module alantech_erp.tests.test_unit_sales_performance
"""

from datetime import date

import frappe
from frappe.tests import UnitTestCase

from alantech_erp.sales import commission as c
from alantech_erp.sales import forecast as f


def plan(**kw):
	base = dict(
		name="P",
		method=c.FLAT,
		rate=0,
		slab_basis=c.SLAB_AMOUNT,
		slabs=[],
		item_group_rates={},
		min_achievement=0,
		max_commission=0,
		clawback=1,
	)
	base.update(kw)
	return frappe._dict(base)


class TestPeriods(UnitTestCase):
	def test_month(self):
		self.assertEqual(f.period_bounds(f.MONTH, "2026-02-14"), (date(2026, 2, 1), date(2026, 2, 28)))

	def test_quarter(self):
		self.assertEqual(f.period_bounds(f.QUARTER, "2026-11-11"), (date(2026, 10, 1), date(2026, 12, 31)))
		self.assertEqual(f.period_bounds(f.QUARTER, "2026-01-01"), (date(2026, 1, 1), date(2026, 3, 31)))

	def test_months_between(self):
		self.assertEqual(
			f.months_between("2026-11-15", "2027-01-02"),
			[date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)],
		)

	def test_labels(self):
		self.assertEqual(f.period_label(f.QUARTER, date(2026, 10, 1)), "Q4 2026")
		self.assertEqual(f.period_label(f.MONTH, date(2026, 11, 1)), "Nov 2026")


def node(name, parent, lft, rgt, is_group=0, **amounts):
	row = frappe._dict(name=name, parent=parent, lft=lft, rgt=rgt, is_group=is_group, indent=0)
	for key in f.AMOUNT_KEYS:
		row[key] = amounts.get(key, 0)
	return row


class TestRollUp(UnitTestCase):
	def tree(self, director_target=0):
		# Director(1-8) > Manager(2-7) > Eng A(3-4), Eng B(5-6)
		return [
			node("Director", None, 1, 8, 1, target=director_target, closed_won=10),
			node("Manager", "Director", 2, 7, 1),
			node("A", "Manager", 3, 4, target=100, closed_won=40, commit_amount=30, best_case=20),
			node("B", "Manager", 5, 6, target=50, closed_won=50, pipeline=70),
		]

	def test_numbers_add_up_the_tree(self):
		rows = {r.name: r for r in f.roll_up(self.tree())}
		self.assertEqual(rows["Manager"].closed_won, 90)
		self.assertEqual(rows["Director"].closed_won, 100)  # own 10 + team 90
		self.assertEqual(rows["Manager"].pipeline, 70)
		self.assertEqual(rows["A"].forecast, 70)
		self.assertEqual(rows["A"].best_case_forecast, 90)
		self.assertEqual(rows["A"].gap, 30)

	def test_group_target_is_team_sum_unless_own(self):
		rows = {r.name: r for r in f.roll_up(self.tree())}
		self.assertEqual(rows["Manager"].target, 150)
		self.assertEqual(rows["Director"].target, 150)
		rows = {r.name: r for r in f.roll_up(self.tree(director_target=500))}
		self.assertEqual(rows["Director"].target, 500)  # the director's own quota wins
		self.assertAlmostEqual(rows["Director"].achievement_pct, 20)

	def test_no_target_no_gap(self):
		row = f.compute_row(frappe._dict(target=0, closed_won=5, commit_amount=5, best_case=0))
		self.assertEqual((row.gap, row.achievement_pct, row.forecast), (0, 0, 10))


class TestCategories(UnitTestCase):
	def test_status_wins(self):
		self.assertEqual(f.category_for_status("Converted"), f.CLOSED)
		self.assertEqual(f.category_for_status("Lost"), f.OMITTED)
		self.assertIsNone(f.category_for_status("Open"))


class TestTiered(UnitTestCase):
	SLABS = ((0, 100000, 2), (100000, 500000, 3), (500000, 0, 5))

	def test_whole(self):
		self.assertEqual(c.tiered(50000, self.SLABS, False), 1000)
		self.assertEqual(c.tiered(200000, self.SLABS, False), 6000)  # 3% on all of it
		self.assertEqual(c.tiered(600000, self.SLABS, False), 30000)

	def test_incremental(self):
		self.assertEqual(c.tiered(50000, self.SLABS, True), 1000)
		self.assertEqual(c.tiered(200000, self.SLABS, True), 2000 + 3000)
		self.assertEqual(c.tiered(600000, self.SLABS, True), 2000 + 12000 + 5000)

	def test_below_first_slab_pays_nothing(self):
		self.assertEqual(c.tiered(5000, [(10000, 0, 5)], False), 0)
		self.assertEqual(c.tiered(5000, [(10000, 0, 5)], True), 0)


class TestCalculate(UnitTestCase):
	def test_flat(self):
		self.assertEqual(c.calculate(plan(rate=2.5), 100000)[0], 2500)

	def test_item_groups_with_default_rate(self):
		p = plan(method=c.ITEM_GROUP, rate=1, item_group_rates={"Pumps": 4})
		commission = c.calculate(p, 300, {"Pumps": 100, "Spares": 200})[0]
		self.assertEqual(commission, 4 + 2)

	def test_achievement_slabs(self):
		p = plan(
			method=c.TIERED_WHOLE,
			slab_basis=c.SLAB_ACHIEVEMENT,
			slabs=[(0, 80, 1), (80, 100, 2), (100, 0, 3)],
		)
		commission, achievement, rate = c.calculate(p, 90000, None, target=100000)
		self.assertEqual((commission, achievement, rate), (1800, 90, 2))
		self.assertEqual(c.calculate(p, 120000, None, target=100000)[0], 3600)

	def test_achievement_slabs_need_a_target(self):
		p = plan(method=c.TIERED_WHOLE, slab_basis=c.SLAB_ACHIEVEMENT, slabs=[(0, 0, 1)])
		self.assertRaises(frappe.ValidationError, c.calculate, p, 1000, None, 0)

	def test_minimum_achievement(self):
		p = plan(rate=5, min_achievement=50)
		self.assertEqual(c.calculate(p, 40000, None, target=100000)[0], 0)
		self.assertEqual(c.calculate(p, 60000, None, target=100000)[0], 3000)

	def test_cap(self):
		self.assertEqual(c.calculate(plan(rate=10, max_commission=5000), 100000)[0], 5000)

	def test_net_clawback_at_base_rate(self):
		self.assertEqual(c.calculate(plan(rate=2), -10000)[0], -200)
		tiered = plan(method=c.TIERED_INCREMENTAL, slabs=[(0, 0, 3)])
		self.assertEqual(c.calculate(tiered, -10000)[0], -300)
