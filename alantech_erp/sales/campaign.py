"""Campaigns (CRM requirements C24, C36).

A Campaign (ERPNext CRM master) is one marketing activity: an exhibition, a mailer, an ad, a
seminar. ERPNext keeps a UTM Campaign "mirror" for every Campaign (UTM Campaign.crm_campaign) and
the sales documents link to that mirror in their `utm_campaign` field ("Campaign").

C36 - the campaign record:
  Campaign Owner, Status, Type, Start / End, Company, Parent Campaign (child campaigns),
  Budget, Costs (Campaign Cost rows) -> Actual Cost, and the results: Income from the submitted
  Sales Orders of the campaign (net total, company currency) and ROI % = (income - cost) / cost.
  Stored figures are the campaign's own; the form and the Campaign ROI report also show them
  rolled up with the child campaigns.

C24 - the campaign carries through the flow:
  Lead.utm_campaign -> Customer.alt_campaign (from the Lead it was made from)
  -> Estimation.utm_campaign (from the Customer or the Deal)
  -> Quotation.utm_campaign (from the Estimation, else the Deal, else the Customer / Lead)
  -> Deal (Opportunity).utm_campaign (from the Quotation, sales/deal.py, else the party)
  -> Sales Order.utm_campaign (from the Quotation, else the Customer)
  -> Sales Invoice.utm_campaign (from the Sales Order, else the Customer)
  A campaign typed on a document is kept; only empty ones are filled.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_link_to_form, getdate, nowdate

CUSTOMER_FIELD = "alt_campaign"  # Customer: the campaign the customer came from
UTM_FIELD = "utm_campaign"  # ERPNext field on Lead / Opportunity / Quotation / Sales Order / Sales Invoice
UTM_DOCTYPE = "UTM Campaign"

# Campaign custom fields (setup/campaigns.py)
OWNER_FIELD = "alt_campaign_owner"
PARENT_FIELD = "alt_parent_campaign"
STATUS_FIELD = "alt_status"
COMPANY_FIELD = "alt_company"
BUDGET_FIELD = "alt_budget"
COSTS_FIELD = "alt_costs"
ACTUAL_COST_FIELD = "alt_actual_cost"
INCOME_FIELD = "alt_income"
ROI_FIELD = "alt_roi"

STATUSES = ("Planned", "Active", "Completed", "Cancelled")


# --------------------------------------------------------------------------- Campaign <-> UTM Campaign
def _mirror_linked():
	return frappe.db.has_column(UTM_DOCTYPE, "crm_campaign")


def utm_of(campaign):
	"""The UTM Campaign the documents of this Campaign link to."""
	if not campaign:
		return None
	if _mirror_linked():
		utm = frappe.db.get_value(UTM_DOCTYPE, {"crm_campaign": campaign})
		if utm:
			return utm
	return campaign if frappe.db.exists(UTM_DOCTYPE, campaign) else None


def campaign_of(utm):
	"""The Campaign behind a UTM Campaign (None for a UTM Campaign made by a web form only)."""
	if not utm:
		return None
	if _mirror_linked():
		campaign = frappe.db.get_value(UTM_DOCTYPE, utm, "crm_campaign")
		if campaign:
			return campaign
	return utm if frappe.db.exists("Campaign", utm) else None


def utm_map(campaigns=None):
	"""{campaign: utm campaign} for the given Campaigns (all when None)."""
	filters = {"name": ["in", list(campaigns)]} if campaigns is not None else {}
	if campaigns is not None and not campaigns:
		return {}
	names = frappe.get_all("Campaign", filters=filters, pluck="name")
	result = {}
	if _mirror_linked():
		for row in frappe.get_all(
			UTM_DOCTYPE, filters={"crm_campaign": ["in", names or [""]]}, fields=["name", "crm_campaign"]
		):
			result[row.crm_campaign] = row.name
	missing = [n for n in names if n not in result]
	if missing:
		for utm in frappe.get_all(UTM_DOCTYPE, filters={"name": ["in", missing]}, pluck="name"):
			result.setdefault(utm, utm)
	return result


# --------------------------------------------------------------------------- campaign tree
def children_map():
	"""{parent campaign: [child campaigns]}"""
	tree = {}
	for row in frappe.get_all("Campaign", filters={PARENT_FIELD: ["is", "set"]}, fields=["name", PARENT_FIELD]):
		tree.setdefault(row.get(PARENT_FIELD), []).append(row.name)
	return tree


def descendants(campaign, tree=None):
	"""Every campaign below `campaign` (children, their children...)."""
	tree = tree if tree is not None else children_map()
	found, stack = [], list(tree.get(campaign, []))
	while stack:
		name = stack.pop()
		if name in found or name == campaign:
			continue
		found.append(name)
		stack.extend(tree.get(name, []))
	return found


# --------------------------------------------------------------------------- Campaign doc_events
def campaign_validate(doc, method=None):
	_set_defaults(doc)
	_validate_dates(doc)
	_validate_parent(doc)
	_set_actual_cost(doc)
	_set_results(doc)
	_warn_over_budget(doc)


def _set_defaults(doc):
	if not doc.get(OWNER_FIELD):
		doc.set(OWNER_FIELD, frappe.session.user)
	if not doc.get(STATUS_FIELD):
		doc.set(STATUS_FIELD, STATUSES[0])
	if not doc.get(COMPANY_FIELD):
		parent_company = doc.get(PARENT_FIELD) and frappe.db.get_value("Campaign", doc.get(PARENT_FIELD), COMPANY_FIELD)
		doc.set(
			COMPANY_FIELD,
			parent_company
			or frappe.defaults.get_user_default("Company")
			or frappe.db.get_single_value("Global Defaults", "default_company"),
		)


def _validate_dates(doc):
	start, end = doc.get("alt_start_date"), doc.get("alt_end_date")
	if start and end and getdate(end) < getdate(start):
		frappe.throw(_("The End Date cannot be before the Start Date."), title=_("Invalid Dates"))


def _validate_parent(doc):
	parent = doc.get(PARENT_FIELD)
	if not parent:
		return
	if parent == doc.name:
		frappe.throw(_("A campaign cannot be its own parent."), title=_("Invalid Parent Campaign"))
	# walk up from the parent: meeting this campaign again would make a loop
	seen, current = set(), parent
	while current and current not in seen:
		if current == doc.name:
			frappe.throw(
				_("{0} is already below {1}; it cannot also be its parent.").format(
					frappe.bold(parent), frappe.bold(doc.name)
				),
				title=_("Invalid Parent Campaign"),
			)
		seen.add(current)
		current = frappe.db.get_value("Campaign", current, PARENT_FIELD)
	parent_company = frappe.db.get_value("Campaign", parent, COMPANY_FIELD)
	if parent_company and doc.get(COMPANY_FIELD) and parent_company != doc.get(COMPANY_FIELD):
		frappe.throw(
			_("Parent Campaign {0} belongs to {1}; a child campaign must be for the same company.").format(
				frappe.bold(parent), frappe.bold(parent_company)
			),
			title=_("Company Mismatch"),
		)


def _set_actual_cost(doc):
	total = 0
	for row in doc.get(COSTS_FIELD) or []:
		if flt(row.amount) <= 0:
			frappe.throw(
				_("Row {0}: the cost amount must be above zero.").format(row.idx), title=_("Invalid Cost")
			)
		if not row.posting_date:
			row.posting_date = nowdate()
		total += flt(row.amount)
	doc.set(ACTUAL_COST_FIELD, flt(total, 2))


def _set_results(doc):
	if doc.is_new():
		doc.set(INCOME_FIELD, 0)
	else:
		doc.set(INCOME_FIELD, own_income(doc.name, doc.get(COMPANY_FIELD)))
	doc.set(ROI_FIELD, roi(doc.get(INCOME_FIELD), doc.get(ACTUAL_COST_FIELD)))


def _warn_over_budget(doc):
	budget, cost = flt(doc.get(BUDGET_FIELD)), flt(doc.get(ACTUAL_COST_FIELD))
	if budget and cost > budget:
		frappe.msgprint(
			_("The actual cost {0} is above the budget {1}.").format(
				frappe.bold(frappe.format(cost, {"fieldtype": "Currency"})),
				frappe.bold(frappe.format(budget, {"fieldtype": "Currency"})),
			),
			indicator="orange",
			alert=True,
		)


def roi(income, cost):
	"""ROI % = (income - cost) / cost x 100; 0 without cost."""
	cost = flt(cost)
	return flt((flt(income) - cost) / cost * 100, 2) if cost else 0


def own_income(campaign, company=None):
	"""Net total (company currency) of the campaign's submitted Sales Orders."""
	utm = utm_of(campaign)
	if not utm:
		return 0
	filters = {UTM_FIELD: utm, "docstatus": 1}
	if company:
		filters["company"] = company
	rows = frappe.get_all("Sales Order", filters=filters, pluck="base_net_total")
	return flt(sum(flt(v) for v in rows), 2)


def refresh_results(campaign):
	"""Recompute the stored Income / ROI of a campaign (after a Sales Order is submitted / cancelled)."""
	if not campaign or not frappe.db.exists("Campaign", campaign):
		return
	values = frappe.db.get_value("Campaign", campaign, [COMPANY_FIELD, ACTUAL_COST_FIELD], as_dict=True)
	if values is None:
		return
	income = own_income(campaign, values.get(COMPANY_FIELD))
	frappe.db.set_value(
		"Campaign",
		campaign,
		{INCOME_FIELD: income, ROI_FIELD: roi(income, values.get(ACTUAL_COST_FIELD))},
		update_modified=False,
	)


# --------------------------------------------------------------------------- carry-through (C24)
def _get(doctype, name, field):
	if not name or not frappe.get_meta(doctype).has_field(field):
		return None
	return frappe.db.get_value(doctype, name, field)


def customer_campaign(customer):
	return _get("Customer", customer, CUSTOMER_FIELD)


def lead_campaign(lead):
	return _get("Lead", lead, UTM_FIELD)


def _set_if_empty(doc, fieldname, *candidates):
	if not doc.meta.has_field(fieldname) or doc.get(fieldname):
		return
	for value in candidates:
		value = value() if callable(value) else value
		if value:
			doc.set(fieldname, value)
			return


def customer_before_validate(doc, method=None):
	"""A customer made from a Lead keeps the Lead's campaign."""
	_set_if_empty(doc, CUSTOMER_FIELD, lambda: lead_campaign(doc.get("lead_name")))


def estimation_campaign(doc):
	"""Estimation: from its Deal, else its Customer."""
	_set_if_empty(
		doc,
		UTM_FIELD,
		lambda: _get("Opportunity", doc.get("opportunity"), UTM_FIELD),
		lambda: customer_campaign(doc.get("customer")),
	)


def _party_campaign(party_type, party):
	if party_type == "Customer":
		return customer_campaign(party)
	if party_type == "Lead":
		return lead_campaign(party)
	return None


def quotation_validate(doc, method=None):
	"""Quotation: from its Estimation, else its Deal, else the Customer / Lead."""
	if doc.docstatus != 0:
		return
	_set_if_empty(
		doc,
		UTM_FIELD,
		lambda: _get("Estimation", doc.get("alt_estimation"), UTM_FIELD),
		lambda: _get("Opportunity", doc.get("opportunity"), UTM_FIELD),
		lambda: _party_campaign(doc.get("quotation_to"), doc.get("party_name")),
	)


def opportunity_validate(doc, method=None):
	"""Deal: from its Quotation, else the Customer / Lead."""
	_set_if_empty(
		doc,
		UTM_FIELD,
		lambda: _get("Quotation", doc.get("alt_quotation"), UTM_FIELD),
		lambda: _party_campaign(doc.get("opportunity_from"), doc.get("party_name")),
	)


def _from_rows(doc, link_field, doctype):
	for row in doc.get("items") or []:
		value = _get(doctype, row.get(link_field), UTM_FIELD)
		if value:
			return value
	return None


def sales_order_validate(doc, method=None):
	"""Sales Order: from its Quotation, else the Customer."""
	if doc.docstatus != 0:
		return
	_set_if_empty(
		doc,
		UTM_FIELD,
		lambda: _from_rows(doc, "prevdoc_docname", "Quotation"),
		lambda: customer_campaign(doc.get("customer")),
	)


def sales_invoice_validate(doc, method=None):
	"""Sales Invoice: from its Sales Order, else the Customer."""
	if doc.docstatus != 0:
		return
	_set_if_empty(
		doc,
		UTM_FIELD,
		lambda: _from_rows(doc, "sales_order", "Sales Order"),
		lambda: customer_campaign(doc.get("customer")),
	)


def sales_order_changed(doc, method=None):
	"""Submitted / cancelled order: the campaign's Income and ROI follow."""
	refresh_results(campaign_of(doc.get(UTM_FIELD)))


# --------------------------------------------------------------------------- results
# (key, doctype, utm field, date field, extra filters, value field or None to count)
RESULT_SOURCES = (
	("leads", "Lead", UTM_FIELD, "creation", {}, None),
	("customers", "Customer", CUSTOMER_FIELD, "creation", {}, None),
	("deals", "Opportunity", UTM_FIELD, "transaction_date", {}, None),
	("quotations", "Quotation", UTM_FIELD, "transaction_date", {"docstatus": 1}, None),
	("sales_orders", "Sales Order", UTM_FIELD, "transaction_date", {"docstatus": 1}, None),
	("income", "Sales Order", UTM_FIELD, "transaction_date", {"docstatus": 1}, "base_net_total"),
)
COUNT_KEYS = ("leads", "customers", "deals", "quotations", "sales_orders")
AMOUNT_KEYS = ("budget", "actual_cost", "income")


def results_by_utm(utms, company=None, from_date=None, to_date=None):
	"""{utm campaign: {leads, customers, deals, quotations, sales_orders, income}}"""
	utms = [u for u in utms if u]
	result = {u: frappe._dict({key: 0 for key, *_ in RESULT_SOURCES}) for u in utms}
	if not utms:
		return result
	for key, doctype, field, date_field, extra, value_field in RESULT_SOURCES:
		meta = frappe.get_meta(doctype)
		if not meta.has_field(field):
			continue
		filters = {field: ["in", utms], **extra}
		if company and meta.has_field("company"):
			filters["company"] = company
		dates = _date_filter(date_field, from_date, to_date)
		if dates:
			filters[date_field] = dates
		fields = [field] + ([value_field] if value_field else [])
		for row in frappe.get_all(doctype, filters=filters, fields=fields):
			bucket = result.get(row.get(field))
			if bucket is not None:
				bucket[key] += flt(row.get(value_field)) if value_field else 1
	return result


def _date_filter(date_field, from_date, to_date):
	if date_field == "creation":
		from_date = from_date and f"{getdate(from_date)} 00:00:00"
		to_date = to_date and f"{getdate(to_date)} 23:59:59.999999"
	if from_date and to_date:
		return ["between", [from_date, to_date]]
	if from_date:
		return [">=", from_date]
	if to_date:
		return ["<=", to_date]
	return None


def costs_by_campaign(campaigns, from_date=None, to_date=None):
	"""{campaign: cost} from the Campaign Cost rows (dated within the period)."""
	if not campaigns:
		return {}
	filters = {"parenttype": "Campaign", "parentfield": COSTS_FIELD, "parent": ["in", list(campaigns)]}
	dates = _date_filter("posting_date", from_date, to_date)
	if dates:
		filters["posting_date"] = dates
	result = {}
	for row in frappe.get_all("Campaign Cost", filters=filters, fields=["parent", "amount"]):
		result[row.parent] = result.get(row.parent, 0) + flt(row.amount)
	return result


def campaign_results(campaigns, company=None, from_date=None, to_date=None):
	"""{campaign: own figures} - counts, budget, actual cost (in the period), income."""
	campaigns = list(campaigns)
	mirrors = utm_map(campaigns)
	by_utm = results_by_utm(list(mirrors.values()), company, from_date, to_date)
	costs = costs_by_campaign(campaigns, from_date, to_date)
	budgets = {
		r.name: flt(r.get(BUDGET_FIELD))
		for r in frappe.get_all("Campaign", filters={"name": ["in", campaigns or [""]]}, fields=["name", BUDGET_FIELD])
	}
	result = {}
	for name in campaigns:
		row = frappe._dict(by_utm.get(mirrors.get(name)) or {key: 0 for key, *_ in RESULT_SOURCES})
		row.budget = budgets.get(name, 0)
		row.actual_cost = flt(costs.get(name), 2)
		row.income = flt(row.income, 2)
		result[name] = row
	return result


def add_ratios(row):
	row.profit = flt(flt(row.income) - flt(row.actual_cost), 2)
	row.roi = roi(row.income, row.actual_cost)
	row.cost_per_lead = flt(flt(row.actual_cost) / row.leads, 2) if cint(row.leads) else 0
	row.win_rate = flt(cint(row.sales_orders) * 100 / cint(row.quotations), 2) if cint(row.quotations) else 0
	return row


def rolled_up(name, own, tree):
	"""Own figures of `name` plus those of every campaign below it."""
	total = frappe._dict({k: flt(v) for k, v in own[name].items()})
	for child in descendants(name, tree):
		for key in COUNT_KEYS + AMOUNT_KEYS:
			total[key] = flt(total.get(key)) + flt((own.get(child) or {}).get(key))
	return add_ratios(total)


@frappe.whitelist()
def get_campaign_summary(campaign: str):
	"""Form dashboard: the campaign's own results and with its child campaigns."""
	frappe.has_permission("Campaign", "read", campaign, throw=True)
	tree = children_map()
	names = [campaign, *descendants(campaign, tree)]
	company = frappe.db.get_value("Campaign", campaign, COMPANY_FIELD)
	own = campaign_results(names, company)
	return {
		"own": add_ratios(frappe._dict(own[campaign])),
		"total": rolled_up(campaign, own, tree),
		"children": len(names) - 1,
		"utm_campaign": utm_of(campaign),
		"currency": company and frappe.get_cached_value("Company", company, "default_currency"),
	}


@frappe.whitelist()
def get_utm_campaign(campaign: str):
	"""UTM Campaign the campaign's documents link to (for the View buttons on the form)."""
	frappe.has_permission("Campaign", "read", campaign, throw=True)
	return utm_of(campaign) or campaign


def campaign_link(campaign):
	return get_link_to_form("Campaign", campaign)
