"""Costing and technical offers for water treatment plants.

Library (masters):
    Sub Assembly    one block of a plant (Multimedia Filter, RO System, Direct Labour...):
                    standard cost items + standard offer text (components with spec tables)
    Plant Assembly  a plant type: ordered Sub Assemblies + costing and offer defaults
    Proposal Settings  company-wide texts, terms, bank details, letter head

Transactions:
    Estimation      costing for a Deal. Assembly -> sub assemblies -> items, then contingencies,
                    financing and margin give the selling price (see estimation.py)
    Technical Offer the proposal document (detailed or single page), built from the same
                    sub assemblies; printed on its own or with its Quotation

Values the engineer must fill in per project are written as [[value]] in the standard text.
A Technical Offer cannot be submitted while any [[ ]] is left.
"""

import re

import frappe
from frappe import _

INCLUDED = "Included"
SEPARATE = "Separate Line"
OPTIONAL = "Optional"

MANPOWER = "Manpower"

DETAILED = "Detailed Proposal"
SINGLE_PAGE = "Single Page Offer"

# [[value to confirm]]; the text inside is the default shown when filling in
PLACEHOLDER = re.compile(r"\[\[(.*?)\]\]", re.S)

# Text fields on the Technical Offer (and its child tables) that may hold [[ ]]
OFFER_TEXT_FIELDS = (
	"project_name", "project_location", "subject", "kind_attn", "your_ref",
	"intro_text", "water_analysis_intro", "water_analysis_remarks",
	"scope_of_supply", "commercial_terms", "bank_details", "price_heading", "price_notes",
)
OFFER_TABLE_FIELDS = {
	"guarantees": ("parameter", "value", "unit"),
	"project_data": ("parameter", "value", "unit"),
	"water_analysis": ("parameter", "value", "unit"),
	"sections": ("description", "specs", "notes"),
	"components": ("qty_label", "title", "description", "specs", "notes"),
	"price_lines": ("description",),
}

COMPONENT_FIELDS = ("qty_label", "title", "is_heading", "page_break", "description", "specs", "notes")
TECH_DATA_FIELDS = ("group_title", "parameter", "value", "unit")


def section_title_of(sub_assembly):
	"""Default section heading for a Sub Assembly (its offer heading, else its name)."""
	return frappe.db.get_value("Sub Assembly", sub_assembly, "offer_title") or sub_assembly


def get_sub_assembly(name):
	doc = frappe.get_cached_doc("Sub Assembly", name)
	if doc.disabled:
		frappe.throw(_("Sub Assembly {0} is disabled.").format(frappe.bold(name)))
	return doc


def find_placeholders(doc):
	"""[(where, field label, current text)] for every [[ ]] left in a Technical Offer."""
	found = []
	meta = doc.meta
	for field in OFFER_TEXT_FIELDS:
		if PLACEHOLDER.search(doc.get(field) or ""):
			found.append((_(meta.get_label(field)), doc.get(field)))
	for table, fields in OFFER_TABLE_FIELDS.items():
		label = _(meta.get_label(table))
		for row in doc.get(table) or []:
			for field in fields:
				if PLACEHOLDER.search(row.get(field) or ""):
					where = row.get("title") or row.get("section_title") or row.get("parameter") or row.get("description")
					found.append((f"{label} #{row.idx} {strip_html(where)[:60]}", row.get(field)))
	return found


def fmt_num(value):
	"""160.0 -> "160", 2.5 -> "2.5" (for capacities in titles)."""
	from frappe.utils import flt

	return ("%f" % flt(value)).rstrip("0").rstrip(".")


def strip_html(text):
	return re.sub(r"<[^>]+>", " ", text or "").strip()


def parse_specs(text):
	"""Split a specification text into tables.

	Each line is "Parameter | Value | Unit" (any number of cells). A line without "|" is a
	group heading row. An empty line ends the current table.
	Returns [[{"group": str} | {"cells": [str, ...]}]].
	"""
	tables, rows = [], []
	for line in (text or "").splitlines():
		line = line.strip()
		if not line:
			if rows:
				tables.append(rows)
				rows = []
			continue
		if "|" in line:
			rows.append({"cells": [c.strip() for c in line.split("|")]})
		else:
			rows.append({"group": line})
	if rows:
		tables.append(rows)
	return tables
