# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales Forecast Accuracy: submitted Sales Forecasts against what was actually won.

One row per Sales Person per submitted forecast in the date range: the Manager Forecast (and the
System Forecast) frozen at submit, Closed Won now for that period (alantech_erp.sales.forecast,
same source as the forecast used), variance and accuracy (100% - |variance| / forecast).
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

from alantech_erp.sales import forecast


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Please select a Company."))
	from_date = getdate(filters.from_date or add_months(today(), -6))
	to_date = getdate(filters.to_date or today())
	root = forecast.check_root_allowed(filters.sales_person)

	conditions = {"company": filters.company, "docstatus": 1, "from_date": ["between", [from_date, to_date]]}
	forecasts = frappe.get_all(
		"Sales Forecast",
		filters=conditions,
		fields=["name", "period_label", "from_date", "to_date", "won_source", "sales_person"],
		order_by="from_date asc",
	)
	allowed = None
	if root:
		lft, rgt = frappe.db.get_value("Sales Person", root, ["lft", "rgt"])
		allowed = set(
			frappe.get_all("Sales Person", filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name")
		)

	currency = forecast.company_currency(filters.company)
	data = []
	for fc in forecasts:
		details = frappe.get_all(
			"Sales Forecast Detail",
			filters={"parent": fc.name, "parenttype": "Sales Forecast"},
			fields=["sales_person", "is_group", "indent", "forecast", "manager_adjusted", "target"],
			order_by="idx asc",
		)
		if allowed is not None:
			details = [d for d in details if d.sales_person in allowed]
		if not filters.show_team_rows:
			details = [d for d in details if not d.is_group]
		if not details:
			continue
		# actual = closed won now, rolled up the same way as the forecast was
		live = {
			r.name: r
			for r in forecast.get_forecast(
				filters.company, fc.from_date, fc.to_date, fc.sales_person, fc.won_source
			)
		}
		for d in details:
			actual = flt(live[d.sales_person].closed_won) if d.sales_person in live else 0.0
			committed = flt(d.manager_adjusted)
			variance = actual - committed
			data.append(
				frappe._dict(
					sales_forecast=fc.name,
					period=fc.period_label,
					sales_person=d.sales_person,
					is_group=d.is_group,
					target=d.target,
					system_forecast=d.forecast,
					manager_forecast=committed,
					actual=actual,
					variance=variance,
					accuracy=max(0.0, 100 - abs(variance) * 100 / committed)
					if committed
					else (100.0 if not actual else 0.0),
					currency=currency,
				)
			)
	return get_columns(), data, None, get_chart(data)


def get_columns():
	def money(fieldname, label):
		return {
			"fieldname": fieldname,
			"label": _(label),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		}

	return [
		{"fieldname": "period", "label": _("Period"), "fieldtype": "Data", "width": 100},
		{
			"fieldname": "sales_forecast",
			"label": _("Sales Forecast"),
			"fieldtype": "Link",
			"options": "Sales Forecast",
			"width": 130,
		},
		{
			"fieldname": "sales_person",
			"label": _("Sales Person"),
			"fieldtype": "Link",
			"options": "Sales Person",
			"width": 200,
		},
		money("target", "Target"),
		money("system_forecast", "System Forecast"),
		money("manager_forecast", "Manager Forecast"),
		money("actual", "Actual Won"),
		money("variance", "Variance"),
		{"fieldname": "accuracy", "label": _("Accuracy %"), "fieldtype": "Percent", "width": 110},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1,
		},
	]


def get_chart(data):
	periods = list(dict.fromkeys(d.period for d in data))
	if not periods:
		return None
	by = lambda key, p: sum(flt(d[key]) for d in data if d.period == p and not d.is_group)  # noqa: E731
	return {
		"data": {
			"labels": periods,
			"datasets": [
				{"name": _("Manager Forecast"), "values": [by("manager_forecast", p) for p in periods]},
				{"name": _("Actual Won"), "values": [by("actual", p) for p in periods]},
			],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
