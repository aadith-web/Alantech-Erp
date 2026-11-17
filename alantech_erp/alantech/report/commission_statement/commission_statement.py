# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Commission Statement: a Sales Person's commission credits (Commission Ledger Entries) with the
document behind each, whether it is paid and in which Commission Payout, and the estimated
commission of the unpaid part under their current plan.

Filters: Company, From / To Date, Sales Person (with their team), Basis, Status (Paid / Unpaid).
Sales Engineers / Managers see only themselves and their team (Sales Person tree).
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, today

from alantech_erp.sales import commission, forecast


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Please select a Company."))
	filters.from_date = getdate(filters.from_date or get_first_day(today()))
	filters.to_date = getdate(filters.to_date or today())
	root = forecast.check_root_allowed(filters.sales_person)

	conditions = {
		"company": filters.company,
		"posting_date": ["between", [filters.from_date, filters.to_date]],
	}
	if root:
		lft, rgt = frappe.db.get_value("Sales Person", root, ["lft", "rgt"])
		conditions["sales_person"] = [
			"in",
			frappe.get_all("Sales Person", filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name"),
		]
	if filters.basis:
		conditions["basis"] = filters.basis
	if filters.status == "Paid":
		conditions["commission_payout"] = ["is", "set"]
	elif filters.status == "Unpaid":
		conditions["commission_payout"] = ["is", "not set"]

	rows = frappe.get_all(
		commission.LEDGER,
		filters=conditions,
		fields=[
			"name",
			"posting_date",
			"sales_person",
			"basis",
			"voucher_type",
			"voucher_no",
			"against_voucher",
			"customer",
			"item_group",
			"base_amount",
			"allocated_percentage",
			"is_return",
			"is_reversal",
			"commission_payout",
		],
		order_by="sales_person asc, posting_date asc, creation asc",
		ignore_permissions=True,  # access is by the Sales Person tree above
	)
	currency = forecast.company_currency(filters.company)
	for r in rows:
		r.currency = currency
		r.status = _("Paid") if r.commission_payout else _("Unpaid")
		r.note = _("Cancelled") if r.is_reversal else (_("Credit Note") if r.is_return else "")
	return get_columns(), rows, None, None, get_summary(rows, filters, currency)


def get_columns():
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "sales_person",
			"label": _("Sales Person"),
			"fieldtype": "Link",
			"options": "Sales Person",
			"width": 170,
		},
		{"fieldname": "basis", "label": _("Basis"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "voucher_type",
			"label": _("Voucher Type"),
			"fieldtype": "Link",
			"options": "DocType",
			"width": 120,
		},
		{
			"fieldname": "voucher_no",
			"label": _("Voucher"),
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 160,
		},
		{
			"fieldname": "against_voucher",
			"label": _("Against Invoice"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 170,
		},
		{
			"fieldname": "item_group",
			"label": _("Item Group"),
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 130,
		},
		{"fieldname": "allocated_percentage", "label": _("Share %"), "fieldtype": "Percent", "width": 80},
		{
			"fieldname": "base_amount",
			"label": _("Credited"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 100},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 80},
		{
			"fieldname": "commission_payout",
			"label": _("Paid In"),
			"fieldtype": "Link",
			"options": "Commission Payout",
			"width": 130,
		},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1,
		},
	]


def get_summary(rows, filters, currency):
	credited = sum(flt(r.base_amount) for r in rows)
	unpaid = sum(flt(r.base_amount) for r in rows if not r.commission_payout)
	paid_commission = 0.0
	payouts = {r.commission_payout for r in rows if r.commission_payout}
	people = {r.sales_person for r in rows}
	if payouts:
		paid_commission = sum(
			flt(v)
			for v in frappe.get_all(
				"Commission Payout Detail",
				filters={"parent": ["in", list(payouts)], "sales_person": ["in", list(people)]},
				pluck="payable_amount",
			)
		)
	summary = [
		{"label": _("Credited Sales"), "value": credited, "datatype": "Currency", "currency": currency},
		{
			"label": _("Not Yet Paid On"),
			"value": unpaid,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Orange",
		},
		{
			"label": _("Commission Paid"),
			"value": paid_commission,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Green",
		},
	]
	if len(people) == 1 and unpaid:
		person = next(iter(people))
		try:
			row, _entries = commission.compute_payout_row(
				person, filters.company, filters.from_date, filters.to_date
			)
			summary.append(
				{
					"label": _("Est. Commission (Unpaid)"),
					"value": row.commission_amount,
					"datatype": "Currency",
					"currency": currency,
					"indicator": "Blue",
				}
			)
		except frappe.ValidationError:
			frappe.clear_last_message()
	return summary
