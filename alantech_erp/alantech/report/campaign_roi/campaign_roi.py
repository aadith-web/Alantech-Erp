# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Campaign ROI (CRM C36): what each campaign cost and what it brought in.

Filters: Company, From / To Date, Campaign (that campaign and its child campaigns), Status,
Campaign Type, Campaign Owner.

Per campaign: Budget, Actual Cost (Campaign Cost rows dated in the period), Leads and Customers
(created in the period), Deals, Quotations Sent (submitted) and Sales Orders (submitted) dated in
the period, Income (net total of those Sales Orders, company currency), Profit, ROI %, Cost per
Lead and Win Rate (orders / quotations sent).

Child campaigns are shown under their parent (tree); a parent row adds up its own figures and its
child campaigns'. The summary cards add up each campaign once.
"""

import frappe
from frappe import _
from frappe.utils import flt

from alantech_erp.sales import campaign as c


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Please select a Company."))
	if filters.from_date and filters.to_date and filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	campaigns = get_campaigns(filters)
	if not campaigns:
		return get_columns(), [], None, None, []

	names = [r.name for r in campaigns]
	own = c.campaign_results(names, filters.company, filters.from_date, filters.to_date)
	shown = set(names)
	tree = {}
	for r in campaigns:
		parent = r.get(c.PARENT_FIELD)
		if parent in shown:
			tree.setdefault(parent, []).append(r.name)

	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	by_name = {r.name: r for r in campaigns}
	data = []

	def add(name, indent):
		info = by_name[name]
		row = c.rolled_up(name, own, tree) if tree.get(name) else c.add_ratios(frappe._dict(own[name]))
		row.update(
			{
				"campaign": name,
				"campaign_name": info.campaign_name,
				"parent_campaign": info.get(c.PARENT_FIELD) if info.get(c.PARENT_FIELD) in shown else None,
				"campaign_type": info.alt_campaign_type,
				"status": info.get(c.STATUS_FIELD),
				"campaign_owner": info.get(c.OWNER_FIELD),
				"start_date": info.alt_start_date,
				"end_date": info.alt_end_date,
				"budget_used": flt(row.actual_cost * 100 / row.budget, 2) if flt(row.budget) else None,
				"is_group": 1 if tree.get(name) else 0,
				"indent": indent,
				"currency": currency,
				"from_date": filters.from_date,
				"to_date": filters.to_date,
			}
		)
		data.append(row)
		for child in sorted(tree.get(name, []), key=lambda n: (by_name[n].campaign_name or n).lower()):
			add(child, indent + 1)

	roots = [r.name for r in campaigns if r.get(c.PARENT_FIELD) not in shown]
	for name in sorted(roots, key=lambda n: (by_name[n].campaign_name or n).lower()):
		add(name, 0)

	return get_columns(), data, None, get_chart(data, currency), get_summary(own, currency)


def get_campaigns(filters):
	conditions = {}
	or_filters = None
	if filters.campaign:
		conditions["name"] = ["in", [filters.campaign, *c.descendants(filters.campaign)]]
	if filters.status:
		conditions[c.STATUS_FIELD] = filters.status
	if filters.campaign_type:
		conditions["alt_campaign_type"] = filters.campaign_type
	if filters.campaign_owner:
		conditions[c.OWNER_FIELD] = filters.campaign_owner
	if filters.company:
		or_filters = [[c.COMPANY_FIELD, "=", filters.company], [c.COMPANY_FIELD, "is", "not set"]]
	return frappe.get_all(
		"Campaign",
		filters=conditions,
		or_filters=or_filters,
		fields=[
			"name",
			"campaign_name",
			c.PARENT_FIELD,
			c.STATUS_FIELD,
			c.OWNER_FIELD,
			"alt_campaign_type",
			"alt_start_date",
			"alt_end_date",
		],
		order_by="campaign_name asc",
	)


def get_columns():
	def money(fieldname, label, width=130):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": "Currency", "options": "currency", "width": width}

	def count(fieldname, label, width=95):
		return {"fieldname": fieldname, "label": _(label), "fieldtype": "Int", "width": width}

	return [
		{"fieldname": "campaign", "label": _("Campaign"), "fieldtype": "Link", "options": "Campaign", "width": 220},
		{"fieldname": "campaign_type", "label": _("Type"), "fieldtype": "Data", "width": 130},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
		{"fieldname": "campaign_owner", "label": _("Owner"), "fieldtype": "Link", "options": "User", "width": 150},
		money("budget", "Budget"),
		money("actual_cost", "Actual Cost"),
		{"fieldname": "budget_used", "label": _("Budget Used %"), "fieldtype": "Percent", "width": 105},
		count("leads", "Leads", 80),
		count("customers", "Customers"),
		count("deals", "Deals", 80),
		count("quotations", "Quotations Sent", 115),
		count("sales_orders", "Sales Orders", 100),
		money("income", "Income (Sales Orders)", 160),
		money("profit", "Profit"),
		{"fieldname": "roi", "label": _("ROI %"), "fieldtype": "Percent", "width": 90},
		money("cost_per_lead", "Cost per Lead", 120),
		{"fieldname": "win_rate", "label": _("Win Rate %"), "fieldtype": "Percent", "width": 95},
		{"fieldname": "start_date", "label": _("Start Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "end_date", "label": _("End Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "campaign_name", "label": _("Campaign Name"), "fieldtype": "Data", "hidden": 1},
		{"fieldname": "parent_campaign", "label": _("Parent Campaign"), "fieldtype": "Link", "options": "Campaign", "hidden": 1},
	]


def get_chart(data, currency):
	top = [r for r in data if not r.indent and (flt(r.actual_cost) or flt(r.income))]
	top = sorted(top, key=lambda r: flt(r.income), reverse=True)[:10]
	if not top:
		return None
	return {
		"data": {
			"labels": [r.campaign_name or r.campaign for r in top],
			"datasets": [
				{"name": _("Actual Cost"), "values": [flt(r.actual_cost) for r in top]},
				{"name": _("Income (Sales Orders)"), "values": [flt(r.income) for r in top]},
			],
		},
		"type": "bar",
		"fieldtype": "Currency",
		"options": currency,
		"colors": ["#f59e0b", "#16a34a"],
	}


def get_summary(own, currency):
	total = frappe._dict({k: 0 for k in c.COUNT_KEYS + c.AMOUNT_KEYS})
	for row in own.values():
		for key in total:
			total[key] += flt(row.get(key))
	c.add_ratios(total)
	cards = [
		(total.budget, "Budget", "blue", "Currency"),
		(total.actual_cost, "Actual Cost", "orange" if total.budget and total.actual_cost > total.budget else "blue", "Currency"),
		(total.income, "Income (Sales Orders)", "green", "Currency"),
		(total.profit, "Profit", "green" if total.profit >= 0 else "red", "Currency"),
		(total.roi, "ROI %", "green" if total.roi >= 0 else "red", "Percent"),
		(total.leads, "Leads", "blue", "Int"),
		(total.sales_orders, "Sales Orders", "blue", "Int"),
	]
	return [
		{"value": value, "label": _(label), "indicator": color, "datatype": datatype, "currency": currency}
		for value, label, color, datatype in cards
	]
