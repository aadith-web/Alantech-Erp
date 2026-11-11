# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales Forecast (Zoho CRM style): target, closed won and open Deals by forecast category for a
month / quarter, per Sales Person and rolled up the Sales Person tree (alantech_erp.sales.forecast).

Filters: Company, Period (Month / Quarter), Period Of (any date in it), Sales Person (team: that
person and everyone under them; blank = the whole sales team, or the user's own team for a Sales
Engineer / Manager), Hide Empty Rows.

Columns: Target, Closed Won, Commit, Best Case, Pipeline, Weighted Pipeline, Forecast (closed won
+ commit), Best Case Forecast, Gap to Target, Achieved %, and Est. Commission (the person's
Commission Plan on the forecast). Group rows (managers) show their own numbers plus their team's.
Clicking a number opens the Deals / orders behind it (report's JS).
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from alantech_erp.sales import commission, forecast


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Please select a Company."))
	filters.period_type = filters.period_type or forecast.settings().period_type
	start, end = forecast.period_bounds(filters.period_type, filters.period_start or today())
	root = forecast.check_root_allowed(filters.sales_person)
	rows = forecast.get_forecast(filters.company, start, end, root)
	currency = forecast.company_currency(filters.company)

	for row in rows:
		row.currency = currency
		row.from_date, row.to_date = start, end
		row.estimated_commission = _estimated_commission(row, filters.company, end)

	if filters.hide_empty:
		keep = {r.name for r in rows if any(flt(r.get(k)) for k in forecast.AMOUNT_KEYS)}
		# keep the managers above anyone shown, so the tree still reads
		for r in rows:
			if r.name in keep:
				parent = r.parent
				while parent and parent not in keep:
					keep.add(parent)
					parent = next((p.parent for p in rows if p.name == parent), None)
		rows = [r for r in rows if r.name in keep]

	label = forecast.period_label(filters.period_type, start)
	return get_columns(), rows, None, get_chart(rows), get_summary(rows, label, currency)


def _estimated_commission(row, company, on_date):
	if row.is_group:
		return None  # a team's commission is not the sum of a plan on the team's sales
	try:
		plan = commission.load_plan(commission.plan_for(row.name, on_date, company), row.name)
		return flt(commission.calculate(plan, row.forecast, None, row.target)[0], 2)
	except frappe.ValidationError:
		frappe.clear_last_message()
		return None


def get_columns():
	def money(fieldname, label, width=130):
		return {
			"fieldname": fieldname,
			"label": _(label),
			"fieldtype": "Currency",
			"options": "currency",
			"width": width,
		}

	return [
		{
			"fieldname": "sales_person",
			"label": _("Sales Person"),
			"fieldtype": "Link",
			"options": "Sales Person",
			"width": 220,
		},
		money("target", "Target"),
		money("closed_won", "Closed Won"),
		money("commit_amount", "Commit"),
		money("best_case", "Best Case"),
		money("pipeline", "Pipeline"),
		money("weighted_pipeline", "Weighted Pipeline", 140),
		money("forecast", "Forecast", 130),
		money("best_case_forecast", "Best Case Forecast", 150),
		money("gap", "Gap to Target"),
		{"fieldname": "achievement_pct", "label": _("Achieved %"), "fieldtype": "Percent", "width": 100},
		money("estimated_commission", "Est. Commission"),
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1,
		},
	]


def get_chart(rows):
	top = [r for r in rows if r.indent == 0]
	people = [r for r in rows if r.indent == 1] or top
	if not people:
		return None
	return {
		"data": {
			"labels": [r.name for r in people],
			"datasets": [
				{"name": _("Target"), "values": [flt(r.target) for r in people]},
				{"name": _("Closed Won"), "values": [flt(r.closed_won) for r in people]},
				{"name": _("Commit"), "values": [flt(r.commit_amount) for r in people]},
				{"name": _("Best Case"), "values": [flt(r.best_case) for r in people]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 0},
		"fieldtype": "Currency",
	}


def get_summary(rows, label, currency):
	top = [r for r in rows if r.indent == 0]
	total = lambda key: sum(flt(r.get(key)) for r in top)  # noqa: E731
	target, won, fc = total("target"), total("closed_won"), total("forecast")
	return [
		{"label": _("Period"), "value": label, "datatype": "Data"},
		{"label": _("Target"), "value": target, "datatype": "Currency", "currency": currency},
		{
			"label": _("Closed Won"),
			"value": won,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Green",
		},
		{
			"label": _("Forecast"),
			"value": fc,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Blue",
		},
		{
			"label": _("Gap to Target"),
			"value": target - fc if target else 0,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Red" if target and fc < target else "Green",
		},
		{
			"label": _("Achieved"),
			"value": f"{flt(won * 100 / target, 1) if target else 0}%",
			"datatype": "Data",
		},
	]


@frappe.whitelist()
def drill_down(company, sales_person, column, from_date, to_date):
	"""Route options for the documents behind a number (clicked in the report)."""
	if not frappe.has_permission("Opportunity", "read"):
		raise frappe.PermissionError
	forecast.check_root_allowed(sales_person)
	from_date, to_date = getdate(from_date), getdate(to_date)
	lft, rgt = frappe.db.get_value("Sales Person", sales_person, ["lft", "rgt"])
	team = frappe.get_all("Sales Person", filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name")
	if column == "closed_won":
		source = forecast.settings().won_source
		date_field = "transaction_date" if source == forecast.SALES_ORDER else "posting_date"
		names = frappe.get_all(
			"Sales Team",
			filters={"parenttype": source, "sales_person": ["in", team]},
			pluck="parent",
			distinct=True,
		)
		return {
			"doctype": source,
			"filters": {
				"name": ["in", names or [""]],
				"docstatus": 1,
				"company": company,
				date_field: ["between", [str(from_date), str(to_date)]],
			},
		}
	category = {
		"commit_amount": forecast.COMMIT,
		"best_case": forecast.BEST_CASE,
		"pipeline": forecast.PIPELINE,
	}.get(column)
	filters = {
		forecast.SALES_PERSON_FIELD: ["in", team],
		"company": company,
		"status": ["not in", list(forecast.CLOSED_STATUSES)],
		"expected_closing": ["between", [str(from_date), str(to_date)]],
	}
	if category:
		filters[forecast.CATEGORY_FIELD] = category
	else:
		filters[forecast.CATEGORY_FIELD] = ["in", list(forecast.OPEN_CATEGORIES)]
	return {"doctype": "Opportunity", "filters": filters}
