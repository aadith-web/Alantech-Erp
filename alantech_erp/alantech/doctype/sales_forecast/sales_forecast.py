# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Sales Forecast: a manager's committed forecast for a month / quarter (Zoho CRM forecast).

Get Forecast fills one row per Sales Person of the team (the chosen Sales Person and everyone
under them in the Sales Person tree, or the whole sales team) with the live numbers from
alantech_erp.sales.forecast: target, closed won, commit / best case / pipeline Deals, weighted
pipeline, system forecast (closed won + commit). The manager sets the Manager Forecast per row
(with remarks) and submits: the figures are frozen, so the Sales Forecast Accuracy report can
compare them with what was actually won.

One submitted forecast per Company, team and period; amend it to revise.
Sales Engineers / Managers can only forecast their own part of the tree.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from alantech_erp.sales import forecast


class SalesForecast(Document):
	def validate(self):
		self.set_period()
		forecast.check_root_allowed(self.sales_person)
		self.currency = forecast.company_currency(self.company)
		if not self.won_source:
			self.won_source = forecast.settings().won_source
		if not self.details:
			self._fill()
		for row in self.details:
			if row.manager_adjusted is None:
				row.manager_adjusted = flt(row.forecast)
			row.gap = flt(row.target) - flt(row.manager_adjusted) if flt(row.target) else 0
		self.set_totals()
		self.check_duplicate()

	def set_period(self):
		start, end = forecast.period_bounds(self.period_type, self.period_start)
		self.from_date, self.to_date = start, end
		self.period_label = forecast.period_label(self.period_type, start)

	def check_duplicate(self):
		filters = {
			"company": self.company,
			"period_type": self.period_type,
			"from_date": self.from_date,
			"docstatus": 1,
			"name": ["!=", self.name],
		}
		filters["sales_person"] = self.sales_person or ["is", "not set"]
		other = frappe.db.get_value("Sales Forecast", filters, "name")
		if other and other != self.amended_from:
			frappe.throw(
				_(
					"Sales Forecast {0} is already submitted for this team and period. Cancel and amend it to revise."
				).format(frappe.get_desk_link("Sales Forecast", other)),
				title=_("Forecast Exists"),
			)

	def top_row(self):
		"""The team's own row (the chosen Sales Person, or the tree root)."""
		for row in self.details:
			if not row.indent:
				return row
		return None

	def set_totals(self):
		top = [r for r in self.details if not r.indent]
		self.total_target = sum(flt(r.target) for r in top)
		self.total_closed_won = sum(flt(r.closed_won) for r in top)
		self.total_forecast = sum(flt(r.forecast) for r in top)
		self.total_manager_forecast = sum(flt(r.manager_adjusted) for r in top)

	@frappe.whitelist()
	def fill_details(self):
		"""Get Forecast button: live numbers for the team."""
		if self.docstatus != 0:
			frappe.throw(_("Only a draft forecast can be refreshed."))
		if not self.is_new():
			self.check_permission("write")
		self._fill()
		return self

	def _fill(self):
		"""Rows from the live forecast (keeps Manager Forecasts already typed for the same people)."""
		self.set_period()
		forecast.check_root_allowed(self.sales_person)
		self.won_source = forecast.settings().won_source
		kept = {
			r.sales_person: (r.manager_adjusted, r.adjustment_remarks)
			for r in self.details
			if r.adjustment_remarks
			or (flt(r.manager_adjusted) and flt(r.manager_adjusted) != flt(r.forecast))
		}
		rows = forecast.get_forecast(
			self.company, self.from_date, self.to_date, self.sales_person, self.won_source
		)
		self.set("details", [])
		for r in rows:
			adjusted, remarks = kept.get(r.name, (r.forecast, None))
			self.append(
				"details",
				{
					"sales_person": r.name,
					"parent_sales_person": r.parent,
					"is_group": r.is_group,
					"indent": r.indent,
					"target": r.target,
					"closed_won": r.closed_won,
					"commit_amount": r.commit_amount,
					"best_case": r.best_case,
					"pipeline": r.pipeline,
					"weighted_pipeline": r.weighted_pipeline,
					"forecast": r.forecast,
					"best_case_forecast": r.best_case_forecast,
					"manager_adjusted": adjusted,
					"adjustment_remarks": remarks,
					"gap": r.gap,
					"achievement_pct": r.achievement_pct,
				},
			)
		self.set_totals()
