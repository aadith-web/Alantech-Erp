# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Loan Product: the Product Code (the document name) is generated, LP-0001, LP-0002, ...

Lending names a Loan Product by its Product Code, a mandatory Data field typed by the user.
    execute()  after_migrate: Product Code read-only and not mandatory on the form, with a note.
    set_product_code(doc)  Loan Product before_insert (before naming): a blank Product Code gets the
                           next LP-#### number (a code already given, e.g. by Data Import, is kept).
Links to a Loan Product (Loan Rule, Loan Application, Loan) show the Product Name, not the code.
Existing products keep their codes.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.model.naming import make_autoname

DOCTYPE = "Loan Product"
FIELD = "product_code"
SERIES = "LP-.####"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return  # Lending not installed
	for prop, value, prop_type in (
		("reqd", 0, "Check"),
		("read_only", 1, "Check"),
		("description", "Generated when the product is saved (LP-0001, LP-0002, ...).", "Small Text"),
	):
		make_property_setter(DOCTYPE, FIELD, prop, value, prop_type, validate_fields_for_doctype=False)
	# links to a product (Loan Rule products, Loan Application, Loan) show its Product Name
	for prop, value, prop_type in (("title_field", "product_name", "Data"), ("show_title_field_in_link", 1, "Check")):
		make_property_setter(DOCTYPE, None, prop, value, prop_type, for_doctype=True,
			validate_fields_for_doctype=False)


def set_product_code(doc, method=None):
	if (doc.get(FIELD) or "").strip():
		return
	code = make_autoname(SERIES, DOCTYPE)
	while frappe.db.exists(DOCTYPE, code):  # a code typed by hand earlier
		code = make_autoname(SERIES, DOCTYPE)
	doc.set(FIELD, code)
