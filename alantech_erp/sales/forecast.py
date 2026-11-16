"""Sales forecast (Zoho CRM style) on the Deal (Opportunity) and the Sales Person tree.

Forecast category on every Deal, as in Zoho:
    Pipeline   early stages, counted only in the pipeline
    Best Case  could close this period
    Commit     the salesperson commits to closing it this period
    Closed     won: its Sales Order is submitted (Won Date = order date, Won Amount = the Deal
               amount, close_deals_won), or the category / status Converted is set by hand.
               Cancelling that Sales Order re-opens the Deal (reopen_deals).
    Omitted    lost or parked, left out of every number

The category and probability come from the Deal's Sales Stage (Sales Stage.alt_forecast_category /
alt_default_probability, seeded for the Alantech stages by setup/sales_performance.py) whenever the
stage moves; between stage changes the salesperson may set them by hand (Zoho's override).

Numbers per Sales Person for a period (month or quarter), rolled up the Sales Person tree
(Sales Team -> Sales Director -> Sales Managers -> Sales Engineers, see sales/hierarchy.py):
    Target      Sales Person > Sales Targets (Target Detail) for the fiscal year, spread over the
                months by its Monthly Distribution (equal twelfths without one). A group without
                its own target gets the sum of its team's.
    Closed Won  from the source in Sales Performance Settings:
                Sales Order / Sales Invoice: submitted in the period, net total in company
                currency, split by the Sales Team allocation %
                Opportunity: Deals won in the period (Won Date), Won Amount, to the Deal's
                Sales Person
    Commit / Best Case / Pipeline
                open Deals expected to close in the period, by category (company currency)
    Weighted    open Deals x probability
    Forecast    Closed Won + Commit;  Best Case Forecast: + Best Case
    Gap         Target - Forecast;    Achievement %: Closed Won / Target

The Deal's Sales Person (alt_sales_person) follows its owner (opportunity_owner -> Employee ->
Sales Person) so Deals roll up the same tree as quotations and approvals.
"""

import calendar
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, get_first_day, getdate

# --------------------------------------------------------------------------- constants
SETTINGS = "Sales Performance Settings"

PIPELINE = "Pipeline"
BEST_CASE = "Best Case"
COMMIT = "Commit"
CLOSED = "Closed"
OMITTED = "Omitted"
CATEGORIES = (PIPELINE, BEST_CASE, COMMIT, CLOSED, OMITTED)
OPEN_CATEGORIES = (PIPELINE, BEST_CASE, COMMIT)

CATEGORY_FIELD = "alt_forecast_category"
SALES_PERSON_FIELD = "alt_sales_person"
STAGE_PROBABILITY_FIELD = "alt_default_probability"

MONTH = "Month"
QUARTER = "Quarter"

SALES_ORDER = "Sales Order"
SALES_INVOICE = "Sales Invoice"
OPPORTUNITY = "Opportunity"  # Deals won (Closed), on their won date

# set when a Deal is won (its Sales Order is submitted, or it is closed by hand)
WON_DATE_FIELD = "alt_won_date"
WON_AMOUNT_FIELD = "alt_won_amount"
WON_BY_FIELD = "alt_won_by"

# Opportunity statuses that are no longer in the pipeline
CLOSED_STATUSES = ("Lost", "Closed", "Converted")

# Number columns of a forecast row (Sales Forecast Detail and the Sales Forecast report)
AMOUNT_KEYS = ("target", "closed_won", "commit_amount", "best_case", "pipeline", "weighted_pipeline")


# --------------------------------------------------------------------------- settings
def settings():
	if not frappe.db.exists("DocType", SETTINGS):
		return frappe._dict(won_source=SALES_ORDER, period_type=MONTH)
	doc = frappe.get_cached_doc(SETTINGS)
	return frappe._dict(
		won_source=doc.get("won_source") or SALES_ORDER,
		period_type=doc.get("period_type") or MONTH,
	)


# --------------------------------------------------------------------------- periods
def period_bounds(period_type, any_date):
	"""(first day, last day) of the month or calendar quarter holding any_date."""
	d = getdate(any_date)
	if period_type == QUARTER:
		start = date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
		end_month = add_months(start, 2)
	else:
		start = date(d.year, d.month, 1)
		end_month = start
	end_month = getdate(end_month)
	end = date(end_month.year, end_month.month, calendar.monthrange(end_month.year, end_month.month)[1])
	return start, end


def months_between(from_date, to_date):
	"""First day of every month touched by [from_date, to_date]."""
	cur = getdate(get_first_day(from_date))
	end = getdate(to_date)
	out = []
	while cur <= end:
		out.append(cur)
		cur = getdate(add_months(cur, 1))
	return out


def period_label(period_type, start):
	start = getdate(start)
	if period_type == QUARTER:
		return f"Q{(start.month - 1) // 3 + 1} {start.year}"
	return start.strftime("%b %Y")


# --------------------------------------------------------------------------- Deal (Opportunity)
def stage_defaults(stage):
	"""(category, probability) set on the Sales Stage, or (None, None)."""
	if not stage or not frappe.get_meta("Sales Stage").has_field(CATEGORY_FIELD):
		return None, None
	row = frappe.db.get_value("Sales Stage", stage, [CATEGORY_FIELD, STAGE_PROBABILITY_FIELD], as_dict=True)
	if not row:
		return None, None
	return row.get(CATEGORY_FIELD) or None, row.get(STAGE_PROBABILITY_FIELD)


def category_for_status(status):
	if status == "Converted":
		return CLOSED
	if status in ("Lost", "Closed"):
		return OMITTED
	return None


def stage_values(stage, status=None, won=False):
	"""Opportunity values to write when its Sales Stage moves (used where the stage is set with
	db.set_value, e.g. sales/quotation.py sync_deal, which skips validate). A won Deal stays Closed."""
	values = {}
	if won and status != "Lost":
		return values
	category, probability = stage_defaults(stage)
	category = category_for_status(status) or category
	if category:
		values[CATEGORY_FIELD] = category
	if probability is not None and category not in (CLOSED, OMITTED):
		values["probability"] = flt(probability)
	return values


def opportunity_validate(doc, method=None):
	"""Opportunity validate: Sales Person from the owner; category / probability from the stage."""
	meta = doc.meta
	if meta.has_field(SALES_PERSON_FIELD):
		owner = doc.get("opportunity_owner") or doc.get("owner") or frappe.session.user
		if not doc.get(SALES_PERSON_FIELD) or doc.has_value_changed("opportunity_owner"):
			from alantech_erp.sales.hierarchy import sales_person_of_user

			person = sales_person_of_user(owner)
			if person:
				doc.set(SALES_PERSON_FIELD, person.name)

	if not meta.has_field(CATEGORY_FIELD):
		return
	won = bool(doc.get(WON_DATE_FIELD)) and doc.get(CATEGORY_FIELD) == CLOSED
	stage_moved = doc.is_new() or doc.has_value_changed("sales_stage")
	if stage_moved and not won:
		category, probability = stage_defaults(doc.get("sales_stage"))
		if category and (not doc.is_new() or not doc.get(CATEGORY_FIELD)):
			doc.set(CATEGORY_FIELD, category)
		# a new Deal keeps the probability typed in the Create Deal dialog (sales/deal.py make_deal)
		if probability is not None and not doc.flags.keep_probability:
			doc.probability = flt(probability)

	by_status = category_for_status(doc.get("status"))
	if by_status:
		doc.set(CATEGORY_FIELD, by_status)
	elif _reopened(doc):
		# back from Converted / Lost / Closed: the stage's category again
		doc.set(CATEGORY_FIELD, stage_defaults(doc.get("sales_stage"))[0] or PIPELINE)
	if not doc.get(CATEGORY_FIELD):
		doc.set(CATEGORY_FIELD, PIPELINE)
	_set_won(doc)


def _reopened(doc):
	if doc.is_new() or doc.get(CATEGORY_FIELD) not in (CLOSED, OMITTED):
		return False
	before = doc.get_doc_before_save()
	return bool(before) and before.get("status") in CLOSED_STATUSES and doc.status not in CLOSED_STATUSES


def _set_won(doc):
	"""Won Date / Amount follow the Closed category (closed by hand: today, the Deal amount)."""
	if not doc.meta.has_field(WON_DATE_FIELD):
		return
	if doc.get(CATEGORY_FIELD) == CLOSED:
		if not doc.get(WON_DATE_FIELD):
			doc.set(WON_DATE_FIELD, getdate())
		if not flt(doc.get(WON_AMOUNT_FIELD)) or not doc.get(WON_BY_FIELD):
			doc.set(WON_AMOUNT_FIELD, flt(doc.get("base_opportunity_amount")))
		doc.probability = 100
	elif doc.get(WON_DATE_FIELD):
		doc.update({WON_DATE_FIELD: None, WON_AMOUNT_FIELD: 0, WON_BY_FIELD: None})


def opportunity_on_update(doc, method=None):
	"""Opportunity on_update: commission credit follows the Deal's won state."""
	from alantech_erp.sales.commission import sync_deal_commission

	sync_deal_commission(doc.name)


# --------------------------------------------------------------------------- Deal won by the order
def deals_of_order(order):
	"""Deals (Opportunities) behind a Sales Order, through its quotations."""
	quotations = {r.get("prevdoc_docname") for r in order.get("items") or [] if r.get("prevdoc_docname")}
	deals = set()
	for quotation in quotations:
		deal = frappe.db.get_value("Quotation", quotation, "opportunity")
		if deal and frappe.db.exists("Opportunity", deal):
			deals.add(deal)
	if order.get("opportunity") and frappe.db.exists("Opportunity", order.opportunity):
		deals.add(order.opportunity)
	return sorted(deals)


def close_deals_won(doc, method=None):
	"""Sales Order on_submit: its Deals are won on the order date."""
	if not frappe.get_meta("Opportunity").has_field(WON_DATE_FIELD):
		return
	from alantech_erp.sales.commission import sync_deal_commission

	for deal in deals_of_order(doc):
		row = frappe.db.get_value(
			"Opportunity", deal, ["status", WON_DATE_FIELD, "base_opportunity_amount"], as_dict=True
		)
		if row.get(WON_DATE_FIELD) or row.status == "Lost":
			continue
		frappe.db.set_value(
			"Opportunity",
			deal,
			{
				CATEGORY_FIELD: CLOSED,
				WON_DATE_FIELD: doc.transaction_date,
				WON_AMOUNT_FIELD: flt(row.base_opportunity_amount) or flt(doc.base_net_total),
				WON_BY_FIELD: doc.name,
				"probability": 100,
			},
		)
		sync_deal_commission(deal)


def reopen_deals(doc, method=None):
	"""Sales Order on_cancel: Deals it won go back to their stage's category."""
	if not frappe.get_meta("Opportunity").has_field(WON_BY_FIELD):
		return
	from alantech_erp.sales.commission import sync_deal_commission

	for deal in frappe.get_all(
		"Opportunity", filters={WON_BY_FIELD: doc.name}, fields=["name", "sales_stage", "status"]
	):
		values = {WON_DATE_FIELD: None, WON_AMOUNT_FIELD: 0, WON_BY_FIELD: None}
		values.update(stage_values(deal.sales_stage))
		values.setdefault(CATEGORY_FIELD, COMMIT)
		frappe.db.set_value("Opportunity", deal.name, values)
		sync_deal_commission(deal.name)


# --------------------------------------------------------------------------- the tree
def tree(root=None, include_disabled=False):
	"""Sales Persons from `root` down (all when root is None), in tree order.

	Returns a list of _dict(name, parent, is_group, lft, rgt, indent, enabled, employee).
	"""
	filters = {}
	if root:
		lft, rgt = frappe.db.get_value("Sales Person", root, ["lft", "rgt"])
		filters = {"lft": [">=", lft], "rgt": ["<=", rgt]}
	if not include_disabled:
		filters["enabled"] = 1
	rows = frappe.get_all(
		"Sales Person",
		filters=filters,
		fields=["name", "parent_sales_person as parent", "is_group", "lft", "rgt", "enabled", "employee"],
		order_by="lft asc",
	)
	# indent from the nesting of lft/rgt
	stack = []
	for row in rows:
		while stack and stack[-1].rgt < row.lft:
			stack.pop()
		row.indent = len(stack)
		stack.append(row)
	return rows


def roots_for_user(user=None):
	"""The Sales Person a restricted user's forecast starts from (None: everything)."""
	from alantech_erp.sales.hierarchy import is_director, is_unrestricted, sales_person_of_user

	user = user or frappe.session.user
	if is_unrestricted(user):
		return None
	person = sales_person_of_user(user)
	if not person or is_director(person):
		return None
	return person.name


def check_root_allowed(root, user=None):
	"""A Sales Engineer / Manager may look at their own part of the tree only."""
	own = roots_for_user(user)
	if not own:
		return root
	if not root:
		return own
	lft, rgt = frappe.db.get_value("Sales Person", own, ["lft", "rgt"])
	r = frappe.db.get_value("Sales Person", root, ["lft", "rgt"])
	if not r or r[0] < lft or r[1] > rgt:
		frappe.throw(
			_("You can see the forecast of {0} and the team under them only.").format(frappe.bold(own)),
			frappe.PermissionError,
		)
	return root


# --------------------------------------------------------------------------- targets
def _distribution(name):
	if not name:
		return {}
	rows = frappe.get_all(
		"Monthly Distribution Percentage",
		filters={"parent": name, "parenttype": "Monthly Distribution"},
		fields=["month", "percentage_allocation"],
	)
	return {r.month: flt(r.percentage_allocation) for r in rows}


def _fiscal_year_of(d, company=None):
	from erpnext.accounts.utils import get_fiscal_year

	try:
		return get_fiscal_year(d, company=company, as_dict=True).name
	except Exception:
		return None


def targets(sales_persons, from_date, to_date, company=None):
	"""{sales person: own target amount for the period} from Sales Person > Sales Targets."""
	if not sales_persons:
		return {}
	rows = frappe.get_all(
		"Target Detail",
		filters={"parenttype": "Sales Person", "parent": ["in", list(sales_persons)]},
		fields=["parent", "fiscal_year", "target_amount", "distribution_id"],
	)
	if not rows:
		return {}
	month_fy = {m: _fiscal_year_of(m, company) for m in months_between(from_date, to_date)}
	cache = {}
	out = {}
	for row in rows:
		if not flt(row.target_amount):
			continue
		if row.distribution_id not in cache:
			cache[row.distribution_id] = _distribution(row.distribution_id)
		dist = cache[row.distribution_id]
		share = 0.0
		for month, fy in month_fy.items():
			if fy != row.fiscal_year:
				continue
			share += dist.get(calendar.month_name[month.month], 0.0) if dist else 100.0 / 12
		if share:
			out[row.parent] = out.get(row.parent, 0.0) + flt(row.target_amount) * share / 100
	return out


# --------------------------------------------------------------------------- actuals
def closed_won(sales_persons, from_date, to_date, company=None, source=None):
	"""{sales person: net sales in company currency} from submitted orders / invoices, or won Deals."""
	if not sales_persons:
		return {}
	source = source or settings().won_source
	if source == OPPORTUNITY:
		return won_deals(sales_persons, from_date, to_date, company)
	date_field = "transaction_date" if source == SALES_ORDER else "posting_date"
	conditions = ""
	values = {"sp": tuple(sales_persons), "from": from_date, "to": to_date}
	if company:
		conditions = "and d.company = %(company)s"
		values["company"] = company
	rows = frappe.db.sql(
		f"""
		select st.sales_person, sum(d.base_net_total * st.allocated_percentage / 100) as amount
		from `tab{source}` d
		inner join `tabSales Team` st on st.parent = d.name and st.parenttype = %(doctype)s
		where d.docstatus = 1 and st.sales_person in %(sp)s
			and d.{date_field} between %(from)s and %(to)s {conditions}
		group by st.sales_person
		""",
		dict(values, doctype=source),
		as_dict=True,
	)
	return {r.sales_person: flt(r.amount) for r in rows}


def won_deals(sales_persons, from_date, to_date, company=None):
	"""{sales person: Won Amount} of Deals won in the period."""
	if not frappe.get_meta("Opportunity").has_field(WON_DATE_FIELD):
		return {}
	conditions = ""
	values = {"sp": tuple(sales_persons), "from": from_date, "to": to_date, "closed": CLOSED}
	if company:
		conditions = "and company = %(company)s"
		values["company"] = company
	rows = frappe.db.sql(
		f"""
		select {SALES_PERSON_FIELD} as sales_person, sum({WON_AMOUNT_FIELD}) as amount
		from `tabOpportunity`
		where docstatus < 2 and {CATEGORY_FIELD} = %(closed)s and {SALES_PERSON_FIELD} in %(sp)s
			and {WON_DATE_FIELD} between %(from)s and %(to)s {conditions}
		group by {SALES_PERSON_FIELD}
		""",
		values,
		as_dict=True,
	)
	return {r.sales_person: flt(r.amount) for r in rows}


def open_deals(sales_persons, from_date, to_date, company=None):
	"""{sales person: {category: amount, "weighted": amount}} of open Deals closing in the period."""
	if not sales_persons or not frappe.get_meta("Opportunity").has_field(CATEGORY_FIELD):
		return {}
	conditions = ""
	values = {
		"sp": tuple(sales_persons),
		"from": from_date,
		"to": to_date,
		"closed": CLOSED_STATUSES,
		"categories": OPEN_CATEGORIES,
	}
	if company:
		conditions = "and company = %(company)s"
		values["company"] = company
	rows = frappe.db.sql(
		f"""
		select {SALES_PERSON_FIELD} as sales_person, {CATEGORY_FIELD} as category,
			sum(base_opportunity_amount) as amount,
			sum(base_opportunity_amount * ifnull(probability, 0) / 100) as weighted
		from `tabOpportunity`
		where docstatus < 2 and status not in %(closed)s
			and {SALES_PERSON_FIELD} in %(sp)s and {CATEGORY_FIELD} in %(categories)s
			and expected_closing between %(from)s and %(to)s {conditions}
		group by {SALES_PERSON_FIELD}, {CATEGORY_FIELD}
		""",
		values,
		as_dict=True,
	)
	out = {}
	for r in rows:
		d = out.setdefault(r.sales_person, {"weighted": 0.0})
		d[r.category] = d.get(r.category, 0.0) + flt(r.amount)
		d["weighted"] += flt(r.weighted)
	return out


# --------------------------------------------------------------------------- the forecast
def compute_row(row):
	"""Derived columns of one forecast row (in place)."""
	row.forecast = flt(row.closed_won) + flt(row.commit_amount)
	row.best_case_forecast = row.forecast + flt(row.best_case)
	row.gap = flt(row.target) - row.forecast if flt(row.target) else 0.0
	row.achievement_pct = flt(row.closed_won) * 100 / flt(row.target) if flt(row.target) else 0.0
	return row


def roll_up(rows):
	"""Group rows get their team's numbers added to their own (rows in tree order, with lft/rgt).

	Targets: a group keeps its own target when it has one (the manager's quota), else the sum of
	its team's.
	"""
	own = {r.name: {k: flt(r.get(k)) for k in AMOUNT_KEYS} for r in rows}
	for r in rows:
		if not r.is_group:
			continue
		team = [c for c in rows if c.lft > r.lft and c.rgt < r.rgt]
		for key in AMOUNT_KEYS:
			if key == "target":
				continue
			r[key] = own[r.name][key] + sum(own[c.name][key] for c in team)
		if not own[r.name]["target"]:
			# nearest-level targets only: a sub-group's own target already stands for its team
			r.target = _team_target(r, rows, own)
	for r in rows:
		compute_row(r)
	return rows


def _team_target(group, rows, own):
	total = 0.0
	for child in rows:
		if child.parent != group.name:
			continue
		if own[child.name]["target"] or not child.is_group:
			total += own[child.name]["target"]
		else:
			total += _team_target(child, rows, own)
	return total


def get_forecast(company=None, from_date=None, to_date=None, root=None, source=None):
	"""Forecast rows for the Sales Person tree from `root` (tree order, rolled up)."""
	people = tree(root)
	names = [p.name for p in people]
	tgt = targets(names, from_date, to_date, company)
	won = closed_won(names, from_date, to_date, company, source)
	deals = open_deals(names, from_date, to_date, company)
	rows = []
	for p in people:
		d = deals.get(p.name, {})
		rows.append(
			frappe._dict(
				name=p.name,
				sales_person=p.name,
				parent=p.parent,
				is_group=cint(p.is_group),
				lft=p.lft,
				rgt=p.rgt,
				indent=p.indent,
				target=flt(tgt.get(p.name)),
				closed_won=flt(won.get(p.name)),
				commit_amount=flt(d.get(COMMIT)),
				best_case=flt(d.get(BEST_CASE)),
				pipeline=flt(d.get(PIPELINE)),
				weighted_pipeline=flt(d.get("weighted")),
			)
		)
	return roll_up(rows)


def company_currency(company):
	if company:
		return frappe.get_cached_value("Company", company, "default_currency")
	return frappe.db.get_default("currency")


# --------------------------------------------------------------------------- permissions
def sales_forecast_query(user=None):
	"""Sales Forecast list: restricted users see the forecasts of their own part of the tree."""
	root = roots_for_user(user)
	if not root:
		return ""
	lft, rgt = frappe.db.get_value("Sales Person", root, ["lft", "rgt"])
	return (
		"`tabSales Forecast`.`sales_person` in (select name from `tabSales Person` "
		f"where lft >= {cint(lft)} and rgt <= {cint(rgt)})"
	)
