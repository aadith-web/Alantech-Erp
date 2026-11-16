# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Commission Plan: how a Sales Person's commission is worked out (alantech_erp.sales.commission).

* Flat Rate / Tiered (Whole) / Tiered (Incremental) / Item Group Rates, on Sales Order, Sales
  Invoice or Payment Received.
* Slabs: ascending, not overlapping; the last may be open ended (To = 0).
* A Sales Person is on one enabled plan at a time: member dates may not overlap another enabled
  plan of the same company.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from alantech_erp.sales.commission import ITEM_GROUP, SLAB_ACHIEVEMENT, TIERED_INCREMENTAL, TIERED_WHOLE

FAR_PAST = getdate("1900-01-01")
FAR_FUTURE = getdate("2999-12-31")


class CommissionPlan(Document):
	def validate(self):
		self.validate_rates()
		self.validate_slabs()
		self.validate_item_groups()
		self.validate_members()

	def validate_rates(self):
		for value, label in (
			(self.rate, "Commission Rate %"),
			(self.min_achievement, "Minimum Target Achievement %"),
		):
			if flt(value) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(label)))
		if self.calculation_method not in (TIERED_WHOLE, TIERED_INCREMENTAL, ITEM_GROUP) and not flt(
			self.rate
		):
			frappe.msgprint(
				_("Commission Rate % is 0: this plan pays nothing."), indicator="orange", alert=True
			)

	def validate_slabs(self):
		if self.calculation_method not in (TIERED_WHOLE, TIERED_INCREMENTAL):
			return
		if not self.slabs:
			frappe.throw(_("Add at least one slab for a tiered plan."), title=_("Slabs Missing"))
		self.slabs.sort(key=lambda s: flt(s.from_value))
		for i, slab in enumerate(self.slabs, start=1):
			slab.idx = i
			if flt(slab.rate) < 0 or flt(slab.from_value) < 0:
				frappe.throw(_("Row {0}: slab values and rates cannot be negative.").format(i))
			if flt(slab.to_value) and flt(slab.to_value) <= flt(slab.from_value):
				frappe.throw(_("Row {0}: To must be more than From (0 for no upper limit).").format(i))
		for prev, slab in zip(self.slabs, self.slabs[1:], strict=False):
			if not flt(prev.to_value):
				frappe.throw(
					_("Row {0}: only the last slab can be open ended (To = 0).").format(prev.idx),
					title=_("Invalid Slabs"),
				)
			if flt(slab.from_value) < flt(prev.to_value):
				frappe.throw(
					_("Row {0} starts at {1}, inside row {2} (up to {3}).").format(
						slab.idx, flt(slab.from_value), prev.idx, flt(prev.to_value)
					),
					title=_("Overlapping Slabs"),
				)
		if self.slab_basis == SLAB_ACHIEVEMENT and any(flt(s.from_value) > 1000 for s in self.slabs):
			frappe.msgprint(
				_("Slabs are on target achievement %: values above 1000% look like amounts."),
				indicator="orange",
				alert=True,
			)

	def validate_item_groups(self):
		seen = set()
		for row in self.item_group_rates:
			if row.item_group in seen:
				frappe.throw(_("Item Group {0} is listed twice.").format(frappe.bold(row.item_group)))
			seen.add(row.item_group)
		if self.calculation_method == ITEM_GROUP and not self.item_group_rates:
			frappe.throw(_("Add the Item Group rates."), title=_("Item Group Rates Missing"))

	def validate_members(self):
		mine = {}
		for row in self.members:
			start, end = getdate(row.from_date or FAR_PAST), getdate(row.to_date or FAR_FUTURE)
			if end < start:
				frappe.throw(_("Row {0}: To Date is before From Date.").format(row.idx))
			for other_start, other_end, idx in mine.get(row.sales_person, []):
				if start <= other_end and other_start <= end:
					frappe.throw(
						_("Rows {0} and {1}: {2} is listed twice for overlapping dates.").format(
							idx, row.idx, frappe.bold(row.sales_person)
						)
					)
			mine.setdefault(row.sales_person, []).append((start, end, row.idx))

		if not self.enabled or not mine:
			return
		others = frappe.db.sql(
			"""
			select m.sales_person, m.from_date, m.to_date, p.name
			from `tabCommission Plan Member` m
			inner join `tabCommission Plan` p on p.name = m.parent and m.parenttype = 'Commission Plan'
			where p.enabled = 1 and p.company = %s and p.name != %s and m.sales_person in %s
			""",
			(self.company, self.name or "", tuple(mine)),
			as_dict=True,
		)
		for other in others:
			o_start, o_end = getdate(other.from_date or FAR_PAST), getdate(other.to_date or FAR_FUTURE)
			for start, end, idx in mine[other.sales_person]:
				if start <= o_end and o_start <= end:
					frappe.throw(
						_("Row {0}: {1} is already on Commission Plan {2} for these dates.").format(
							idx,
							frappe.bold(other.sales_person),
							frappe.get_desk_link("Commission Plan", other.name),
						),
						title=_("Sales Person On Another Plan"),
					)

	def on_update(self):
		frappe.clear_document_cache(self.doctype, self.name)


@frappe.whitelist()
def preview(plan, amount, target=0):
	"""Commission on an amount (the form's Try It button)."""
	from alantech_erp.sales.commission import calculate, load_plan

	frappe.has_permission("Commission Plan", "read", throw=True)
	commission, achievement, rate = calculate(load_plan(plan), flt(amount), None, flt(target))
	return {"commission": commission, "achievement": achievement, "rate": rate}
