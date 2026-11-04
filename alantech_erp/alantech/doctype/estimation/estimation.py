# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Estimation: the cost sheet of a plant for a Customer (Company or Individual).

Built as Plant Assembly -> Sub Assemblies (sections) -> free-text Items, plus Other Expenses
(manpower, transport, travel...), like the water treatment costing workbook. Items are typed text,
never Item master records: no stock, warehouse or valuation impact. All costs are per train:

    item:      Amount = Qty x Unit Cost;  Add-on = Amount x Add-on %;  Amount incl. Add-on
    expense:   Amount = Qty x Rate  (tagged to a section, or untagged = general to the plant)
    section:   items incl. add-on + expenses tagged to it
    Total Item Cost        = items of sections priced Included or Separate Line (not Optional)
    Total Other Expenses   = expenses of those sections + untagged expenses
    Total Cost             = Total Item Cost + Total Other Expenses
    Total Cost incl. Contingencies = Total Cost + Contingencies (+ Financing Cost when ticked)
    section selling price  = section cost x (Total Cost incl. Contingencies / cost of the priced sections)
                             (untagged expenses, contingencies and financing spread in proportion;
                              Optional sections only carry contingencies and financing)
                             then + margin: x (1 + Margin %)  Markup on Cost
                                        or  / (1 - Margin %)  Margin on Selling Price
    Main Plant Price per Train = Included sections
    Selling Price per Train    = Main Plant Price + Separate Line sections
    Profit Margin              = Selling Price - Total Cost incl. Contingencies - Sales Commission
    Selling Price, all Trains  = Selling Price per Train x No. of Trains

Flow: Lead -> Customer -> Estimation (optional, Sales Manager) -> Technical Offer -> Quotation
-> approval up the sales hierarchy -> client -> Sales Order. Once submitted the Estimation is fixed;
a revised quotation keeps the same Estimation. The Deal is created from the Quotation.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt

from alantech_erp.proposal import (
	EXPENSE_FIELDS,
	EXPENSE_MANPOWER,
	INCLUDED,
	ITEM_FIELDS,
	MANPOWER,
	OPTIONAL,
	SEPARATE,
	get_sub_assembly,
	section_title_of,
)

CLOSED_DEAL_STATUSES = ("Lost", "Closed", "Converted")

# Copied from a Plant Assembly into an Estimation
ASSEMBLY_FIELDS = (
	"plant_type", "capacity", "capacity_uom", "no_of_trains", "quote_item",
	"default_addon_pct", "contingency_pct", "financing_pct", "include_financing",
	"margin_basis", "profit_pct", "sales_commission_pct", "round_to",
)


def _p(doc, field, value):
	return flt(value, doc.precision(field))


def calculate_pricing(doc):
	"""Fill every computed amount on an Estimation (same formulas as public/js/estimation_pricing.js)."""
	sections = {s.section_title: s for s in doc.get("sections") or []}
	for s in sections.values():
		s.amount = s.addon_amount = s.expense_cost = s.total_cost = 0.0

	for row in doc.get("items") or []:
		if flt(row.qty) < 0 or flt(row.unit_cost) < 0:
			frappe.throw(_("Items row {0}: Qty and Unit Cost cannot be negative.").format(row.idx))
		row.amount = _p(row, "amount", flt(row.qty) * flt(row.unit_cost))
		row.addon_amount = _p(row, "addon_amount", row.amount * flt(row.addon_pct) / 100)
		row.total_cost = _p(row, "total_cost", row.amount + row.addon_amount)
		section = sections.get(row.section)
		if section:
			section.amount += row.amount
			section.addon_amount += row.addon_amount

	manpower = other = untagged = 0.0
	for row in doc.get("expenses") or []:
		if flt(row.qty) < 0 or flt(row.rate) < 0:
			frappe.throw(_("Other Expenses row {0}: Qty and Rate cannot be negative.").format(row.idx))
		row.amount = _p(row, "amount", flt(row.qty) * flt(row.rate))
		section = sections.get(row.section) if row.section else None
		if section:
			section.expense_cost += row.amount
			if section.pricing_mode == OPTIONAL:
				continue
		else:
			untagged += row.amount
		if row.expense_type == EXPENSE_MANPOWER:
			manpower += row.amount
		else:
			other += row.amount

	amount = addon = item_cost = tagged = section_cost = 0.0
	for s in sections.values():
		s.total_cost = s.amount + s.addon_amount + s.expense_cost
		if s.pricing_mode == OPTIONAL:
			continue
		amount += s.amount
		addon += s.addon_amount
		item_cost += s.amount + s.addon_amount
		tagged += s.expense_cost
		section_cost += s.total_cost

	doc.total_amount = _p(doc, "total_amount", amount)
	doc.total_addon = _p(doc, "total_addon", addon)
	doc.total_item_cost = _p(doc, "total_item_cost", item_cost)
	doc.manpower_cost = _p(doc, "manpower_cost", manpower)
	doc.general_cost = _p(doc, "general_cost", other)
	doc.total_other_expenses = _p(doc, "total_other_expenses", tagged + untagged)
	doc.total_cost = _p(doc, "total_cost", item_cost + tagged + untagged)

	financing_on = cint(doc.include_financing)
	doc.contingency_amount = _p(doc, "contingency_amount", doc.total_cost * flt(doc.contingency_pct) / 100)
	doc.financing_amount = _p(doc, "financing_amount", doc.total_cost * flt(doc.financing_pct) / 100)
	doc.cost_price = _p(
		doc, "cost_price", doc.total_cost + doc.contingency_amount + (doc.financing_amount if financing_on else 0)
	)

	# contingencies, financing and untagged expenses spread over the priced sections by their cost
	pct_load = 1 + (flt(doc.contingency_pct) + (flt(doc.financing_pct) if financing_on else 0)) / 100
	load = doc.cost_price / section_cost if section_cost else pct_load
	main = separate = optional = 0.0
	for s in sections.values():
		s.amount = _p(s, "amount", s.amount)
		s.addon_amount = _p(s, "addon_amount", s.addon_amount)
		s.expense_cost = _p(s, "expense_cost", s.expense_cost)
		s.total_cost = _p(s, "total_cost", s.total_cost)
		margin = flt(s.margin_pct) if cint(s.override_margin) else flt(doc.profit_pct)
		base = s.total_cost * (pct_load if s.pricing_mode == OPTIONAL else load)
		s.selling_price = _p(s, "selling_price", apply_margin(base, margin, doc.margin_basis, doc.round_to))
		if s.pricing_mode == OPTIONAL:
			optional += s.selling_price
		elif s.pricing_mode == SEPARATE:
			separate += s.selling_price
		else:
			main += s.selling_price
	if not section_cost and doc.cost_price:
		# only untagged expenses (or no sections at all): priced as the main plant
		main += apply_margin(doc.cost_price, doc.profit_pct, doc.margin_basis, doc.round_to)

	doc.main_price = _p(doc, "main_price", main)
	doc.selling_price = _p(doc, "selling_price", main + separate)
	doc.optional_price = _p(doc, "optional_price", optional)
	doc.sales_commission_amount = _p(
		doc, "sales_commission_amount", doc.selling_price * flt(doc.sales_commission_pct) / 100
	)
	doc.profit_amount = _p(doc, "profit_amount", doc.selling_price - doc.cost_price - doc.sales_commission_amount)
	doc.profit_on_cost_pct = flt(doc.profit_amount / doc.cost_price * 100, 2) if doc.cost_price else 0
	doc.grand_selling_price = _p(doc, "grand_selling_price", doc.selling_price * max(cint(doc.no_of_trains), 1))


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
		self.set_company_and_currency()
		self.validate_customer()
		if cint(self.no_of_trains) < 1:
			self.no_of_trains = 1
		self.validate_sections()
		calculate_pricing(self)

	def before_submit(self):
		if not (self.items or self.expenses):
			frappe.throw(_("Add at least one item or other expense before submitting."), title=_("Cost Sheet Empty"))
		if not self.quote_item:
			frappe.throw(
				_("Set the Quotation Item (the plant item quoted to the client) before submitting."),
				title=_("Quotation Item Missing"),
			)

	def set_company_and_currency(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
				"Global Defaults", "default_company"
			)
		if not self.currency:
			self.currency = (
				self.customer and frappe.db.get_value("Customer", self.customer, "default_currency")
			) or (self.company and frappe.get_cached_value("Company", self.company, "default_currency"))

	def validate_customer(self):
		if not self.customer:
			return
		if frappe.db.get_value("Customer", self.customer, "disabled"):
			frappe.throw(_("Customer {0} is disabled.").format(frappe.bold(self.customer)), title=_("Customer Disabled"))
		if not self.sales_user:
			owner = frappe.db.get_value("Customer", self.customer, "owner")
			if owner and owner not in ("Administrator", "Guest"):
				self.sales_user = owner
		if self.contact_person and not frappe.db.exists(
			"Dynamic Link",
			{"parenttype": "Contact", "parent": self.contact_person, "link_doctype": "Customer", "link_name": self.customer},
		):
			frappe.throw(
				_("Contact {0} is not linked to Customer {1}.").format(
					frappe.bold(self.contact_person), frappe.bold(self.customer)
				),
				title=_("Wrong Contact"),
			)

	def validate_sections(self):
		"""Items belong to a section of the Sub Assemblies table; expenses may (optional)."""
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
						_("Items row {0} ({1}): select its Section.").format(row.idx, frappe.bold(row.cost_head)),
						title=_("Section Missing"),
					)
		for row in [*self.items, *self.expenses]:
			if row.section and row.section not in titles:
				# typed in or imported: add the section instead of losing the cost
				self.append("sections", {"section_title": row.section, "cost_type": "Equipment", "pricing_mode": INCLUDED})
				titles.append(row.section)

		sub_of = {s.section_title: s.sub_assembly for s in self.sections}
		for row in [*self.items, *self.expenses]:
			row.sub_assembly = sub_of.get(row.section) if row.section else None

	# ------------------------------------------------------------------ actions from the form
	@frappe.whitelist()
	def apply_plant_assembly(self):
		"""Replace the sub assemblies, items, expenses and costing defaults with the Plant Assembly's."""
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
		self.set("expenses", [])
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
		"""Add a Sub Assembly (master) as a new section with its standard items and other expenses."""
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
			row.update({"section": title, "sub_assembly": sub.name})
			if row["addon_pct"] is None:
				row["addon_pct"] = 0 if sub.cost_type == MANPOWER else self.default_addon_pct
			self.append("items", row)
		for expense in sub.get("expenses") or []:
			row = {field: expense.get(field) for field in EXPENSE_FIELDS}
			row.update({"section": title, "sub_assembly": sub.name})
			self.append("expenses", row)
		calculate_pricing(self)

	@frappe.whitelist()
	def remove_zero_rows(self):
		"""Drop items and expenses with no quantity or no cost (unused lines of the standard sub assemblies)."""
		self.check_draft()
		items = [row for row in self.items if flt(row.qty) and flt(row.unit_cost)]
		expenses = [row for row in self.expenses if flt(row.qty) and flt(row.rate)]
		removed = len(self.items) - len(items) + len(self.expenses) - len(expenses)
		self.set("items", items)
		self.set("expenses", expenses)
		for table in (self.items, self.expenses):
			for idx, row in enumerate(table, 1):
				row.idx = idx
		calculate_pricing(self)
		return removed

	def check_draft(self):
		if self.docstatus != 0:
			frappe.throw(_("Only a draft Estimation can be changed."))


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
	"""Draft Quotation for the estimation's Customer.

	One line for the plant (Qty = No. of Trains, Rate = main plant price per train) and one line
	per Separate Line sub assembly. Optional sub assemblies are only described in the Technical Offer.
	"""
	from erpnext.controllers.accounts_controller import _get_default_taxes_and_charges
	from erpnext.setup.utils import get_exchange_rate

	est = frappe.db.get_value("Estimation", source_name, ["customer", "opportunity"], as_dict=True)
	if not est or not est.customer:
		frappe.throw(_("Set the Customer on Estimation {0} first.").format(frappe.bold(source_name)))
	if frappe.db.get_value("Customer", est.customer, "disabled"):
		frappe.throw(_("Customer {0} is disabled.").format(frappe.bold(est.customer)))
	deal_open = est.opportunity and frappe.db.get_value("Opportunity", est.opportunity, "status") not in CLOSED_DEAL_STATUSES

	def set_missing_values(source, target):
		target.quotation_to = "Customer"
		target.party_name = source.customer
		target.customer_name = source.customer_name
		target.contact_person = source.contact_person
		target.opportunity = source.opportunity if deal_open else None
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
				"field_map": {"name": "alt_estimation"},
				"field_no_map": [
					"naming_series", "remarks", "items", "sections", "expenses", "customer", "opportunity",
					"total_amount", "total_cost", "selling_price", "amended_from",
				],
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
