# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Estimation: the costing of a plant for a Deal (ERPNext Opportunity).

Built as Plant Assembly -> Sub Assemblies (sections) -> cost items, like the water treatment
costing workbook. All costs are per train:

    item:     Amount = Qty x Unit Cost;  Transport = Amount x Transport %;  Total Cost = Amount + Transport
    section:  sum of its items (Sub Total of the workbook)
    Total Cost                       = sections priced Included or Separate Line (Optional ones are left out)
    Total Cost incl. Contingencies   = Total Cost + Contingencies (+ Financing Cost when ticked)
    section selling price            = section cost x (Total Cost incl. Contingencies / Total Cost)
                                       then + margin: x (1 + Margin %)       Markup on Cost
                                                  or  / (1 - Margin %)      Margin on Selling Price
    Main Plant Price per Train       = Included sections
    Selling Price per Train          = Main Plant Price + Separate Line sections
    Profit Margin                    = Selling Price - Total Cost incl. Contingencies - Sales Commission
    Selling Price, all Trains        = Selling Price per Train x No. of Trains

Flow: Deal -> Estimation (Sales Manager) -> Technical Offer (Proposal Engineer) -> Quotation
-> manager approval -> client approval -> Sales Order. Once submitted the Estimation is fixed.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt

from alantech_erp.proposal import INCLUDED, MANPOWER, OPTIONAL, SEPARATE, get_sub_assembly, section_title_of

CLOSED_DEAL_STATUSES = ("Lost", "Closed", "Converted")

# Copied from a Plant Assembly into an Estimation
ASSEMBLY_FIELDS = (
	"plant_type", "capacity", "capacity_uom", "no_of_trains", "quote_item",
	"default_addon_pct", "contingency_pct", "financing_pct", "include_financing",
	"margin_basis", "profit_pct", "sales_commission_pct", "round_to",
)
ITEM_FIELDS = ("cost_head", "item_code", "type_model", "moc", "make", "qty", "uom", "unit_cost", "addon_pct")


def calculate_pricing(doc):
	"""Fill every computed amount on an Estimation (same formulas as public/js/estimation_pricing.js)."""
	sections = {s.section_title: s for s in doc.get("sections") or []}
	for s in sections.values():
		s.amount = s.addon_amount = s.total_cost = 0.0

	for row in doc.get("items") or []:
		if flt(row.qty) < 0 or flt(row.unit_cost) < 0:
			frappe.throw(_("Row {0} ({1}): Qty and Unit Cost cannot be negative.").format(row.idx, row.cost_head))
		row.amount = flt(flt(row.qty) * flt(row.unit_cost), row.precision("amount"))
		row.addon_amount = flt(row.amount * flt(row.addon_pct) / 100, row.precision("addon_amount"))
		row.total_cost = flt(row.amount + row.addon_amount, row.precision("total_cost"))
		section = sections.get(row.section)
		if section:
			section.amount += row.amount
			section.addon_amount += row.addon_amount
			section.total_cost += row.total_cost

	totals = {"amount": 0.0, "addon": 0.0, "cost": 0.0, "Equipment": 0.0, "Manpower": 0.0, "Other": 0.0}
	for s in sections.values():
		if s.pricing_mode == OPTIONAL:
			continue
		totals["amount"] += s.amount
		totals["addon"] += s.addon_amount
		totals["cost"] += s.total_cost
		key = s.cost_type if s.cost_type in ("Equipment", "Manpower") else "Other"
		totals[key] += s.total_cost

	doc.total_amount = flt(totals["amount"], doc.precision("total_amount"))
	doc.total_addon = flt(totals["addon"], doc.precision("total_addon"))
	doc.total_cost = flt(totals["cost"], doc.precision("total_cost"))
	doc.equipment_cost = flt(totals["Equipment"], doc.precision("equipment_cost"))
	doc.manpower_cost = flt(totals["Manpower"], doc.precision("manpower_cost"))
	doc.general_cost = flt(totals["Other"], doc.precision("general_cost"))

	doc.contingency_amount = flt(doc.total_cost * flt(doc.contingency_pct) / 100, doc.precision("contingency_amount"))
	doc.financing_amount = flt(doc.total_cost * flt(doc.financing_pct) / 100, doc.precision("financing_amount"))
	doc.cost_price = flt(
		doc.total_cost + doc.contingency_amount + (doc.financing_amount if cint(doc.include_financing) else 0),
		doc.precision("cost_price"),
	)

	# contingencies and financing spread over the sections in proportion to their cost
	load = (
		doc.cost_price / doc.total_cost
		if doc.total_cost
		else 1 + (flt(doc.contingency_pct) + (flt(doc.financing_pct) if cint(doc.include_financing) else 0)) / 100
	)
	main = separate = optional = 0.0
	for s in sections.values():
		margin = flt(s.margin_pct) if cint(s.override_margin) else flt(doc.profit_pct)
		s.selling_price = flt(apply_margin(s.total_cost * load, margin, doc.margin_basis, doc.round_to), s.precision("selling_price"))
		if s.pricing_mode == OPTIONAL:
			optional += s.selling_price
		elif s.pricing_mode == SEPARATE:
			separate += s.selling_price
		else:
			main += s.selling_price

	doc.main_price = flt(main, doc.precision("main_price"))
	doc.selling_price = flt(main + separate, doc.precision("selling_price"))
	doc.optional_price = flt(optional, doc.precision("optional_price"))
	doc.sales_commission_amount = flt(
		doc.selling_price * flt(doc.sales_commission_pct) / 100, doc.precision("sales_commission_amount")
	)
	doc.profit_amount = flt(
		doc.selling_price - doc.cost_price - doc.sales_commission_amount, doc.precision("profit_amount")
	)
	doc.profit_on_cost_pct = flt(doc.profit_amount / doc.cost_price * 100, 2) if doc.cost_price else 0
	doc.grand_selling_price = flt(
		doc.selling_price * max(cint(doc.no_of_trains), 1), doc.precision("grand_selling_price")
	)


def apply_margin(cost, margin_pct, basis, round_to=None):
	if basis == "Margin on Selling Price":
		if flt(margin_pct) >= 100:
			frappe.throw(_("Margin on Selling Price must be below 100%."))
		price = cost / (1 - flt(margin_pct) / 100)
	else:
		price = cost * (1 + flt(margin_pct) / 100)
	step = cint(round_to)
	if step > 1 and price:
		price = round(price / step) * step
	return price


class Estimation(Document):
	def validate(self):
		self.validate_deal()
		if cint(self.no_of_trains) < 1:
			self.no_of_trains = 1
		self.validate_sections()
		calculate_pricing(self)

	def before_submit(self):
		if not self.items:
			frappe.throw(_("Add at least one cost item before submitting."), title=_("Cost Sheet Empty"))
		if not self.quote_item:
			frappe.throw(
				_("Set the Quotation Item (the plant item quoted to the client) before submitting."),
				title=_("Quotation Item Missing"),
			)

	def validate_sections(self):
		"""Every cost item belongs to a section of the Sub Assemblies table."""
		titles = []
		for s in self.sections:
			s.section_title = (s.section_title or "").strip()
			if s.section_title in titles:
				frappe.throw(
					_("Sub Assemblies row {0}: section {1} is used twice. Give each section its own title (e.g. RO 1, RO 2).").format(
						s.idx, frappe.bold(s.section_title)
					),
					title=_("Duplicate Section"),
				)
			titles.append(s.section_title)
			s.pricing_mode = s.pricing_mode or INCLUDED

		for row in self.items:
			if not row.section:
				if len(titles) == 1:
					row.section = titles[0]
				else:
					frappe.throw(
						_("Cost item row {0} ({1}): select its Section.").format(row.idx, frappe.bold(row.cost_head)),
						title=_("Section Missing"),
					)
			if row.section not in titles:
				# typed in or imported: add the section instead of losing the cost
				self.append("sections", {"section_title": row.section, "cost_type": "Equipment", "pricing_mode": INCLUDED})
				titles.append(row.section)

	# ------------------------------------------------------------------ actions from the form
	@frappe.whitelist()
	def apply_plant_assembly(self):
		"""Replace the sub assemblies, cost items and costing defaults with the Plant Assembly's."""
		self.check_draft()
		if not self.plant_assembly:
			return
		assembly = frappe.get_doc("Plant Assembly", self.plant_assembly)
		assembly.check_permission("read")
		for field in ASSEMBLY_FIELDS:
			if assembly.get(field) not in (None, ""):
				self.set(field, assembly.get(field))
		self.set("sections", [])
		self.set("items", [])
		for row in assembly.sections:
			self.add_sub_assembly(
				row.sub_assembly,
				section_title=row.section_title,
				pricing_mode=row.pricing_mode,
				include_in_offer=row.include_in_offer,
				price_description=row.price_description,
			)
		calculate_pricing(self)

	@frappe.whitelist()
	def add_sub_assembly(self, sub_assembly, section_title=None, pricing_mode=None, include_in_offer=None, price_description=None):
		"""Add a Sub Assembly as a new section with its standard cost items."""
		self.check_draft()
		sub = get_sub_assembly(sub_assembly)
		title = (section_title or "").strip() or section_title_of(sub.name)
		if any(s.section_title == title for s in self.sections):
			frappe.throw(
				_("Section {0} is already in this estimation. Give the new one another title (e.g. {0} 2).").format(
					frappe.bold(title)
				),
				title=_("Duplicate Section"),
			)
		self.append(
			"sections",
			{
				"section_title": title,
				"sub_assembly": sub.name,
				"cost_type": sub.cost_type,
				"pricing_mode": pricing_mode or sub.default_pricing_mode or INCLUDED,
				"include_in_offer": cint(sub.include_in_offer if include_in_offer is None else include_in_offer),
				"price_description": price_description or sub.price_description,
			},
		)
		for item in sub.items:
			row = {field: item.get(field) for field in ITEM_FIELDS}
			row["section"] = title
			if row["addon_pct"] is None:
				row["addon_pct"] = 0 if sub.cost_type == MANPOWER else self.default_addon_pct
			self.append("items", row)
		calculate_pricing(self)

	@frappe.whitelist()
	def remove_zero_rows(self):
		"""Drop cost items with no quantity or no unit cost (unused lines of the standard sub assemblies)."""
		self.check_draft()
		keep = [row for row in self.items if flt(row.qty) and flt(row.unit_cost)]
		removed = len(self.items) - len(keep)
		self.set("items", keep)
		for idx, row in enumerate(self.items, 1):
			row.idx = idx
		calculate_pricing(self)
		return removed

	def check_draft(self):
		if self.docstatus != 0:
			frappe.throw(_("Only a draft Estimation can be changed."))

	def validate_deal(self):
		status = frappe.db.get_value("Opportunity", self.opportunity, "status")
		if status in CLOSED_DEAL_STATUSES:
			frappe.throw(
				_("Deal {0} is {1}. Estimations can only be made for open deals.").format(
					frappe.bold(self.opportunity), _(status)
				),
				title=_("Deal Not Open"),
			)


@frappe.whitelist()
def make_plant_assembly(source_name: str, assembly_name: str):
	"""Save this estimation's sub assemblies and costing defaults as a new Plant Assembly."""
	source = frappe.get_doc("Estimation", source_name)
	source.check_permission("read")
	assembly = frappe.new_doc("Plant Assembly")
	assembly.assembly_name = assembly_name
	for field in ASSEMBLY_FIELDS:
		assembly.set(field, source.get(field))
	skipped = []
	for s in source.sections:
		if not s.sub_assembly:
			skipped.append(s.section_title)
			continue
		assembly.append(
			"sections",
			{
				"sub_assembly": s.sub_assembly,
				"section_title": s.section_title,
				"pricing_mode": s.pricing_mode,
				"include_in_offer": s.include_in_offer,
				"price_description": s.price_description,
			},
		)
	if source.plant_assembly:
		# keep the offer defaults of the assembly this estimation started from
		base = frappe.get_doc("Plant Assembly", source.plant_assembly)
		for field in (
			"offer_format", "subject", "intro_text", "cover_image", "flow_diagram",
			"scope_of_supply_terms", "commercial_terms", "price_notes",
		):
			assembly.set(field, base.get(field))
		for table in ("guarantees", "project_data", "water_analysis", "bought_out_items"):
			for row in base.get(table):
				assembly.append(table, row.as_dict(no_default_fields=True))
	assembly.insert()
	return {"name": assembly.name, "skipped": skipped}


@frappe.whitelist()
def make_technical_offer(source_name: str, target_doc=None):
	from alantech_erp.alantech.doctype.technical_offer.technical_offer import make_from_estimation

	return make_from_estimation(source_name)


@frappe.whitelist()
def make_quotation(source_name: str, target_doc=None):
	"""Draft Quotation for the deal's party.

	One line for the plant (Qty = trains, rate = main plant price per train) and one line per
	Separate Line sub assembly. Optional sub assemblies are only described in the Technical Offer.
	"""
	from erpnext.controllers.accounts_controller import _get_default_taxes_and_charges
	from erpnext.setup.utils import get_exchange_rate

	deal = frappe.db.get_value(
		"Opportunity",
		frappe.db.get_value("Estimation", source_name, "opportunity"),
		["name", "opportunity_from", "party_name", "status"],
		as_dict=True,
	)
	if deal.status in CLOSED_DEAL_STATUSES:
		frappe.throw(_("Deal {0} is {1}.").format(frappe.bold(deal.name), _(deal.status)))

	def set_missing_values(source, target):
		target.quotation_to = deal.opportunity_from
		target.party_name = deal.party_name
		target.opportunity = deal.name
		chosen = (frappe.flags.args or {}).get("technical_offer")
		target.alt_technical_offer = chosen or latest_technical_offer(source.name)

		trains = max(cint(source.no_of_trains), 1)
		description = " ".join(
			part for part in (
				source.plant_type,
				f"{frappe.format(source.capacity)} {source.capacity_uom or ''}".strip() if source.capacity else "",
			) if part
		)
		has_sections = bool(source.sections)
		target.append(
			"items",
			{
				"item_code": source.quote_item,
				"qty": trains,
				"rate": source.main_price if has_sections else source.selling_price,
				"description": description or None,
			},
		)
		for s in source.sections:
			if s.pricing_mode == SEPARATE and flt(s.selling_price):
				target.append(
					"items",
					{
						"item_code": source.quote_item,
						"qty": trains,
						"rate": s.selling_price,
						"description": s.price_description or s.section_title,
					},
				)

		company_currency = frappe.get_cached_value("Company", target.company, "default_currency")
		target.conversion_rate = (
			1
			if company_currency == target.currency
			else get_exchange_rate(
				target.currency, company_currency, target.transaction_date, args="for_selling"
			)
		)
		taxes = _get_default_taxes_and_charges("Sales Taxes and Charges Template", company=target.company)
		if taxes.get("taxes"):
			target.update(taxes)

		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	return get_mapped_doc(
		"Estimation",
		source_name,
		{
			"Estimation": {
				"doctype": "Quotation",
				"field_map": {"name": "alt_estimation", "opportunity": "opportunity"},
				"field_no_map": ["remarks", "items", "sections", "total_amount", "total_cost"],
				"validation": {"docstatus": ["=", 1]},
			},
		},
		target_doc,
		set_missing_values,
	)


def latest_technical_offer(estimation):
	"""The newest Technical Offer of an estimation that is not cancelled (submitted first)."""
	rows = frappe.get_all(
		"Technical Offer",
		filters={"estimation": estimation, "docstatus": ["<", 2]},
		fields=["name"],
		order_by="docstatus desc, creation desc",
		limit=1,
	)
	return rows[0].name if rows else None
