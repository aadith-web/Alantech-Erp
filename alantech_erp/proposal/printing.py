"""Data for the print formats (registered as Jinja methods in hooks.py).

    get_offer_context(offer)       -> Alantech Technical Offer / Alantech Proposal (Quotation)
    get_cost_sheet_context(est)    -> Alantech Cost Sheet (Estimation)

Values still to fill in ([[ ]]) are printed highlighted so a draft shows what is open.
"""

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt, fmt_money, formatdate

from alantech_erp.proposal import INCLUDED, OPTIONAL, PLACEHOLDER, SEPARATE, SINGLE_PAGE, parse_specs

def mark(html):
	"""Highlight [[ ]] in HTML text (Text Editor content)."""
	return PLACEHOLDER.sub(lambda m: f'<span class="alt-fill">{m.group(1) or "&nbsp;&nbsp;&nbsp;"}</span>', html or "")


def mark_text(text):
	"""Escape plain text, then highlight [[ ]]."""
	return mark(escape_html(text or ""))


def has_text(html):
	return bool(frappe.utils.strip_html(html or "").strip()) or "<img" in (html or "")


def spec_tables(text):
	tables = []
	for table in parse_specs(text):
		rows = []
		width = max((len(r["cells"]) for r in table if "cells" in r), default=2)
		for r in table:
			if "group" in r:
				rows.append({"group": mark_text(r["group"]), "span": max(width, 2)})
			else:
				cells = [mark_text(c) for c in r["cells"]]
				cells += [""] * (width - len(cells))
				rows.append({"cells": cells})
		tables.append({"rows": rows, "width": max(width, 2)})
	return tables


def money(amount, currency, precision=0):
	return fmt_money(flt(amount), precision=precision, currency=currency)


def get_offer_context(offer):
	"""Everything the technical offer templates print, grouped and numbered."""
	if isinstance(offer, str):
		offer = frappe.get_doc("Technical Offer", offer)

	components_by_section = {}
	for c in offer.components:
		components_by_section.setdefault(c.section, []).append(c)

	sections = []
	for no, s in enumerate(offer.sections, 1):
		components = []
		for c in components_by_section.get(s.section_title, []):
			components.append({
				"qty": mark_text(c.qty_label),
				"title": mark_text(c.title),
				"is_heading": cint(c.is_heading),
				"page_break": cint(c.page_break),
				"description": mark(c.description) if has_text(c.description) else "",
				"tables": spec_tables(c.specs),
				"notes": mark(c.notes) if has_text(c.notes) else "",
			})
		sections.append({
			"no": no,
			"title": mark_text(s.section_title),
			"page_break": cint(s.page_break),
			"description": mark(s.description) if has_text(s.description) else "",
			"tables": spec_tables(s.specs),
			"notes": mark(s.notes) if has_text(s.notes) else "",
			"components": components,
		})

	return {
		"offer": offer,
		"single_page": offer.offer_format == SINGLE_PAGE,
		"offer_no": offer.offer_no or offer.name,
		"date": formatdate(offer.offer_date, "MMMM d, yyyy") if offer.offer_date else "",
		"valid_till": formatdate(offer.valid_till) if offer.valid_till else "",
		"customer": offer.customer_name or "",
		"project_name": mark_text(offer.project_name),
		"project_location": mark_text(offer.project_location),
		"subject": mark_text(offer.subject),
		"kind_attn": mark_text(offer.kind_attn),
		"your_ref": mark_text(offer.your_ref),
		"intro_text": mark(offer.intro_text) if has_text(offer.intro_text) else "",
		"guarantees": tech_rows(offer.guarantees),
		"project_data": tech_rows(offer.project_data),
		"water_analysis": tech_rows(offer.water_analysis),
		"water_analysis_intro": mark(offer.water_analysis_intro) if has_text(offer.water_analysis_intro) else "",
		"water_analysis_remarks": mark(offer.water_analysis_remarks) if has_text(offer.water_analysis_remarks) else "",
		"sections": sections,
		"scope_of_supply": mark(offer.scope_of_supply) if has_text(offer.scope_of_supply) else "",
		"commercial_terms": mark(offer.commercial_terms) if has_text(offer.commercial_terms) else "",
		"bank_details": mark_text(offer.bank_details).replace("\n", "<br>") if offer.bank_details else "",
		"pricing": price_schedule(offer),
		"price_notes": mark(offer.price_notes) if has_text(offer.price_notes) else "",
		"bought_out_items": [{"item_group": escape_html(r.item_group), "manufacturer": escape_html(r.manufacturer or "")} for r in offer.bought_out_items],
	}


def tech_rows(rows):
	out = []
	for r in rows or []:
		out.append({
			"group": mark_text(r.group_title),
			"parameter": mark_text(r.parameter),
			"value": mark_text(r.value),
			"unit": mark_text(r.unit),
		})
	return out


def price_schedule(offer):
	"""Rows of section D. Pricing: heading, numbered lines, main price, separate lines, total, optional."""
	cur = offer.currency
	show = cint(offer.show_line_prices)
	rows = []
	included = [r for r in offer.price_lines if (r.pricing_mode or INCLUDED) == INCLUDED]
	separate = [r for r in offer.price_lines if r.pricing_mode == SEPARATE]
	optional = [r for r in offer.price_lines if r.pricing_mode == OPTIONAL]
	if not offer.price_lines:
		return {"rows": [], "optional": [], "currency": cur}

	if offer.price_heading:
		rows.append({"kind": "heading", "no": "A", "text": mark_text(offer.price_heading), "amount": ""})
	n = 0
	for r in included:
		n += 1
		rows.append({"kind": "line", "no": n, "text": mark_text(r.description), "amount": money(r.amount, cur) if show else ""})
	if separate:
		rows.append({"kind": "subtotal", "no": "", "text": mark_text(offer.main_price_label or _("Price ex works")), "amount": money(offer.main_total, cur)})
		for r in separate:
			n += 1
			rows.append({"kind": "line", "no": n, "text": mark_text(r.description), "amount": money(r.amount, cur)})
	rows.append({
		"kind": "total",
		"no": "B" if offer.price_heading else "",
		"text": mark_text(offer.total_label or offer.main_price_label or _("Total price")),
		"amount": money(offer.grand_total, cur),
	})
	opt = [{"no": i, "text": mark_text(r.description), "amount": money(r.amount, cur)} for i, r in enumerate(optional, 1)]
	return {"rows": rows, "optional": opt, "currency": cur}


def get_cost_sheet_context(est):
	"""Estimation grouped by section with sub totals, like the costing workbook."""
	if isinstance(est, str):
		est = frappe.get_doc("Estimation", est)
	cur = est.currency
	by_section = {}
	for row in est.items:
		by_section.setdefault(row.section, []).append(row)
	groups = []
	sl = 0
	for s in est.sections:
		items = []
		for row in by_section.get(s.section_title, []):
			sl += 1
			items.append({
				"sl": sl, "item": row.cost_head, "type_model": row.type_model or "", "moc": row.moc or "",
				"make": row.make or "", "qty": frappe.format(row.qty, {"fieldtype": "Float"}),
				"unit_cost": money(row.unit_cost, cur, 2), "amount": money(row.amount, cur, 2),
				"transport": money(row.addon_amount, cur, 2), "total": money(row.total_cost, cur, 2),
			})
		groups.append({
			"title": s.section_title, "mode": s.pricing_mode, "cost_type": s.cost_type, "items": items,
			"amount": money(s.amount, cur, 2), "transport": money(s.addon_amount, cur, 2),
			"total": money(s.total_cost, cur, 2), "selling": money(s.selling_price, cur, 0),
		})
	totals = {
		field: money(est.get(field), cur, 0 if field in ("main_price", "selling_price", "optional_price", "grand_selling_price") else 2)
		for field in (
			"total_amount", "total_addon", "total_cost", "equipment_cost", "manpower_cost", "general_cost",
			"contingency_amount", "financing_amount", "cost_price", "main_price", "selling_price",
			"optional_price", "sales_commission_amount", "profit_amount", "grand_selling_price",
		)
	}
	return {"groups": groups, "currency": cur, "totals": totals}
