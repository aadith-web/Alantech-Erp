# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Plant Assembly: a plant type made of Sub Assemblies, with the costing and offer defaults for it.

Picked on an Estimation (loads sections, cost items, percentages) and on a Technical Offer
(loads sections, standard text, design basis tables and terms).
"""

import frappe
from frappe import _
from frappe.model.document import Document

from alantech_erp.proposal import INCLUDED, section_title_of


class PlantAssembly(Document):
	def validate(self):
		titles = set()
		for row in self.sections:
			if not row.section_title:
				row.section_title = section_title_of(row.sub_assembly)
			if row.section_title in titles:
				frappe.throw(
					_("Row {0}: section {1} is used twice. Give each section its own title (e.g. RO 1, RO 2).").format(
						row.idx, frappe.bold(row.section_title)
					),
					title=_("Duplicate Section"),
				)
			titles.add(row.section_title)
			row.pricing_mode = row.pricing_mode or INCLUDED
