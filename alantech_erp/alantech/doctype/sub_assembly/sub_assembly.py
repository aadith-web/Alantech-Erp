# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Sub Assembly: a reusable block of a plant (master), e.g. Multimedia Filter, RO System, Installation.

Standard Items         free text (not Item master records, no stock impact), copied into an
                       Estimation when the sub assembly is added to it
Standard Other Expenses  manpower man-days, transport... copied into the Estimation's Other Expenses
Offer Text             (introduction, design data, components with spec tables) is copied into a
                       Technical Offer. Values to confirm per project are written as [[value]].
"""

from frappe.model.document import Document
from frappe.utils import flt


class SubAssembly(Document):
	def validate(self):
		item_cost = expense_cost = 0.0
		for row in self.items:
			row.amount = flt(flt(row.qty) * flt(row.unit_cost), row.precision("amount"))
			item_cost += row.amount + row.amount * flt(row.addon_pct) / 100
		for row in self.get("expenses") or []:
			row.amount = flt(flt(row.qty) * flt(row.rate), row.precision("amount"))
			expense_cost += row.amount
		self.item_cost = flt(item_cost, self.precision("item_cost"))
		self.expense_cost = flt(expense_cost, self.precision("expense_cost"))
		self.total_cost = flt(item_cost + expense_cost, self.precision("total_cost"))
		for row in self.components:
			row.section = None  # only used inside a Technical Offer
