"""Customer Tax Type: Local or Overseas (doc_events on Customer, checks for Quotation / Sales Order).

Local     GSTIN is mandatory (GST Category from the GSTIN, India Compliance), and the customer needs
          an Address carrying that GSTIN: the quick entry creates it from its address fields, a
          converted Lead brings its own, otherwise the form asks for it right after the first save.
          Later saves, quotation approval and Sales Order confirmation are blocked until it exists.
Overseas  GST Category "Overseas" and no GSTIN.

Customers created before the field existed get their tax type from their GST Category / GSTIN once
(setup/sales_flow.py); the rest must pick one on their next save.
"""

import frappe
from frappe import _
from frappe.utils import get_link_to_form

from alantech_erp.sales import TAX_LOCAL, TAX_OVERSEAS, TAX_TYPE_FIELD

OVERSEAS_CATEGORY = "Overseas"
LOCAL_DEFAULT_CATEGORY = "Registered Regular"
# GST categories that cannot go with a Local customer's GSTIN
NOT_LOCAL_CATEGORIES = ("", None, OVERSEAS_CATEGORY, "Unregistered")


def _has_gst(doctype="Customer"):
	meta = frappe.get_meta(doctype)
	return meta.has_field("gstin") and meta.has_field("gst_category")


def _address_has_gstin():
	return frappe.get_meta("Address").has_field("gstin")


def before_validate(doc, method=None):
	"""Line the GST Category up with the tax type before India Compliance validates the GSTIN."""
	tax_type = doc.get(TAX_TYPE_FIELD)
	if not tax_type or not _has_gst():
		return
	if tax_type == TAX_OVERSEAS:
		doc.gst_category = OVERSEAS_CATEGORY
		doc.gstin = None
	elif doc.get("gst_category") in NOT_LOCAL_CATEGORIES:
		# refined from the GSTIN by India Compliance (SEZ, Composition...)
		doc.gst_category = LOCAL_DEFAULT_CATEGORY


def validate(doc, method=None):
	if doc.get(TAX_TYPE_FIELD) != TAX_LOCAL:
		return
	if _has_gst() and not doc.get("gstin"):
		frappe.throw(
			_("GSTIN is mandatory for a {0} customer. Enter the GSTIN, or set Tax Type to {1}.").format(
				frappe.bold(_(TAX_LOCAL)), frappe.bold(_(TAX_OVERSEAS))
			),
			title=_("GSTIN Required"),
		)
	if doc.is_new() or doc.disabled or _skip_address_check():
		# new: the address is made right after insert (quick entry / Lead / the form's prompt)
		return
	problem = address_problem(doc.name, doc.get("gstin"))
	if problem:
		frappe.throw(problem, title=_("Address Required"))


def onload(doc, method=None):
	"""Tells the form whether the Local customer still needs its GST address."""
	if doc.get(TAX_TYPE_FIELD) == TAX_LOCAL and not doc.is_new():
		doc.set_onload("alt_address_problem", address_problem(doc.name, doc.get("gstin"), html=False))


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
		fields=["name", "gstin"] if _address_has_gstin() else ["name"],
		distinct=True,
	)


def address_problem(customer, gstin, html=True):
	"""Why the Local customer's address is not ready (None when it is)."""
	addresses = linked_addresses(customer)
	if not addresses:
		return _("A {0} customer needs an address. Add the customer's address with GSTIN {1}.").format(
			frappe.bold(_(TAX_LOCAL)) if html else _(TAX_LOCAL), frappe.bold(gstin) if html else gstin
		)
	if gstin and _address_has_gstin() and not any(a.get("gstin") == gstin for a in addresses):
		return _("None of this customer's addresses has GSTIN {0}. Set the GSTIN on the address (or add a new address with it).").format(
			frappe.bold(gstin) if html else gstin
		)
	return None


def check_tax_details(customer, address=None, before=None):
	"""Raise when the customer's tax details are not complete (Quotation approval, Sales Order)."""
	if not customer or not frappe.get_meta("Customer").has_field(TAX_TYPE_FIELD):
		return
	values = frappe.db.get_value(
		"Customer", customer, [TAX_TYPE_FIELD, "gstin"] if _has_gst() else [TAX_TYPE_FIELD], as_dict=True
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
	if _has_gst() and not gstin:
		frappe.throw(
			_("Customer {0} is {1}: enter its GSTIN before {2}.").format(link, frappe.bold(_(TAX_LOCAL)), before),
			title=_("GSTIN Required"),
		)
	problem = address_problem(customer, gstin)
	if problem:
		frappe.throw(_("Customer {0}: {1}").format(link, problem), title=_("Address Required"))
	if address and _address_has_gstin() and not frappe.db.get_value("Address", address, "gstin"):
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
