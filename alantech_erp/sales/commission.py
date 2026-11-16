"""Sales Person commission (Zoho CRM style plans on top of the ERPNext Sales Team).

Credit
    A won Deal (Opportunity, sales/forecast.py: its Sales Order submitted or closed by hand)
    credits its Sales Person with the Won Amount on the Won Date (basis Opportunity); re-opened,
    lost or cancelled order: the credit is reversed (sync_deal_commission).
    Every submitted Sales Order, Sales Invoice (credit notes too) and Payment Entry against a
    Sales Invoice writes Commission Ledger Entries: one per Sales Person in the document's Sales
    Team and Item Group, amount = net amount (company currency) x the Sales Team allocation %.
    A Payment Entry credits the paid share of each invoice (allocated / invoice grand total).
    Cancelling a document writes the opposite entries, so the ledger is never edited.
    Each entry carries its Basis (Sales Order / Sales Invoice / Payment Received); the Sales
    Person's Commission Plan picks which basis counts, so the plan can change without re-posting.

    Sales Team left empty on an order or invoice: the quotation's Sales Person (creator), else the
    Sales Person of the user who made it, at 100% (fill_sales_team).

Plans (Commission Plan, assigned to Sales Persons with from / to dates in its Members table)
    Flat Rate            base x rate
    Tiered (Whole)       the slab reached by the period total sets the rate for all of it
    Tiered (Incremental) each slab's rate on the part of the total that falls inside it
    Item Group Rates     a rate per Item Group (sub-groups follow their parent), else the plan rate
    Slabs are on the period's amount or on the % of the Sales Person's target (sales/forecast.py).
    Minimum achievement % (nothing below it), a cap per period, and clawback of credit notes.
    No plan: the Sales Person's own Commission Rate (ERPNext field), flat.

Payout (Commission Payout, submittable = approved)
    For a period: per Sales Person the unpaid entries of the plan's basis, the commission, manual
    adjustments; on submit a Journal Entry (Commission Expense Dr / Commission Payable Cr per
    employee) or an Additional Salary per employee for payroll, and the entries are marked paid.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from alantech_erp.sales.forecast import SETTINGS

# Basis of an entry / a plan
BASIS_ORDER = "Sales Order"
BASIS_INVOICE = "Sales Invoice"
BASIS_PAYMENT = "Payment Received"
BASIS_DEAL = "Opportunity"  # Deal won (Zoho: closed-won deal), the Deal's Sales Person
BASES = (BASIS_DEAL, BASIS_ORDER, BASIS_INVOICE, BASIS_PAYMENT)

# Calculation methods
FLAT = "Flat Rate"
TIERED_WHOLE = "Tiered (Whole)"
TIERED_INCREMENTAL = "Tiered (Incremental)"
ITEM_GROUP = "Item Group Rates"
METHODS = (FLAT, TIERED_WHOLE, TIERED_INCREMENTAL, ITEM_GROUP)

# Slab basis
SLAB_AMOUNT = "Amount"
SLAB_ACHIEVEMENT = "Target Achievement %"

# Payout methods
PAY_JOURNAL = "Journal Entry"
PAY_SALARY = "Additional Salary"

LEDGER = "Commission Ledger Entry"


def enabled():
	if not frappe.db.exists("DocType", SETTINGS):
		return False
	return cint(frappe.get_cached_doc(SETTINGS).get("enable_commission"))


# --------------------------------------------------------------------------- calculation (pure)
def tiered(total, slabs, incremental):
	"""Commission on `total` by slabs [(from, to or 0 = no limit, rate %)] sorted by from."""
	slabs = sorted(((flt(f), flt(t), flt(r)) for f, t, r in slabs), key=lambda s: s[0])
	if not slabs or total <= 0:
		return 0.0
	if not incremental:
		rate = 0.0
		for low, _high, r in slabs:
			if total >= low:
				rate = r
		return total * rate / 100
	commission = 0.0
	for low, high, r in slabs:
		if total <= low:
			break
		upper = min(total, high) if high else total
		if upper > low:
			commission += (upper - low) * r / 100
	return commission


def calculate(plan, base, by_item_group=None, target=0.0):
	"""(commission, achievement %, effective rate %) for one Sales Person and period.

	plan: _dict with method, rate, slab_basis, slabs [(from, to, rate)], item_group_rates
	{item group: rate}, min_achievement, max_commission; or None (= flat at plan.rate).
	by_item_group: {item group: base}; target: the period target (for achievement slabs).
	"""
	base = flt(base)
	target = flt(target)
	achievement = base * 100 / target if target else 0.0
	method = plan.method or FLAT

	if flt(plan.get("min_achievement")) and achievement < flt(plan.min_achievement) and base > 0:
		return 0.0, achievement, 0.0

	if base <= 0:
		# a net clawback (credit notes > sales): taken back at the plan's base rate
		rate = flt(plan.rate) or (flt(plan.slabs[0][2]) if plan.get("slabs") else 0.0)
		return base * rate / 100, achievement, rate

	if method == FLAT:
		commission = base * flt(plan.rate) / 100
	elif method == ITEM_GROUP:
		commission = 0.0
		for group, amount in (by_item_group or {"": base}).items():
			rate = (plan.get("item_group_rates") or {}).get(group)
			commission += flt(amount) * flt(plan.rate if rate is None else rate) / 100
	else:
		slabs = plan.get("slabs") or []
		if plan.get("slab_basis") == SLAB_ACHIEVEMENT:
			if not target:
				frappe.throw(
					_(
						"Commission Plan {0} pays on target achievement, but the Sales Person has no target "
						"for this period."
					).format(frappe.bold(plan.get("name") or "")),
					title=_("Target Missing"),
				)
			slabs = [(flt(f) * target / 100, flt(t) * target / 100, r) for f, t, r in slabs]
		commission = tiered(base, slabs, incremental=method == TIERED_INCREMENTAL)

	if flt(plan.get("max_commission")) and commission > flt(plan.max_commission):
		commission = flt(plan.max_commission)
	return commission, achievement, commission * 100 / base if base else 0.0


# --------------------------------------------------------------------------- plans
def plan_for(sales_person, on_date, company=None):
	"""The enabled Commission Plan a Sales Person is on at `on_date` (name or None)."""
	values = {"sp": sales_person, "d": getdate(on_date)}
	condition = ""
	if company:
		condition = "and p.company = %(company)s"
		values["company"] = company
	rows = frappe.db.sql(
		f"""
		select p.name from `tabCommission Plan` p
		inner join `tabCommission Plan Member` m on m.parent = p.name and m.parenttype = 'Commission Plan'
		where p.enabled = 1 and m.sales_person = %(sp)s
			and (m.from_date is null or m.from_date <= %(d)s)
			and (m.to_date is null or m.to_date >= %(d)s) {condition}
		order by m.from_date desc limit 1
		""",
		values,
	)
	return rows[0][0] if rows else None


def load_plan(name, sales_person=None):
	"""Plan as a _dict for calculate(); None name: flat at the Sales Person's Commission Rate."""
	if not name:
		rate = (
			flt(frappe.db.get_value("Sales Person", sales_person, "commission_rate")) if sales_person else 0
		)
		return frappe._dict(
			name=None,
			method=FLAT,
			rate=rate,
			basis=default_basis(),
			clawback=1,
			slabs=[],
			item_group_rates={},
		)
	doc = frappe.get_cached_doc("Commission Plan", name)
	return frappe._dict(
		name=doc.name,
		method=doc.calculation_method,
		basis=doc.basis,
		rate=flt(doc.rate),
		slab_basis=doc.slab_basis,
		slabs=[(s.from_value, s.to_value, s.rate) for s in doc.slabs],
		item_group_rates=_expand_item_groups({r.item_group: flt(r.rate) for r in doc.item_group_rates}),
		min_achievement=flt(doc.min_achievement),
		max_commission=flt(doc.max_commission),
		clawback=cint(doc.clawback_on_return),
	)


def _expand_item_groups(rates):
	"""A rate on a group also covers its sub-groups (a sub-group's own rate wins)."""
	if not rates:
		return {}
	from frappe.utils.nestedset import get_descendants_of

	out = {}
	# parents first, so a deeper group's own rate overrides what it inherited
	order = sorted(rates, key=lambda g: frappe.db.get_value("Item Group", g, "lft") or 0)
	for group in order:
		for child in get_descendants_of("Item Group", group, ignore_permissions=True):
			out[child] = rates[group]
		out[group] = rates[group]
	for group in order:  # own rates always win over an inherited one
		out[group] = rates[group]
	return out


def default_basis():
	if frappe.db.exists("DocType", SETTINGS):
		return frappe.get_cached_doc(SETTINGS).get("default_basis") or BASIS_INVOICE
	return BASIS_INVOICE


# --------------------------------------------------------------------------- Sales Team default
def fill_sales_team(doc, method=None):
	"""Sales Order / Sales Invoice validate: an empty Sales Team gets the creator's Sales Person."""
	if doc.docstatus != 0 or doc.get("sales_team") or not doc.meta.has_field("sales_team"):
		return
	if doc.doctype == "Sales Invoice" and cint(doc.get("is_return")):
		return  # a credit note copies the invoice's team (ERPNext); never invent one
	person = None
	quotations = {r.get("prevdoc_docname") for r in doc.get("items") or [] if r.get("prevdoc_docname")}
	for quotation in sorted(quotations):
		if frappe.get_meta("Quotation").has_field("alt_sales_person"):
			person = frappe.db.get_value("Quotation", quotation, "alt_sales_person")
		if person:
			break
	if not person:
		from alantech_erp.sales.hierarchy import sales_person_of_user

		row = sales_person_of_user(doc.get("owner") or frappe.session.user)
		person = row.name if row else None
	if not person:
		return
	doc.append(
		"sales_team",
		{
			"sales_person": person,
			"allocated_percentage": 100,
			"commission_rate": flt(frappe.db.get_value("Sales Person", person, "commission_rate")),
		},
	)
	if hasattr(doc, "calculate_commission"):
		doc.calculate_commission()


# --------------------------------------------------------------------------- ledger posting
def _item_group_amounts(doc, ratio=1.0):
	"""{item group: net amount in company currency x ratio} of a sales document."""
	out = {}
	for item in doc.get("items") or []:
		group = item.get("item_group") or ""
		out[group] = out.get(group, 0.0) + flt(item.get("base_net_amount")) * ratio
	return out


def _entries(doc, basis, groups, posting_date, against=None, sign=1):
	rows = []
	for member in doc.get("sales_team") or []:
		share = flt(member.allocated_percentage) / 100
		if not member.sales_person or not share:
			continue
		for group, amount in groups.items():
			amount = flt(amount * share * sign, 2)
			if not amount:
				continue
			rows.append(
				{
					"sales_person": member.sales_person,
					"basis": basis,
					"item_group": group or None,
					"base_amount": amount,
					"allocated_percentage": member.allocated_percentage,
					"customer": doc.get("customer"),
					"company": doc.company,
					"posting_date": posting_date,
					"against_voucher_type": against.doctype if against else None,
					"against_voucher": against.name if against else None,
					"is_return": cint(doc.get("is_return")),
				}
			)
	return rows


def _write(voucher_type, voucher_no, rows):
	for row in rows:
		entry = frappe.new_doc(LEDGER)
		entry.update(row)
		entry.voucher_type = voucher_type
		entry.voucher_no = voucher_no
		entry.flags.ignore_permissions = True
		entry.flags.ignore_links = True  # system ledger, written from a document being submitted
		entry.insert()


def _reverse(voucher_type, voucher_no):
	"""Opposite entries for everything a cancelled voucher posted (paid or not)."""
	originals = frappe.get_all(
		LEDGER,
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_reversal": 0, "reversed": 0},
		fields=["*"],
	)
	for row in originals:
		entry = frappe.new_doc(LEDGER)
		for field in (
			"sales_person",
			"basis",
			"item_group",
			"allocated_percentage",
			"customer",
			"company",
			"posting_date",
			"against_voucher_type",
			"against_voucher",
			"is_return",
		):
			entry.set(field, row.get(field))
		entry.voucher_type = voucher_type
		entry.voucher_no = voucher_no
		entry.base_amount = -flt(row.base_amount)
		entry.is_reversal = 1
		entry.reversal_of = row.name
		entry.flags.ignore_links = True
		# not paid yet: nets off in its own period; already paid: clawed back in the period cancelled
		entry.posting_date = getdate() if row.get("commission_payout") else row.posting_date
		entry.flags.ignore_permissions = True
		entry.insert()
		frappe.db.set_value(LEDGER, row.name, "reversed", 1, update_modified=False)


def on_sales_order_submit(doc, method=None):
	if enabled():
		_write(
			doc.doctype, doc.name, _entries(doc, BASIS_ORDER, _item_group_amounts(doc), doc.transaction_date)
		)


def on_sales_invoice_submit(doc, method=None):
	if enabled():
		_write(
			doc.doctype, doc.name, _entries(doc, BASIS_INVOICE, _item_group_amounts(doc), doc.posting_date)
		)


def on_payment_entry_submit(doc, method=None):
	if not enabled() or doc.get("payment_type") != "Receive":
		return
	for ref in doc.get("references") or []:
		if ref.reference_doctype != "Sales Invoice" or not flt(ref.allocated_amount):
			continue
		invoice = frappe.get_doc("Sales Invoice", ref.reference_name)
		total = flt(invoice.rounded_total) or flt(invoice.grand_total)
		if not total:
			continue
		ratio = flt(ref.allocated_amount) / total
		groups = _item_group_amounts(invoice, ratio)
		_write(
			doc.doctype, doc.name, _entries(invoice, BASIS_PAYMENT, groups, doc.posting_date, against=invoice)
		)


def sync_deal_commission(name):
	"""Ledger entries of a Deal follow its won state (won once, at the Won Amount / Won Date)."""
	from alantech_erp.sales import forecast as fc

	if not enabled() or not frappe.get_meta("Opportunity").has_field(fc.WON_DATE_FIELD):
		return
	deal = frappe.db.get_value(
		"Opportunity",
		name,
		[
			"name",
			"company",
			"opportunity_from",
			"party_name",
			fc.CATEGORY_FIELD,
			fc.SALES_PERSON_FIELD,
			fc.WON_DATE_FIELD,
			fc.WON_AMOUNT_FIELD,
		],
		as_dict=True,
	)
	wanted = None
	if (
		deal
		and deal.get(fc.CATEGORY_FIELD) == fc.CLOSED
		and deal.get(fc.WON_DATE_FIELD)
		and deal.get(fc.SALES_PERSON_FIELD)
		and flt(deal.get(fc.WON_AMOUNT_FIELD))
	):
		wanted = (
			deal.get(fc.SALES_PERSON_FIELD),
			flt(deal.get(fc.WON_AMOUNT_FIELD), 2),
			getdate(deal.get(fc.WON_DATE_FIELD)),
		)
	active = frappe.get_all(
		LEDGER,
		filters={"voucher_type": "Opportunity", "voucher_no": name, "is_reversal": 0, "reversed": 0},
		fields=["sales_person", "base_amount", "posting_date"],
	)
	current = (
		(active[0].sales_person, flt(active[0].base_amount, 2), getdate(active[0].posting_date))
		if len(active) == 1
		else None
	)
	if active and current != wanted:
		_reverse("Opportunity", name)
		active = []
	if wanted and not active:
		_write(
			"Opportunity",
			name,
			[
				{
					"sales_person": wanted[0],
					"basis": BASIS_DEAL,
					"base_amount": wanted[1],
					"allocated_percentage": 100,
					"customer": deal.party_name if deal.opportunity_from == "Customer" else None,
					"company": deal.company,
					"posting_date": wanted[2],
				}
			],
		)


def on_cancel(doc, method=None):
	if frappe.db.exists(LEDGER, {"voucher_type": doc.doctype, "voucher_no": doc.name}):
		_reverse(doc.doctype, doc.name)


# --------------------------------------------------------------------------- payout
def unpaid_entries(sales_person, basis, from_date, to_date, company, clawback=True):
	filters = {
		"sales_person": sales_person,
		"basis": basis,
		"company": company,
		"posting_date": ["between", [from_date, to_date]],
		"commission_payout": ["is", "not set"],
	}
	rows = frappe.get_all(
		LEDGER, filters=filters, fields=["name", "item_group", "base_amount", "is_return", "is_reversal"]
	)
	if not clawback:
		rows = [r for r in rows if not r.is_return]
	return rows


def people_with_entries(company, from_date, to_date, sales_persons=None):
	filters = {
		"company": company,
		"posting_date": ["between", [from_date, to_date]],
		"commission_payout": ["is", "not set"],
	}
	if sales_persons:
		filters["sales_person"] = ["in", list(sales_persons)]
	return sorted(set(frappe.get_all(LEDGER, filters=filters, pluck="sales_person")))


def compute_payout_row(sales_person, company, from_date, to_date):
	"""Commission of one Sales Person for the period (a Commission Payout Detail row) and the
	ledger entries it pays."""
	from alantech_erp.sales.forecast import targets

	plan_name = plan_for(sales_person, to_date, company)
	plan = load_plan(plan_name, sales_person)
	basis = plan.basis or default_basis()
	entries = unpaid_entries(sales_person, basis, from_date, to_date, company, clawback=bool(plan.clawback))
	base = sum(flt(e.base_amount) for e in entries)
	by_group = {}
	for e in entries:
		by_group[e.item_group or ""] = by_group.get(e.item_group or "", 0.0) + flt(e.base_amount)
	target = targets([sales_person], from_date, to_date, company).get(sales_person, 0.0)
	commission, achievement, rate = calculate(plan, base, by_group, target)
	return (
		frappe._dict(
			sales_person=sales_person,
			employee=frappe.db.get_value("Sales Person", sales_person, "employee"),
			commission_plan=plan_name,
			basis=basis,
			base_amount=flt(base, 2),
			target=flt(target, 2),
			achievement_pct=flt(achievement, 2),
			effective_rate=flt(rate, 4),
			commission_amount=flt(commission, 2),
		),
		[e.name for e in entries],
	)
