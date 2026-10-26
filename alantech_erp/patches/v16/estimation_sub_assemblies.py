"""Move Estimations to the Plant Assembly / Sub Assembly structure.

1. Each Estimation Template becomes a Plant Assembly; its cost item sections become Sub Assemblies
   (with the template's cost items) and its equipment specifications become offer components.
2. Every Estimation gets a Sub Assemblies (sections) table built from the sections of its cost
   items, and its Plant Assembly is set from the old Plant Template.
3. Estimations that had proposal data (project data, raw water analysis, equipment specs) get a
   draft Technical Offer holding that data.

Nothing is deleted here. The Estimation Template doctype has no files any more, so `bench migrate`
removes its DocType record afterwards (the table and rows stay in the database).
"""

from collections import OrderedDict

import frappe

GENERAL = "General"
TEMPLATE_FIELDS = (
	"plant_type", "capacity", "capacity_uom", "no_of_trains", "quote_item",
	"default_addon_pct", "contingency_pct", "financing_pct", "include_financing",
	"profit_pct", "sales_commission_pct",
)


def execute():
	assembly_of = migrate_templates() if frappe.db.table_exists("Estimation Template") else {}
	migrate_estimations(assembly_of)
	migrate_proposal_data()


def rows(child, parenttype, parent, parentfield=None):
	filters = {"parenttype": parenttype, "parent": parent}
	if parentfield:
		filters["parentfield"] = parentfield
	return frappe.get_all(child, filters=filters, fields="*", order_by="idx asc")


def migrate_templates():
	assembly_of = {}
	columns = set(frappe.db.get_table_columns("Estimation Template"))
	for tpl in frappe.db.sql("select * from `tabEstimation Template`", as_dict=True):
		name = tpl.get("template_name") or tpl.name
		if frappe.db.exists("Plant Assembly", name):
			assembly_of[tpl.name] = name
			continue

		items = rows("Estimation Item", "Estimation Template", tpl.name, "items")
		specs = rows("Estimation Technical Data", "Estimation Template", tpl.name, "equipment_specs")
		groups = OrderedDict()
		for spec in specs:
			groups.setdefault(spec.group_title or GENERAL, []).append(spec)
		sections = OrderedDict()
		for item in items:
			sections.setdefault((item.section or "").strip() or GENERAL, []).append(item)

		assembly = frappe.new_doc("Plant Assembly")
		assembly.assembly_name = name
		for field in TEMPLATE_FIELDS:
			if field in columns:
				assembly.set(field, tpl.get(field))
		for table in ("project_data", "water_analysis"):
			for row in rows("Estimation Technical Data", "Estimation Template", tpl.name, table):
				assembly.append(table, {f: row.get(f) for f in ("group_title", "parameter", "value", "unit")})

		for section, section_items in sections.items():
			sub = make_sub_assembly(section, tpl.name, section_items, groups.pop(section, []))
			assembly.append("sections", {"sub_assembly": sub, "section_title": section, "pricing_mode": "Included"})
		if groups:
			specs_left = [spec for group in groups.values() for spec in group]
			sub = make_sub_assembly("Specifications", tpl.name, [], specs_left, cost_type="Services")
			assembly.append("sections", {"sub_assembly": sub, "section_title": "Specifications"})

		assembly.disabled = tpl.get("disabled") or 0
		assembly.flags.ignore_permissions = True
		assembly.flags.ignore_mandatory = True
		assembly.insert()
		assembly_of[tpl.name] = assembly.name
	return assembly_of


def make_sub_assembly(section, template, items, specs, cost_type="Equipment"):
	# named after the template too, so they never take the name of a standard library sub assembly
	name = section if section.endswith(f" - {template}") else f"{section} - {template}"
	if frappe.db.exists("Sub Assembly", name):
		return name
	sub = frappe.new_doc("Sub Assembly")
	sub.sub_assembly_name = name
	sub.offer_title = section
	sub.price_description = section
	sub.cost_type = cost_type
	for item in items:
		sub.append("items", {
			"cost_head": item.cost_head or item.item_code or "-",
			"item_code": item.item_code,
			"qty": item.qty,
			"uom": item.uom,
			"unit_cost": item.unit_cost,
			"addon_pct": item.addon_pct,
		})
	by_group = OrderedDict()
	for spec in specs:
		by_group.setdefault(spec.group_title or section, []).append(spec)
	for group, group_specs in by_group.items():
		sub.append("components", {"title": group, "specs": specs_text(group_specs)})
	sub.flags.ignore_permissions = True
	sub.flags.ignore_links = True
	sub.insert()
	return sub.name


def specs_text(specs):
	return "\n".join(" | ".join(p for p in (s.parameter or "", s.value or "", s.unit or "")).rstrip(" |") for s in specs)


def migrate_estimations(assembly_of):
	from alantech_erp.alantech.doctype.estimation.estimation import calculate_pricing

	has_template_col = frappe.db.has_column("Estimation", "estimation_template")
	for name in frappe.get_all("Estimation", pluck="name"):
		if has_template_col:
			template = frappe.db.get_value("Estimation", name, "estimation_template")
			if template and assembly_of.get(template) and not frappe.db.get_value("Estimation", name, "plant_assembly"):
				frappe.db.set_value("Estimation", name, "plant_assembly", assembly_of[template], update_modified=False)

		if frappe.db.exists("Estimation Section", {"parenttype": "Estimation", "parent": name}):
			continue
		doc = frappe.get_doc("Estimation", name)
		if not doc.items:
			continue
		titles = []
		for item in doc.items:
			if not (item.section or "").strip():
				item.section = GENERAL
				frappe.db.set_value("Estimation Item", item.name, "section", GENERAL, update_modified=False)
			if item.section not in titles:
				titles.append(item.section)
		for title in titles:
			doc.append("sections", {"section_title": title, "cost_type": "Equipment", "pricing_mode": "Included", "include_in_offer": 1})
		calculate_pricing(doc)
		for row in doc.sections:
			row.db_insert()
		doc.db_set(
			{
				"main_price": doc.main_price,
				"optional_price": doc.optional_price,
				"equipment_cost": doc.equipment_cost,
				"manpower_cost": doc.manpower_cost,
				"general_cost": doc.general_cost,
				"margin_basis": doc.margin_basis or "Markup on Cost",
			},
			update_modified=False,
		)


def migrate_proposal_data():
	"""Proposal tables that used to sit on the Estimation go to a draft Technical Offer."""
	estimations = frappe.get_all(
		"Estimation Technical Data", filters={"parenttype": "Estimation"}, pluck="parent", distinct=True
	)
	for name in estimations:
		if frappe.db.exists("Technical Offer", {"estimation": name}):
			continue
		est = frappe.db.get_value(
			"Estimation", name, ["name", "opportunity", "customer_name", "company", "currency", "docstatus"], as_dict=True
		)
		if not est or est.docstatus == 2:
			continue
		offer = frappe.new_doc("Technical Offer")
		offer.update({
			"estimation": est.name, "opportunity": est.opportunity, "customer_name": est.customer_name,
			"company": est.company, "currency": est.currency,
		})
		for table in ("project_data", "water_analysis"):
			for row in rows("Estimation Technical Data", "Estimation", name, table):
				offer.append(table, {f: row.get(f) for f in ("group_title", "parameter", "value", "unit")})
		specs = rows("Estimation Technical Data", "Estimation", name, "equipment_specs")
		if specs:
			section = "Equipment Specifications"
			offer.append("sections", {"section_title": section})
			by_group = OrderedDict()
			for spec in specs:
				by_group.setdefault(spec.group_title or section, []).append(spec)
			for group, group_specs in by_group.items():
				offer.append("components", {"section": section, "title": group, "specs": specs_text(group_specs)})
		offer.flags.ignore_permissions = True
		offer.flags.ignore_mandatory = True
		offer.insert()
