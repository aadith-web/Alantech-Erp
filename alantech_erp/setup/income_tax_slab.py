"""Income Tax Slab filled on Salary Structure Assignment.

ClickUp: https://app.clickup.com/t/14yr2e589ev (parent 14yr2e586v0, Sub Task 2)

On every save of an assignment (form, the Create / Edit Salary Structure popups, Data Import, API):
- Income Tax Slab empty: filled with the slab that applies on the From Date: submitted, not
  disabled, of the assignment's company (or no company) and currency, Effective From on or before
  the From Date; of several, the latest Effective From (then the last created).
  E.g. From Date 2026-11-23 -> "New Tax Regime: 2025-2026" (2025-04-01) rather than the 2024-2025
  one or "Old Tax Regime: 2019".
- No slab applies: left blank, with an orange message saying why.
- A slab already there is kept: chosen by HR, or by the employee in India Payroll's Tax Regime
  Selector (Old regime). Only a slab this hook picked for an earlier From Date of the same draft is
  picked again when the From Date changes.

hooks.py: doc_events Salary Structure Assignment before_validate (HRMS's validate refuses an empty slab
when the structure has a tax component, so it is filled before that runs).
"""

import frappe
from frappe import _
from frappe.utils import getdate


def get_applicable_slab(from_date, company=None, currency=None):
	"""Name of the Income Tax Slab in force on `from_date`, or None."""
	if not from_date:
		return None
	filters = {
		"docstatus": 1,
		"disabled": 0,
		"effective_from": ("<=", getdate(from_date)),
	}
	if currency:
		filters["currency"] = currency
	rows = frappe.get_all(
		"Income Tax Slab",
		filters=filters,
		fields=["name", "company"],
		order_by="effective_from desc, creation desc",
	)
	for row in rows:
		if not company or not row.company or row.company == company:
			return row.name
	return None


def set_income_tax_slab(doc, method=None):
	"""Salary Structure Assignment.before_validate."""
	if doc.docstatus == 2 or not doc.from_date:
		return
	slab = get_applicable_slab(doc.from_date, doc.company, doc.currency)

	if doc.income_tax_slab:
		before = doc.get_doc_before_save()
		date_changed = before and getdate(before.from_date) != getdate(doc.from_date)
		was_auto = (
			date_changed
			and before.income_tax_slab == doc.income_tax_slab
			and doc.income_tax_slab == get_applicable_slab(before.from_date, before.company, before.currency)
		)
		if not was_auto:
			return  # chosen by hand (or in the Tax Regime Selector): kept
		doc.income_tax_slab = slab
		if slab:
			return

	if slab:
		doc.income_tax_slab = slab
		return
	frappe.msgprint(
		_(
			"No Income Tax Slab applies on {0} for {1} ({2}): none is submitted and enabled with an "
			"Effective From on or before that date. Income Tax Slab is left blank; create the slab or "
			"select one."
		).format(
			frappe.bold(frappe.format_value(getdate(doc.from_date), "Date")), doc.company, doc.currency
		),
		title=_("No Income Tax Slab"),
		indicator="orange",
	)


@frappe.whitelist()
def get_slab_for_popup(from_date, company=None):
	"""Create / Edit Salary Structure popups: the slab the assignment will get on save for
	`from_date` (same rule as set_income_tax_slab), shown read-only before it is created."""
	frappe.has_permission("Salary Structure Assignment", "create", throw=True)
	company = company or frappe.defaults.get_user_default("Company")
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	return get_applicable_slab(from_date, company, currency)
