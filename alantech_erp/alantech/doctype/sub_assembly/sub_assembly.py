# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Sub Assembly: a reusable block of a plant (e.g. Multimedia Filter, RO System, Direct Labour).

Costing Items  are copied into an Estimation when the sub assembly is added to it.
Offer Text     (introduction, design data, components with spec tables) is copied into a
               Technical Offer. Values to confirm per project are written as [[value]].
"""

from frappe.model.document import Document
from frappe.utils import flt


class SubAssembly(Document):
	def validate(self):
		total = 0.0
		for row in self.items:
			amount = flt(row.qty) * flt(row.unit_cost)
			total += amount + amount * flt(row.addon_pct) / 100
		self.total_cost = flt(total, self.precision("total_cost"))
		for row in self.components:
			row.section = None  # only used inside a Technical Offer
