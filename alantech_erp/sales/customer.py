"""Customer rules (CRM-F04): Customer Type, Tax Type and lifecycle (doc_events on Customer / Address,
checks for Quotation / Sales Order). Mobile / email / GSTIN / name duplicates: sales/customer_unique.py.

Customer Type
Company / Partnership  Territory and Industry mandatory; Mobile No and Email ID (the Primary
          Contact's) mandatory, as for every customer.
Individual  Industry hidden; GSTIN optional when Local (GST Category Unregistered without one).

Local     GSTIN is mandatory for a Company (GST Category from the GSTIN, India Compliance), and the customer needs
          an Address carrying that GSTIN: the quick entry creates it from its address fields, a
          converted Lead brings its own, otherwise the form asks for it right after the first save.
          Later saves, quotation approval and Sales Order confirmation are blocked until it exists.
          Billing addresses in India, the GSTIN's state code matching the address GST State.
Overseas  GST Category "Overseas" and no GSTIN, Default Currency mandatory, no billing address in India.

Customer Stage  read only: Account until the first submitted Sales Order (sales/sales_order.py).
Locked    Customer Type, Tax Type and GSTIN after the first submitted Quotation / Sales Order /
          Sales Invoice, except for a Sales Manager.
Disable   warns about open Quotations / Sales Orders of the customer.

Customers created before the field existed get their tax type from their GST Category / GSTIN once
(setup/sales_flow.py); the rest must pick one on their next save.
"""

import frappe
from frappe import _
from frappe.utils import cstr, get_link_to_form

from alantech_erp.sales import INDIVIDUAL, LOCKED_FIELD_EDITORS, TAX_LOCAL, TAX_OVERSEAS, TAX_TYPE_FIELD

OVERSEAS_CATEGORY = "Overseas"
LOCAL_DEFAULT_CATEGORY = "Registered Regular"
UNREGISTERED_CATEGORY = "Unregistered"
INDIA = "India"
STAGE_FIELD = "alt_customer_stage"
STAGE_ACCOUNT = "Account"
# fixed after the first submitted transaction (LOCKED_FIELD_EDITORS can still change them)
LOCKED_FIELDS = ("customer_type", TAX_TYPE_FIELD, "gstin")
# (doctype, customer field, extra filters) of the transactions that lock them
TRANSACTIONS = (
	("Quotation", "party_name", {"quotation_to": "Customer"}),
	("Sales Order", "customer", {}),
	("Sales Invoice", "customer", {}),
)
# GST categories that cannot go with a Local customer's GSTIN
NOT_LOCAL_CATEGORIES = ("", None, OVERSEAS_CATEGORY, "Unregistered")


def _has_gst(doctype="Customer"):
	meta = frappe.get_meta(doctype)
	return meta.has_field("gstin") and meta.has_field("gst_category")


def _address_has_gstin():
	return frappe.get_meta("Address").has_field("gstin")


def is_individual(doc_or_type):
	customer_type = doc_or_type if isinstance(doc_or_type, str) or doc_or_type is None else doc_or_type.get("customer_type")
	return customer_type == INDIVIDUAL


def gstin_required(customer_type):
	"""Local customers need a GSTIN, except Individuals."""
	return not is_individual(customer_type)


def before_validate(doc, method=None):
	"""Line the GST Category up with the tax type before India Compliance validates the GSTIN."""
	_keep_stage(doc)
	tax_type = doc.get(TAX_TYPE_FIELD)
	if not tax_type or not _has_gst():
		return
	if tax_type == TAX_OVERSEAS:
		doc.gst_category = OVERSEAS_CATEGORY
		doc.gstin = None
	elif is_individual(doc) and not doc.get("gstin"):
		doc.gst_category = UNREGISTERED_CATEGORY
	elif doc.get("gst_category") in NOT_LOCAL_CATEGORIES:
		# refined from the GSTIN by India Compliance (SEZ, Composition...)
		doc.gst_category = LOCAL_DEFAULT_CATEGORY


def _keep_stage(doc):
	"""Customer Stage is set by the Sales Orders only (sales/sales_order.py set_customer_stage)."""
	if not doc.meta.has_field(STAGE_FIELD):
		return
	if doc.is_new():
		doc.set(STAGE_FIELD, STAGE_ACCOUNT)
		return
	saved = frappe.db.get_value("Customer", doc.name, STAGE_FIELD)
	if saved and doc.get(STAGE_FIELD) != saved:
		doc.set(STAGE_FIELD, saved)


def validate(doc, method=None):
	if _skip_rules():
		return
	validate_customer_type(doc)
	validate_locked_fields(doc)
	warn_open_documents_on_disable(doc)

	tax_type = doc.get(TAX_TYPE_FIELD)
	if tax_type == TAX_OVERSEAS:
		validate_overseas(doc)
		return
	if tax_type != TAX_LOCAL:
		return
	if _has_gst() and not doc.get("gstin") and gstin_required(doc.get("customer_type")):
		frappe.throw(
			_("GSTIN is mandatory for a {0} {1} customer. Enter the GSTIN, or set Tax Type to {2}.").format(
				frappe.bold(_(TAX_LOCAL)), frappe.bold(_(doc.customer_type)), frappe.bold(_(TAX_OVERSEAS))
			),
			title=_("GSTIN Required"),
		)
	if doc.is_new() or doc.disabled or _skip_address_check():
		# new: the address is made right after insert (quick entry / Lead / the form's prompt)
		return
	problem = address_problem(doc.name, doc.get("gstin"))
	if problem:
		frappe.throw(problem, title=_("Address Required"))


def _skip_rules():
	flags = frappe.flags
	return bool(flags.in_migrate or flags.in_install or flags.in_patch or flags.in_fixtures)


def validate_customer_type(doc):
	"""Company / Partnership: Territory and Industry mandatory."""
	if is_individual(doc):
		return
	meta = doc.meta
	missing = [
		_(meta.get_label(field))
		for field in ("territory", "industry")
		if meta.has_field(field) and not doc.get(field)
	]
	if missing:
		frappe.throw(
			_("{0} mandatory for a {1} customer.").format(
				(" " + _("and") + " ").join(frappe.bold(m) for m in missing), frappe.bold(_(doc.customer_type))
			),
			title=_("Missing Values Required"),
		)


def validate_overseas(doc):
	if doc.meta.has_field("default_currency") and not doc.get("default_currency"):
		frappe.throw(
			_("Set the {0} of the {1} customer.").format(
				frappe.bold(_(doc.meta.get_label("default_currency"))), frappe.bold(_(TAX_OVERSEAS))
			),
			title=_("Currency Required"),
		)
	if doc.is_new() or doc.disabled or _skip_address_check():
		return
	indian = [a.name for a in linked_addresses(doc.name) if _is_billing(a) and a.get("country") == INDIA]
	if indian:
		frappe.throw(
			_("An {0} customer cannot have a billing address in India: {1}. Correct the address, or set Tax Type to {2}.").format(
				frappe.bold(_(TAX_OVERSEAS)),
				", ".join(get_link_to_form("Address", a) for a in indian),
				frappe.bold(_(TAX_LOCAL)),
			),
			title=_("Overseas Address"),
		)


def can_edit_locked_fields():
	return bool(set(frappe.get_roles()) & set(LOCKED_FIELD_EDITORS))


def has_submitted_transactions(customer):
	for doctype, field, filters in TRANSACTIONS:
		if frappe.db.exists("DocType", doctype) and frappe.db.exists(
			doctype, {**filters, field: customer, "docstatus": 1}
		):
			return doctype
	return None


def validate_locked_fields(doc):
	"""Customer Type, Tax Type and GSTIN cannot change after the first submitted transaction."""
	if doc.is_new() or can_edit_locked_fields():
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [
		_(doc.meta.get_label(field))
		for field in LOCKED_FIELDS
		if doc.meta.has_field(field) and cstr(before.get(field)).strip() != cstr(doc.get(field)).strip()
	]
	if not changed:
		return
	transaction = has_submitted_transactions(doc.name)
	if transaction:
		frappe.throw(
			_("{0} cannot be changed: the customer already has a submitted {1}. Ask a {2} to change it.").format(
				", ".join(frappe.bold(c) for c in changed), _(transaction), _(LOCKED_FIELD_EDITORS[0])
			),
			title=_("Not Allowed"),
		)


def open_documents(customer):
	"""Open Quotations and Sales Orders of the customer: {doctype: [names]}."""
	result = {}
	quotations = frappe.get_all(
		"Quotation",
		filters={
			"quotation_to": "Customer",
			"party_name": customer,
			"docstatus": ["<", 2],
			"status": ["not in", ("Lost", "Ordered", "Expired", "Cancelled")],
		},
		pluck="name",
		limit=20,
	)
	if quotations:
		result["Quotation"] = quotations
	orders = frappe.get_all(
		"Sales Order",
		filters={"customer": customer, "docstatus": ["<", 2], "status": ["not in", ("Completed", "Closed", "Cancelled")]},
		pluck="name",
		limit=20,
	)
	if orders:
		result["Sales Order"] = orders
	return result


def warn_open_documents_on_disable(doc):
	if doc.is_new() or not doc.disabled:
		return
	before = doc.get_doc_before_save()
	if before and before.disabled:
		return
	documents = open_documents(doc.name)
	if not documents:
		return
	lines = "".join(
		f"<li>{_(doctype)}: {', '.join(get_link_to_form(doctype, n) for n in names)}</li>"
		for doctype, names in documents.items()
	)
	frappe.msgprint(
		_("Customer {0} is disabled but still has open documents:").format(frappe.bold(doc.customer_name))
		+ f"<ul>{lines}</ul>"
		+ _("Close, cancel or mark them lost if they are no longer needed."),
		title=_("Open Documents"),
		indicator="orange",
	)


def onload(doc, method=None):
	"""Tells the form whether the Local customer still needs its GST address, and whether Customer
	Type / Tax Type / GSTIN are locked."""
	if doc.is_new():
		return
	if doc.get(TAX_TYPE_FIELD) == TAX_LOCAL:
		doc.set_onload("alt_address_problem", address_problem(doc.name, doc.get("gstin"), html=False))
	if not can_edit_locked_fields():
		doc.set_onload("alt_locked_by", has_submitted_transactions(doc.name))


def _skip_address_check():
	flags = frappe.flags
	return bool(flags.in_import or flags.in_migrate or flags.in_install or flags.in_patch)


def linked_addresses(customer):
	return frappe.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", "Customer"],
			["Dynamic Link", "link_name", "=", customer],
			["disabled", "=", 0],
		],
		fields=["name", "address_type", "country"]
		+ (["gstin"] if _address_has_gstin() else [])
		+ (["gst_state"] if frappe.get_meta("Address").has_field("gst_state") else []),
		distinct=True,
	)


def _is_billing(address):
	return (address.get("address_type") or "Billing") == "Billing"


def _state_number(state):
	try:
		from india_compliance.gst_india.constants import STATE_NUMBERS
	except ImportError:
		return None
	return STATE_NUMBERS.get(state)


def address_problem(customer, gstin, html=True):
	"""Why the Local customer's address is not ready (None when it is)."""
	bold = frappe.bold if html else (lambda v: v)
	addresses = linked_addresses(customer)
	if not addresses:
		if gstin:
			return _("A {0} customer needs an address. Add the customer's address with GSTIN {1}.").format(
				bold(_(TAX_LOCAL)), bold(gstin)
			)
		return _("A {0} customer needs an address. Add the customer's billing address in India.").format(bold(_(TAX_LOCAL)))
	foreign = [a.name for a in addresses if _is_billing(a) and a.get("country") and a.get("country") != INDIA]
	if foreign:
		return _("A {0} customer's billing address must be in India: correct {1}, or set Tax Type to {2}.").format(
			bold(_(TAX_LOCAL)), ", ".join(foreign), bold(_(TAX_OVERSEAS))
		)
	if not gstin or not _address_has_gstin():
		return None
	matching = [a for a in addresses if a.get("gstin") == gstin]
	if not matching:
		return _("None of this customer's addresses has GSTIN {0}. Set the GSTIN on the address (or add a new address with it).").format(
			bold(gstin)
		)
	state_code = gstin[:2]
	for address in matching:
		expected = _state_number(address.get("gst_state")) if address.get("gst_state") else None
		if address.get("gst_state") and expected and expected != state_code:
			return _("GSTIN {0} is of state code {1}, but address {2} is in {3} ({4}). Correct the GST State of the address.").format(
				bold(gstin), state_code, address.name, bold(address.gst_state), expected
			)
	return None


def check_tax_details(customer, address=None, before=None):
	"""Raise when the customer's tax details are not complete (Quotation approval, Sales Order)."""
	if not customer or not frappe.get_meta("Customer").has_field(TAX_TYPE_FIELD):
		return
	values = frappe.db.get_value(
		"Customer",
		customer,
		[TAX_TYPE_FIELD, "customer_type", "default_currency"] + (["gstin"] if _has_gst() else []),
		as_dict=True,
	)
	if not values:
		return
	before = before or _("continuing")
	link = get_link_to_form("Customer", customer)
	tax_type = values.get(TAX_TYPE_FIELD)

	if not tax_type:
		frappe.throw(
			_("Set the Tax Type ({0} or {1}) of Customer {2} before {3}.").format(
				_(TAX_LOCAL), _(TAX_OVERSEAS), link, before
			),
			title=_("Tax Type Required"),
		)
	if tax_type != TAX_LOCAL:
		return

	gstin = values.get("gstin")
	if _has_gst() and not gstin and gstin_required(values.get("customer_type")):
		frappe.throw(
			_("Customer {0} is {1}: enter its GSTIN before {2}.").format(link, frappe.bold(_(TAX_LOCAL)), before),
			title=_("GSTIN Required"),
		)
	problem = address_problem(customer, gstin)
	if problem:
		frappe.throw(_("Customer {0}: {1}").format(link, problem), title=_("Address Required"))
	if gstin and address and _address_has_gstin() and not frappe.db.get_value("Address", address, "gstin"):
		frappe.throw(
			_("Address {0} has no GSTIN. Select the customer's GST address (GSTIN {1}) before {2}.").format(
				get_link_to_form("Address", address), frappe.bold(gstin), before
			),
			title=_("GST Address Required"),
		)


def tax_type_from_gst(gst_category, gstin):
	"""Tax type for a customer made before the field existed (None: cannot tell)."""
	if gst_category == OVERSEAS_CATEGORY:
		return TAX_OVERSEAS
	if gstin:
		return TAX_LOCAL
	return None


def address_validate(doc, method=None):
	"""Address.validate: a Local customer's billing address in India, an Overseas customer's outside."""
	if _skip_rules() or doc.get("disabled") or not _is_billing(doc) or not doc.get("country"):
		return
	customers = [l.link_name for l in doc.get("links") or [] if l.link_doctype == "Customer" and l.link_name]
	if not customers or not frappe.get_meta("Customer").has_field(TAX_TYPE_FIELD):
		return
	for row in frappe.get_all("Customer", filters={"name": ["in", customers]}, fields=["name", TAX_TYPE_FIELD]):
		tax_type = row.get(TAX_TYPE_FIELD)
		if tax_type == TAX_LOCAL and doc.country != INDIA:
			frappe.throw(
				_("Customer {0} is {1}: its billing address must be in India.").format(
					get_link_to_form("Customer", row.name), frappe.bold(_(TAX_LOCAL))
				),
				title=_("Local Address"),
			)
		if tax_type == TAX_OVERSEAS and doc.country == INDIA:
			frappe.throw(
				_("Customer {0} is {1}: its billing address cannot be in India.").format(
					get_link_to_form("Customer", row.name), frappe.bold(_(TAX_OVERSEAS))
				),
				title=_("Overseas Address"),
			)
