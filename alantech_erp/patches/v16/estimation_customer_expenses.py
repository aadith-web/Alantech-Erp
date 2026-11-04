"""Estimation / Technical Offer: Customer instead of Deal, free-text Items + Other Expenses (02-Nov).

1. Estimation and Technical Offer get the Customer of their Deal (a Deal for a Lead uses the
   Customer made from that Lead). The Deal link stays on the Estimation for history.
2. Sub Assemblies of cost type Manpower / General / Services: their cost lines become Standard
   Other Expenses (the add-on goes into the rate, so the cost is unchanged).
3. Estimations: cost lines of Manpower / General / Services sections move to Other Expenses,
   tagged to the same section (section cost and prices unchanged); the new totals (Total Item
   Cost, Total Other Expenses) are filled in. Submitted estimations keep their prices.

Safe to re-run: anything that already has a Customer / Other Expenses is skipped.
"""

import frappe
from frappe.utils import flt

from alantech_erp.proposal import EQUIPMENT, EXPENSE_FIELDS, item_row_as_expense

COST_FIELDS = (
	"total_amount", "total_addon", "total_item_cost", "manpower_cost", "general_cost",
	"total_other_expenses", "total_cost", "contingency_amount", "financing_amount", "cost_price",
)


def execute():
	migrate_customers()
	migrate_sub_assemblies()
	migrate_estimations()


# ---------------------------------------------------------------------- 1. customers
def customer_of_deal(opportunity):
	if not opportunity:
		return None, None
	deal = frappe.db.get_value(
		"Opportunity", opportunity, ["opportunity_from", "party_name", "contact_person"], as_dict=True
	)
	if not deal:
		return None, None
	if deal.opportunity_from == "Customer":
		return deal.party_name, deal.contact_person
	if deal.opportunity_from == "Lead":
		return frappe.db.get_value("Customer", {"lead_name": deal.party_name}, "name"), None
	return None, None


def migrate_customers():
	for est in frappe.get_all(
		"Estimation", filters={"customer": ["is", "not set"]}, fields=["name", "opportunity"]
	):
		customer, contact = customer_of_deal(est.opportunity)
		if customer:
			frappe.db.set_value(
				"Estimation",
				est.name,
				{
					"customer": customer,
					"customer_name": frappe.db.get_value("Customer", customer, "customer_name"),
					"contact_person": contact,
				},
				update_modified=False,
			)

	has_deal = frappe.db.has_column("Technical Offer", "opportunity")
	fields = ["name", "estimation"] + (["opportunity"] if has_deal else [])
	for offer in frappe.get_all("Technical Offer", filters={"customer": ["is", "not set"]}, fields=fields):
		customer = contact = None
		if offer.estimation:
			customer, contact = frappe.db.get_value("Estimation", offer.estimation, ["customer", "contact_person"]) or (None, None)
		if not customer and has_deal:
			customer, contact = customer_of_deal(offer.opportunity)
		if customer:
			frappe.db.set_value(
				"Technical Offer", offer.name, {"customer": customer, "contact_person": contact}, update_modified=False
			)


# ---------------------------------------------------------------------- 2. sub assemblies
def migrate_sub_assemblies():
	for name in frappe.get_all("Sub Assembly", filters={"cost_type": ["!=", EQUIPMENT]}, pluck="name"):
		doc = frappe.get_doc("Sub Assembly", name)
		if doc.get("expenses") or not doc.items:
			continue
		for row in doc.items:
			doc.append("expenses", item_row_as_expense(row.as_dict(), doc.cost_type))
		doc.set("items", [])
		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True
		doc.save()


# ---------------------------------------------------------------------- 3. estimations
def migrate_estimations():
	from alantech_erp.alantech.doctype.estimation.estimation import calculate_pricing

	for name in frappe.get_all("Estimation", filters={"docstatus": ["<", 2]}, pluck="name"):
		frappe.db.savepoint("alt_estimation_expenses")
		try:
			_migrate_estimation(name, calculate_pricing)
		except Exception:
			# one bad legacy record must not stop bench migrate: undo it, fix by hand later
			frappe.db.rollback(save_point="alt_estimation_expenses")
			frappe.log_error(title=f"Estimation {name}: Other Expenses migration skipped")
			print(f"Estimation {name}: skipped, see Error Log.")


def _migrate_estimation(name, calculate_pricing):
	doc = frappe.get_doc("Estimation", name)
	moved = []
	if not doc.get("expenses"):
		cost_type = {s.section_title: s.cost_type for s in doc.sections}
		for row in doc.items:
			section_type = cost_type.get(row.section) or EQUIPMENT
			if section_type == EQUIPMENT:
				continue
			expense = item_row_as_expense(row.as_dict(), section_type)
			doc.append("expenses", {**{f: expense[f] for f in EXPENSE_FIELDS}, "section": row.section})
			moved.append(row)
	if moved:
		doc.set("items", [row for row in doc.items if row not in moved])
		for idx, row in enumerate(doc.items, 1):
			row.idx = idx

	before = {"main_price": doc.main_price, "selling_price": doc.selling_price}
	doc.validate_sections()
	calculate_pricing(doc)

	if moved:
		frappe.db.delete("Estimation Item", {"name": ["in", [row.name for row in moved]]})
	for row in doc.items:
		row.db_update()
	for row in doc.expenses:
		_save_row(row, "Estimation Expense")
	for row in doc.sections:
		if doc.docstatus == 1 and not _is_new(row, "Estimation Section"):
			frappe.db.set_value(
				"Estimation Section", row.name, {"expense_cost": row.expense_cost}, update_modified=False
			)
		else:
			_save_row(row, "Estimation Section")

	values = {field: doc.get(field) for field in COST_FIELDS}
	if doc.docstatus == 0:
		values.update(
			{field: doc.get(field) for field in (
				"main_price", "selling_price", "optional_price", "sales_commission_amount",
				"profit_amount", "profit_on_cost_pct", "grand_selling_price",
			)}
		)
	elif abs(flt(before["selling_price"]) - flt(doc.selling_price)) > 1:
		print(f"Estimation {name}: submitted price kept ({before['selling_price']}, recalculated {doc.selling_price}).")
	frappe.db.set_value("Estimation", name, values, update_modified=False)


def _is_new(row, doctype):
	return bool(row.get("__islocal")) or not row.name or not frappe.db.exists(doctype, row.name)


def _save_row(row, doctype):
	row.docstatus = frappe.db.get_value(row.parenttype, row.parent, "docstatus") or 0
	if _is_new(row, doctype):
		row.db_insert()
	else:
		row.db_update()
