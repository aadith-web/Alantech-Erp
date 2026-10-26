# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Technical Offer: the proposal sent to the client, detailed (cover, letter, design basis,
process items, scope, commercial conditions, pricing) or as a single page offer.

Built from a Plant Assembly (standard sections and text) or from an Estimation (its sections and
prices). Each section's components come from its Sub Assembly and are edited per project; values
to confirm are written as [[value]] and must all be filled in before the offer is submitted.

Revisions: cancel and amend. The amended offer gets the next revision number, printed as
<offer no>/Rev<n>. A Quotation links to its Technical Offer (alt_technical_offer) and prints it.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate

from alantech_erp.proposal import (
	COMPONENT_FIELDS,
	INCLUDED,
	OPTIONAL,
	SEPARATE,
	SINGLE_PAGE,
	TECH_DATA_FIELDS,
	find_placeholders,
	fmt_num,
	get_sub_assembly,
	section_title_of,
)

SETTINGS = "Proposal Settings"

# Text defaults: Technical Offer field <- (Plant Assembly field, Proposal Settings field)
TEXT_DEFAULTS = {
	"subject": ("subject", None),
	"intro_text": ("intro_text", "intro_text"),
	"cover_image": ("cover_image", None),
	"flow_diagram": ("flow_diagram", None),
	"water_analysis_intro": (None, "water_analysis_intro"),
	"water_analysis_remarks": (None, "water_analysis_remarks"),
	"price_notes": ("price_notes", "price_notes"),
	"bank_details": (None, "bank_details"),
	"letter_head": (None, "letter_head"),
	"place": (None, "place"),
	"signatory_name": (None, "signatory_name"),
	"signatory_contact": (None, "signatory_contact"),
}
TERMS_DEFAULTS = {
	# Technical Offer template field, text field <- Plant Assembly field / Proposal Settings field
	"scope_of_supply_terms": ("scope_of_supply", "scope_of_supply_terms", "scope_of_supply_terms"),
	"commercial_terms_template": ("commercial_terms", "commercial_terms", "commercial_terms"),
}
TABLE_DEFAULTS = {
	"guarantees": ("guarantees", None),
	"project_data": ("project_data", None),
	"water_analysis": ("water_analysis", None),
	"bought_out_items": ("bought_out_items", "bought_out_items"),
}


class TechnicalOffer(Document):
	def validate(self):
		self.set_missing_values()
		self.set_offer_no()
		self.validate_estimation()
		self.validate_sections()
		self.calculate_totals()
		if self.docstatus == 0:
			left = find_placeholders(self)
			if left:
				frappe.msgprint(
					_("{0} values are still to be filled in ([[ ]]). Use Fill In Values before submitting.").format(len(left)),
					indicator="orange",
					alert=True,
				)

	def before_insert(self):
		# Link fields named letter_head start with the site's default letter head; proposals use
		# the one in Proposal Settings unless another was picked
		letter_head = frappe.db.get_single_value(SETTINGS, "letter_head")
		default = frappe.db.get_value("Letter Head", {"is_default": 1}, "name")
		if letter_head and self.letter_head in (None, "", default):
			self.letter_head = letter_head

	def before_submit(self):
		left = find_placeholders(self)
		if left:
			rows = "".join(f"<li>{frappe.utils.escape_html(where)}</li>" for where, _text in left[:25])
			more = _("<p>... and {0} more</p>").format(len(left) - 25) if len(left) > 25 else ""
			frappe.throw(
				_("Fill in these values ([[ ]]) before submitting the offer:") + f"<ul>{rows}</ul>{more}",
				title=_("Values to Fill In"),
			)
		if not self.sections:
			frappe.throw(_("Add at least one section to the offer."), title=_("Offer Empty"))

	# ------------------------------------------------------------------ validation helpers
	def set_missing_values(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
				"Global Defaults", "default_company"
			)
		if not self.currency and self.company:
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		settings = frappe.get_cached_doc(SETTINGS)
		for field in ("letter_head", "place", "signatory_name", "signatory_contact", "bank_details"):
			if not self.get(field):
				self.set(field, settings.get(field))
		if not self.offer_date:
			self.offer_date = nowdate()

	def set_offer_no(self):
		if self.amended_from:
			self.revision = cint(frappe.db.get_value("Technical Offer", self.amended_from, "revision")) + 1
		else:
			self.revision = 0
		base = re.sub(r"-\d+$", "", self.name) if self.amended_from else self.name
		if base and not base.startswith("new-"):
			self.offer_no = f"{base}/Rev{self.revision}"

	def validate_estimation(self):
		if not self.estimation:
			return
		est = frappe.db.get_value("Estimation", self.estimation, ["opportunity", "docstatus"], as_dict=True)
		if est.docstatus == 2:
			frappe.throw(_("Estimation {0} is cancelled.").format(frappe.bold(self.estimation)))
		if not self.opportunity:
			self.opportunity = est.opportunity
		elif est.opportunity != self.opportunity:
			frappe.throw(
				_("Estimation {0} belongs to Deal {1}, not {2}.").format(
					frappe.bold(self.estimation), frappe.bold(est.opportunity), frappe.bold(self.opportunity)
				),
				title=_("Wrong Estimation"),
			)

	def validate_sections(self):
		titles = []
		for s in self.sections:
			s.section_title = (s.section_title or "").strip()
			if s.section_title in titles:
				frappe.throw(
					_("Sections row {0}: {1} is used twice.").format(s.idx, frappe.bold(s.section_title)),
					title=_("Duplicate Section"),
				)
			titles.append(s.section_title)
		for row in self.components:
			if not row.section and len(titles) == 1:
				row.section = titles[0]
			if not row.section:
				frappe.throw(
					_("Components row {0} ({1}): select its Section.").format(row.idx, frappe.bold(row.title)),
					title=_("Section Missing"),
				)
			if row.section not in titles:
				self.append("sections", {"section_title": row.section})
				titles.append(row.section)

	def calculate_totals(self):
		totals = {INCLUDED: 0.0, SEPARATE: 0.0, OPTIONAL: 0.0}
		for row in self.price_lines:
			row.pricing_mode = row.pricing_mode or INCLUDED
			totals[row.pricing_mode] += flt(row.amount)
		self.main_total = flt(totals[INCLUDED], self.precision("main_total"))
		self.separate_total = flt(totals[SEPARATE], self.precision("separate_total"))
		self.optional_total = flt(totals[OPTIONAL], self.precision("optional_total"))
		self.grand_total = flt(self.main_total + self.separate_total, self.precision("grand_total"))

	# ------------------------------------------------------------------ actions from the form
	@frappe.whitelist()
	def apply_plant_assembly(self, keep_sections=False):
		"""Load the Plant Assembly's offer defaults and (unless keep_sections) its sections."""
		self.check_draft()
		if not self.plant_assembly:
			return
		assembly = frappe.get_doc("Plant Assembly", self.plant_assembly)
		assembly.check_permission("read")
		settings = frappe.get_cached_doc(SETTINGS)

		self.offer_format = assembly.offer_format or self.offer_format
		for field, (assembly_field, settings_field) in TEXT_DEFAULTS.items():
			value = (assembly.get(assembly_field) if assembly_field else None) or (
				settings.get(settings_field) if settings_field else None
			)
			if value:
				self.set(field, value)
		single_page = self.offer_format == SINGLE_PAGE
		for template_field, (text_field, assembly_field, settings_field) in TERMS_DEFAULTS.items():
			# a single page offer only carries the terms its assembly names
			template = assembly.get(assembly_field) or (None if single_page else settings.get(settings_field))
			if template:
				self.set(template_field, template)
				self.set(text_field, get_terms_text(template, self))
		for table, (assembly_table, settings_table) in TABLE_DEFAULTS.items():
			rows = assembly.get(assembly_table) or (settings.get(settings_table) if settings_table else None) or []
			if rows:
				fields = TECH_DATA_FIELDS if table != "bought_out_items" else ("item_group", "manufacturer")
				self.set(table, [{f: r.get(f) for f in fields} for r in rows])
		if not self.price_heading and assembly.capacity:
			self.price_heading = _("Process Items - {0} {1} capacity").format(
				fmt_num(assembly.capacity), assembly.capacity_uom or ""
			).strip()
		if not self.project_name and assembly.capacity:
			self.project_name = f"{fmt_num(assembly.capacity)} {assembly.capacity_uom or ''} {assembly.plant_type or ''}".strip()

		if not cint(keep_sections):
			self.set("sections", [])
			self.set("components", [])
			for row in assembly.sections:
				if cint(row.include_in_offer):
					self.add_sub_assembly(row.sub_assembly, row.section_title)

	@frappe.whitelist()
	def add_sub_assembly(self, sub_assembly, section_title=None):
		"""Add a section with the Sub Assembly's standard text and components."""
		self.check_draft()
		sub = get_sub_assembly(sub_assembly)
		title = (section_title or "").strip() or section_title_of(sub.name)
		if any(s.section_title == title for s in self.sections):
			frappe.throw(
				_("Section {0} is already in this offer.").format(frappe.bold(title)), title=_("Duplicate Section")
			)
		self.append(
			"sections",
			{
				"section_title": title,
				"sub_assembly": sub.name,
				"description": sub.description,
				"specs": sub.specs,
				"notes": sub.notes,
			},
		)
		for comp in sub.components:
			row = {field: comp.get(field) for field in COMPONENT_FIELDS}
			row["section"] = title
			self.append("components", row)

	@frappe.whitelist()
	def fetch_prices(self):
		"""Rebuild the price schedule from the Estimation's section prices."""
		self.check_draft()
		if not self.estimation:
			frappe.throw(_("Select the Estimation first."))
		est = frappe.get_doc("Estimation", self.estimation)
		est.check_permission("read")
		self.set("price_lines", price_lines_from_estimation(est))
		if not self.price_heading and est.capacity:
			self.price_heading = _("Process Items - {0} {1} capacity").format(
				fmt_num(est.capacity), est.capacity_uom or ""
			).strip()
		self.calculate_totals()

	def check_draft(self):
		if self.docstatus != 0:
			frappe.throw(_("Only a draft Technical Offer can be changed."))


def get_terms_text(template, doc=None):
	from erpnext.setup.doctype.terms_and_conditions.terms_and_conditions import get_terms_and_conditions

	return get_terms_and_conditions(template, doc.as_dict() if doc else {})


def price_lines_from_estimation(est):
	"""Price schedule rows (amounts for all trains) from an Estimation's sections.

	Included sections with a Price Schedule Line are listed; the price of Included sections
	without one (labour, general costs...) is spread over the listed lines in proportion, so the
	lines add up to the main plant price. Separate Line and Optional sections are always listed.
	"""
	trains = max(cint(est.no_of_trains), 1)
	step = cint(est.round_to) or 0
	included = [s for s in est.sections if (s.pricing_mode or INCLUDED) == INCLUDED]
	listed = [s for s in included if s.price_description]
	unlisted = sum(flt(s.selling_price) for s in included if not s.price_description)
	base = sum(flt(s.selling_price) for s in listed)
	main_total = flt(est.main_price) * trains

	lines = []
	if listed:
		for s in listed:
			share = unlisted * flt(s.selling_price) / base if base else (unlisted if s is listed[0] else 0)
			amount = (flt(s.selling_price) + share) * trains
			if step > 1:
				amount = round(amount / step) * step
			lines.append({"description": s.price_description, "pricing_mode": INCLUDED, "amount": amount, "section_title": s.section_title})
		diff = main_total - sum(line["amount"] for line in lines)
		if abs(diff) >= 0.005:
			max(lines, key=lambda line: line["amount"])["amount"] += diff
	elif main_total:
		description = " ".join(p for p in (est.plant_type, f"{fmt_num(est.capacity)} {est.capacity_uom or ''}".strip() if est.capacity else "") if p)
		lines.append({"description": description or _("Water treatment plant"), "pricing_mode": INCLUDED, "amount": main_total})

	for mode in (SEPARATE, OPTIONAL):
		for s in est.sections:
			if s.pricing_mode == mode and flt(s.selling_price):
				lines.append({
					"description": s.price_description or s.section_title,
					"pricing_mode": mode,
					"amount": flt(s.selling_price) * trains,
					"section_title": s.section_title,
				})
	return lines


def make_from_estimation(estimation):
	est = frappe.get_doc("Estimation", estimation)
	est.check_permission("read")
	if est.docstatus == 2:
		frappe.throw(_("Estimation {0} is cancelled.").format(frappe.bold(est.name)))

	offer = frappe.new_doc("Technical Offer")
	offer.estimation = est.name
	offer.opportunity = est.opportunity
	offer.customer_name = est.customer_name
	offer.company = est.company
	offer.currency = est.currency
	offer.offer_date = getdate()
	if est.capacity:
		offer.project_name = f"{fmt_num(est.capacity)} {est.capacity_uom or ''} {est.plant_type or ''}".strip()
	contact = frappe.db.get_value("Opportunity", est.opportunity, "contact_display")
	if contact:
		offer.kind_attn = contact

	if est.plant_assembly:
		offer.plant_assembly = est.plant_assembly
		offer.apply_plant_assembly(keep_sections=True)
	else:
		offer.set_missing_values()
		settings = frappe.get_cached_doc(SETTINGS)
		for field, (_assembly_field, settings_field) in TEXT_DEFAULTS.items():
			if settings_field and settings.get(settings_field) and not offer.get(field):
				offer.set(field, settings.get(settings_field))
		for template_field, (text_field, _assembly_field, settings_field) in TERMS_DEFAULTS.items():
			if settings.get(settings_field):
				offer.set(template_field, settings.get(settings_field))
				offer.set(text_field, get_terms_text(settings.get(settings_field), offer))
		offer.set(
			"bought_out_items",
			[{"item_group": r.item_group, "manufacturer": r.manufacturer} for r in settings.bought_out_items],
		)

	for s in est.sections:
		if not cint(s.include_in_offer):
			continue
		if s.sub_assembly and frappe.db.exists("Sub Assembly", {"name": s.sub_assembly, "disabled": 0}):
			offer.add_sub_assembly(s.sub_assembly, s.section_title)
		else:
			offer.append("sections", {"section_title": s.section_title})

	offer.set("price_lines", price_lines_from_estimation(est))
	if not offer.price_heading and est.capacity:
		offer.price_heading = _("Process Items - {0} {1} capacity").format(
			fmt_num(est.capacity), est.capacity_uom or ""
		).strip()
	offer.calculate_totals()
	return offer
